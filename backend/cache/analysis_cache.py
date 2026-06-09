"""Hash-based RepositoryState cache (safe version)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.database import RepositoryCache, utcnow
from backend.storage.state_storage import StateStorage
from shared.repository_schema import RepositoryState


class AnalysisCache:
    def __init__(self, state_storage: StateStorage | None = None) -> None:
        self.state_storage = state_storage or StateStorage()
        self.settings = get_settings()

    # =========================
    # SAFE DB ACCESS WRAPPER
    # =========================
    def _safe_query(self, session: Session, repo_hash: str):
        """
        Prevent crash if table doesn't exist.
        """
        try:
            return session.scalar(
                select(RepositoryCache).where(
                    RepositoryCache.repo_hash == repo_hash
                )
            )
        except Exception:
            # DB not ready or table missing → disable cache safely
            return None

    # =========================
    # CACHE CHECK
    # =========================
    def is_cached(self, session: Session, repo_hash: str) -> bool:
        entry = self._safe_query(session, repo_hash)
        return (
            entry is not None
            and self.state_storage.state_exists(entry.state_path)
        )

    # =========================
    # GET CACHE
    # =========================
    def get_cached_state(
        self, session: Session, repo_hash: str
    ) -> RepositoryState | None:

        entry = self._safe_query(session, repo_hash)

        if not entry or not self.state_storage.state_exists(entry.state_path):
            return None

        try:
            entry.hit_count += 1
            entry.analysis_timestamp = utcnow()
            session.flush()
        except Exception:
            # ignore DB write failure
            pass

        return self.state_storage.load_state(entry.state_path)

    # =========================
    # SAVE CACHE
    # =========================
    def cache_state(self, session: Session, repo_hash: str, state_path: str) -> str:
        entry = self._safe_query(session, repo_hash)

        try:
            if entry:
                entry.state_path = state_path
                entry.analysis_timestamp = utcnow()
                session.flush()
                return entry.state_path
        except Exception:
            pass

        # fallback file cache (NO DB dependency)
        cache_path = str(
            (self.settings.states_dir / f"{repo_hash}.pkl").resolve()
        )

        try:
            if state_path != cache_path:
                Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(state_path, cache_path)
        except Exception:
            # if file copy fails, still continue
            cache_path = state_path

        # try DB insert safely
        try:
            entry = RepositoryCache(
                id=str(uuid.uuid4()),
                repo_hash=repo_hash,
                state_path=cache_path,
                hit_count=0,
            )
            session.add(entry)
            session.flush()
        except Exception:
            # DB broken → ignore caching completely
            pass

        return cache_path

    # =========================
    # INVALIDATE CACHE
    # =========================
    def invalidate_cache(self, session: Session, repo_hash: str) -> None:
        entry = self._safe_query(session, repo_hash)

        if not entry:
            return

        try:
            self.state_storage.delete_state(entry.state_path)
            session.delete(entry)
            session.flush()
        except Exception:
            pass

    # =========================
    # COPY CACHE
    # =========================
    def copy_cached_state_to(
        self, session: Session, repo_hash: str, destination: str
    ) -> Optional[str]:

        entry = self._safe_query(session, repo_hash)

        if (
            not entry
            or not self.state_storage.state_exists(entry.state_path)
        ):
            return None

        try:
            dest = Path(destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry.state_path, dest)

            entry.hit_count += 1
            session.flush()

            return str(dest.resolve())

        except Exception:
            return None