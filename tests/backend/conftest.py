from __future__ import annotations

import atexit
import os
from pathlib import Path

from lumina.config import Settings, get_settings


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYTEST_RUNTIME_ROOT = (
    REPOSITORY_ROOT / ".cache" / "pytest" / f"runtime-{os.getpid()}"
)
PYTEST_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)


def _remove_empty_pytest_runtime() -> None:
    for directory_name in ("artifacts", "files"):
        try:
            (PYTEST_RUNTIME_ROOT / directory_name).rmdir()
        except OSError:
            pass
    try:
        PYTEST_RUNTIME_ROOT.rmdir()
    except OSError:
        # Keep non-empty directories as forensic evidence if a test unexpectedly
        # exercised the process-wide default database or filesystem paths.
        pass


atexit.register(_remove_empty_pytest_runtime)

# Test modules import ``lumina.main`` during collection. Its module-level app and
# database engine must never inherit the repository .env and point at live data.
os.environ["LUMINA_ENVIRONMENT"] = "test"
os.environ["LUMINA_DATA_DIR"] = str(PYTEST_RUNTIME_ROOT)
os.environ["LUMINA_FILES_DIR"] = str(PYTEST_RUNTIME_ROOT / "files")
os.environ["LUMINA_ARTIFACTS_DIR"] = str(PYTEST_RUNTIME_ROOT / "artifacts")
isolated_database_url = (
    f"sqlite:///{(PYTEST_RUNTIME_ROOT / 'lumina.db').as_posix()}"
)
os.environ["DATABASE_URL"] = isolated_database_url
os.environ["LUMINA_DATABASE_URL"] = isolated_database_url

# Prime the cached process settings without changing the application's public
# dotenv contract. Direct ``Settings(...)`` construction in configuration tests
# continues to use the repository .env unless that test supplies ``_env_file``.
configured_env_file = Settings.model_config.get("env_file")
Settings.model_config["env_file"] = None
try:
    get_settings.cache_clear()
    get_settings()
finally:
    Settings.model_config["env_file"] = configured_env_file
