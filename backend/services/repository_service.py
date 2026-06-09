"""Repository upload and lifecycle service."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from backend.cache.analysis_cache import AnalysisCache
from backend.core.errors import InvalidUploadError, RepositoryNotFoundError
from backend.repositories import repo_repository
from backend.schemas.api_schemas import RepositorySummary, UploadRepoResponse
from backend.storage.file_storage import FileStorage
from backend.storage.state_storage import StateStorage


class RepositoryService:
    def __init__(
        self,
        file_storage: FileStorage | None = None,
        state_storage: StateStorage | None = None,
        analysis_cache: AnalysisCache | None = None,
    ) -> None:
        self.file_storage = file_storage or FileStorage()
        self.state_storage = state_storage or StateStorage()
        self.analysis_cache = analysis_cache or AnalysisCache(self.state_storage)

    async def upload_repository(
        self,
        db: Session,
        file: UploadFile | None = None,
        github_url: str | None = None,
        name: str | None = None,
    ) -> UploadRepoResponse:
        if file is None and not github_url:
            raise InvalidUploadError("Provide either a ZIP file or a GitHub URL.")
        if file is not None and github_url:
            raise InvalidUploadError("Provide only one of ZIP file or GitHub URL.")

        if file is not None:
            root_path = await self.file_storage.extract_zip(file)
            repo_name = name or Path(file.filename or "upload").stem
            source_url = None
        else:
            root_path = await asyncio.to_thread(self.file_storage.clone_github, github_url)
            repo_name = name or Path(github_url.rstrip("/")).name.replace(".git", "")
            source_url = github_url

        repo_hash = self.file_storage.compute_repo_hash(root_path)
        file_count = sum(1 for path in Path(root_path).rglob("*") if path.is_file())
        if file_count == 0:
            self.file_storage.cleanup_repository(root_path)
            raise InvalidUploadError("Repository contains no analyzable files.")

        cached = self.analysis_cache.is_cached(db, repo_hash)
        repo = repo_repository.create_repository(
            db,
            name=repo_name,
            root_path=root_path,
            source_url=source_url,
            repo_hash=repo_hash,
        )
        repo_repository.update_repository_metadata(
            db,
            repo.id,
            repo_hash=repo_hash,
            file_count=file_count,
            status="cached" if cached else "uploaded",
        )
        db.flush()

        return UploadRepoResponse(
            repository_id=repo.id,
            name=repo.name,
            repo_hash=repo_hash,
            file_count=file_count,
            language_summary={},
            status=repo.status,
            cached=cached,
        )

    def get_repository(self, db: Session, repo_id: str):
        repo = repo_repository.get_repository(db, repo_id)
        if not repo:
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": repo_id})
        return repo

    def list_repositories(self, db: Session) -> list[RepositorySummary]:
        return [
            RepositorySummary(
                id=repo.id,
                name=repo.name,
                source_url=repo.source_url,
                file_count=repo.file_count,
                language_summary=repo.language_summary,
                status=repo.status,
                upload_timestamp=repo.upload_timestamp,
            )
            for repo in repo_repository.list_repositories(db)
        ]

    def delete_repository(self, db: Session, repo_id: str) -> None:
        repo = self.get_repository(db, repo_id)
        if repo.repo_hash:
            self.analysis_cache.invalidate_cache(db, repo.repo_hash)
        if repo.state_path:
            self.state_storage.delete_state(repo.state_path)
        self.file_storage.cleanup_repository(repo.root_path)
        repo_repository.delete_repository(db, repo_id)

    def get_settings(self, db: Session, repo_id: str) -> dict:
        repo = self.get_repository(db, repo_id)
        return repo.settings or {"cache_behavior": "enabled", "rebuild_analysis": False}

    def update_settings(self, db: Session, repo_id: str, settings: dict) -> dict:
        repo = repo_repository.update_repository_settings(db, repo_id, settings)
        if not repo:
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": repo_id})
        return repo.settings or {}
