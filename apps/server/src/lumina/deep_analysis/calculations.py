from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import ProjectFile, ProjectFileVersion, Run, User
from ..project_files.service import (
    create_project_file,
    create_project_file_version,
    logical_path_key,
    get_project_file_version,
)
from ..storage import ManagedStorage


MAX_SCRIPT_CHARS = 50_000
MAX_INPUT_BYTES = 2_000_000
MAX_INPUT_ROWS = 50_000
MAX_OUTPUT_ROWS = 50_000
MAX_OUTPUT_COLUMNS = 200
CALCULATION_TIMEOUT_SECONDS = 12
MAX_STATIC_INTEGER = 100_000

PYTHON_CALCULATION_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_python_calculation",
        "description": (
            "Run a bounded, reproducible numeric calculation for a deep-analysis Node. "
            "CSV inputs are exposed as INPUTS[path], a list of string-valued row dictionaries. "
            "The script must assign a list of dictionaries to RESULT_ROWS. Imports, file/network "
            "access, dynamic code execution, and private attributes are blocked. The exact .py "
            "script and resulting .csv are saved in the Mission Project-file directory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                    "description": "Short descriptive filename, with or without .py.",
                },
                "result_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                    "description": "Short descriptive filename, with or without .csv.",
                },
                "input_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 30,
                    "description": "CSV Project-file paths from the fixed Run manifest.",
                },
                "script": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_SCRIPT_CHARS,
                    "description": (
                        "Python body. Read INPUTS and assign RESULT_ROWS. Available helpers: "
                        "sum, min, max, round, abs, len, range, enumerate, zip, sorted, int, "
                        "float, str, bool, list, dict, set, tuple, math, statistics, Decimal."
                    ),
                },
            },
            "required": ["script_name", "result_name", "input_paths", "script"],
            "additionalProperties": False,
        },
    },
}


_BLOCKED_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "help",
    "dir",
    "type",
    "object",
    "super",
}
_SAFE_FILE_STEM = re.compile(r"[^0-9A-Za-z가-힣._ -]+")


_WORKER = r'''
import json, math, statistics, sys
from decimal import Decimal

payload = json.loads(sys.stdin.read())
safe_builtins = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "float": float, "int": int, "len": len,
    "list": list, "max": max, "min": min, "range": range, "round": round,
    "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
    "zip": zip,
}
scope = {
    "__builtins__": safe_builtins,
    "INPUTS": payload["inputs"],
    "math": math,
    "statistics": statistics,
    "Decimal": Decimal,
}
exec(compile(payload["script"], "calculation.py", "exec"), scope, scope)
rows = scope.get("RESULT_ROWS")
if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
    raise ValueError("RESULT_ROWS must be a list of dictionaries")
sys.stdout.write(json.dumps({"rows": rows}, ensure_ascii=False, default=str))
'''


def _static_integer(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _static_integer(node.operand)
        if value is None:
            return None
        return value if isinstance(node.op, ast.UAdd) else -value
    if not isinstance(node, ast.BinOp):
        return None
    left = _static_integer(node.left)
    right = _static_integer(node.right)
    if left is None or right is None:
        return None
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        if left and abs(right) > MAX_STATIC_INTEGER // min(abs(left), MAX_STATIC_INTEGER):
            return MAX_STATIC_INTEGER + 1
        return left * right
    if isinstance(node.op, ast.Pow):
        if right < 0 or right > 20 or abs(left) > MAX_STATIC_INTEGER:
            return MAX_STATIC_INTEGER + 1
        return left**right
    if isinstance(node.op, ast.FloorDiv) and right:
        return left // right
    return None


def _validate_script(script: str) -> None:
    if len(script) > MAX_SCRIPT_CHARS:
        raise ValueError("Python 계산식이 허용된 길이를 초과했습니다.")
    try:
        tree = ast.parse(script, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Python 계산식 문법 오류: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise ValueError("Python 계산식에서는 import와 전역 범위 변경을 사용할 수 없습니다.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Python 계산식에서는 private 속성에 접근할 수 없습니다.")
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ValueError(f"Python 계산식에서 {node.id}을(를) 사용할 수 없습니다.")
        static_integer = _static_integer(node)
        if static_integer is not None and abs(static_integer) > MAX_STATIC_INTEGER:
            raise ValueError("Python 계산식의 정적 정수 또는 반복 크기가 너무 큽니다.")


def _safe_name(value: Any, suffix: str, fallback: str) -> str:
    name = PurePosixPath(str(value or "").replace("\\", "/")).name.strip()
    name = _SAFE_FILE_STEM.sub("_", name).strip(" ._")
    if not name:
        name = fallback
    if not name.casefold().endswith(suffix):
        name += suffix
    return name[:120]


def _manifest_versions(run: Run) -> dict[str, dict[str, Any]]:
    manifest = run.snapshot_json.get("project_file_manifest", [])
    return {
        str(item.get("logicalPath")): dict(item)
        for item in manifest
        if isinstance(item, dict) and item.get("logicalPath") and item.get("versionId")
    }


def _load_inputs(
    db: Session,
    storage: ManagedStorage,
    *,
    run: Run,
    input_paths: list[str],
) -> dict[str, list[dict[str, str]]]:
    manifest = _manifest_versions(run)
    total_bytes = 0
    total_rows = 0
    inputs: dict[str, list[dict[str, str]]] = {}
    for raw_path in input_paths:
        path = str(raw_path).strip()
        snapshot = manifest.get(path)
        if snapshot is None:
            raise ValueError(f"고정 입력 manifest에 없는 파일입니다: {path}")
        if not path.casefold().endswith(".csv"):
            raise ValueError(f"Python 계산 입력은 CSV만 지원합니다: {path}")
        version = db.get(ProjectFileVersion, str(snapshot["versionId"]))
        if (
            version is None
            or version.content_hash != snapshot.get("contentHash")
            or version.project_file_id != snapshot.get("projectFileId")
        ):
            raise ValueError(f"고정 입력 버전을 확인할 수 없습니다: {path}")
        content = storage.read_bytes(
            version.storage_key, expected_sha256=version.content_hash
        )
        total_bytes += len(content)
        if total_bytes > MAX_INPUT_BYTES:
            raise ValueError("Python 계산 입력 CSV의 합계 크기가 2MB를 초과했습니다.")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"UTF-8 CSV가 아닙니다: {path}") from exc
        rows = [dict(row) for row in csv.DictReader(io.StringIO(text))]
        total_rows += len(rows)
        if total_rows > MAX_INPUT_ROWS:
            raise ValueError("Python 계산 입력 행 수가 50,000개를 초과했습니다.")
        inputs[path] = rows
    return inputs


def _run_script(script: str, inputs: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    _validate_script(script)
    payload = json.dumps({"script": script, "inputs": inputs}, ensure_ascii=False)
    environment = {"PYTHONIOENCODING": "utf-8"}
    if os.name == "nt" and os.environ.get("SystemRoot"):
        environment["SystemRoot"] = os.environ["SystemRoot"]
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with tempfile.TemporaryDirectory(prefix="lumina-calc-") as workdir:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed interpreter and worker
                [sys.executable, "-I", "-S", "-c", _WORKER],
                input=payload,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=environment,
                shell=False,
                timeout=CALCULATION_TIMEOUT_SECONDS,
                creationflags=creation_flags,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Python 계산이 12초 제한시간을 초과했습니다.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "Python 계산 실행 실패").strip()[-2_000:]
        raise ValueError(detail)
    try:
        rows = json.loads(completed.stdout).get("rows")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("Python 계산 결과를 해석할 수 없습니다.") from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("RESULT_ROWS는 dictionary 목록이어야 합니다.")
    if len(rows) > MAX_OUTPUT_ROWS:
        raise ValueError("Python 계산 결과가 50,000행을 초과했습니다.")
    columns = {str(key) for row in rows for key in row}
    if len(columns) > MAX_OUTPUT_COLUMNS:
        raise ValueError("Python 계산 결과가 200열을 초과했습니다.")
    return [dict(row) for row in rows]


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            label = str(key)
            if label not in seen:
                seen.add(label)
                columns.append(label)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    if columns:
        writer.writeheader()
        writer.writerows({str(key): value for key, value in row.items()} for row in rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _upsert_file(
    db: Session,
    storage: ManagedStorage,
    *,
    run: Run,
    user: User,
    path: str,
    content: bytes,
    max_upload_bytes: int,
) -> tuple[ProjectFile, ProjectFileVersion]:
    existing = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == run.project_id,
            ProjectFile.active_path_key == logical_path_key(path),
            ProjectFile.deleted_at.is_(None),
        )
    )
    if existing is None:
        project_file, version = create_project_file(
            db,
            user=user,
            project_id=run.project_id,
            logical_path=path,
            original_filename=PurePosixPath(path).name,
            content=content,
            change_reason="심층분석 Python 계산 산출물",
            max_upload_bytes=max_upload_bytes,
            storage=storage,
        )
        version.source_run_id = run.id
        return project_file, version
    current = get_project_file_version(db, existing)
    if current.content_hash == hashlib.sha256(content).hexdigest():
        return existing, current
    return create_project_file_version(
        db,
        user=user,
        project_id=run.project_id,
        file_id=existing.id,
        base_version=existing.current_version_number,
        original_filename=PurePosixPath(path).name,
        content=content,
        change_reason="심층분석 Python 계산 재실행",
        source_run_id=run.id,
        max_upload_bytes=max_upload_bytes,
        storage=storage,
    )


def execute_python_calculation(
    db: Session,
    storage: ManagedStorage,
    *,
    run: Run,
    user: User,
    arguments: dict[str, Any],
    max_upload_bytes: int,
) -> dict[str, Any]:
    deep_analysis = run.snapshot_json.get("deep_analysis")
    if not isinstance(deep_analysis, dict):
        raise ApiProblem(403, "deep_analysis_only", "심층분석 Run에서만 사용할 수 있습니다.")
    output_dir = str(deep_analysis.get("output_directory") or "").strip("/")
    node_key = str(deep_analysis.get("node_key") or "Node")
    if not output_dir:
        raise ValueError("심층분석 출력 경로가 없습니다.")
    script = str(arguments.get("script") or "")
    raw_input_paths = arguments.get("input_paths")
    if not isinstance(raw_input_paths, list):
        raise ValueError("input_paths는 목록이어야 합니다.")
    input_paths = [str(item) for item in raw_input_paths]
    inputs = _load_inputs(db, storage, run=run, input_paths=input_paths)
    rows = _run_script(script, inputs)

    script_name = _safe_name(arguments.get("script_name"), ".py", "calculation.py")
    result_name = _safe_name(arguments.get("result_name"), ".csv", "result.csv")
    script_path = f"{output_dir}/{node_key}_{script_name}"
    result_path = f"{output_dir}/{node_key}_{result_name}"
    script_file, script_version = _upsert_file(
        db,
        storage,
        run=run,
        user=user,
        path=script_path,
        content=script.encode("utf-8"),
        max_upload_bytes=max_upload_bytes,
    )
    result_file, result_version = _upsert_file(
        db,
        storage,
        run=run,
        user=user,
        path=result_path,
        content=_csv_bytes(rows),
        max_upload_bytes=max_upload_bytes,
    )
    files = [
        {
            "projectFileId": script_file.id,
            "path": script_file.logical_path,
            "version": script_version.version_number,
            "contentHash": script_version.content_hash,
            "kind": "python",
        },
        {
            "projectFileId": result_file.id,
            "path": result_file.logical_path,
            "version": result_version.version_number,
            "contentHash": result_version.content_hash,
            "kind": "csv",
        },
    ]
    return {
        "files": files,
        "inputPaths": input_paths,
        "rowCount": len(rows),
        "columnCount": len({str(key) for row in rows for key in row}),
        "previewRows": rows[:50],
        "previewTruncated": len(rows) > 50,
        "message": "검증된 Python 계산과 CSV 결과를 Project 파일로 저장했습니다.",
    }
