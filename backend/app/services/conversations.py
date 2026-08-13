from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageSendStatus,
    MessageSenderType,
    OutboxEvent,
    OutboxStatus,
)
from app.redis_bus import conversation_event

_PHONE_SEP_RE = re.compile(r"[\s\-()./+]+")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_phone_digits(raw: str) -> str:
    return _PHONE_SEP_RE.sub("", (raw or "").strip())


def _sql_strip_phone(expr: ColumnElement) -> ColumnElement:
    """Remove common phone separators so '0812' matches '0812-xxx'."""
    out: ColumnElement = cast(expr, String)
    for ch in (" ", "-", "(", ")", ".", "/", "+"):
        out = func.replace(out, ch, "")
    return out


def _contains_ci(expr: ColumnElement, needle: str) -> ColumnElement:
    pattern = f"%{_escape_like(needle.lower())}%"
    return func.lower(func.coalesce(cast(expr, String), "")).like(pattern, escape="\\")


def _search_filter(term: str) -> ColumnElement | None:
    raw = (term or "").strip()
    if not raw:
        return None
    clauses: list[ColumnElement] = [
        _contains_ci(Conversation.customer_email, raw),
        _contains_ci(Conversation.customer_name, raw),
        _contains_ci(Conversation.external_code, raw),
        _contains_ci(Conversation.external_id, raw),
    ]
    phone_json = Conversation.customer_snapshot["phone"].as_string()
    owner_email_json = Conversation.customer_snapshot["owner_email"].as_string()
    clauses.append(_contains_ci(phone_json, raw))
    clauses.append(_contains_ci(owner_email_json, raw))

    phone_q = _normalize_phone_digits(raw)
    if phone_q and any(c.isdigit() for c in raw):
        # Digits-only so "0812" matches snapshot "0812-3456-7890".
        clauses.append(_contains_ci(_sql_strip_phone(phone_json), phone_q))

    return or_(*clauses)


def list_conversations(
    db: Session,
    workspace_id: UUID,
    *,
    status: str | None = None,
    queue: str | None = None,
    assignee_id: UUID | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[Conversation]:
    stmt = select(Conversation).where(Conversation.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(Conversation.status == ConversationStatus(status))
    if queue == "human":
        stmt = stmt.where(Conversation.needs_human.is_(True)).where(
            Conversation.status.in_([ConversationStatus.queued, ConversationStatus.assigned])
        )
    if queue == "mine" and assignee_id:
        stmt = stmt.where(Conversation.assignee_id == assignee_id)
    if queue == "closed":
        stmt = stmt.where(Conversation.status == ConversationStatus.closed)
    search = _search_filter(q or "")
    if search is not None:
        stmt = stmt.where(search)
    stmt = stmt.order_by(Conversation.last_message_at.desc().nullslast()).limit(limit)
    return list(db.scalars(stmt))


def get_conversation(db: Session, conversation_id: UUID, workspace_id: UUID) -> Conversation | None:
    return db.scalar(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.workspace_id == workspace_id)
    )


def send_outbound_message(
    db: Session,
    conv: Conversation,
    *,
    body: str,
    sender_type: MessageSenderType,
    sender_id: UUID | None = None,
    as_note: bool = False,
) -> Message:
    settings = get_settings()
    # AI → visitor delivery gated by AI_SEND_TO_CUSTOMER (default false).
    # Human agent composer still delivers via outbox.
    deliver = True
    if (
        not as_note
        and sender_type == MessageSenderType.ai
        and not settings.ai_send_to_customer
    ):
        deliver = False

    direction = MessageDirection.note if as_note else MessageDirection.outbound
    meta: dict = {"source": "ai"} if sender_type == MessageSenderType.ai else {}
    if not deliver:
        meta = {
            **meta,
            "deliver": "skipped",
            "reason": "AI_SEND_TO_CUSTOMER=false",
        }

    if as_note:
        send_status = MessageSendStatus.local
    elif not deliver:
        send_status = MessageSendStatus.local_only
    else:
        send_status = MessageSendStatus.pending

    msg = Message(
        conversation_id=conv.id,
        channel_connection_id=conv.channel_connection_id,
        direction=direction,
        sender_type=sender_type,
        sender_id=sender_id,
        body=body,
        send_status=send_status,
        meta=meta,
    )
    db.add(msg)
    db.flush()

    conv.last_message_at = datetime.now(timezone.utc)
    if sender_type == MessageSenderType.agent and conv.status != ConversationStatus.closed:
        conv.status = ConversationStatus.assigned
        if sender_id:
            conv.assignee_id = sender_id

    if not as_note and deliver:
        db.add(
            OutboxEvent(
                workspace_id=conv.workspace_id,
                channel_connection_id=conv.channel_connection_id,
                conversation_id=conv.id,
                message_id=msg.id,
                event_type="send_message",
                payload={"body": body, "as_note": False},
                status=OutboxStatus.pending,
            )
        )
    db.commit()
    db.refresh(msg)
    conversation_event(conv.id, "message.created", {"message_id": str(msg.id)})
    return msg


def assign_conversation(
    db: Session, conv: Conversation, agent_id: UUID | None
) -> Conversation:
    conv.assignee_id = agent_id
    conv.status = ConversationStatus.assigned if agent_id else ConversationStatus.queued
    conv.needs_human = True
    db.commit()
    db.refresh(conv)
    conversation_event(conv.id, "conversation.assigned", {"assignee_id": str(agent_id) if agent_id else None})
    return conv


def close_conversation(db: Session, conv: Conversation) -> Conversation:
    conv.status = ConversationStatus.closed
    db.commit()
    db.refresh(conv)
    conversation_event(conv.id, "conversation.closed")
    return conv
