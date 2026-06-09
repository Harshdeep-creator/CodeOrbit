"""Database CRUD for chat sessions and messages."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.database import ChatMessage, ChatSession, utcnow


def create_session(session: Session, repo_id: str, title: str = "New Chat") -> ChatSession:
    chat = ChatSession(
        id=str(uuid.uuid4()),
        repository_id=repo_id,
        title=title,
    )
    session.add(chat)
    session.flush()
    return chat


def list_sessions(session: Session, repo_id: str) -> List[ChatSession]:
    return list(
        session.scalars(
            select(ChatSession)
            .where(ChatSession.repository_id == repo_id)
            .order_by(ChatSession.updated_at.desc())
        )
    )


def get_session(session: Session, chat_id: str) -> Optional[ChatSession]:
    return session.get(ChatSession, chat_id)


def delete_session(session: Session, chat_id: str) -> bool:
    chat = session.get(ChatSession, chat_id)
    if not chat:
        return False
    session.delete(chat)
    return True


def add_message(
    session: Session,
    chat_id: str,
    role: str,
    content: str,
    evidence: dict | None = None,
    confidence: float | None = None,
    graph_path: list | None = None,
) -> ChatMessage:
    message = ChatMessage(
        id=str(uuid.uuid4()),
        chat_session_id=chat_id,
        role=role,
        content=content,
        evidence=evidence,
        confidence=confidence,
        graph_path=graph_path,
    )
    session.add(message)
    chat = session.get(ChatSession, chat_id)
    if chat:
        chat.updated_at = utcnow()
    session.flush()
    return message


def get_messages(session: Session, chat_id: str) -> List[ChatMessage]:
    return list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.chat_session_id == chat_id)
            .order_by(ChatMessage.created_at.asc())
        )
    )
