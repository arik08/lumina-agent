from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.deep_analysis.calculations import execute_python_calculation
from lumina.deep_analysis.models import (
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)
from lumina.main import create_app
from lumina.models import Organization, ProjectFile, Run, User
from lumina.storage import ManagedLocalStorage


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _create_viewer() -> dict[str, str]:
    with SessionLocal() as db:
        organization_id = db.scalar(
            select(Organization.id).where(Organization.slug == "posco")
        )
        assert organization_id is not None
        user = create_user(
            db,
            login_name="deep-analysis-viewer",
            password="password",
            organization_id=organization_id,
            display_name="Deep Analysis Viewer",
            role="user",
            status="active",
        )
        db.commit()
        return {"id": user.id, "loginId": user.login_id}


def _login_viewer(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "deep-analysis-viewer",
            "loginDomain": "posco.com",
            "password": "password",
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def test_mission_workflow_persists_and_uses_revision_cas(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "전사 영업원가 변동 원인 분석",
                "objective": "전년 대비 영업원가 변동의 핵심 원인을 정량적으로 설명한다.",
                "autonomyMode": "balanced",
            },
        )
        assert created.status_code == 201, created.text
        mission = created.json()
        assert mission["revision"] == 1
        assert mission["executionAvailable"] is True
        assert mission["spentMicrousd"] == 0
        assert mission["workflow"]["revisionNumber"] == 1
        assert [node["nodeKey"] for node in mission["workflow"]["nodes"]] == [
            "N001",
            "N010",
            "N020",
            "N030",
            "N040",
        ]
        assert len(mission["workflow"]["edges"]) == 4

        listing = client.get(f"/api/projects/{project_id}/deep-analysis/missions")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [mission["id"]]

        restored = client.get(f"/api/deep-analysis/missions/{mission['id']}")
        assert restored.status_code == 200
        assert (
            restored.json()["workflow"]["graphDigest"]
            == mission["workflow"]["graphDigest"]
        )

        updated = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={"expectedRevision": 1, "autonomyMode": "guided"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2
        assert updated.json()["autonomyMode"] == "guided"

        stale = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={"expectedRevision": 1, "title": "충돌하는 변경"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"
        assert stale.json()["details"] == {"currentRevision": 2}


def test_mission_endpoints_require_auth_and_project_access(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert (
            client.get("/api/projects/missing/deep-analysis/missions").status_code
            == 401
        )
        headers = _login(client)
        denied = client.post(
            "/api/projects/missing/deep-analysis/missions",
            headers=headers,
            json={"title": "접근 불가"},
        )
        assert denied.status_code == 404


def test_mission_executes_all_nodes_and_persists_markdown_outputs(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "실행 가능한 분석",
                "objective": "실제 Run을 거쳐 Node별 Markdown을 생성한다.",
            },
        ).json()

        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["workflow"]["nodes"][0]["runId"] is not None

        deadline = time.monotonic() + 10
        restored = started.json()
        while time.monotonic() < deadline and restored["status"] == "running":
            time.sleep(0.1)
            restored = client.get(f"/api/deep-analysis/missions/{created['id']}").json()

        assert restored["status"] == "completed"
        assert all(
            node["status"] == "completed" for node in restored["workflow"]["nodes"]
        )
        assert all(node["runId"] for node in restored["workflow"]["nodes"])
        assert all(node["outputMarkdown"] for node in restored["workflow"]["nodes"])
        assert all(
            node["outputLogicalPath"].startswith("심층분석/실행 가능한 분석_")
            for node in restored["workflow"]["nodes"]
        )
        assert restored["completionContract"]["finalOutputPath"].endswith(
            "N040_최종 보고서.md"
        )

        visible_conversations = client.get(
            f"/api/conversations?project_id={project_id}"
        ).json()["items"]
        assert all(
            item["title"] != "심층분석 · 실행 가능한 분석"
            for item in visible_conversations
        )


def test_mission_delete_checks_revision_and_cascades_workflow(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        mission = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "삭제할 분석"},
        ).json()
        workflow_id = mission["workflow"]["id"]
        node_ids = [node["id"] for node in mission["workflow"]["nodes"]]
        edge_ids = [edge["id"] for edge in mission["workflow"]["edges"]]
        output_path = (
            f"심층분석/삭제할 분석_{mission['id'][:8]}/N001_목표·범위 확정.md"
        )
        output = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": output_path, "changeReason": "삭제 연동 검증"},
            files={
                "file": (
                    "N001_목표·범위 확정.md",
                    "# 삭제할 산출물\n".encode(),
                    "text/markdown",
                )
            },
        )
        assert output.status_code == 201, output.text

        stale = client.delete(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            params={"expected_revision": 2},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"

        deleted = client.delete(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            params={"expected_revision": 1},
        )
        assert deleted.status_code == 204, deleted.text
        assert (
            client.get(f"/api/deep-analysis/missions/{mission['id']}").status_code
            == 404
        )
        assert (
            client.get(f"/api/projects/{project_id}/deep-analysis/missions").json()
            == []
        )

        with SessionLocal() as db:
            assert db.get(DeepAnalysisMission, mission["id"]) is None
            assert db.get(DeepAnalysisWorkflowRevision, workflow_id) is None
            assert all(
                db.get(DeepAnalysisWorkflowNode, node_id) is None
                for node_id in node_ids
            )
            assert all(
                db.get(DeepAnalysisWorkflowEdge, edge_id) is None
                for edge_id in edge_ids
            )
            output_file = db.get(ProjectFile, output.json()["id"])
            assert output_file is not None
            assert output_file.status == "deleted"
            assert output_file.deleted_at is not None


def test_running_mission_can_be_cancelled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "시작할 분석"},
        ).json()

        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["executionAvailable"] is True
        assert started.json()["revision"] == 2
        assert started.json()["charter"]["confirmed"] is True
        assert started.json()["workflow"]["nodes"][0]["status"] == "running"

        cancelled = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["revision"] == 3
        assert cancelled.json()["workflow"]["nodes"][0]["status"] == "cancelled"

        duplicate_cancel = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        )
        assert duplicate_cancel.status_code == 200, duplicate_cancel.text
        assert duplicate_cancel.json()["revision"] == 3


def test_cancelled_node_can_be_retried_with_attempt_history(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "재실행 검증"},
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        first_run_id = started["workflow"]["nodes"][0]["runId"]
        cancelled = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        ).json()

        retried = client.post(
            f"/api/deep-analysis/missions/{created['id']}/retry",
            headers=headers,
            json={"expectedRevision": 3, "nodeKey": "N001"},
        )
        assert retried.status_code == 200, retried.text
        payload = retried.json()
        node = payload["workflow"]["nodes"][0]
        assert payload["status"] == "running"
        assert payload["revision"] == 4
        assert node["status"] == "running"
        assert node["runId"] != first_run_id
        assert node["runHistory"] == [
            {
                "attempt": 1,
                "runId": first_run_id,
                "status": "cancelled",
                "costMicrousd": 0,
                "errorMessage": None,
                "startedAt": node["runHistory"][0]["startedAt"],
                "finishedAt": node["runHistory"][0]["finishedAt"],
            }
        ]
        assert cancelled["revision"] == 3


def test_python_calculation_uses_frozen_csv_and_saves_script_and_result(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "inputs/cost.csv", "changeReason": "계산 테스트"},
            files={
                "file": (
                    "cost.csv",
                    "item,previous,current\nA,100,125\nB,200,180\n".encode(),
                    "text/csv",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        prior_output = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={
                "logicalPath": "심층분석/이전 분석_deadbeef/N040_최종 보고서.md",
                "changeReason": "이전 Mission 산출물",
            },
            files={
                "file": (
                    "N040_최종 보고서.md",
                    "# 이전 분석 결과\n".encode(),
                    "text/markdown",
                )
            },
        )
        assert prior_output.status_code == 201, prior_output.text
        mission = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "원가 계산"},
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        assert [item["logicalPath"] for item in started["sourceManifest"]] == [
            "inputs/cost.csv"
        ]
        run_id = started["workflow"]["nodes"][0]["runId"]
        changed_after_start = client.post(
            f"/api/projects/{project_id}/files/{uploaded.json()['id']}/versions",
            headers=headers,
            data={"baseVersion": "1", "changeReason": "Mission 시작 후 변경"},
            files={
                "file": (
                    "cost.csv",
                    "item,previous,current\nA,100,999\nB,200,999\n".encode(),
                    "text/csv",
                )
            },
        )
        assert changed_after_start.status_code == 201, changed_after_start.text

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            result = execute_python_calculation(
                db,
                ManagedLocalStorage(settings.files_dir),
                run=run,
                user=user,
                arguments={
                    "script_name": "variance.py",
                    "result_name": "variance-result.csv",
                    "input_paths": ["inputs/cost.csv"],
                    "script": (
                        "rows = INPUTS['inputs/cost.csv']\n"
                        "RESULT_ROWS = [\n"
                        "    {'item': row['item'], 'variance': float(row['current']) - float(row['previous'])}\n"
                        "    for row in rows\n"
                        "]\n"
                    ),
                },
                max_upload_bytes=settings.max_upload_bytes,
            )
            db.commit()
            assert result["rowCount"] == 2
            assert result["previewRows"] == [
                {"item": "A", "variance": 25.0},
                {"item": "B", "variance": -20.0},
            ]
            paths = list(
                db.scalars(
                    select(ProjectFile.logical_path)
                    .where(ProjectFile.project_id == project_id)
                    .order_by(ProjectFile.logical_path)
                )
            )
            assert any(path.endswith("N001_variance.py") for path in paths)
            assert any(path.endswith("N001_variance-result.csv") for path in paths)


def test_python_calculation_blocks_imports(tmp_path: Path) -> None:
    from lumina.deep_analysis.calculations import _run_script

    try:
        _run_script("import os\nRESULT_ROWS = []", {})
    except ValueError as exc:
        assert "import" in str(exc)
    else:
        raise AssertionError("unsafe import was not blocked")


def test_python_calculation_blocks_oversized_static_repetition(tmp_path: Path) -> None:
    from lumina.deep_analysis.calculations import _run_script

    try:
        _run_script("RESULT_ROWS = [{'value': 'x' * 100001}]", {})
    except ValueError as exc:
        assert "반복 크기" in str(exc)
    else:
        raise AssertionError("oversized static repetition was not blocked")


def test_project_viewer_can_read_but_cannot_mutate_missions(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        owner_headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        viewer = _create_viewer()
        membership = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": viewer["id"], "role": "viewer"},
        )
        assert membership.status_code == 201, membership.text
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=owner_headers,
            json={"title": "공유 분석"},
        )
        assert created.status_code == 201, created.text
        mission_id = created.json()["id"]

        viewer_headers = _login_viewer(client)
        listing = client.get(f"/api/projects/{project_id}/deep-analysis/missions")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [mission_id]
        assert (
            client.get(f"/api/deep-analysis/missions/{mission_id}").status_code == 200
        )

        create_denied = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=viewer_headers,
            json={"title": "허용되지 않은 분석"},
        )
        assert create_denied.status_code == 404
        update_denied = client.patch(
            f"/api/deep-analysis/missions/{mission_id}",
            headers=viewer_headers,
            json={"expectedRevision": 1, "title": "허용되지 않은 변경"},
        )
        assert update_denied.status_code == 404
        start_denied = client.post(
            f"/api/deep-analysis/missions/{mission_id}/start",
            headers=viewer_headers,
            json={"expectedRevision": 1},
        )
        assert start_denied.status_code == 404
        cancel_denied = client.post(
            f"/api/deep-analysis/missions/{mission_id}/cancel",
            headers=viewer_headers,
            json={"expectedRevision": 1},
        )
        assert cancel_denied.status_code == 404
        delete_denied = client.delete(
            f"/api/deep-analysis/missions/{mission_id}",
            headers=viewer_headers,
            params={"expected_revision": 1},
        )
        assert delete_denied.status_code == 404
