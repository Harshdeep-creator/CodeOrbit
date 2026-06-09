"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlalchemy.orm import Session

from backend.cache.analysis_cache import AnalysisCache
from backend.models.database import get_db_session
from backend.services.analysis_service import AnalysisService
from backend.services.chat_service import BookmarkService, ChatService
from backend.services.query_service import QueryService
from backend.services.repository_service import RepositoryService
from backend.storage.file_storage import FileStorage
from backend.storage.state_storage import StateStorage
from engine.orchestrator import IntelligenceOrchestrator


def get_db() -> Generator[Session, None, None]:
    yield from get_db_session()


@lru_cache
def get_orchestrator() -> IntelligenceOrchestrator:
    return IntelligenceOrchestrator()


@lru_cache
def get_file_storage() -> FileStorage:
    return FileStorage()


@lru_cache
def get_state_storage() -> StateStorage:
    return StateStorage()


@lru_cache
def get_analysis_cache() -> AnalysisCache:
    return AnalysisCache(get_state_storage())


@lru_cache
def get_repository_service() -> RepositoryService:
    return RepositoryService(get_file_storage(), get_state_storage(), get_analysis_cache())


@lru_cache
def get_analysis_service() -> AnalysisService:
    return AnalysisService(get_state_storage(), get_analysis_cache())


@lru_cache
def get_query_service() -> QueryService:
    return QueryService(get_orchestrator(), get_state_storage())


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(get_query_service())


@lru_cache
def get_bookmark_service() -> BookmarkService:
    return BookmarkService()
