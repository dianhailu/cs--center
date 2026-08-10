#!/usr/bin/env python3
"""Mine customer→human-agent reply pairs from DB into knowledge/history_pairs.json.

Usage:
  python scripts/build_history_knowledge.py
  python scripts/build_history_knowledge.py --limit-conversations 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.faq import detect_lang
from app.config import get_settings
from app.db import SessionLocal
from app.models import Conversation, Message, MessageDirection, MessageSenderType

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_history_knowledge")

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-conversations", type=int, default=5000)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: settings.history_path)",
    )
    args = parser.parse_args()
    settings = get_settings()
    out = args.out or settings.history_path

    db = SessionLocal()
    pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    try:
        convs = list(
            db.scalars(
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .order_by(Conversation.last_message_at.desc())
                .limit(args.limit_conversations)
            )
        )
        logger.info("scanning conversations=%s", len(convs))
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
        logger.info("wrote %s pairs -> %s", len(pairs), out)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
