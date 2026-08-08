from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChannelConnection
from app.schemas import WebhookAck
from app.services.inbound import import_ticket

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/liveagent/{connection_id}", response_model=WebhookAck)
async def liveagent_webhook(
    connection_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
) -> WebhookAck:
    conn = db.get(ChannelConnection, connection_id)
    if not conn or conn.provider != "liveagent":
        raise HTTPException(404, "connection not found")
    if conn.webhook_secret and x_webhook_secret != conn.webhook_secret:
        raise HTTPException(401, "invalid webhook secret")

    raw = await request.json()
    ticket_id = (
        raw.get("ticket_id")
        or raw.get("ticketId")
        or raw.get("conversation_id")
        or raw.get("conversationId")
        or raw.get("code")
    )
    if not ticket_id and isinstance(raw.get("ticket"), dict):
        ticket_id = raw["ticket"].get("id")
    if not ticket_id:
        raise HTTPException(400, "ticket_id required")

    conv, imported, ai_enqueued = import_ticket(db, conn, str(ticket_id), enqueue_ai=True)
    return WebhookAck(
        ok=True,
        conversation_id=conv.id,
        imported_messages=imported,
        ai_enqueued=ai_enqueued,
    )
