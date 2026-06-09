"""Upload integration tests."""

from backend.tests.conftest import wait_for_job


def test_upload_repository(client, sample_zip):
    response = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["repository_id"]
    assert payload["repo_hash"]
    assert payload["file_count"] >= 2


def test_upload_invalid_extension(client):
    response = client.post(
        "/upload_repo",
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_upload"
