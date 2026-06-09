"""Shared pytest fixtures."""

from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config import get_settings  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.models.database import Base, get_engine, get_session_factory, init_db  # noqa: E402


@pytest.fixture()
def test_paths(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    uploads = data_dir / "uploads"
    states = data_dir / "states"
    repos = data_dir / "repositories"
    db_path = data_dir / "test.db"
    for path in (uploads, states, repos):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("STATES_DIR", str(states))
    monkeypatch.setenv("REPOS_DIR", str(repos))
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "false")
    get_settings.cache_clear()

    from backend.core import dependencies

    dependencies.get_orchestrator.cache_clear()
    dependencies.get_file_storage.cache_clear()
    dependencies.get_state_storage.cache_clear()
    dependencies.get_analysis_cache.cache_clear()
    dependencies.get_repository_service.cache_clear()
    dependencies.get_analysis_service.cache_clear()
    dependencies.get_query_service.cache_clear()
    dependencies.get_chat_service.cache_clear()
    dependencies.get_bookmark_service.cache_clear()

    import backend.models.database as db_module

    db_module._engine = None
    db_module._session_factory = None
    init_db()
    yield {
        "data_dir": data_dir,
        "uploads": uploads,
        "states": states,
        "repos": repos,
    }
    get_settings.cache_clear()


@pytest.fixture()
def client(test_paths):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def sample_zip() -> io.BytesIO:
    fixture_root = Path(__file__).parent / "fixtures" / "sample_repo"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in fixture_root.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(fixture_root).as_posix())
    buffer.seek(0)
    return buffer


def wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/analysis_status/{job_id}")
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.2)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
