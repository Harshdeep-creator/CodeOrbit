"""Chat integration tests."""

from backend.tests.conftest import wait_for_job


def test_chat_persistence(client, sample_zip):
    upload = client.post(
        "/upload_repo",
        files={"file": ("sample_repo.zip", sample_zip, "application/zip")},
    )
    repo_id = upload.json()["repository_id"]
    analyze = client.post("/analyze", json={"repository_id": repo_id})
    wait_for_job(client, analyze.json()["job_id"])

    create = client.post("/chat/create", json={"repository_id": repo_id, "title": "Test Chat"})
    create.raise_for_status()
    chat_id = create.json()["id"]

    message = client.post(f"/chat/{chat_id}/message", json={"query": "explain main function"})
    message.raise_for_status()
    assert message.json()["response"]["answer"]

    fetched = client.get(f"/chat/{chat_id}")
    fetched.raise_for_status()
    assert len(fetched.json()["messages"]) == 2

    listed = client.get("/chat/list", params={"repository_id": repo_id})
    listed.raise_for_status()
    assert any(item["id"] == chat_id for item in listed.json())
