"""Cache integration tests."""

from backend.tests.conftest import wait_for_job


def test_cache_reuse(client, sample_zip):
    first = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    first.raise_for_status()
    first_repo = first.json()["repository_id"]
    first_hash = first.json()["repo_hash"]

    analyze = client.post("/analyze", json={"repository_id": first_repo})
    wait_for_job(client, analyze.json()["job_id"])

    sample_zip.seek(0)
    second = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    second.raise_for_status()
    second_payload = second.json()
    assert second_payload["repo_hash"] == first_hash
    assert second_payload["cached"] is True

    second_analyze = client.post("/analyze", json={"repository_id": second_payload["repository_id"]})
    status = wait_for_job(client, second_analyze.json()["job_id"], timeout=10.0)
    assert status["status"] == "completed"
    assert "cache" in status["message"].lower()
