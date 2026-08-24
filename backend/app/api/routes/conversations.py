from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AuthContext, get_auth
from app.db import get_db
from app.models import Conversation, MessageSenderType, Product, ROLE_SYSTEM_ADMIN, Workspace
from app.rbac import list_accessible_workspaces, normalize_product, workspace_allowed
from app.schemas import (
    AssignRequest,
    ConversationDetail,
    ConversationOut,
    MessageOut,
    SendMessageRequest,
)
from app.services import conversations as conv_svc

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _workspace_ids_for_list(
    auth: AuthContext,
    db: Session,
    *,
    all_products: bool,
    product_code: str | None,
) -> list[UUID]:
    accessible = list_accessible_workspaces(db, auth.agent)
    if all_products and auth.role == ROLE_SYSTEM_ADMIN:
        if product_code:
            pc = normalize_product(product_code)
            return [w.id for w in accessible if w.product_code == pc]
        return [w.id for w in accessible]
    if product_code:
        pc = normalize_product(product_code)
        matched = [w.id for w in accessible if w.product_code == pc]
        if matched:
            return matched
    return [auth.workspace_id]


def _conversation_meta(
    db: Session, workspace_ids: list[UUID]
) -> dict[UUID, tuple[str, str, str]]:
    rows = db.scalars(select(Workspace).where(Workspace.id.in_(workspace_ids))).all()
    products = {
        p.code: p.name
        for p in db.scalars(
            select(Product).where(Product.code.in_([w.product_code for w in rows] or ["__none__"]))
        )
    }
    out: dict[UUID, tuple[str, str, str]] = {}
    for ws in rows:
        out[ws.id] = (ws.product_code, products.get(ws.product_code, ws.product_code), ws.name)
    return out


def _to_conversation_out(conv, meta: dict[UUID, tuple[str, str, str]]) -> ConversationOut:
    pc, pn, wn = meta.get(conv.workspace_id, (None, None, None))
    base = ConversationOut.model_validate(conv)
    return base.model_copy(
        update={
            "product_code": pc,
            "product_name": pn,
            "workspace_name": wn,
        }
    )


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    queue: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Fuzzy search: phone / email / ticket code"),
    all_products: bool = Query(default=False, description="System admin: merge all product inboxes"),
    product_code: str | None = Query(default=None, description="Filter by product code"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> list:
    if all_products and auth.role != ROLE_SYSTEM_ADMIN:
        raise HTTPException(403, "all_products requires system_admin")
    workspace_ids = _workspace_ids_for_list(
        auth, db, all_products=all_products, product_code=product_code
    )
    rows = conv_svc.list_conversations(
        db,
        workspace_ids,
        status=status,
        queue=queue,
        assignee_id=auth.agent.id,
        q=q,
    )
    meta = _conversation_meta(db, workspace_ids)
    return [_to_conversation_out(c, meta) for c in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    if not conv:
        raise HTTPException(404, "not found")
    if not workspace_allowed(db, auth.agent, conv.workspace_id):
        raise HTTPException(403, "workspace not allowed")
    messages = sorted(conv.messages, key=lambda m: m.created_at)
    meta = _conversation_meta(db, [conv.workspace_id])
    base = _to_conversation_out(conv, meta)
    return ConversationDetail(
        **base.model_dump(),
        customer_snapshot=conv.customer_snapshot or {},
        messages=[MessageOut.model_validate(m) for m in messages],
    )


def _get_conversation_allowed(db: Session, auth: AuthContext, conversation_id: UUID) -> Conversation | None:
    conv = conv_svc.get_conversation_any(db, conversation_id)
    if not conv or not workspace_allowed(db, auth.agent, conv.workspace_id):
        return None
    return conv


@router.post("/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: UUID,
    body: SendMessageRequest,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> MessageOut:
    conv = _get_conversation_allowed(db, auth, conversation_id)
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
    conv = _get_conversation_allowed(db, auth, conversation_id)
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
    conv = _get_conversation_allowed(db, auth, conversation_id)
    if not conv:
        raise HTTPException(404, "not found")
    conv = conv_svc.close_conversation(db, conv)
    return ConversationOut.model_validate(conv)
