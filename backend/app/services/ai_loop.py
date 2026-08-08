from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent import SupportAgent
from app.ai.faq import FaqIndex
from app.channels.liveagent import client_from_connection
from app.config import get_settings
from app.models import (
    AiJob,
    ChannelConnection,
    Conversation,
    ConversationStatus,
    Message,
    MessageSenderType,
)
from app.services.conversations import send_outbound_message

logger = logging.getLogger(__name__)

_faq: FaqIndex | None = None
_agent: SupportAgent | None = None


def get_support_agent() -> SupportAgent:
    global _faq, _agent
    settings = get_settings()
    if _faq is None:
        _faq = FaqIndex(settings.faq_path)
    if _agent is None:
        _agent = SupportAgent(settings, _faq)
    return _agent


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
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        try:
            conv = db.get(Conversation, job.conversation_id)
            if not conv:
                raise RuntimeError("conversation missing")
            trigger = db.get(Message, job.trigger_message_id) if job.trigger_message_id else None
            text = trigger.body if trigger else ""
            decision = agent.decide(text)
            result = {
                "action": decision.action,
                "reason": decision.reason,
                "lang": decision.lang,
                "reply": decision.reply,
                "faq": [
                    {"id": h.faq_id, "score": round(h.score, 4), "q": h.question}
                    for h in decision.faq_hits
                ],
            }
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
                # keep assigned/queued as answered-like
                if conv.status == ConversationStatus.ai_pending:
                    conv.status = ConversationStatus.queued
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
