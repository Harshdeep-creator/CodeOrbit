"""Chat and bookmark services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.core.errors import ChatNotFoundError, RepositoryNotFoundError, BookmarkNotFoundError
from backend.repositories import chat_repository, repo_repository
from backend.repositories.metadata_repository import create_bookmark, delete_bookmark, get_bookmark, list_bookmarks
from backend.schemas.api_schemas import (
    BookmarkCreateRequest,
    BookmarkResponse,
    ChatCreateRequest,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatMessageSchema,
    ChatSessionResponse,
    EvidenceSchema,
    QueryResponseSchema,
)
from backend.services.query_service import QueryService


class ChatService:
    def __init__(self, query_service: QueryService | None = None) -> None:
        self.query_service = query_service or QueryService()

    def create_chat(self, db: Session, payload: ChatCreateRequest) -> ChatSessionResponse:
        if not repo_repository.get_repository(db, payload.repository_id):
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": payload.repository_id})
        chat = chat_repository.create_session(db, payload.repository_id, payload.title)
        return self._to_session(db, chat)

    def list_chats(self, db: Session, repository_id: str) -> list[ChatSessionResponse]:
        return [self._to_session(db, chat) for chat in chat_repository.list_sessions(db, repository_id)]

    def get_chat(self, db: Session, chat_id: str) -> ChatSessionResponse:
        chat = chat_repository.get_session(db, chat_id)
        if not chat:
            raise ChatNotFoundError("Chat session not found.", {"chat_id": chat_id})
        return self._to_session(db, chat, include_messages=True)

    def send_message(self, db: Session, chat_id: str, payload: ChatMessageRequest) -> ChatMessageResponse:
        chat = chat_repository.get_session(db, chat_id)
        if not chat:
            raise ChatNotFoundError("Chat session not found.", {"chat_id": chat_id})

        user_message = chat_repository.add_message(db, chat_id, "user", payload.query)
        response = self.query_service.execute_query(db, chat.repository_id, payload.query, chat_id=chat_id)
        assistant_message = chat_repository.add_message(
            db,
            chat_id,
            "assistant",
            response.answer,
            evidence=response.evidence.model_dump(),
            confidence=response.confidence,
            graph_path=response.graph_path,
        )
        return ChatMessageResponse(
            user_message=self._to_message(user_message),
            assistant_message=self._to_message(assistant_message),
            response=response,
        )

    def delete_chat(self, db: Session, chat_id: str) -> None:
        if not chat_repository.delete_session(db, chat_id):
            raise ChatNotFoundError("Chat session not found.", {"chat_id": chat_id})

    @staticmethod
    def _to_message(message) -> ChatMessageSchema:
        evidence = message.evidence or {}
        return ChatMessageSchema(
            id=message.id,
            role=message.role,
            content=message.content,
            evidence=EvidenceSchema(
                files=list(evidence.get("files", [])),
                functions=list(evidence.get("functions", [])),
                lines=list(evidence.get("lines", [])),
            )
            if evidence
            else None,
            confidence=message.confidence,
            graph_path=message.graph_path,
            created_at=message.created_at,
        )

    def _to_session(self, db: Session, chat, include_messages: bool = False) -> ChatSessionResponse:
        messages = []
        if include_messages:
            messages = [self._to_message(msg) for msg in chat_repository.get_messages(db, chat.id)]
        return ChatSessionResponse(
            id=chat.id,
            repository_id=chat.repository_id,
            title=chat.title,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            messages=messages,
        )


class BookmarkService:
    def create(self, db: Session, payload: BookmarkCreateRequest) -> BookmarkResponse:
        if not repo_repository.get_repository(db, payload.repository_id):
            raise RepositoryNotFoundError("Repository not found.", {"repository_id": payload.repository_id})
        bookmark = create_bookmark(
            db,
            payload.repository_id,
            payload.query,
            payload.answer,
            payload.evidence.model_dump() if payload.evidence else None,
            payload.confidence,
            payload.graph_path,
        )
        return self._to_response(bookmark)

    def list(self, db: Session, repository_id: str | None = None) -> list[BookmarkResponse]:
        return [self._to_response(item) for item in list_bookmarks(db, repository_id)]

    def delete(self, db: Session, bookmark_id: str) -> None:
        if not delete_bookmark(db, bookmark_id):
            raise BookmarkNotFoundError("Bookmark not found.", {"bookmark_id": bookmark_id})

    @staticmethod
    def _to_response(bookmark) -> BookmarkResponse:
        evidence = bookmark.evidence or {}
        return BookmarkResponse(
            id=bookmark.id,
            repository_id=bookmark.repository_id,
            query=bookmark.query,
            answer=bookmark.answer,
            evidence=EvidenceSchema(
                files=list(evidence.get("files", [])),
                functions=list(evidence.get("functions", [])),
                lines=list(evidence.get("lines", [])),
            )
            if evidence
            else None,
            confidence=bookmark.confidence,
            graph_path=bookmark.graph_path,
            created_at=bookmark.created_at,
        )
