from pathlib import Path

from fastapi.testclient import TestClient

from lumina import main as main_module
from lumina.config import Settings


def test_production_bundle_falls_back_for_client_side_routes(
    monkeypatch, tmp_path: Path
) -> None:
    dist = tmp_path / "apps" / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body>Lumina shell</body></html>", encoding="utf-8"
    )
    (dist / "app.js").write_text("console.log('lumina')", encoding="utf-8")
    monkeypatch.setattr(main_module, "REPOSITORY_ROOT", tmp_path)
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'spa.db').as_posix()}",
        data_dir=tmp_path / "data",
        files_dir=tmp_path / "data" / "files",
        artifacts_dir=tmp_path / "data" / "artifacts",
        cookie_secure=False,
    )

    with TestClient(main_module.create_app(settings)) as client:
        shared = client.get("/shared/sample-token")
        assert shared.status_code == 200
        assert "Lumina shell" in shared.text

        asset = client.get("/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text

        missing_asset = client.get("/missing.js")
        assert missing_asset.status_code == 404

        health = client.get("/api/health/live")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
