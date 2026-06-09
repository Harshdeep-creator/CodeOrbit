"""Query integration tests."""

from backend.tests.conftest import wait_for_job


def test_query_repository(client, sample_zip):
    upload = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    repo_id = upload.json()["repository_id"]
    analyze = client.post("/analyze", json={"repository_id": repo_id})
    wait_for_job(client, analyze.json()["job_id"])

    response = client.post(
        "/query",
        json={"repository_id": repo_id, "query": "what is the main entry point?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert "evidence" in payload
    assert "graph_path" in payload
    assert "confidence" in payload
    assert isinstance(payload["confidence"], float)
