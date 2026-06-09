"""Health and dashboard integration tests."""

from backend.tests.conftest import wait_for_job


def test_health_and_dashboard(client, sample_zip):
    upload = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    repo_id = upload.json()["repository_id"]
    analyze = client.post("/analyze", json={"repository_id": repo_id})
    wait_for_job(client, analyze.json()["job_id"])

    health = client.get(f"/repository/{repo_id}/health")
    health.raise_for_status()
    health_payload = health.json()
    assert "health_score" in health_payload
    assert "dead_code_count" in health_payload

    dashboard = client.get(f"/repository/{repo_id}/dashboard")
    dashboard.raise_for_status()
    assert dashboard.json()["repository_id"] == repo_id

    metadata = client.get(f"/repository/{repo_id}/metadata")
    metadata.raise_for_status()
    assert metadata.json()["files_parsed"] >= 2

    graph = client.get(f"/repository/{repo_id}/graph")
    graph.raise_for_status()
    assert "nodes" in graph.json()

    flow = client.get(f"/repository/{repo_id}/execution_flow")
    flow.raise_for_status()
    assert "execution_flows" in flow.json()


def test_delete_repository(client, sample_zip):
    upload = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    repo_id = upload.json()["repository_id"]
    delete = client.delete(f"/repository/{repo_id}")
    delete.raise_for_status()
    assert delete.json()["deleted"] is True

    missing = client.get(f"/repository/{repo_id}/dashboard")
    assert missing.status_code == 404
