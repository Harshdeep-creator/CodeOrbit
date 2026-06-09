"""Background analysis job runner using ThreadPoolExecutor."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys

from sqlalchemy.orm import Session

from backend.cache.analysis_cache import AnalysisCache
from backend.core.config import get_settings
from backend.models.database import get_session_factory
from backend.repositories import job_repository, metadata_repository, repo_repository
from backend.storage.state_storage import StateStorage
from engine.orchestrator import IntelligenceOrchestrator

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)
_orchestrator = IntelligenceOrchestrator()
_state_storage = StateStorage()
_cache = AnalysisCache(_state_storage)


class AnalysisTask:
    def __init__(self, repo_id: str, job_id: str, root_path: str, state_path: str, force: bool) -> None:
        self.repo_id = repo_id
        self.job_id = job_id
        self.root_path = root_path
        self.state_path = state_path
        self.force = force


def _language_summary(state) -> dict:
    counts: dict[str, int] = {}
    for file_info in state.files.values():
        counts[file_info.language] = counts.get(file_info.language, 0) + 1
    return counts


def _run_analysis_sync(root_path: str):
    started = time.perf_counter()

    if not root_path or not Path(root_path).exists():
        raise ValueError(f"Invalid repo path: {root_path}")

    logger.info(f"Starting analysis at: {root_path}")

    state = _orchestrator.analyze_repository(root_path)

    logger.info(
        "Analysis complete: files=%s functions=%s classes=%s",
        len(state.files),
        len(state.functions),
        len(state.classes),
    )

    duration = time.perf_counter() - started
    return state, duration


def _process_job(repo_id: str, job_id: str, root_path: str, state_path: str, force: bool) -> None:
    session: Session = get_session_factory()()
    settings = get_settings()

    try:
        job_repository.update_job_status(session, job_id, "processing", 0.1, "Starting analysis")
        session.commit()

        repo = repo_repository.get_repository(session, repo_id)
        if not repo:
            job_repository.mark_failed(session, job_id, "Repository not found")
            session.commit()
            return

        repo_hash = repo.repo_hash

        # ---------------- CACHE PATH ----------------
        if repo_hash and not force and _cache.is_cached(session, repo_hash):
            copied = _cache.copy_cached_state_to(session, repo_hash, state_path)

            if copied:
                state = _state_storage.load_state(copied)

                metadata_repository.create_metadata(
                    session,
                    repo_id,
                    file_count=len(state.files),
                    function_count=len(state.functions),
                    class_count=len(state.classes),
                    graph_node_count=len(state.graph_nodes),
                    graph_edge_count=len(state.graph_edges),
                    embedding_count=len(state.embeddings),
                    entry_points=list(state.entry_points),
                    issue_count=len(state.issues),
                    analysis_duration=0.0,
                )

                repo_repository.update_repository_metadata(
                    session,
                    repo_id,
                    file_count=len(state.files),
                    language_summary=_language_summary(state),
                    state_path=copied,
                    status="analyzed",
                )

                job_repository.update_job_status(
                    session,
                    job_id,
                    "completed",
                    1.0,
                    "Analysis reused from cache",
                )
                session.commit()
                return

        # ---------------- NORMAL ANALYSIS ----------------
        attempt = 0
        last_error = "Unknown failure"

        while attempt < settings.max_analysis_retries:
            attempt += 1

            try:
                job_repository.update_job_status(
                    session,
                    job_id,
                    "processing",
                    0.2 + attempt * 0.1,
                    f"Analysis attempt {attempt}",
                )
                session.commit()

                state, duration = _run_analysis_sync(root_path)

                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                _state_storage.save_state(state, state_path)

                metadata_repository.create_metadata(
                    session,
                    repo_id,
                    file_count=len(state.files),
                    function_count=len(state.functions),
                    class_count=len(state.classes),
                    graph_node_count=len(state.graph_nodes),
                    graph_edge_count=len(state.graph_edges),
                    embedding_count=len(state.embeddings),
                    entry_points=list(state.entry_points),
                    issue_count=len(state.issues),
                    analysis_duration=duration,
                )

                if repo_hash:
                    _cache.cache_state(session, repo_hash, state_path)

                repo_repository.update_repository_metadata(
                    session,
                    repo_id,
                    file_count=len(state.files),
                    language_summary=_language_summary(state),
                    state_path=state_path,
                    status="analyzed",
                )

                job_repository.update_job_status(
                    session,
                    job_id,
                    "completed",
                    1.0,
                    "Analysis completed",
                )

                session.commit()
                return

            except Exception as exc:
                last_error = str(exc)
                logger.exception("Analysis attempt %s failed for repo %s", attempt, repo_id)
                job_repository.increment_retry(session, job_id)
                session.commit()

        job_repository.mark_failed(session, job_id, last_error)
        repo_repository.update_repository_status(session, repo_id, "failed")
        session.commit()

    except Exception as exc:
        logger.exception("Background job crashed for repo %s", repo_id)
        try:
            job_repository.mark_failed(session, job_id, str(exc))
            repo_repository.update_repository_status(session, repo_id, "failed")
            session.commit()
        except Exception:
            session.rollback()

    finally:
        session.close()


async def run_analysis_job(repo_id: str, job_id: str, root_path: str, state_path: str, force: bool = False) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _process_job, repo_id, job_id, root_path, state_path, force)


def build_state_path(repo_id: str) -> str:
    settings = get_settings()
    return str((settings.states_dir / f"{repo_id}.pkl").resolve())