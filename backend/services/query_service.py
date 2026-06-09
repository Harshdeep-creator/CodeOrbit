"""Query execution service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.core.errors import AnalysisNotReadyError, RepositoryNotFoundError
from backend.repositories import repo_repository
from backend.schemas.api_schemas import QueryResponseSchema, EvidenceSchema
from backend.storage.state_storage import StateStorage
from engine.orchestrator import IntelligenceOrchestrator


class QueryService:
    def __init__(
        self,
        orchestrator: IntelligenceOrchestrator | None = None,
        state_storage: StateStorage | None = None,
    ) -> None:
        self.orchestrator = orchestrator or IntelligenceOrchestrator()
        self.state_storage = state_storage or StateStorage()

    def execute_query(self, db: Session, repo_id: str, query: str, chat_id: str | None = None) -> QueryResponseSchema:
        repo = repo_repository.get_repository(db, repo_id)
        if not repo:
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": repo_id})
        if not repo.state_path or not self.state_storage.state_exists(repo.state_path):
            raise AnalysisNotReadyError(
                "Analysis is not ready for this repository.",
                {"repository_id": repo_id, "status": repo.status},
            )

        state = self.state_storage.load_state(repo.state_path)
        result = self.orchestrator.answer_query(query, state=state)
        evidence = result.get("evidence", {})
        return QueryResponseSchema(
            answer=result.get("answer", ""),
            evidence=EvidenceSchema(
                files=list(evidence.get("files", [])),
                functions=list(evidence.get("functions", [])),
                lines=list(evidence.get("lines", [])),
            ),
            graph_path=list(result.get("graph_path", [])),
            confidence=float(result.get("confidence", 0.0)),
        )
