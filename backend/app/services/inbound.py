from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

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
from app.services.ai_loop import (
    normalize_body,
    skip_reason_for_trigger,
)
from app.services.message_time import parse_la_timestamp

logger = logging.getLogger(__name__)

_PHONE_LINE_RE = re.compile(r"(?i)^phone\s*:\s*(.+)$")


def _enrich_snapshot_from_inbound(
    conv: Conversation,
    *,
    body: str,
    userid: str,
    contact_id: str,
) -> None:
    snap = dict(conv.customer_snapshot or {})
    phone_m = _PHONE_LINE_RE.match((body or "").strip())
    if phone_m and not snap.get("phone"):
        snap["phone"] = phone_m.group(1).strip()
    uid = (userid or "").strip()
    if uid and uid != contact_id and not snap.get("visitor_userid"):
        snap["visitor_userid"] = uid
    conv.customer_snapshot = snap


def _find_unlinked_ai_echo(
    db: Session,
    conv: Conversation,
    *,
    body: str,
) -> Message | None:
    """Match LA echo of a local Smart outbound that still lacks external_id."""
    norm = normalize_body(body)
    if not norm:
        return None
    candidates = list(
        db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.sender_type == MessageSenderType.ai,
                Message.direction == MessageDirection.outbound,
                Message.external_id.is_(None),
            )
            .order_by(Message.created_at.desc())
            .limit(20)
        )
    )
    for m in candidates:
        if normalize_body(m.body) == norm:
            return m
    return None


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
        agent_dir = la.list_agent_directory()
    finally:
        la.close()

    contact_id = str(ticket.get("owner_contactid") or "").strip()

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
    prev_snap = conv.customer_snapshot or {}
    conv.customer_snapshot = {
        "owner_contactid": ticket.get("owner_contactid"),
        "owner_email": ticket.get("owner_email"),
        "owner_name": ticket.get("owner_name"),
        "departmentid": ticket.get("departmentid"),
        "la_status": ticket.get("status"),
        **({"phone": prev_snap["phone"]} if prev_snap.get("phone") else {}),
        **(
            {"visitor_userid": prev_snap["visitor_userid"]}
            if prev_snap.get("visitor_userid")
            else {}
        ),
    }

    known_ai_bodies = {
        normalize_body(m.body)
        for m in db.scalars(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.sender_type == MessageSenderType.ai,
            )
        )
        if normalize_body(m.body)
    }

    imported = 0
    latest_inbound: Message | None = None
    new_inbound = False
    for item in flat:
        body_raw = str(item.get("body") or "")
        body_norm = normalize_body(body_raw)
        # Prefer body-match so LA echoes of Smart stay labeled ai (not PinGo CS human).
        direction_s, sender_s = LiveAgentClient.classify_sender(
            {**item, "body": body_raw},
            agent_user_ids=agent_dir["ids"],
            agent_emails=agent_dir["emails"],
            agent_names=agent_dir["names"],
            agent_email=connection.agent_email or "",
            contact_id=contact_id,
            known_ai_bodies=known_ai_bodies,
        )
        if body_norm and body_norm in known_ai_bodies:
            direction_s, sender_s = "outbound", "ai"
        direction = MessageDirection(direction_s)
        sender_type = MessageSenderType(sender_s)

        existing = db.scalar(
            select(Message).where(
                Message.channel_connection_id == connection.id,
                Message.external_id == item["external_id"],
            )
        )
        if existing:
            # Never demote local/imported Smart bubbles to human PinGo CS.
            if existing.sender_type == MessageSenderType.ai:
                sender_type = MessageSenderType.ai
                direction = MessageDirection.outbound
            if existing.sender_type != sender_type or existing.direction != direction:
                existing.sender_type = sender_type
                existing.direction = direction
            # Always refresh LA timestamp metadata (stats bucket by consult time).
            existing.meta = {
                **(existing.meta or {}),
                "userid": item.get("userid"),
                "user_email": item.get("user_email"),
                "user_name": item.get("user_name"),
                "datecreated": item.get("datecreated"),
                **({"la_echo_of_ai": True} if sender_type == MessageSenderType.ai else {}),
            }
            la_at = parse_la_timestamp(item.get("datecreated"))
            if la_at is not None:
                existing.created_at = la_at
            if direction == MessageDirection.inbound:
                latest_inbound = existing
                _enrich_snapshot_from_inbound(
                    conv,
                    body=body_raw or existing.body or "",
                    userid=str(item.get("userid") or ""),
                    contact_id=contact_id,
                )
            continue

        # Link LA echo onto local Smart outbound (same body, no external_id yet).
        if direction == MessageDirection.outbound or sender_type in {
            MessageSenderType.agent,
            MessageSenderType.ai,
        }:
            local_ai = _find_unlinked_ai_echo(db, conv, body=body_raw)
            if local_ai:
                local_ai.external_id = str(item["external_id"])
                local_ai.sender_type = MessageSenderType.ai
                local_ai.direction = MessageDirection.outbound
                local_ai.send_status = MessageSendStatus.sent
                local_ai.meta = {
                    **(local_ai.meta or {}),
                    "userid": item.get("userid"),
                    "user_email": item.get("user_email"),
                    "user_name": item.get("user_name"),
                    "datecreated": item.get("datecreated"),
                    "la_echo_of_ai": True,
                }
                la_at = parse_la_timestamp(item.get("datecreated"))
                if la_at is not None:
                    local_ai.created_at = la_at
                known_ai_bodies.add(normalize_body(local_ai.body))
                continue

        la_at = parse_la_timestamp(item.get("datecreated"))
        msg = Message(
            conversation_id=conv.id,
            channel_connection_id=connection.id,
            external_id=item["external_id"],
            direction=direction,
            sender_type=sender_type,
            body=item["body"],
            send_status=MessageSendStatus.sent,
            created_at=la_at or datetime.now(timezone.utc),
            meta={
                "userid": item.get("userid"),
                "user_email": item.get("user_email"),
                "user_name": item.get("user_name"),
                "datecreated": item.get("datecreated"),
                **({"la_echo_of_ai": True} if sender_type == MessageSenderType.ai else {}),
            },
        )
        db.add(msg)
        imported += 1
        if sender_type == MessageSenderType.ai and body_norm:
            known_ai_bodies.add(body_norm)
        if direction == MessageDirection.inbound:
            latest_inbound = msg
            new_inbound = True
            _enrich_snapshot_from_inbound(
                conv,
                body=body_raw,
                userid=str(item.get("userid") or ""),
                contact_id=contact_id,
            )
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

    # New customer turn → AI may answer again unless human already covered it.
    if new_inbound:
        conv.ai_handled = False

    ai_enqueued = False
    db.flush()
    if enqueue_ai:
        # Serialize enqueue against concurrent webhook+poll for this conversation.
        locked = db.scalar(
            select(Conversation).where(Conversation.id == conv.id).with_for_update()
        )
        if locked:
            conv = locked
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
        skip = skip_reason_for_trigger(db, conv, trigger) if trigger else "missing_trigger"
        # AI-first: enqueue when no human/AI reply yet for this inbound.
        if trigger and not pending and not skip:
            job = AiJob(
                conversation_id=conv.id,
                trigger_message_id=trigger.id,
                status="pending",
            )
            db.add(job)
            conv.status = ConversationStatus.ai_pending
            ai_enqueued = True
        elif skip and trigger:
            logger.info(
                "skip ai enqueue conversation=%s trigger=%s reason=%s",
                conv.id,
                trigger.id,
                skip,
            )

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
