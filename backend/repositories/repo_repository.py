"""Database CRUD for repositories."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.database import Repository, utcnow


def create_repository(
    session: Session,
    name: str,
    root_path: str,
    source_url: str | None = None,
    repo_hash: str | None = None,
) -> Repository:
    repo = Repository(
        id=str(uuid.uuid4()),
        name=name,
        source_url=source_url,
        root_path=root_path,
        repo_hash=repo_hash,
        status="uploaded",
        settings={"cache_behavior": "enabled", "rebuild_analysis": False},
    )
    session.add(repo)
    session.flush()
    return repo


def get_repository(session: Session, repo_id: str) -> Optional[Repository]:
    return session.get(Repository, repo_id)


def list_repositories(session: Session) -> List[Repository]:
    return list(session.scalars(select(Repository).order_by(Repository.upload_timestamp.desc())))


def update_repository_status(session: Session, repo_id: str, status: str) -> None:
    repo = session.get(Repository, repo_id)
    if repo:
        repo.status = status


def update_repository_metadata(
    session: Session,
    repo_id: str,
    *,
    repo_hash: str | None = None,
    file_count: int | None = None,
    language_summary: dict | None = None,
    state_path: str | None = None,
    status: str | None = None,
) -> None:
    repo = session.get(Repository, repo_id)
    if not repo:
        return
    if repo_hash is not None:
        repo.repo_hash = repo_hash
    if file_count is not None:
        repo.file_count = file_count
    if language_summary is not None:
        repo.language_summary = language_summary
    if state_path is not None:
        repo.state_path = state_path
    if status is not None:
        repo.status = status
    repo.upload_timestamp = utcnow()


def update_repository_settings(session: Session, repo_id: str, settings: dict) -> Repository | None:
    repo = session.get(Repository, repo_id)
    if not repo:
        return None
    merged = dict(repo.settings or {})
    merged.update(settings)
    repo.settings = merged
    session.flush()
    return repo


def find_by_hash(session: Session, repo_hash: str) -> Optional[Repository]:
    return session.scalar(select(Repository).where(Repository.repo_hash == repo_hash))


def delete_repository(session: Session, repo_id: str) -> bool:
    repo = session.get(Repository, repo_id)
    if not repo:
        return False
    session.delete(repo)
    return True
