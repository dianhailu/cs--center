from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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


def list_conversations(
    db: Session,
    workspace_id: UUID,
    *,
    status: str | None = None,
    queue: str | None = None,
    assignee_id: UUID | None = None,
    limit: int = 50,
) -> list[Conversation]:
    q = select(Conversation).where(Conversation.workspace_id == workspace_id)
    if status:
        q = q.where(Conversation.status == ConversationStatus(status))
    if queue == "human":
        q = q.where(Conversation.needs_human.is_(True)).where(
            Conversation.status.in_([ConversationStatus.queued, ConversationStatus.assigned])
        )
    if queue == "mine" and assignee_id:
        q = q.where(Conversation.assignee_id == assignee_id)
    if queue == "closed":
        q = q.where(Conversation.status == ConversationStatus.closed)
    q = q.order_by(Conversation.last_message_at.desc().nullslast()).limit(limit)
    return list(db.scalars(q))


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
    direction = MessageDirection.note if as_note else MessageDirection.outbound
    msg = Message(
        conversation_id=conv.id,
        channel_connection_id=conv.channel_connection_id,
        direction=direction,
        sender_type=sender_type,
        sender_id=sender_id,
        body=body,
        send_status=MessageSendStatus.pending if not as_note else MessageSendStatus.local,
    )
    db.add(msg)
    db.flush()

    conv.last_message_at = datetime.now(timezone.utc)
    if sender_type == MessageSenderType.agent and conv.status != ConversationStatus.closed:
        conv.status = ConversationStatus.assigned
        if sender_id:
            conv.assignee_id = sender_id

    if not as_note:
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
