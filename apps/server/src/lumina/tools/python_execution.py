from __future__ import annotations

import asyncio
import contextlib
import json
import locale
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..artifacts.service import require_artifact
from ..http_client import TrustProfile, redact_sensitive_text
from ..extensions.package_content import decode_package_content
from ..models import (
    ArtifactVersion,
    Run,
    User,
)
from ..storage import ManagedLocalStorage
from .skill_resources import (
    active_skill_snapshot,
    frozen_skill_package,
    safe_skill_package_path,
)


MAX_PYTHON_ARGUMENTS = 32
MAX_PYTHON_ARGUMENT_CHARS = 2_000
MAX_PYTHON_INPUT_JSON_BYTES = 1_000_000
MAX_PYTHON_OUTPUT_BYTES = 100_000
MAX_PYTHON_SCRIPT_BYTES = 1_000_000
DEFAULT_PYTHON_TIMEOUT_SECONDS = 120
MAX_PYTHON_TIMEOUT_SECONDS = 600
DEFAULT_HEAVY_PYTHON_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_MAX_PYTHON_TIMEOUT_SECONDS = 24 * 60 * 60

_MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_SAFE_ARTIFACT_NAME = re.compile(r"[^0-9A-Za-z가-힣._ -]+")
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}
_RUN_PATH_WORKER = (
    "import runpy,sys;"
    "root=sys.argv.pop(1);"
    "script=sys.argv.pop(1);"
    "sys.path.insert(0,root);"
    "sys.argv[0]=script;"
    "runpy.run_path(script,run_name='__main__')"
)
_RUN_MODULE_WORKER = (
    "import runpy,sys;"
    "root=sys.argv.pop(1);"
    "module=sys.argv.pop(1);"
    "sys.path.insert(0,root);"
    "runpy.run_module(module,run_name='__main__',alter_sys=True)"
)


PYTHON_EXECUTION_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Run Python from one exact Lumina-managed source without a shell. "
            "For newly authored code, first use write_file with a .py path, then pass its "
            "artifact_id and artifact_version here. To run code bundled with an active Skill, "
            "pass source='skill', the active skill_id, and exactly one of path or module. "
            "Skill execution uses the version or draft revision frozen in the current Run. "
            "This is local code execution and normally requires user approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["artifact", "skill"],
                },
                "artifact_id": {
                    "type": "string",
                    "description": "Artifact ID returned by write_file.",
                },
                "artifact_version": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Exact Artifact version returned by write_file.",
                },
                "skill_id": {
                    "type": "string",
                    "description": "ID or slug of an active Skill in the current Run.",
                },
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "description": (
                        "Relative .py entrypoint inside the active Skill package. "
                        "Use this for scripts such as scripts/helper.py."
                    ),
                },
                "module": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 240,
                    "description": (
                        "Python module inside the active Skill package, equivalent to "
                        "python -m module. Use this for packages such as engine."
                    ),
                },
                "profile": {
                    "type": "string",
                    "enum": ["standard", "heavy"],
                    "default": "standard",
                    "description": (
                        "Use heavy only for an active Skill that needs a long-running "
                        "managed Python runtime. The server administrator must enable it."
                    ),
                },
                "args": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "maxLength": MAX_PYTHON_ARGUMENT_CHARS,
                    },
                    "maxItems": MAX_PYTHON_ARGUMENTS,
                    "default": [],
                },
                "input_json": {
                    "type": "string",
                    "maxLength": MAX_PYTHON_INPUT_JSON_BYTES,
                    "description": (
                        "Optional JSON object collected from the user. Lumina validates "
                        "and writes it to the program's UTF-8 stdin. Skill wrappers should "
                        "read one JSON value from stdin and print their result to stdout."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": ABSOLUTE_MAX_PYTHON_TIMEOUT_SECONDS,
                    "default": DEFAULT_PYTHON_TIMEOUT_SECONDS,
                },
            },
            "required": ["source"],
            "allOf": [
                {
                    "if": {
                        "properties": {"source": {"const": "artifact"}},
                        "required": ["source"],
                    },
                    "then": {
                        "required": ["artifact_id", "artifact_version"],
                    },
                },
                {
                    "if": {
                        "properties": {"source": {"const": "skill"}},
                        "required": ["source"],
                    },
                    "then": {
                        "required": ["skill_id"],
                        "oneOf": [
                            {"required": ["path"]},
                            {"required": ["module"]},
                        ],
                    },
                },
            ],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True, slots=True)
class PythonExecutionPolicy:
    heavy_enabled: bool = False
    heavy_max_timeout_seconds: int = 24 * 60 * 60
    executable: str = sys.executable

    @classmethod
    def from_settings(cls, settings: Any) -> "PythonExecutionPolicy":
        configured_executable = getattr(settings, "python_execution_executable", None)
        return cls(
            heavy_enabled=bool(
                getattr(settings, "python_heavy_execution_enabled", False)
            ),
            heavy_max_timeout_seconds=int(
                getattr(
                    settings,
                    "python_heavy_max_timeout_seconds",
                    24 * 60 * 60,
                )
            ),
            executable=str(configured_executable or sys.executable),
        )


@dataclass(frozen=True, slots=True)
class PreparedPythonExecution:
    source_type: str
    files: Mapping[str, str]
    entrypoint: str
    module: str | None
    args: tuple[str, ...]
    timeout_seconds: int
    source_metadata: Mapping[str, Any]
    profile: str = "standard"
    executable: str = sys.executable
    stdin_json: str | None = None


def prepare_python_execution(
    db: Session,
    artifact_storage: ManagedLocalStorage,
    *,
    run: Run,
    user: User,
    arguments: Mapping[str, Any],
    policy: PythonExecutionPolicy | None = None,
) -> PreparedPythonExecution:
    execution_policy = policy or PythonExecutionPolicy()
    source = str(arguments.get("source") or "").strip().casefold()
    profile = _profile(arguments.get("profile"))
    if profile == "heavy" and not execution_policy.heavy_enabled:
        raise ValueError("heavy Python 실행은 서버 관리자가 활성화해야 합니다.")
    if source == "artifact" and profile != "standard":
        raise ValueError("heavy Python 실행은 고정된 활성 Skill에만 허용됩니다.")
    args = _arguments(arguments.get("args"))
    stdin_json = _input_json(arguments.get("input_json"))
    timeout_seconds = _timeout(
        arguments.get("timeout_seconds"),
        profile=profile,
        policy=execution_policy,
    )
    executable = _python_executable(execution_policy.executable)
    if source == "artifact":
        return _prepare_artifact_execution(
            db,
            artifact_storage,
            run=run,
            user=user,
            arguments=arguments,
            args=args,
            stdin_json=stdin_json,
            timeout_seconds=timeout_seconds,
            executable=executable,
        )
    if source == "skill":
        return _prepare_skill_execution(
            db,
            run=run,
            arguments=arguments,
            args=args,
            stdin_json=stdin_json,
            timeout_seconds=timeout_seconds,
            profile=profile,
            executable=executable,
        )
    raise ValueError("source는 artifact 또는 skill이어야 합니다.")


def _prepare_artifact_execution(
    db: Session,
    storage: ManagedLocalStorage,
    *,
    run: Run,
    user: User,
    arguments: Mapping[str, Any],
    args: tuple[str, ...],
    stdin_json: str | None,
    timeout_seconds: int,
    executable: str,
) -> PreparedPythonExecution:
    artifact_id = str(arguments.get("artifact_id") or "").strip()
    if not artifact_id:
        raise ValueError("Artifact Python 실행에는 artifact_id가 필요합니다.")
    if arguments.get("skill_id") or arguments.get("path") or arguments.get("module"):
        raise ValueError(
            "Artifact Python 실행에는 Skill 경로를 함께 지정할 수 없습니다."
        )
    artifact = require_artifact(db, user, artifact_id)
    if artifact.project_id != run.project_id:
        raise ApiProblem(
            403, "artifact_project_mismatch", "현재 Project의 Artifact가 아닙니다."
        )
    if PurePosixPath(artifact.display_name).suffix.casefold() != ".py":
        raise ValueError("run_python은 .py Artifact만 실행할 수 있습니다.")
    requested_version = arguments.get("artifact_version")
    if (
        not isinstance(requested_version, int)
        or isinstance(requested_version, bool)
        or requested_version < 1
    ):
        raise ValueError(
            "Artifact Python 실행에는 1 이상의 artifact_version이 필요합니다."
        )
    version = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.version_number == requested_version,
        )
    )
    if version is None:
        raise ValueError("실행할 Artifact 버전을 찾을 수 없습니다.")
    content = storage.read_bytes(
        version.storage_key, expected_sha256=version.content_hash
    )
    if len(content) > MAX_PYTHON_SCRIPT_BYTES:
        raise ValueError("Python Artifact가 1MB 실행 제한을 초과했습니다.")
    script = _decode_python(content, label=artifact.display_name)
    filename = _safe_artifact_filename(artifact.display_name)
    return PreparedPythonExecution(
        source_type="artifact",
        files={filename: script},
        entrypoint=filename,
        module=None,
        args=args,
        stdin_json=stdin_json,
        timeout_seconds=timeout_seconds,
        source_metadata={
            "artifactId": artifact.id,
            "artifactVersion": version.version_number,
            "contentHash": version.content_hash,
        },
        executable=executable,
    )


def _prepare_skill_execution(
    db: Session,
    *,
    run: Run,
    arguments: Mapping[str, Any],
    args: tuple[str, ...],
    stdin_json: str | None,
    timeout_seconds: int,
    profile: str,
    executable: str,
) -> PreparedPythonExecution:
    requested_skill = str(arguments.get("skill_id") or "").strip()
    if not requested_skill:
        raise ValueError("Skill Python 실행에는 skill_id가 필요합니다.")
    if arguments.get("artifact_id") or arguments.get("artifact_version"):
        raise ValueError("Skill Python 실행에는 Artifact를 함께 지정할 수 없습니다.")
    skill = active_skill_snapshot(run, requested_skill)
    package = frozen_skill_package(db, skill)
    path_value = str(arguments.get("path") or "").strip()
    module_value = str(arguments.get("module") or "").strip()
    if bool(path_value) == bool(module_value):
        raise ValueError("Skill 실행에는 path 또는 module 중 하나만 지정해야 합니다.")
    if path_value:
        entrypoint = safe_skill_package_path(path_value)
        if PurePosixPath(entrypoint).suffix.casefold() != ".py":
            raise ValueError("Skill Python entrypoint는 .py 파일이어야 합니다.")
        if entrypoint not in package:
            raise ValueError(f"Skill snapshot에 Python 파일이 없습니다: {entrypoint}")
        module = None
    else:
        if not _MODULE_NAME.fullmatch(module_value):
            raise ValueError("안전하지 않은 Python module 이름입니다.")
        module_entry = PurePosixPath(*module_value.split("."))
        candidates = (
            f"{module_entry.as_posix()}.py",
            f"{module_entry.as_posix()}/__main__.py",
            f"{module_entry.as_posix()}/__init__.py",
        )
        if not any(candidate in package for candidate in candidates):
            raise ValueError(
                f"Skill snapshot에 Python module이 없습니다: {module_value}"
            )
        entrypoint = module_value
        module = module_value
    return PreparedPythonExecution(
        source_type="skill",
        files=package,
        entrypoint=entrypoint,
        module=module,
        args=args,
        stdin_json=stdin_json,
        timeout_seconds=timeout_seconds,
        source_metadata={
            "skillId": str(skill.get("extension_id", "")),
            "slug": str(skill.get("slug", "")),
            "digest": str(skill.get("digest", "")),
            **(
                {
                    "draftId": str(skill.get("draft_id", "")),
                    "draftRevision": int(skill.get("draft_revision", 0)),
                }
                if skill.get("source") == "draft"
                else {
                    "versionId": str(skill.get("version_id", "")),
                    "version": int(skill.get("version", 0)),
                }
            ),
        },
        profile=profile,
        executable=executable,
    )


async def execute_python(
    prepared: PreparedPythonExecution,
    *,
    trust_profile: TrustProfile | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    started = time.monotonic()
    temporary = tempfile.TemporaryDirectory(prefix="lumina-python-")
    try:
        root = Path(temporary.name).resolve()
        materialize_task = asyncio.create_task(
            asyncio.to_thread(_materialize, root, prepared.files)
        )
        try:
            await asyncio.shield(materialize_task)
        except asyncio.CancelledError:
            await asyncio.gather(materialize_task, return_exceptions=True)
            raise
        if prepared.module is None:
            worker = _RUN_PATH_WORKER
            target = str(root / PurePosixPath(prepared.entrypoint))
        else:
            worker = _RUN_MODULE_WORKER
            target = prepared.module
        command = [
            prepared.executable,
            "-I",
            "-B",
            "-c",
            worker,
            str(root),
            target,
            *prepared.args,
        ]
        environment = _python_environment(trust_profile)
        process = await _create_process(
            command,
            cwd=root,
            env=environment,
            pipe_stdin=prepared.stdin_json is not None,
        )
        stdin_task = (
            asyncio.create_task(
                _write_stdin(process.stdin, prepared.stdin_json.encode("utf-8"))
            )
            if prepared.stdin_json is not None
            else None
        )
        stdout_task = asyncio.create_task(_collect_output(process.stdout))
        stderr_task = asyncio.create_task(_collect_output(process.stderr))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=prepared.timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            await _terminate_process_tree(process)
        except asyncio.CancelledError:
            await _terminate_process_tree(process)
            raise
        finally:
            if stdin_task is not None:
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await stdin_task
            stdout_bytes, stdout_truncated = await stdout_task
            stderr_bytes, stderr_truncated = await stderr_task
    finally:
        await asyncio.shield(asyncio.to_thread(temporary.cleanup))
    stdout = _redact_execution_paths(_decode_output(stdout_bytes), root)
    stderr = _redact_execution_paths(_decode_output(stderr_bytes), root)
    stdout = redact_sensitive_text(stdout, secrets=secrets)
    stderr = redact_sensitive_text(stderr, secrets=secrets)
    return_code = process.returncode
    return {
        "ok": not timed_out and return_code == 0,
        "source": {
            "type": prepared.source_type,
            **dict(prepared.source_metadata),
        },
        "profile": prepared.profile,
        "entrypoint": prepared.entrypoint,
        "returnCode": return_code,
        "timedOut": timed_out,
        "timeoutSeconds": prepared.timeout_seconds,
        "durationMs": max(0, int((time.monotonic() - started) * 1000)),
        "stdout": stdout,
        "stderr": stderr,
        "stdoutTruncated": stdout_truncated,
        "stderrTruncated": stderr_truncated,
    }


def _arguments(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("args는 문자열 목록이어야 합니다.")
    if len(value) > MAX_PYTHON_ARGUMENTS:
        raise ValueError(f"Python 인자는 최대 {MAX_PYTHON_ARGUMENTS}개까지 허용합니다.")
    arguments: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Python 인자는 모두 문자열이어야 합니다.")
        if "\x00" in item or len(item) > MAX_PYTHON_ARGUMENT_CHARS:
            raise ValueError("Python 인자가 허용된 길이 또는 형식을 벗어났습니다.")
        arguments.append(item)
    return tuple(arguments)


def _input_json(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("input_json은 JSON object 문자열이어야 합니다.")
    if "\x00" in value:
        raise ValueError("input_json에 NUL byte를 포함할 수 없습니다.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("input_json이 올바른 JSON이 아닙니다.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("input_json의 최상위 값은 object여야 합니다.")
    normalized = json.dumps(
        parsed,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(normalized.encode("utf-8")) > MAX_PYTHON_INPUT_JSON_BYTES:
        raise ValueError(
            f"input_json은 UTF-8 기준 {MAX_PYTHON_INPUT_JSON_BYTES} byte 이하여야 합니다."
        )
    return normalized + "\n"


def _profile(value: Any) -> str:
    profile = str(value or "standard").strip().casefold()
    if profile not in {"standard", "heavy"}:
        raise ValueError("profile은 standard 또는 heavy여야 합니다.")
    return profile


def _timeout(
    value: Any,
    *,
    profile: str,
    policy: PythonExecutionPolicy,
) -> int:
    if value is None:
        return (
            DEFAULT_HEAVY_PYTHON_TIMEOUT_SECONDS
            if profile == "heavy"
            else DEFAULT_PYTHON_TIMEOUT_SECONDS
        )
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("timeout_seconds는 정수여야 합니다.")
    maximum = (
        policy.heavy_max_timeout_seconds
        if profile == "heavy"
        else MAX_PYTHON_TIMEOUT_SECONDS
    )
    maximum = min(maximum, ABSOLUTE_MAX_PYTHON_TIMEOUT_SECONDS)
    if not 1 <= value <= maximum:
        raise ValueError(
            f"timeout_seconds는 {profile} profile에서 1~{maximum} 범위여야 합니다."
        )
    return value


def _python_executable(value: str) -> str:
    executable = Path(value).expanduser().resolve()
    if not executable.is_file():
        raise ValueError("관리자가 설정한 Python 실행 파일을 찾을 수 없습니다.")
    return str(executable)


def _safe_artifact_filename(value: str) -> str:
    name = PurePosixPath(str(value).replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("안전하지 않은 Python Artifact 이름입니다.")
    safe_name = _SAFE_ARTIFACT_NAME.sub("_", name).strip(" .")
    if not safe_name:
        safe_name = "artifact.py"
    if not safe_name.casefold().endswith(".py"):
        safe_name += ".py"
    if PurePosixPath(safe_name).stem.casefold() in _WINDOWS_RESERVED_NAMES:
        safe_name = f"_{safe_name}"
    return safe_name[:120]


def _decode_python(content: bytes, *, label: str) -> str:
    if b"\x00" in content:
        raise ValueError(f"Python 파일에 NUL byte가 포함되어 있습니다: {label}")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"UTF-8 Python 파일이 아닙니다: {label}") from exc


def _materialize(root: Path, files: Mapping[str, str]) -> None:
    for relative, content in files.items():
        safe_relative = safe_skill_package_path(relative)
        target = (root / PurePosixPath(safe_relative)).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "Python 실행 package 경로가 임시 root를 벗어났습니다."
            ) from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        payload, encoding = decode_package_content(content)
        if encoding == "utf-8":
            target.write_text(content, encoding="utf-8", newline="\n")
        else:
            target.write_bytes(payload)


def _python_environment(trust_profile: TrustProfile | None) -> dict[str, str]:
    allowed = (
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "TEMP",
        "TMP",
        "WINDIR",
    )
    environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return (
        trust_profile.subprocess_environment(environment)
        if trust_profile is not None
        else environment
    )


async def _create_process(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    pipe_stdin: bool,
) -> asyncio.subprocess.Process:
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = int(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ) | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        options["start_new_session"] = True
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=dict(env),
        stdin=asyncio.subprocess.PIPE if pipe_stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **options,
    )


async def _write_stdin(
    stream: asyncio.StreamWriter | None,
    content: bytes,
) -> None:
    if stream is None:
        return
    try:
        stream.write(content)
        await stream.drain()
    finally:
        stream.close()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            await stream.wait_closed()


async def _collect_output(
    stream: asyncio.StreamReader | None,
) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    output = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            return bytes(output), truncated
        remaining = MAX_PYTHON_OUTPUT_BYTES - len(output)
        if remaining > 0:
            output.extend(chunk[:remaining])
        if len(chunk) > max(0, remaining):
            truncated = True


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(taskkill.wait(), timeout=5)
    else:
        kill_process_group = getattr(os, "killpg", None)
        sigkill = getattr(signal, "SIGKILL", None)
        if callable(kill_process_group) and sigkill is not None:
            with contextlib.suppress(ProcessLookupError):
                kill_process_group(process.pid, sigkill)
    if process.returncode is None:
        process.kill()
    with contextlib.suppress(ProcessLookupError):
        await process.wait()


def _decode_output(value: bytes) -> str:
    if not value:
        return ""
    candidates = ("utf-8", locale.getpreferredencoding(False), "cp949")
    replacements: list[str] = []
    for encoding in dict.fromkeys(item for item in candidates if item):
        try:
            return value.decode(encoding).replace("\r\n", "\n")
        except (LookupError, UnicodeDecodeError):
            with contextlib.suppress(LookupError):
                replacements.append(value.decode(encoding, errors="replace"))
    decoded = min(replacements, key=lambda item: item.count("\ufffd"))
    return decoded.replace("\r\n", "\n")


def _redact_execution_paths(value: str, root: Path) -> str:
    redacted = value
    for rendered in {str(root), root.as_posix()}:
        if rendered:
            redacted = redacted.replace(rendered, "<python-workdir>")
    return redacted


__all__ = [
    "PYTHON_EXECUTION_TOOL_SCHEMA",
    "PreparedPythonExecution",
    "PythonExecutionPolicy",
    "execute_python",
    "prepare_python_execution",
]
