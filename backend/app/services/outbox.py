from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.liveagent import client_from_connection
from app.config import get_settings
from app.models import (
    ChannelConnection,
    Conversation,
    ConversationStatus,
    Message,
    MessageSendStatus,
    MessageSenderType,
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
            db.rollback()
            event = db.get(OutboxEvent, event.id) or event
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

    # Safety net: never deliver Smart/AI to visitors when flag is off
    # (covers leftover pending outbox rows created before the gate).
    settings = get_settings()
    if msg.sender_type == MessageSenderType.ai and not settings.ai_send_to_customer:
        msg.send_status = MessageSendStatus.local_only
        msg.meta = {
            **(msg.meta or {}),
            "deliver": "skipped",
            "reason": "AI_SEND_TO_CUSTOMER=false",
        }
        db.commit()
        logger.info(
            "skipped AI outbox deliver message=%s conversation=%s",
            msg.id,
            conv.external_id,
        )
        return

    la = client_from_connection(conn)
    deliver_meta: dict = {}
    result: dict = {}
    try:
        session: str | None = None
        # Panel 「回复」 must run while the chat is still ringing. attendants
        # transfer first removes ringing and makes pickUpChat return 无效请求.
        if la.config.panel_accept and not la.config.dry_run:
            try:
                accepted = la.accept_chat(conv.external_id)
                session = str(accepted.get("session") or "") or None
                deliver_meta["panel_accept"] = {
                    "answered": accepted.get("answered"),
                    "join": accepted.get("join"),
                }
                if str(accepted.get("answered") or "").upper() == "Y":
                    if conv.status != ConversationStatus.closed:
                        conv.status = ConversationStatus.assigned
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "accept_chat failed conversation=%s; continuing without panel accept: %s",
                    conv.external_id,
                    exc,
                )
                deliver_meta["panel_accept_error"] = str(exc)[:500]

            if session:
                try:
                    result = la.create_chat_answer(conv.external_id, msg.body, session=session)
                    deliver_meta["visitor_path"] = "type_c"
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "create_chat_answer failed conversation=%s answered=%s; fallback type5: %s",
                        conv.external_id,
                        (deliver_meta.get("panel_accept") or {}).get("answered"),
                        exc,
                    )
                    deliver_meta["visitor_path"] = "type_5_fallback"
                    deliver_meta["create_chat_answer_error"] = str(exc)[:500]
                    result = la.post_reply(conv.external_id, msg.body, as_note=False)
            else:
                deliver_meta["visitor_path"] = "type_5_no_session"
                result = la.post_reply(conv.external_id, msg.body, as_note=False)
        else:
            deliver_meta["visitor_path"] = "type_5"
            result = la.post_reply(conv.external_id, msg.body, as_note=False)

        # Transfer after panel accept so ringing pickUpChat can succeed first.
        if la.config.auto_transfer and not la.config.dry_run:
            try:
                la.transfer_to_agent(conv.external_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "transfer_to_agent failed conversation=%s; message already posted: %s",
                    conv.external_id,
                    exc,
                )
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
    meta = {**(msg.meta or {}), **deliver_meta}
    if isinstance(result, dict) and result.get("dry_run"):
        meta["dry_run"] = True
        logger.warning(
            "outbox message %s marked sent under DRY_RUN — not visible in LiveAgent",
            msg.id,
        )
    msg.meta = meta
    msg.send_status = MessageSendStatus.sent
    try:
        db.commit()
    except Exception:
        # e.g. uq_msg_external when a prior partial send already stored this stub
        db.rollback()
        db.refresh(msg)
        if not msg.external_id and external:
            msg.external_id = f"{external}-{msg.id}"
        msg.meta = meta
        msg.send_status = MessageSendStatus.sent
        db.commit()
        logger.warning(
            "outbox message %s committed after external_id conflict; visitor_path=%s",
            msg.id,
            deliver_meta.get("visitor_path"),
        )
