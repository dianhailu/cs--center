from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent import SupportAgent
from app.ai.faq import FaqIndex
from app.ai.history import HistoryIndex
from app.ai.phone import is_phone_like
from app.ai.unknown import append_unknown, should_record_unknown
from app.channels.liveagent import client_from_connection
from app.config import get_settings
from app.models import (
    AiJob,
    ChannelConnection,
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageSenderType,
    Workspace,
)
from app.rbac import resolve_customer_reply_lang
from app.product_brand import faq_items_for_brand, load_product_brand
from app.services.conversations import send_outbound_message

logger = logging.getLogger(__name__)

_faq: FaqIndex | None = None
_history: HistoryIndex | None = None
_agent: SupportAgent | None = None


def get_support_agent() -> SupportAgent:
    global _faq, _history, _agent
    settings = get_settings()
    if _faq is None:
        _faq = FaqIndex(settings.faq_path)
    else:
        _faq.maybe_reload()
    if _history is None:
        _history = HistoryIndex(settings.history_path)
    else:
        _history.maybe_reload()
    if _agent is None:
        _agent = SupportAgent(settings, _faq, _history)
    return _agent


def normalize_body(body: str | None) -> str:
    return " ".join((body or "").strip().split())


def human_replied_after_trigger(db: Session, conv_id: UUID, trigger: Message | None) -> bool:
    """True if a real human agent outbound exists after this customer inbound."""
    if not trigger:
        return False
    q = (
        select(Message.id)
        .where(
            Message.conversation_id == conv_id,
            Message.direction == MessageDirection.outbound,
            Message.sender_type == MessageSenderType.agent,
            Message.created_at >= trigger.created_at,
        )
        .limit(1)
    )
    return db.scalar(q) is not None


def ai_replied_after_trigger(db: Session, conv_id: UUID, trigger: Message | None) -> bool:
    """True if Smart already sent an outbound for this customer inbound."""
    if not trigger:
        return False
    q = (
        select(Message.id)
        .where(
            Message.conversation_id == conv_id,
            Message.direction == MessageDirection.outbound,
            Message.sender_type == MessageSenderType.ai,
            Message.created_at >= trigger.created_at,
        )
        .limit(1)
    )
    return db.scalar(q) is not None


def trigger_already_has_job(db: Session, trigger_id: UUID | None, *, exclude_job_id: UUID | None = None) -> AiJob | None:
    """Return a non-failed AiJob already tied to this inbound message."""
    if not trigger_id:
        return None
    q = select(AiJob).where(
        AiJob.trigger_message_id == trigger_id,
        AiJob.status.in_(["pending", "processing", "done"]),
    )
    if exclude_job_id:
        q = q.where(AiJob.id != exclude_job_id)
    for job in db.scalars(q):
        # Skipped twins do not count as a real reply.
        if job.status == "done" and (job.result or {}).get("skipped"):
            continue
        return job
    return None


def skip_reason_for_trigger(db: Session, conv: Conversation, trigger: Message | None, *, job_id: UUID | None = None) -> str | None:
    """AI-first gate: skip only if human or AI already covered this inbound turn."""
    if trigger is None:
        return "missing_trigger"
    if human_replied_after_trigger(db, conv.id, trigger):
        return "human_already_replied"
    if ai_replied_after_trigger(db, conv.id, trigger):
        return "ai_already_replied"
    prior = trigger_already_has_job(db, trigger.id, exclude_job_id=job_id)
    if prior and prior.status == "done":
        return "trigger_already_processed"
    return None


def early_panel_accept(db: Session, conv: Conversation) -> dict:
    """pickUpChat as soon as an AI job starts — clear visitor waiting before LLM latency.

    Outbox will call accept_chat again before createAnswer (idempotent when already answered).
    """
    conn = db.get(ChannelConnection, conv.channel_connection_id)
    if not conn or not conv.external_id:
        return {}
    la = client_from_connection(conn)
    try:
        if not la.config.panel_accept or la.config.dry_run:
            return {"skipped": "panel_accept_disabled"}
        accepted = la.accept_chat(conv.external_id)
        if str(accepted.get("answered") or "").upper() == "Y":
            conv.status = ConversationStatus.assigned
            conv.la_status = conv.la_status or "T"
            db.commit()
            logger.info(
                "early_panel_accept ok conversation=%s external=%s",
                conv.id,
                conv.external_id,
            )
        return {
            "answered": accepted.get("answered"),
            "join": accepted.get("join"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "early_panel_accept failed conversation=%s external=%s: %s",
            conv.id,
            conv.external_id,
            exc,
        )
        return {"error": str(exc)[:500]}
    finally:
        la.close()


def process_ai_jobs(db: Session, limit: int = 10) -> int:
    settings = get_settings()
    if not settings.ai_enabled:
        return 0
    jobs = list(
        db.scalars(
            select(AiJob).where(AiJob.status == "pending").order_by(AiJob.created_at.asc()).limit(limit)
        )
    )
    agent = get_support_agent()
    count = 0
    for job in jobs:
        db.refresh(job)
        if job.status != "pending":
            continue
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        # At most one AI outbound per conversation turn: drop other pending twins.
        for sibling in db.scalars(
            select(AiJob).where(
                AiJob.conversation_id == job.conversation_id,
                AiJob.status == "pending",
                AiJob.id != job.id,
            )
        ):
            sibling.status = "done"
            sibling.result = {"skipped": "duplicate_job", "superseded_by": str(job.id)}
            sibling.updated_at = datetime.now(timezone.utc)
        db.commit()
        try:
            conv = db.get(Conversation, job.conversation_id)
            if not conv:
                raise RuntimeError("conversation missing")
            trigger = db.get(Message, job.trigger_message_id) if job.trigger_message_id else None
            reason = skip_reason_for_trigger(db, conv, trigger, job_id=job.id)
            if reason:
                # Prior AI may have fallen back to type-5 (visitor still waiting). Retry
                # pickUp while the chat might still be ringing.
                accept_retry = {}
                if reason == "ai_already_replied":
                    accept_retry = early_panel_accept(db, conv)
                job.status = "done"
                job.result = {"skipped": reason, "early_panel_accept": accept_retry}
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                continue

            # Accept ringing chat BEFORE LLM so visitor leaves "waiting" in ~1–2s,
            # not after the full model round-trip (often 30–60s).
            early_accept = early_panel_accept(db, conv)
            db.refresh(conv)

            text = trigger.body if trigger else ""
            forced_lang = None
            brand = None
            ws = db.get(Workspace, conv.workspace_id)
            if ws:
                forced_lang = resolve_customer_reply_lang(
                    db, ws.product_code, fallback=get_settings().default_reply_lang or "id"
                )
                brand = load_product_brand(db, ws.product_code)
            decision = agent.decide(text, forced_reply_lang=forced_lang, brand=brand)
            result = {
                "action": decision.action,
                "reason": decision.reason,
                "lang": decision.lang,
                "reply": decision.reply,
                "trigger_message_id": str(trigger.id) if trigger else None,
                "early_panel_accept": early_accept,
                "faq": [
                    {"id": h.faq_id, "score": round(h.score, 4), "q": h.question}
                    for h in decision.faq_hits
                ],
                "history": [
                    {"id": h.pair_id, "score": round(h.score, 4), "q": h.question[:120]}
                    for h in decision.history_hits
                ],
            }
            # Knowledge gap: log for teaching (never forces customer delivery by itself).
            # Phone-like inbounds are reception only — skip unknown / FAQ capture.
            if (
                text
                and not is_phone_like(text)
                and should_record_unknown(decision.action, decision.reason)
            ):
                draft = None
                if decision.action == "reply" and "weak retrieval" in (decision.reason or "").lower():
                    draft = decision.reply
                try:
                    uq = append_unknown(
                        settings.unknown_questions_path,
                        question=text,
                        conversation_id=str(conv.id),
                        external_code=conv.external_code or conv.external_id,
                        suggested_draft=draft,
                        reason=decision.reason,
                    )
                    if uq:
                        result["unknown_id"] = uq.get("id")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("unknown question log failed: %s", exc)
            # Re-check after LLM (human may have replied, or sibling finished).
            db.refresh(conv)
            if trigger:
                db.refresh(trigger)
            reason = skip_reason_for_trigger(db, conv, trigger, job_id=job.id)
            if reason:
                job.status = "done"
                job.result = {**result, "skipped": reason}
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                continue

            # One action per turn: either content reply OR handoff (never both).
            if decision.action == "reply" and decision.reply:
                send_outbound_message(
                    db,
                    conv,
                    body=decision.reply,
                    sender_type=MessageSenderType.ai,
                )
                conv = db.get(Conversation, job.conversation_id)
                assert conv
                conv.ai_handled = True
                conv.needs_human = False
                # Keep assigned after successful panel accept; else open queue.
                if conv.status == ConversationStatus.ai_pending:
                    conv.status = (
                        ConversationStatus.assigned
                        if str((early_accept or {}).get("answered") or "").upper() == "Y"
                        else ConversationStatus.queued
                    )
                _safe_tag(db, conv, "ai_replied")
            elif decision.action == "handoff":
                if decision.reply:
                    send_outbound_message(
                        db,
                        conv,
                        body=decision.reply,
                        sender_type=MessageSenderType.ai,
                    )
                conv = db.get(Conversation, job.conversation_id)
                assert conv
                conv.ai_handled = True
                conv.needs_human = True
                # Do not downgrade an accepted chat back to queued (midplatform 「未接入」).
                if conv.status != ConversationStatus.assigned:
                    conv.status = ConversationStatus.queued
                _safe_tag(db, conv, "ai_handoff")
            else:
                conv.ai_handled = True
            job.status = "done"
            job.result = result
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai job failed %s: %s", job.id, exc)
            job.status = "failed"
            job.result = {"error": str(exc)}
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
    return count


def _safe_tag(db: Session, conv: Conversation, tag: str) -> None:
    tags = list(conv.tags or [])
    if tag not in tags:
        tags.append(tag)
        conv.tags = tags
    conn = db.get(ChannelConnection, conv.channel_connection_id)
    if not conn:
        return
    la = client_from_connection(conn)
    try:
        la.add_tags(conv.external_id, [tag])
    except Exception as exc:  # noqa: BLE001
        logger.warning("LA tag failed: %s", exc)
    finally:
        la.close()
