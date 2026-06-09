"""Database CRUD for bookmarks and analysis metadata."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.database import AnalysisMetadata, Bookmark


def create_metadata(
    session: Session,
    repository_id: str,
    *,
    file_count: int,
    function_count: int,
    class_count: int,
    graph_node_count: int,
    graph_edge_count: int,
    embedding_count: int,
    entry_points: list,
    issue_count: int,
    analysis_duration: float,
) -> AnalysisMetadata:
    row = AnalysisMetadata(
        id=str(uuid.uuid4()),
        repository_id=repository_id,
        file_count=file_count,
        function_count=function_count,
        class_count=class_count,
        graph_node_count=graph_node_count,
        graph_edge_count=graph_edge_count,
        embedding_count=embedding_count,
        entry_points=entry_points,
        issue_count=issue_count,
        analysis_duration=analysis_duration,
    )
    session.add(row)
    session.flush()
    return row


def get_latest_metadata(session: Session, repository_id: str) -> Optional[AnalysisMetadata]:
    return session.scalar(
        select(AnalysisMetadata)
        .where(AnalysisMetadata.repository_id == repository_id)
        .order_by(AnalysisMetadata.created_at.desc())
        .limit(1)
    )


def create_bookmark(
    session: Session,
    repository_id: str,
    query: str,
    answer: str,
    evidence: dict | None,
    confidence: float | None,
    graph_path: list | None,
) -> Bookmark:
    bookmark = Bookmark(
        id=str(uuid.uuid4()),
        repository_id=repository_id,
        query=query,
        answer=answer,
        evidence=evidence,
        confidence=confidence,
        graph_path=graph_path,
    )
    session.add(bookmark)
    session.flush()
    return bookmark


def list_bookmarks(session: Session, repository_id: str | None = None) -> List[Bookmark]:
    stmt = select(Bookmark).order_by(Bookmark.created_at.desc())
    if repository_id:
        stmt = stmt.where(Bookmark.repository_id == repository_id)
    return list(session.scalars(stmt))


def get_bookmark(session: Session, bookmark_id: str) -> Optional[Bookmark]:
    return session.get(Bookmark, bookmark_id)


def delete_bookmark(session: Session, bookmark_id: str) -> bool:
    bookmark = session.get(Bookmark, bookmark_id)
    if not bookmark:
        return False
    session.delete(bookmark)
    return True
