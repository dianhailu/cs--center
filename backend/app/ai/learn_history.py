from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.faq import detect_lang
from app.config import Settings
from app.models import Conversation, MessageDirection, MessageSenderType

logger = logging.getLogger(__name__)

NOISE_RE = re.compile(
    r"^(phone\s*:|started from|visitor ip|preferred language|user is now on|chat was ended|"
    r"answered the chat|resolved ticket|added tag|\[midplatform\]|\[test |\[smart test\])",
    re.I,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _usable(text: str) -> bool:
    t = _clean(text)
    if len(t) < 2:
        return False
    if NOISE_RE.search(t):
        return False
    return True


def build_history_pairs(
    db: Session,
    settings: Settings,
    *,
    limit_conversations: int | None = None,
    out_path: Path | None = None,
) -> dict:
    """Rebuild history_pairs.json from all customer→human-agent pairs in DB.

    Running this nightly naturally includes today's new chats on top of history.
    """
    out = out_path or settings.history_path
    limit = limit_conversations or settings.history_learn_limit_conversations
    pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    convs = list(
        db.scalars(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
    )
    logger.info("history learn scanning conversations=%s", len(convs))
    for conv in convs:
        msgs = sorted(conv.messages, key=lambda m: (m.created_at, str(m.id)))
        pending_customer: str | None = None
        for msg in msgs:
            body = _clean(msg.body or "")
            if not _usable(body):
                continue
            if msg.sender_type == MessageSenderType.customer or (
                msg.direction == MessageDirection.inbound and msg.sender_type != MessageSenderType.ai
            ):
                pending_customer = body
                continue
            if msg.sender_type == MessageSenderType.agent and pending_customer:
                key = (pending_customer.lower(), body.lower())
                if key in seen:
                    pending_customer = None
                    continue
                seen.add(key)
                pairs.append(
                    {
                        "id": len(pairs) + 1,
                        "question": pending_customer,
                        "answer": body,
                        "lang": detect_lang(pending_customer, settings.default_reply_lang),
                        "conversation_id": str(conv.id),
                        "external_id": conv.external_id,
                    }
                )
                pending_customer = None

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    stamp = {
        "built_at": datetime.now(tz=ZoneInfo(settings.history_learn_timezone)).isoformat(),
        "pairs": len(pairs),
        "conversations_scanned": len(convs),
    }
    stamp_path = out.with_suffix(".meta.json")
    stamp_path.write_text(json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("history learn wrote pairs=%s -> %s", len(pairs), out)
    return stamp


def last_learn_date(settings: Settings) -> date | None:
    meta = settings.history_path.with_suffix(".meta.json")
    if not meta.exists():
        return None
    try:
        raw = json.loads(meta.read_text(encoding="utf-8"))
        built = raw.get("built_at")
        if not built:
            return None
        return datetime.fromisoformat(built).date()
    except Exception:  # noqa: BLE001
        return None


def should_run_nightly_learn(settings: Settings, *, now: datetime | None = None) -> bool:
    """True once per calendar day during HISTORY_LEARN_HOUR (first 10 minutes)."""
    if not settings.history_learn_enabled:
        return False
    hour = int(settings.history_learn_hour)
    if hour < 0 or hour > 23:
        logger.warning("invalid HISTORY_LEARN_HOUR=%s (expected 0-23)", hour)
        return False
    tz = ZoneInfo(settings.history_learn_timezone)
    current = now.astimezone(tz) if now else datetime.now(tz=tz)
    if current.hour != hour:
        return False
    # Only run in the first 10 minutes of the hour to avoid repeat loops
    if current.minute > 10:
        return False
    last = last_learn_date(settings)
    return last != current.date()


def needs_initial_learn(settings: Settings) -> bool:
    path = settings.history_path
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return not isinstance(data, list) or len(data) == 0
    except Exception:  # noqa: BLE001
        return True
