"""Database CRUD for analysis jobs."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import AnalysisJob, utcnow


def create_job(session: Session, repo_id: str) -> AnalysisJob:
    job = AnalysisJob(
        id=str(uuid.uuid4()),
        repository_id=repo_id,
        status="queued",
        progress=0.0,
        message="Queued",
    )
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: str) -> Optional[AnalysisJob]:
    return session.get(AnalysisJob, job_id)


def update_job_status(
    session: Session,
    job_id: str,
    status: str,
    progress: float,
    message: str,
) -> None:
    job = session.get(AnalysisJob, job_id)
    if not job:
        return
    job.status = status
    job.progress = progress
    job.message = message
    job.updated_at = utcnow()


def mark_failed(session: Session, job_id: str, error_detail: str) -> None:
    job = session.get(AnalysisJob, job_id)
    if not job:
        return
    job.status = "failed"
    job.progress = 1.0
    job.message = "Analysis failed"
    job.error_detail = error_detail
    job.updated_at = utcnow()


def increment_retry(session: Session, job_id: str) -> int:
    job = session.get(AnalysisJob, job_id)
    if not job:
        return 0
    job.retry_count += 1
    job.updated_at = utcnow()
    return job.retry_count
