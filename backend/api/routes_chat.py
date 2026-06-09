"""Chat and bookmark routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.core.dependencies import get_bookmark_service, get_chat_service, get_db
from backend.schemas.api_schemas import (
    BookmarkCreateRequest,
    BookmarkResponse,
    ChatCreateRequest,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
)
from backend.services.chat_service import BookmarkService, ChatService

router = APIRouter(tags=["chat"])


@router.post("/chat/create", response_model=ChatSessionResponse, summary="Create chat session")
def create_chat(
    payload: ChatCreateRequest,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionResponse:
    return service.create_chat(db, payload)


@router.get("/chat/list", response_model=list[ChatSessionResponse], summary="List chat sessions")
def list_chats(
    repository_id: str = Query(...),
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
) -> list[ChatSessionResponse]:
    return service.list_chats(db, repository_id)


@router.get("/chat/{chat_id}", response_model=ChatSessionResponse, summary="Get chat with messages")
def get_chat(
    chat_id: str,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionResponse:
    return service.get_chat(db, chat_id)


@router.post(
    "/chat/{chat_id}/message",
    response_model=ChatMessageResponse,
    summary="Send chat message and query orchestrator",
)
def send_chat_message(
    chat_id: str,
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    return service.send_message(db, chat_id, payload)


@router.delete("/chat/{chat_id}", summary="Delete chat session")
def delete_chat(
    chat_id: str,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    service.delete_chat(db, chat_id)
    return {"deleted": True, "chat_id": chat_id}


@router.post("/bookmark", response_model=BookmarkResponse, summary="Create bookmark")
def create_bookmark(
    payload: BookmarkCreateRequest,
    db: Session = Depends(get_db),
    service: BookmarkService = Depends(get_bookmark_service),
) -> BookmarkResponse:
    return service.create(db, payload)


@router.get("/bookmark/list", response_model=list[BookmarkResponse], summary="List bookmarks")
def list_bookmarks(
    repository_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    service: BookmarkService = Depends(get_bookmark_service),
) -> list[BookmarkResponse]:
    return service.list(db, repository_id)


@router.delete("/bookmark/{bookmark_id}", summary="Delete bookmark")
def delete_bookmark(
    bookmark_id: str,
    db: Session = Depends(get_db),
    service: BookmarkService = Depends(get_bookmark_service),
) -> dict:
    service.delete(db, bookmark_id)
    return {"deleted": True, "bookmark_id": bookmark_id}
