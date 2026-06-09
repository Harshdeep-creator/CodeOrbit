"""Query routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.dependencies import get_db, get_query_service
from backend.schemas.api_schemas import QueryRequest, QueryResponseSchema
from backend.services.query_service import QueryService

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponseSchema, summary="Query analyzed repository")
def query_repository(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    service: QueryService = Depends(get_query_service),
) -> QueryResponseSchema:
    return service.execute_query(db, payload.repository_id, payload.query, payload.chat_id)
