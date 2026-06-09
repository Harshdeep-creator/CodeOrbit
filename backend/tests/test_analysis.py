"""Analysis integration tests."""

from backend.tests.conftest import wait_for_job


def _upload_and_analyze(client, sample_zip):
    upload = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    upload.raise_for_status()
    repo_id = upload.json()["repository_id"]
    analyze = client.post("/analyze", json={"repository_id": repo_id})
    analyze.raise_for_status()
    job_id = analyze.json()["job_id"]
    status = wait_for_job(client, job_id)
    assert status["status"] == "completed", status
    return repo_id, job_id


def test_analyze_repository(client, sample_zip):
    repo_id, job_id = _upload_and_analyze(client, sample_zip)
    dashboard = client.get(f"/repository/{repo_id}/dashboard")
    dashboard.raise_for_status()
    data = dashboard.json()
    assert data["file_count"] >= 2
    assert data["function_count"] >= 2


def test_rebuild_analysis(client, sample_zip):
    repo_id, _ = _upload_and_analyze(client, sample_zip)
    rebuild = client.post(f"/repository/{repo_id}/rebuild")
    rebuild.raise_for_status()
    status = wait_for_job(client, rebuild.json()["job_id"])
    assert status["status"] == "completed"
