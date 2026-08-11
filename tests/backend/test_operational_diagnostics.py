from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import certifi
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from lumina.config import Settings
from lumina.diagnostics.cli import main as diagnostics_main
from lumina.diagnostics.environment import DiagnosticEnvironment
from lumina.diagnostics.service import run_diagnostics
from lumina.main import create_app
from lumina.observability import structured_event


def _pgpt_environment() -> DiagnosticEnvironment:
    return DiagnosticEnvironment(
        pgpt_api_key=SecretStr("api-key-must-not-leak"),
        pgpt_employee_no=SecretStr("employee-must-not-leak"),
        pgpt_company_code=SecretStr("company-must-not-leak"),
        pgpt_base_url="https://pgpt.example.test/v1",
    )


def test_no_network_pgpt_diagnostics_are_staged_and_redacted(
    tmp_path: Path, monkeypatch
) -> None:
    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("no-network diagnostics attempted a network call")

    monkeypatch.setattr(
        "lumina.diagnostics.service.socket.getaddrinfo", unexpected_network
    )
    report = run_diagnostics(
        environment=_pgpt_environment(),
        repo_root=tmp_path,
        network=False,
        check_pgpt=True,
    )

    assert report.ok
    by_stage = {step.stage: step for step in report.steps}
    assert by_stage["public_ca"].status == "passed"
    assert by_stage["company_ca"].status == "skipped"
    assert by_stage["credentials"].status == "passed"
    for stage in ("dns", "connect", "tls", "authentication", "endpoint", "provider"):
        assert by_stage[stage].status == "skipped"

    serialized = json.dumps(report.as_dict(), ensure_ascii=False)
    for secret in (
        "api-key-must-not-leak",
        "employee-must-not-leak",
        "company-must-not-leak",
        "https://pgpt.example.test/v1",
    ):
        assert secret not in serialized


def test_company_ca_relative_path_and_invalid_ca_are_reported(tmp_path: Path) -> None:
    certificate_dir = tmp_path / "certs"
    certificate_dir.mkdir()
    valid_ca = certificate_dir / "company-ca.crt"
    valid_ca.write_bytes(Path(certifi.where()).read_bytes())
    valid = run_diagnostics(
        environment=DiagnosticEnvironment(lumina_ca_cert="certs/company-ca.crt"),
        repo_root=tmp_path,
        network=False,
        require_company_ca=True,
    )
    assert valid.ok
    assert (tmp_path / "data" / "certs" / "runtime" / "combined-ca.pem").is_file()

    compatible = run_diagnostics(
        environment=DiagnosticEnvironment(
            lumina_ca_cert="certs/company-ca.crt",
            lumina_tls_compat_mode=True,
        ),
        repo_root=tmp_path,
        network=False,
        require_company_ca=True,
    )
    trust_step = next(step for step in compatible.steps if step.stage == "trust_bundle")
    assert "compatibility mode is active" in trust_step.message

    invalid_ca = certificate_dir / "invalid.crt"
    invalid_ca.write_text("not a PEM certificate", encoding="utf-8")
    invalid = run_diagnostics(
        environment=DiagnosticEnvironment(lumina_ca_cert=str(invalid_ca)),
        repo_root=tmp_path,
        network=False,
        require_company_ca=True,
    )
    assert not invalid.ok
    by_stage = {step.stage: step for step in invalid.steps}
    assert by_stage["company_ca"].status == "failed"
    assert by_stage["trust_bundle"].status == "failed"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    (
        (200, {"authentication": "passed", "endpoint": "passed", "provider": "passed"}),
        (
            401,
            {"authentication": "failed", "endpoint": "skipped", "provider": "skipped"},
        ),
        (
            404,
            {"authentication": "passed", "endpoint": "failed", "provider": "skipped"},
        ),
        (503, {"authentication": "passed", "endpoint": "passed", "provider": "failed"}),
    ),
)
def test_opt_in_pgpt_probe_classifies_failure_stage(
    tmp_path: Path,
    monkeypatch,
    status_code: int,
    expected: dict[str, str],
) -> None:
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    environment = DiagnosticEnvironment(
        pgpt_api_key=SecretStr("network-api-key"),
        pgpt_employee_no=SecretStr("network-employee"),
        pgpt_company_code=SecretStr("network-company"),
        pgpt_base_url="http://pgpt.example.test/v1",
    )
    monkeypatch.setattr(
        "lumina.diagnostics.service.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, None)],
    )
    monkeypatch.setattr(
        "lumina.diagnostics.service.socket.create_connection",
        lambda *_args, **_kwargs: FakeConnection(),
    )
    monkeypatch.setattr(
        "lumina.diagnostics.service._pgpt_probe",
        lambda **_kwargs: httpx.Response(status_code),
    )

    report = run_diagnostics(
        environment=environment,
        repo_root=tmp_path,
        network=True,
        check_pgpt=True,
    )
    by_stage = {step.stage: step.status for step in report.steps}
    assert by_stage["dns"] == "passed"
    assert by_stage["connect"] == "passed"
    assert by_stage["tls"] == "skipped"
    for stage, expected_status in expected.items():
        assert by_stage[stage] == expected_status


def test_diagnostics_cli_exit_code_and_output_do_not_leak_credentials(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    for key in (
        "PGPT_API_KEY",
        "PGPT_EMPLOYEE_NO",
        "PGPT_COMPANY_CODE",
        "PGPT_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "PGPT_API_KEY=cli-api-key-must-not-leak",
                "PGPT_EMPLOYEE_NO=cli-employee-must-not-leak",
                "PGPT_COMPANY_CODE=cli-company-must-not-leak",
                "PGPT_BASE_URL=https://pgpt.example.test/v1",
            )
        ),
        encoding="utf-8",
    )
    exit_code = diagnostics_main(
        [
            "--repo-root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "--no-network",
            "--pgpt",
            "--json",
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(output)["ok"] is True
    for secret in (
        "cli-api-key-must-not-leak",
        "cli-employee-must-not-leak",
        "cli-company-must-not-leak",
        "https://pgpt.example.test/v1",
    ):
        assert secret not in output

    missing = diagnostics_main(
        [
            "--repo-root",
            str(tmp_path),
            "--env-file",
            str(tmp_path / "missing"),
            "--no-network",
            "--pgpt",
        ]
    )
    assert missing == 1


def test_diagnostics_cli_can_explicitly_skip_dotenv_for_offline_postgres(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite:///must-not-win.db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://lumina:offline@127.0.0.1/lumina",
    )

    exit_code = diagnostics_main(
        [
            "--repo-root",
            str(tmp_path),
            "--no-env-file",
            "--no-network",
            "--database",
            "--require-postgres",
            "--json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True
    assert any(
        step["stage"] == "database_config"
        and step["status"] == "passed"
        and "postgresql" in step["message"]
        for step in output["steps"]
    )


def test_health_readiness_and_structured_redaction_regression(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'health.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        live = client.get("/api/health/live")
        ready = client.get("/api/health/ready")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ok",
        "database": "ready",
        "executor": "ready",
    }

    log_line = structured_event(
        "diagnostic_test",
        pgpt_api_key="api-key-value",
        employee_no="employee-value",
        company_code="company-value",
        nested={"secret_ref": "vault://must-not-leak"},
    )
    for secret in (
        "api-key-value",
        "employee-value",
        "company-value",
        "vault://must-not-leak",
    ):
        assert secret not in log_line


def test_powershell_env_update_preserves_unrelated_values(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KEEP_ME=original\nPGPT_API_KEY=old-value\n",
        encoding="utf-8",
    )
    helper = Path(__file__).resolve().parents[2] / "devtools" / "LuminaInstall.Env.ps1"
    command = (
        f". '{helper}'; "
        f"Set-LuminaDotEnvValue -Path '{env_file}' -Key 'PGPT_API_KEY' "
        "-Value 'new-fake$secret with space'"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "new-fake$secret with space" not in completed.stdout
    updated = env_file.read_text(encoding="utf-8")
    assert "KEEP_ME=original" in updated
    assert 'PGPT_API_KEY="new-fake$secret with space"' in updated


def test_powershell_env_reader_does_not_consume_the_next_key(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LUMINA_CA_CERT=\nLUMINA_CA_BUNDLE=C:/runtime/combined-ca.pem\n",
        encoding="utf-8",
    )
    helper = Path(__file__).resolve().parents[2] / "devtools" / "LuminaInstall.Env.ps1"
    command = (
        f". '{helper}'; "
        f"$value = Get-LuminaDotEnvValue -Path '{env_file}' -Key 'LUMINA_CA_CERT'; "
        "Write-Output ('<' + $value + '>')"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "<>"


@pytest.mark.skipif(os.name != "nt", reason="Windows native module locks")
def test_installer_frontend_lock_check_reports_locked_native_module(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")
    native_module = tmp_path / "node_modules" / "binding.node"
    native_module.parent.mkdir()
    native_module.write_bytes(b"fixture")
    helper = (
        Path(__file__).resolve().parents[2]
        / "devtools"
        / "LuminaInstall.Frontend.ps1"
    )
    command = (
        f". '{helper}'; "
        f"$lock = [System.IO.File]::Open('{native_module}', 'Open', 'Read', 'None'); "
        f"try {{ Assert-LuminaFrontendNativeModulesUnlocked -WebRoot '{tmp_path}' }} "
        "finally { $lock.Dispose() }"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "locked native module" in output
    assert "binding.node" in output


def test_codegraph_update_is_portable_and_reindexes_after_cli_upgrades() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "devtools" / "update_codegraph.ps1"
    ).read_text(encoding="utf-8")

    assert "git rev-parse" not in script
    assert "codegraph.Source sync" in script
    assert "reindexRecommended" in script
    assert "codegraph.Source index" in script
    assert script.index("Get-Command codegraph.cmd") < script.index(
        "Get-Command codegraph.exe"
    )
    assert script.index("Get-Command codegraph.exe") < script.index(
        "Get-Command codegraph -ErrorAction"
    )
    assert "npm.cmd install -g @colbymchenry/codegraph" in script

    agent_guidance = (
        Path(__file__).resolve().parents[2] / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "codegraph_explore" in agent_guidance
    assert "개별 도구가 없다는 이유로 연결 실패로 판단하지 않습니다" in agent_guidance


def test_installer_validate_only_forces_offline_uv(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    capture = tmp_path / "invocations.txt"
    if os.name == "nt":
        suffix = ".cmd"
        script = (
            '@echo off\r\n>>"%LUMINA_INSTALL_TEST_CAPTURE%" echo %*\r\nexit /b 0\r\n'
        )
    else:
        suffix = ""
        script = (
            '#!/usr/bin/env sh\nprintf "%s\\n" "$*" >> "$LUMINA_INSTALL_TEST_CAPTURE"\n'
        )
    for command_name in ("uv", "node", "npm"):
        command = tmp_path / f"{command_name}{suffix}"
        command_script = script
        if command_name == "node":
            command_script = (
                '@echo off\r\n>>"%LUMINA_INSTALL_TEST_CAPTURE%" echo %*\r\n'
                'echo v22.12.0\r\nexit /b 0\r\n'
            ) if os.name == "nt" else (
                '#!/usr/bin/env sh\nprintf "%s\\n" "$*" >> "$LUMINA_INSTALL_TEST_CAPTURE"\nprintf "v22.12.0\\n"\n'
            )
        command.write_text(command_script, encoding="utf-8")
        command.chmod(0o700)

    installer = Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment.get('PATH', '')}"
    environment["LUMINA_INSTALL_TEST_CAPTURE"] = str(capture)
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-NonInteractive",
            "-SkipPgpt",
            "-NoNetwork",
            "-ValidateOnly",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    invocation = capture.read_text(encoding="utf-8")
    assert "run --offline --project" in invocation


@pytest.mark.skipif(os.name != "nt", reason="Windows batch entrypoint")
def test_installer_batch_keeps_failure_visible_and_preserves_exit_code(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    installer = repository_root / "installer.bat"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "powershell.cmd").write_text(
        "@echo off\r\necho simulated installer failure\r\nexit /b 7\r\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}"
    completed = subprocess.run(
        ["cmd", "/d", "/c", str(installer)],
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    assert completed.returncode == 7
    assert "simulated installer failure" in completed.stdout
    assert "Lumina installation failed" in completed.stdout
    assert "Press any key" in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows batch entrypoint")
def test_installer_batch_keeps_success_visible_until_keypress(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    installer = repository_root / "installer.bat"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "powershell.cmd").write_text(
        "@echo off\r\necho simulated installer success\r\nexit /b 0\r\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}"
    completed = subprocess.run(
        ["cmd", "/d", "/c", str(installer)],
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    assert completed.returncode == 0
    assert "simulated installer success" in completed.stdout
    assert "Lumina installation completed successfully" in completed.stdout
    assert "Press any key" in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows batch entrypoint")
def test_development_launcher_keeps_failure_visible_and_preserves_exit_code(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    launcher = repository_root / "run_lumina_dev.bat"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "powershell.cmd").write_text(
        "@echo off\r\necho simulated development failure\r\nexit /b 9\r\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}"
    completed = subprocess.run(
        ["cmd", "/d", "/c", str(launcher)],
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    assert completed.returncode == 9
    assert "simulated development failure" in completed.stdout
    assert "Development launcher failed with exit code 9" in completed.stdout
    assert "run_lumina_dev.state.json" in completed.stdout
    assert "Press R to restart. Press any other key to close this window." in completed.stdout


def test_runtime_bootstrap_uses_migrated_schema_without_create_all() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "server"
        / "src"
        / "lumina"
        / "main.py"
    ).read_text(encoding="utf-8")

    assert (
        "with session_scope() as db:\n                bootstrap_database(db, settings=config)"
        in source
    )


def test_installer_missing_uv_offline_error_includes_install_guidance(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    suffix = ".cmd" if os.name == "nt" else ""
    shim = "@echo off\r\nexit /b 0\r\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n"
    for command_name in ("node", "npm"):
        command = tmp_path / f"{command_name}{suffix}"
        command.write_text(shim, encoding="utf-8")
        command.chmod(0o700)

    installer = Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path)
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-NonInteractive",
            "-SkipPgpt",
            "-NoNetwork",
            "-ValidateOnly",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "uv was not found on PATH" in output
    assert "cannot be installed while -NoNetwork is active" in output
    assert "astral.sh/uv/install.ps1" in output


def test_installer_bootstraps_missing_uv_with_official_command() -> None:
    installer = (
        Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    ).read_text(encoding="utf-8")

    assert 'Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1"' in installer
    assert "Invoke-Expression $installScript" in installer
    assert 'Join-Path $HOME ".local\\bin"' in installer
    assert "$env:UV_INSTALL_DIR = $installDirectory" in installer
    assert '$env:PATH = "$installDirectory;$env:PATH"' in installer


def test_installer_makes_codex_provider_dependency_opt_in() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    installer = (repository_root / "devtools" / "install_lumina.ps1").read_text(
        encoding="utf-8"
    )
    pyproject = (repository_root / "apps" / "server" / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    core_dependencies, optional_dependencies = pyproject.split(
        "[project.optional-dependencies]", maxsplit=1
    )
    assert "openai-codex" not in core_dependencies
    assert 'codex = ["openai-codex>=0.1.0b2,<0.2"]' in optional_dependencies
    assert '[switch]$InstallCodex' in installer
    assert '[switch]$SkipCodex' in installer
    assert 'Install the optional Codex Provider support? [y/N]' in installer
    assert '$pythonInstallArguments += @("--extra", "codex")' in installer
    assert '$enableCodex = [bool]$InstallCodex' in installer


def test_server_imports_when_optional_codex_dependency_is_missing() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "apps" / "server" / "src"
    script = r'''
import asyncio
import builtins

real_import = builtins.__import__

def without_codex(name, *args, **kwargs):
    if name == "openai_codex" or name.startswith("openai_codex."):
        raise ModuleNotFoundError(
            "No module named 'openai_codex'", name="openai_codex"
        )
    return real_import(name, *args, **kwargs)

builtins.__import__ = without_codex

from lumina.providers.codex import CodexResponsesAdapter, codex_oauth_available
from lumina.providers.errors import ProviderConfigurationError
from lumina.main import create_app

assert codex_oauth_available() is False
assert callable(create_app)

async def verify_unavailable_adapter():
    adapter = CodexResponsesAdapter()
    try:
        await adapter.warmup()
    except ProviderConfigurationError as exc:
        assert "installer.bat -InstallCodex" in str(exc)
    else:
        raise AssertionError("missing Codex dependency must be reported")
    await adapter.close()

asyncio.run(verify_unavailable_adapter())
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_installer_enables_uv_system_certificates_before_uv_network_work() -> None:
    installer = (
        Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    ).read_text(encoding="utf-8")

    assert '$env:UV_SYSTEM_CERTS = "true"' in installer
    assert "Assert-NodeVersion\nEnable-UvSystemCertificates\n" in installer
    assert installer.index("Enable-UvSystemCertificates\n$NpmCommand") < installer.index(
        'Invoke-Checked -Command "uv"'
    )


def test_installer_rejects_node_version_too_old_for_vite(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")
    if os.name != "nt":
        pytest.skip("Windows command shims are used by the installer entrypoint")

    (tmp_path / "uv.cmd").write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    (tmp_path / "npm.cmd").write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    (tmp_path / "node.cmd").write_text("@echo off\r\necho v18.20.0\r\n", encoding="utf-8")
    installer = Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path)
    completed = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer), "-NonInteractive", "-SkipPgpt", "-ValidateOnly"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "Node.js 20.19.0 or newer is required" in output
    assert "nodejs.org" in output


def test_installer_ignores_missing_saved_optional_company_ca(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")
    if os.name != "nt":
        pytest.skip("Windows command shims are used by the installer entrypoint")

    capture = tmp_path / "invocations.txt"
    shim = (
        '@echo off\r\n'
        '>>"%LUMINA_INSTALL_TEST_CAPTURE%" echo %~n0 %*\r\n'
        'if /I "%~n0"=="node" echo v22.12.0\r\n'
        'exit /b 0\r\n'
    )
    for command_name in ("uv", "node", "npm"):
        (tmp_path / f"{command_name}.cmd").write_text(shim, encoding="utf-8")

    installer = Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment.get('PATH', '')}"
    environment["LUMINA_INSTALL_TEST_CAPTURE"] = str(capture)
    environment["LUMINA_CA_CERT"] = str(tmp_path / "office-only-company-ca.crt")
    environment.pop("LUMINA_CA_BUNDLE", None)
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-NonInteractive",
            "-SkipPgpt",
            "-SkipDependencyInstall",
            "-SkipFrontendBuild",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "Saved company CA path was not found" in output
    assert "Continuing with public CA trust" in output


def test_installer_uses_npm_cmd_instead_of_npm_ps1_on_windows(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not installed")
    if os.name != "nt":
        pytest.skip("npm.cmd and npm.ps1 precedence is Windows-specific")

    capture = tmp_path / "invocations.txt"
    (tmp_path / "uv.cmd").write_text(
        '@echo off\r\n>>"%LUMINA_INSTALL_TEST_CAPTURE%" echo uv %*\r\nexit /b 0\r\n',
        encoding="utf-8",
    )
    (tmp_path / "node.cmd").write_text(
        "@echo off\r\necho v22.12.0\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    (tmp_path / "npm.ps1").write_text(
        'Write-Error "npm.ps1 must not be invoked by the installer"\nexit 9\n',
        encoding="utf-8",
    )
    (tmp_path / "npm.cmd").write_text(
        '@echo off\r\n>>"%LUMINA_INSTALL_TEST_CAPTURE%" echo npm.cmd %*\r\nexit /b 0\r\n',
        encoding="utf-8",
    )

    installer = Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment.get('PATH', '')}"
    environment["LUMINA_INSTALL_TEST_CAPTURE"] = str(capture)
    environment.pop("LUMINA_CA_CERT", None)
    environment.pop("LUMINA_CA_BUNDLE", None)
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-NonInteractive",
            "-SkipPgpt",
            "-InstallCodex",
            "-SkipFrontendBuild",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    invocation = capture.read_text(encoding="utf-8")
    assert "uv sync --project" in invocation
    assert "--python 3.13 --extra codex" in invocation
    assert invocation.count("npm.cmd ci --prefix") == 2
    assert "extensions\\mcp\\korea-weather\\runtime" in invocation
    assert "national-assembly\\runtime\\bootstrap.py --install-only" in invocation


def test_national_assembly_bootstrap_pins_upstream_revision() -> None:
    bootstrap = (
        Path(__file__).resolve().parents[2]
        / "extensions"
        / "mcp"
        / "national-assembly"
        / "runtime"
        / "bootstrap.py"
    ).read_text(encoding="utf-8")

    assert 'REPO_REVISION = "f74c6b452c59d87e2fa7265fd985b90e4057a8ef"' in bootstrap
    assert 'Path(".cache") / "mcp" / "assembly-api-mcp"' in bootstrap
    assert '["git", "clone", "--depth", "1", REPO_URL' in bootstrap
    assert '["git", "checkout", "--detach", REPO_REVISION]' in bootstrap
    assert 'install_only = "--install-only" in sys.argv[1:]' in bootstrap

    installer = (
        Path(__file__).resolve().parents[2] / "devtools" / "install_lumina.ps1"
    ).read_text(encoding="utf-8")
    assert 'Assert-Command "git"' in installer
