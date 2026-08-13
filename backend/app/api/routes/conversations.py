from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth
from app.db import get_db
from app.models import MessageSenderType
from app.schemas import (
    AssignRequest,
    ConversationDetail,
    ConversationOut,
    MessageOut,
    SendMessageRequest,
)
from app.services import conversations as conv_svc

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    queue: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Fuzzy search: phone / email / ticket code"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> list:
    return conv_svc.list_conversations(
        db,
        auth.workspace_id,
        status=status,
        queue=queue,
        assignee_id=auth.agent.id,
        q=q,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    conv = conv_svc.get_conversation(db, conversation_id, auth.workspace_id)
    if not conv:
        raise HTTPException(404, "not found")
    messages = sorted(conv.messages, key=lambda m: m.created_at)
    return ConversationDetail(
        id=conv.id,
        workspace_id=conv.workspace_id,
        external_id=conv.external_id,
        external_code=conv.external_code,
        subject=conv.subject,
        status=conv.status.value,
        customer_name=conv.customer_name,
        customer_email=conv.customer_email,
        tags=conv.tags or [],
        assignee_id=conv.assignee_id,
        channel_type=conv.channel_type,
        la_status=conv.la_status,
        ai_handled=conv.ai_handled,
        needs_human=conv.needs_human,
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
        customer_snapshot=conv.customer_snapshot or {},
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.post("/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: UUID,
    body: SendMessageRequest,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> MessageOut:
    conv = conv_svc.get_conversation(db, conversation_id, auth.workspace_id)
    if not conv:
        raise HTTPException(404, "not found")
    msg = conv_svc.send_outbound_message(
        db,
        conv,
        body=body.body,
        sender_type=MessageSenderType.agent,
        sender_id=auth.agent.id,
        as_note=body.as_note,
    )
    return MessageOut.model_validate(msg)


@router.post("/{conversation_id}/assign", response_model=ConversationOut)
def assign(
    conversation_id: UUID,
    body: AssignRequest,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> ConversationOut:
    conv = conv_svc.get_conversation(db, conversation_id, auth.workspace_id)
    if not conv:
        raise HTTPException(404, "not found")
    agent_id = body.agent_id or auth.agent.id
    conv = conv_svc.assign_conversation(db, conv, agent_id)
    return ConversationOut.model_validate(conv)


@router.post("/{conversation_id}/close", response_model=ConversationOut)
def close(
    conversation_id: UUID,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> ConversationOut:
    conv = conv_svc.get_conversation(db, conversation_id, auth.workspace_id)
    if not conv:
        raise HTTPException(404, "not found")
    conv = conv_svc.close_conversation(db, conv)
    return ConversationOut.model_validate(conv)
