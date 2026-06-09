"""Pydantic request and response models for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    error: str = Field(..., examples=["repository_not_found"])
    message: str = Field(..., examples=["Repository not found."])
    details: Dict[str, Any] = Field(default_factory=dict)


class EvidenceSchema(BaseModel):
    files: List[str] = Field(default_factory=list)
    functions: List[Any] = Field(default_factory=list)
    lines: List[Any] = Field(default_factory=list)


class QueryResponseSchema(BaseModel):
    answer: str
    evidence: EvidenceSchema = Field(default_factory=EvidenceSchema)
    graph_path: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "Execution flow starts at `main.py` and reaches 4 graph nodes.",
                "evidence": {"files": ["main.py"], "functions": [], "lines": []},
                "graph_path": ["function:main.py:main"],
                "confidence": 0.86,
            }
        }
    )


class UploadRepoResponse(BaseModel):
    repository_id: str
    name: str
    repo_hash: str
    file_count: int
    language_summary: Dict[str, int]
    status: str
    cached: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "repository_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "sample-repo",
                "repo_hash": "abc123",
                "file_count": 12,
                "language_summary": {"python": 10, "javascript": 2},
                "status": "uploaded",
                "cached": False,
            }
        }
    )


class AnalyzeRequest(BaseModel):
    repository_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    force: bool = False


class AnalyzeResponse(BaseModel):
    job_id: str
    repository_id: str
    status: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "660e8400-e29b-41d4-a716-446655440001",
                "repository_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "queued",
            }
        }
    )


class AnalysisStatusResponse(BaseModel):
    job_id: str
    repository_id: str
    status: str
    progress: float
    message: str
    retry_count: int = 0
    error_detail: Optional[str] = None
    updated_at: datetime


class QueryRequest(BaseModel):
    repository_id: str
    query: str = Field(..., min_length=1, examples=["what is the main entry point?"])
    chat_id: Optional[str] = None


class RepositorySummary(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    file_count: int
    language_summary: Optional[Dict[str, int]] = None
    status: str
    upload_timestamp: datetime


class ChatCreateRequest(BaseModel):
    repository_id: str
    title: str = "New Chat"


class ChatMessageSchema(BaseModel):
    id: str
    role: str
    content: str
    evidence: Optional[EvidenceSchema] = None
    confidence: Optional[float] = None
    graph_path: Optional[List[str]] = None
    created_at: datetime


class ChatSessionResponse(BaseModel):
    id: str
    repository_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessageSchema] = Field(default_factory=list)


class ChatMessageRequest(BaseModel):
    query: str = Field(..., min_length=1)


class ChatMessageResponse(BaseModel):
    user_message: ChatMessageSchema
    assistant_message: ChatMessageSchema
    response: QueryResponseSchema


class DashboardResponse(BaseModel):
    repository_id: str
    name: str
    languages: Dict[str, int]
    file_count: int
    function_count: int
    class_count: int
    entry_points: List[str]
    analysis_timestamp: Optional[datetime] = None


class HealthReportResponse(BaseModel):
    repository_id: str
    health_score: float
    dead_code_count: int
    circular_dependency_count: int
    security_smell_count: int
    architecture_smell_count: int
    evidence: EvidenceSchema
    issues: List[Dict[str, Any]] = Field(default_factory=list)


class MetadataResponse(BaseModel):
    repository_id: str
    files_parsed: int
    functions_indexed: int
    classes_indexed: int
    graph_nodes: int
    graph_edges: int
    embeddings_generated: int
    entry_points: List[str]
    analysis_timestamp: Optional[datetime] = None
    analysis_duration: float = 0.0


class GraphNodeSchema(BaseModel):
    id: str
    type: str
    label: str
    file: Optional[str] = None
    line: Optional[int] = None


class GraphEdgeSchema(BaseModel):
    source: str
    target: str
    type: str
    weight: float = 1.0


class GraphResponse(BaseModel):
    repository_id: str
    nodes: List[GraphNodeSchema]
    edges: List[GraphEdgeSchema]


class ExecutionFlowResponse(BaseModel):
    repository_id: str
    entry_points: List[str]
    execution_flows: Dict[str, List[str]]


class RepositorySettingsSchema(BaseModel):
    cache_behavior: str = "enabled"
    rebuild_analysis: bool = False


class RepositorySettingsUpdate(BaseModel):
    cache_behavior: Optional[str] = None
    rebuild_analysis: Optional[bool] = None


class RebuildResponse(BaseModel):
    repository_id: str
    job_id: str
    status: str


class BookmarkCreateRequest(BaseModel):
    repository_id: str
    query: str
    answer: str
    evidence: Optional[EvidenceSchema] = None
    confidence: Optional[float] = None
    graph_path: Optional[List[str]] = None


class BookmarkResponse(BaseModel):
    id: str
    repository_id: str
    query: str
    answer: str
    evidence: Optional[EvidenceSchema] = None
    confidence: Optional[float] = None
    graph_path: Optional[List[str]] = None
    created_at: datetime


class ExportResponse(BaseModel):
    repository_id: str
    format: str
    content: str


class CompareRequest(BaseModel):
    repo_a: str
    repo_b: str


class CompareResponse(BaseModel):
    repo_a: str
    repo_b: str
    architecture_diff: Dict[str, Any]
    complexity_diff: Dict[str, Any]
    risk_diff: Dict[str, Any]
    maintainability_diff: Dict[str, Any]
