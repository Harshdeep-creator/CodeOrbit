"""Repository, analysis, export, and settings routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from sqlalchemy.orm import Session

from backend.core.dependencies import get_analysis_service, get_db, get_repository_service
from backend.schemas.api_schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisStatusResponse,
    CompareRequest,
    CompareResponse,
    DashboardResponse,
    ExecutionFlowResponse,
    ExportResponse,
    GraphResponse,
    HealthReportResponse,
    MetadataResponse,
    RebuildResponse,
    RepositorySettingsSchema,
    RepositorySettingsUpdate,
    RepositorySummary,
    UploadRepoResponse,
)
from backend.services.analysis_service import AnalysisService
from backend.services.repository_service import RepositoryService

router = APIRouter(tags=["repository"])


# =========================
# 🔥 FIXED UPLOAD ENDPOINT
# =========================
@router.post(
    "/upload_repo",
    response_model=UploadRepoResponse,
    summary="Upload a repository ZIP or GitHub URL",
)
async def upload_repo(
    file: UploadFile | None = File(default=None),
    github_url: Optional[str] = Form(default=None),
    name: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    service: RepositoryService = Depends(get_repository_service),
) -> UploadRepoResponse:

    # =========================
    # 🔧 INPUT NORMALIZATION (CRITICAL FIX)
    # =========================
    if github_url == "":
        github_url = None
    if name == "":
        name = None

    # Swagger sometimes sends empty file string
    if file is not None and not getattr(file, "filename", None):
        file = None

    # =========================
    # VALIDATION (PREVENT 500s)
    # =========================
    if not file and not github_url:
        raise HTTPException(
            status_code=400,
            detail="Provide either a ZIP file or a GitHub URL"
        )

    if file and github_url:
        raise HTTPException(
            status_code=400,
            detail="Provide only one source: file OR github_url"
        )

    try:
        return await service.upload_repository(
            db,
            file=file,
            github_url=github_url,
            name=name
        )

    except Exception as e:
        # Prevent silent 500 crashes
        raise HTTPException(
            status_code=500,
            detail=f"Repository upload failed: {str(e)}"
        )


# =========================
# ANALYZE
# =========================
@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_repository(
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalyzeResponse:

    job_id, repository_id, task = service.start_analysis(
        db,
        payload.repository_id,
        force=payload.force
    )

    if task:
        asyncio.create_task(service.dispatch_analysis(task))

    return AnalyzeResponse(
        job_id=job_id,
        repository_id=repository_id,
        status="queued"
    )


# =========================
# STATUS
# =========================
@router.get("/analysis_status/{job_id}")
def analysis_status(
    job_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisStatusResponse:
    return service.get_analysis_status(db, job_id)


# =========================
# DASHBOARD
# =========================
@router.get("/repository/{repo_id}/dashboard")
def repository_dashboard(
    repo_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> DashboardResponse:
    return service.get_dashboard(db, repo_id)


# =========================
# HEALTH
# =========================
@router.get("/repository/{repo_id}/health")
def repository_health(
    repo_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> HealthReportResponse:
    return service.get_health_report(db, repo_id)


# =========================
# METADATA
# =========================
@router.get("/repository/{repo_id}/metadata")
def repository_metadata(
    repo_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> MetadataResponse:
    return service.get_metadata(db, repo_id)


# =========================
# GRAPH
# =========================
@router.get("/repository/{repo_id}/graph")
def repository_graph(
    repo_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> GraphResponse:
    return service.get_graph(db, repo_id)


# =========================
# EXECUTION FLOW
# =========================
@router.get("/repository/{repo_id}/execution_flow")
def repository_execution_flow(
    repo_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> ExecutionFlowResponse:
    return service.get_execution_flow(db, repo_id)


# =========================
# SETTINGS
# =========================
@router.get("/repository/{repo_id}/settings")
def get_repository_settings(
    repo_id: str,
    db: Session = Depends(get_db),
    service: RepositoryService = Depends(get_repository_service),
) -> RepositorySettingsSchema:
    settings = service.get_settings(db, repo_id)
    return RepositorySettingsSchema(**settings)


@router.patch("/repository/{repo_id}/settings")
def update_repository_settings(
    repo_id: str,
    payload: RepositorySettingsUpdate,
    db: Session = Depends(get_db),
    service: RepositoryService = Depends(get_repository_service),
) -> RepositorySettingsSchema:
    settings = service.update_settings(
        db,
        repo_id,
        payload.model_dump(exclude_none=True)
    )
    return RepositorySettingsSchema(**settings)


# =========================
# REBUILD
# =========================
@router.post("/repository/{repo_id}/rebuild")
async def rebuild_repository(
    repo_id: str,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> RebuildResponse:

    response, task = service.rebuild(db, repo_id)

    if task:
        asyncio.create_task(service.dispatch_analysis(task))

    return response


# =========================
# EXPORTS
# =========================
@router.get("/repository/{repo_id}/export/readme")
def export_readme(
    repo_id: str,
    fmt: str = "markdown",
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> ExportResponse:
    return service.export_readme(db, repo_id, fmt=fmt)


@router.get("/repository/{repo_id}/export/documentation")
def export_documentation(
    repo_id: str,
    fmt: str = "markdown",
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> ExportResponse:
    return service.export_documentation(db, repo_id, fmt=fmt)


@router.get("/repository/{repo_id}/export/health")
def export_health(
    repo_id: str,
    fmt: str = "json",
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> ExportResponse:
    return service.export_health(db, repo_id, fmt=fmt)


# =========================
# COMPARE
# =========================
@router.post("/repository/compare")
def compare_repositories(
    payload: CompareRequest,
    db: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
) -> CompareResponse:
    return service.compare_repositories(
        db,
        payload.repo_a,
        payload.repo_b
    )


# =========================
# LIST
# =========================
@router.get("/repositories")
def list_repositories(
    db: Session = Depends(get_db),
    service: RepositoryService = Depends(get_repository_service),
) -> list[RepositorySummary]:
    return service.list_repositories(db)


# =========================
# DELETE
# =========================
@router.delete("/repository/{repo_id}")
def delete_repository(
    repo_id: str,
    db: Session = Depends(get_db),
    service: RepositoryService = Depends(get_repository_service),
) -> dict:
    service.delete_repository(db, repo_id)
    return {"deleted": True, "repository_id": repo_id}