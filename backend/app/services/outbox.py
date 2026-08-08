from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.liveagent import client_from_connection
from app.models import (
    ChannelConnection,
    Conversation,
    Message,
    MessageSendStatus,
    OutboxEvent,
    OutboxStatus,
)
from app.redis_bus import conversation_event

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 8


def process_outbox_batch(db: Session, limit: int = 20) -> int:
    events = list(
        db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.pending)
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )
    )
    done = 0
    for event in events:
        event.status = OutboxStatus.processing
        event.attempts += 1
        event.updated_at = datetime.now(timezone.utc)
        db.commit()
        try:
            _process_one(db, event)
            event.status = OutboxStatus.done
            event.last_error = None
            done += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("outbox failed %s: %s", event.id, exc)
            event.last_error = str(exc)[:2000]
            event.status = OutboxStatus.dead if event.attempts >= MAX_ATTEMPTS else OutboxStatus.pending
            msg = db.get(Message, event.message_id)
            if msg:
                msg.send_status = MessageSendStatus.failed
        event.updated_at = datetime.now(timezone.utc)
        db.commit()
        conversation_event(event.conversation_id, "outbox.updated", {"event_id": str(event.id)})
    return done


def _process_one(db: Session, event: OutboxEvent) -> None:
    conn = db.get(ChannelConnection, event.channel_connection_id)
    conv = db.get(Conversation, event.conversation_id)
    msg = db.get(Message, event.message_id)
    if not conn or not conv or not msg:
        raise RuntimeError("missing outbox relations")

    la = client_from_connection(conn)
    try:
        result = la.post_reply(conv.external_id, msg.body, as_note=False)
    finally:
        la.close()

    external = None
    if isinstance(result, dict):
        external = (
            result.get("id")
            or result.get("messageid")
            or (result.get("response") or {}).get("messageid")
            or result.get("external_stub")
        )
    if external:
        msg.external_id = str(external)
    msg.send_status = MessageSendStatus.sent
    db.commit()
