"""Analysis orchestration service."""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy.orm import Session

from backend.cache.analysis_cache import AnalysisCache
from backend.core.errors import AnalysisNotReadyError, JobNotFoundError, RepositoryNotFoundError
from backend.jobs.job_runner import AnalysisTask, build_state_path, run_analysis_job
from backend.repositories import job_repository, metadata_repository, repo_repository
from backend.schemas.api_schemas import (
    AnalysisStatusResponse,
    CompareResponse,
    DashboardResponse,
    ExecutionFlowResponse,
    ExportResponse,
    GraphEdgeSchema,
    GraphNodeSchema,
    GraphResponse,
    HealthReportResponse,
    MetadataResponse,
    RebuildResponse,
    EvidenceSchema,
)
from backend.storage.state_storage import StateStorage
from shared.repository_schema import RepositoryState


class AnalysisService:
    def __init__(
        self,
        state_storage: StateStorage | None = None,
        analysis_cache: AnalysisCache | None = None,
    ) -> None:
        self.state_storage = state_storage or StateStorage()
        self.analysis_cache = analysis_cache or AnalysisCache(self.state_storage)

    def start_analysis(self, db: Session, repo_id: str, force: bool = False) -> tuple[str, str, AnalysisTask | None]:
        """Create analysis job. Returns job_id, repository_id, and optional background task."""
        repo = repo_repository.get_repository(db, repo_id)
        if not repo:
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": repo_id})

        settings = repo.settings or {}
        cache_enabled = settings.get("cache_behavior", "enabled") == "enabled"
        use_cache = cache_enabled and not force

        if use_cache and repo.repo_hash and self.analysis_cache.is_cached(db, repo.repo_hash):
            state_path = build_state_path(repo_id)
            copied = self.analysis_cache.copy_cached_state_to(db, repo.repo_hash, state_path)
            if copied:
                state = self.state_storage.load_state(copied)
                metadata_repository.create_metadata(
                    db,
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
                    db,
                    repo_id,
                    file_count=len(state.files),
                    language_summary=self._language_summary(state),
                    state_path=copied,
                    status="analyzed",
                )
                job = job_repository.create_job(db, repo_id)
                job_repository.update_job_status(db, job.id, "completed", 1.0, "Analysis reused from cache")
                db.flush()
                return job.id, repo_id, None

        job = job_repository.create_job(db, repo_id)
        state_path = build_state_path(repo_id)
        repo_repository.update_repository_status(db, repo_id, "analyzing")
        db.flush()
        return job.id, repo_id, AnalysisTask(repo_id, job.id, repo.root_path, state_path, force)

    async def dispatch_analysis(self, task: AnalysisTask) -> None:
        await run_analysis_job(task.repo_id, task.job_id, task.root_path, task.state_path, task.force)

    def get_analysis_status(self, db: Session, job_id: str) -> AnalysisStatusResponse:
        job = job_repository.get_job(db, job_id)
        if not job:
            raise JobNotFoundError("Analysis job not found.", {"job_id": job_id})
        return AnalysisStatusResponse(
            job_id=job.id,
            repository_id=job.repository_id,
            status=job.status,
            progress=job.progress,
            message=job.message,
            retry_count=job.retry_count,
            error_detail=job.error_detail,
            updated_at=job.updated_at,
        )

    def _load_state(self, db: Session, repo_id: str) -> tuple[RepositoryState, object]:
        repo = repo_repository.get_repository(db, repo_id)
        if not repo:
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": repo_id})
        if not repo.state_path or not self.state_storage.state_exists(repo.state_path):
            raise AnalysisNotReadyError(
                "Analysis is not ready for this repository.",
                {"repository_id": repo_id, "status": repo.status},
            )
        return self.state_storage.load_state(repo.state_path), repo

    def get_dashboard(self, db: Session, repo_id: str) -> DashboardResponse:
        state, repo = self._load_state(db, repo_id)
        metadata = metadata_repository.get_latest_metadata(db, repo_id)
        return DashboardResponse(
            repository_id=repo_id,
            name=repo.name,
            languages=self._language_summary(state),
            file_count=len(state.files),
            function_count=len(state.functions),
            class_count=len(state.classes),
            entry_points=list(state.entry_points),
            analysis_timestamp=metadata.created_at if metadata else None,
        )

    def get_health_report(self, db: Session, repo_id: str) -> HealthReportResponse:
        state, _repo = self._load_state(db, repo_id)
        counts = Counter(issue.type for issue in state.issues)
        dead_code = counts.get("dead_code", 0)
        circular = counts.get("circular_dependency", 0)
        security = counts.get("security_smell", 0)
        architecture = counts.get("architecture_smell", 0)
        penalty = min(70, dead_code * 2 + circular * 5 + security * 4 + architecture * 3)
        health_score = round(max(10.0, 100.0 - penalty), 2)

        files = sorted({ref.file for issue in state.issues[:20] for ref in issue.evidence})
        lines = [ref.__dict__ for issue in state.issues[:20] for ref in issue.evidence]
        evidence = EvidenceSchema(files=files, functions=[], lines=lines)
        issues = [
            {
                "id": issue.id,
                "type": issue.type,
                "severity": issue.severity,
                "title": issue.title,
                "description": issue.description,
                "confidence": issue.confidence,
            }
            for issue in state.issues[:50]
        ]
        return HealthReportResponse(
            repository_id=repo_id,
            health_score=health_score,
            dead_code_count=dead_code,
            circular_dependency_count=circular,
            security_smell_count=security,
            architecture_smell_count=architecture,
            evidence=evidence,
            issues=issues,
        )

    def get_metadata(self, db: Session, repo_id: str) -> MetadataResponse:
        state, _repo = self._load_state(db, repo_id)
        metadata = metadata_repository.get_latest_metadata(db, repo_id)
        return MetadataResponse(
            repository_id=repo_id,
            files_parsed=len(state.files),
            functions_indexed=len(state.functions),
            classes_indexed=len(state.classes),
            graph_nodes=len(state.graph_nodes),
            graph_edges=len(state.graph_edges),
            embeddings_generated=len(state.embeddings),
            entry_points=list(state.entry_points),
            analysis_timestamp=metadata.created_at if metadata else None,
            analysis_duration=metadata.analysis_duration if metadata else 0.0,
        )

    def get_graph(self, db: Session, repo_id: str) -> GraphResponse:
        state, _repo = self._load_state(db, repo_id)
        nodes = [
            GraphNodeSchema(
                id=node.id,
                type=node.type,
                label=node.label,
                file=node.file,
                line=node.line,
            )
            for node in state.graph_nodes.values()
        ]
        edges = [
            GraphEdgeSchema(source=edge.source, target=edge.target, type=edge.type, weight=edge.weight)
            for edge in state.graph_edges
        ]
        return GraphResponse(repository_id=repo_id, nodes=nodes, edges=edges)

    def get_execution_flow(self, db: Session, repo_id: str) -> ExecutionFlowResponse:
        state, _repo = self._load_state(db, repo_id)
        return ExecutionFlowResponse(
            repository_id=repo_id,
            entry_points=list(state.entry_points),
            execution_flows=dict(state.execution_flows),
        )

    def rebuild(self, db: Session, repo_id: str) -> tuple[RebuildResponse, AnalysisTask | None]:
        repo = repo_repository.get_repository(db, repo_id)
        if not repo:
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": repo_id})
        if repo.repo_hash:
            self.analysis_cache.invalidate_cache(db, repo.repo_hash)
        job_id, _, task = self.start_analysis(db, repo_id, force=True)
        response = RebuildResponse(repository_id=repo_id, job_id=job_id, status="queued")
        return response, task

    def compare_repositories(self, db: Session, repo_a: str, repo_b: str) -> CompareResponse:
        state_a, _ = self._load_state(db, repo_a)
        state_b, _ = self._load_state(db, repo_b)
        return CompareResponse(
            repo_a=repo_a,
            repo_b=repo_b,
            architecture_diff={
                "file_delta": len(state_b.files) - len(state_a.files),
                "class_delta": len(state_b.classes) - len(state_a.classes),
                "entry_points_a": state_a.entry_points,
                "entry_points_b": state_b.entry_points,
            },
            complexity_diff={
                "function_delta": len(state_b.functions) - len(state_a.functions),
                "avg_complexity_a": self._avg_complexity(state_a),
                "avg_complexity_b": self._avg_complexity(state_b),
            },
            risk_diff={
                "issue_delta": len(state_b.issues) - len(state_a.issues),
                "issues_by_type_a": dict(Counter(i.type for i in state_a.issues)),
                "issues_by_type_b": dict(Counter(i.type for i in state_b.issues)),
            },
            maintainability_diff={
                "graph_edge_delta": len(state_b.graph_edges) - len(state_a.graph_edges),
                "embedding_delta": len(state_b.embeddings) - len(state_a.embeddings),
            },
        )

    def export_readme(self, db: Session, repo_id: str, fmt: str = "markdown") -> ExportResponse:
        dashboard = self.get_dashboard(db, repo_id)
        metadata = self.get_metadata(db, repo_id)
        if fmt == "json":
            content = json.dumps({"dashboard": dashboard.model_dump(), "metadata": metadata.model_dump()}, indent=2)
        else:
            content = (
                f"# {dashboard.name}\n\n"
                f"- Files: {dashboard.file_count}\n"
                f"- Functions: {dashboard.function_count}\n"
                f"- Classes: {dashboard.class_count}\n"
                f"- Entry points: {', '.join(dashboard.entry_points) or 'none'}\n"
            )
        return ExportResponse(repository_id=repo_id, format=fmt, content=content)

    def export_documentation(self, db: Session, repo_id: str, fmt: str = "markdown") -> ExportResponse:
        state, repo = self._load_state(db, repo_id)
        if fmt == "json":
            content = json.dumps(state.to_dict(), indent=2, default=str)
        else:
            lines = [f"# Documentation: {repo.name}", "", "## Files"]
            for path in sorted(state.files.keys())[:100]:
                lines.append(f"- {path}")
            content = "\n".join(lines)
        return ExportResponse(repository_id=repo_id, format=fmt, content=content)

    def export_health(self, db: Session, repo_id: str, fmt: str = "json") -> ExportResponse:
        report = self.get_health_report(db, repo_id)
        if fmt == "markdown":
            content = (
                f"# Health Report\n\n"
                f"- Score: {report.health_score}\n"
                f"- Dead code: {report.dead_code_count}\n"
                f"- Circular dependencies: {report.circular_dependency_count}\n"
                f"- Security smells: {report.security_smell_count}\n"
                f"- Architecture smells: {report.architecture_smell_count}\n"
            )
        else:
            content = report.model_dump_json(indent=2)
        return ExportResponse(repository_id=repo_id, format=fmt, content=content)

    @staticmethod
    def _language_summary(state: RepositoryState) -> dict[str, int]:
        counts: dict[str, int] = {}
        for file_info in state.files.values():
            counts[file_info.language] = counts.get(file_info.language, 0) + 1
        return counts

    @staticmethod
    def _avg_complexity(state: RepositoryState) -> float:
        if not state.functions:
            return 0.0
        return round(sum(fn.complexity for fn in state.functions.values()) / len(state.functions), 2)
