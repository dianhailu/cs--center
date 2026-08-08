from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.liveagent import LiveAgentClient, client_from_connection
from app.models import (
    AiJob,
    ChannelConnection,
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageSendStatus,
    MessageSenderType,
)
from app.redis_bus import conversation_event

logger = logging.getLogger(__name__)


def import_ticket(
    db: Session,
    connection: ChannelConnection,
    ticket_id: str,
    *,
    enqueue_ai: bool = True,
) -> tuple[Conversation, int, bool]:
    la = client_from_connection(connection)
    try:
        ticket = la.get_ticket(ticket_id)
        groups = la.get_ticket_messages(ticket_id)
        flat = la.flatten_messages(groups)
    finally:
        la.close()

    conv = db.scalar(
        select(Conversation).where(
            Conversation.channel_connection_id == connection.id,
            Conversation.external_id == ticket_id,
        )
    )
    if not conv:
        conv = Conversation(
            workspace_id=connection.workspace_id,
            channel_connection_id=connection.id,
            external_id=ticket_id,
            status=ConversationStatus.queued,
        )
        db.add(conv)
        db.flush()

    conv.external_code = ticket.get("code") or conv.external_code
    conv.subject = ticket.get("subject") or conv.subject
    conv.customer_name = ticket.get("owner_name") or conv.customer_name
    conv.customer_email = ticket.get("owner_email") or conv.customer_email
    conv.channel_type = ticket.get("channel_type") or conv.channel_type
    conv.la_status = ticket.get("status") or conv.la_status
    tags = ticket.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in tags.split(",") if t]
    conv.tags = tags
    conv.customer_snapshot = {
        "owner_contactid": ticket.get("owner_contactid"),
        "owner_email": ticket.get("owner_email"),
        "owner_name": ticket.get("owner_name"),
        "departmentid": ticket.get("departmentid"),
        "la_status": ticket.get("status"),
    }

    imported = 0
    latest_inbound: Message | None = None
    for item in flat:
        existing = db.scalar(
            select(Message).where(
                Message.channel_connection_id == connection.id,
                Message.external_id == item["external_id"],
            )
        )
        if existing:
            continue
        is_note = bool(item.get("is_note"))
        # Treat notes as outbound/system; public messages without agent heuristic as inbound customer
        if is_note:
            direction = MessageDirection.note
            sender_type = MessageSenderType.system
        else:
            # If conversation already has AI/agent outbound with same body recently, skip mis-classify
            direction = MessageDirection.inbound
            sender_type = MessageSenderType.customer
        msg = Message(
            conversation_id=conv.id,
            channel_connection_id=connection.id,
            external_id=item["external_id"],
            direction=direction,
            sender_type=sender_type,
            body=item["body"],
            send_status=MessageSendStatus.sent,
            meta={"userid": item.get("userid"), "datecreated": item.get("datecreated")},
        )
        db.add(msg)
        imported += 1
        if direction == MessageDirection.inbound:
            latest_inbound = msg
            created = item.get("datecreated")
            if created:
                try:
                    # LA timestamps are naive UTC-ish strings
                    conv.last_message_at = datetime.fromisoformat(str(created).replace(" ", "T")).replace(
                        tzinfo=timezone.utc
                    )
                except Exception:  # noqa: BLE001
                    conv.last_message_at = datetime.now(timezone.utc)
            else:
                conv.last_message_at = datetime.now(timezone.utc)

    ai_enqueued = False
    db.flush()
    if enqueue_ai and not conv.ai_handled and not conv.needs_human:
        trigger = latest_inbound
        if trigger is None:
            trigger = db.scalar(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.direction == MessageDirection.inbound,
                )
                .order_by(Message.created_at.desc())
            )
        pending = db.scalar(
            select(AiJob).where(
                AiJob.conversation_id == conv.id,
                AiJob.status.in_(["pending", "processing"]),
            )
        )
        if trigger and not pending:
            job = AiJob(
                conversation_id=conv.id,
                trigger_message_id=trigger.id,
                status="pending",
            )
            db.add(job)
            conv.status = ConversationStatus.ai_pending
            ai_enqueued = True

    # reopen closed/queued if new inbound
    if latest_inbound and conv.status == ConversationStatus.closed:
        conv.status = ConversationStatus.queued

    db.commit()
    db.refresh(conv)
    conversation_event(conv.id, "conversation.updated", {"imported": imported})
    return conv, imported, ai_enqueued


def poll_connection(db: Session, connection: ChannelConnection, limit: int = 30) -> int:
    la = client_from_connection(connection)
    try:
        tickets = la.list_recent_tickets(per_page=limit)
    finally:
        la.close()
    count = 0
    for t in tickets:
        tid = t.get("id")
        if not tid:
            continue
        try:
            _, imported, _ = import_ticket(db, connection, tid, enqueue_ai=True)
            count += imported
        except Exception as exc:  # noqa: BLE001
            logger.exception("poll import failed for %s: %s", tid, exc)
            db.rollback()
    return count


def backfill_connection(
    db: Session,
    connection: ChannelConnection,
    *,
    per_page: int = 50,
    max_pages: int = 100,
    enqueue_ai: bool = False,
    channel_type: str | None = None,
) -> dict[str, int]:
    """Page through LiveAgent tickets and import messages (for historical sync)."""
    la = client_from_connection(connection)
    stats = {"pages": 0, "tickets": 0, "imported_messages": 0, "errors": 0, "skipped": 0}
    try:
        for page in range(1, max_pages + 1):
            try:
                tickets = la.list_tickets(page=page, per_page=per_page, sort_field="date_created", sort_dir="DESC")
            except Exception as exc:  # noqa: BLE001
                logger.exception("backfill list page=%s failed: %s", page, exc)
                stats["errors"] += 1
                break
            if not tickets:
                break
            stats["pages"] = page
            for t in tickets:
                tid = t.get("id")
                if not tid:
                    continue
                if channel_type:
                    ct = str(t.get("channel_type") or "")
                    if ct.lower() != channel_type.lower():
                        stats["skipped"] += 1
                        continue
                try:
                    _, imported, _ = import_ticket(db, connection, str(tid), enqueue_ai=enqueue_ai)
                    stats["tickets"] += 1
                    stats["imported_messages"] += imported
                except Exception as exc:  # noqa: BLE001
                    logger.exception("backfill import failed for %s: %s", tid, exc)
                    db.rollback()
                    stats["errors"] += 1
            if len(tickets) < per_page:
                break
    finally:
        la.close()
    return stats
