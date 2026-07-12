from __future__ import annotations

import json
import os
import shutil
import subprocess
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
        command.write_text(script, encoding="utf-8")
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
