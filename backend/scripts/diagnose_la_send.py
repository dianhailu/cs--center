#!/usr/bin/env python3
"""Diagnose LiveAgent outbound send path and optionally send a test note.

Usage inside api container:
  python scripts/diagnose_la_send.py
  python scripts/diagnose_la_send.py --send-note --ticket-id <LA_TICKET_ID>
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from app.channels.liveagent import client_from_connection
from app.config import get_settings
from app.db import SessionLocal
from app.models import ChannelConnection, Message, MessageSenderType, OutboxEvent, OutboxStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("diagnose_la_send")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-note", action="store_true", help="Post a private note to a ticket via V1 API")
    parser.add_argument("--ticket-id", default="", help="LiveAgent ticket/conversation id")
    args = parser.parse_args()

    settings = get_settings()
    logger.info(
        "env dry_run=%s has_v1=%s has_v3=%s agent_email=%s",
        settings.liveagent_dry_run,
        bool(settings.liveagent_api_v1_key),
        bool(settings.liveagent_api_v3_key),
        bool(settings.liveagent_agent_email),
    )

    db = SessionLocal()
    try:
        conns = list(db.scalars(select(ChannelConnection).where(ChannelConnection.provider == "liveagent")))
        for conn in conns:
            logger.info(
                "connection id=%s dry_run=%s has_v1=%s has_v3=%s agent_email=%s",
                conn.id,
                conn.dry_run,
                bool(conn.api_v1_key),
                bool(conn.api_v3_key),
                bool(conn.agent_email),
            )

        pending = list(db.scalars(select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.pending).limit(20)))
        dead = list(db.scalars(select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.dead).limit(20)))
        logger.info("outbox pending=%s dead=%s", len(pending), len(dead))
        for ev in dead[:5]:
            logger.info("dead outbox id=%s err=%s", ev.id, (ev.last_error or "")[:300])

        ai_msgs = list(
            db.scalars(
                select(Message)
                .where(Message.sender_type == MessageSenderType.ai)
                .order_by(Message.created_at.desc())
                .limit(5)
            )
        )
        for m in ai_msgs:
            logger.info(
                "ai msg id=%s status=%s external=%s dry_meta=%s body=%s",
                m.id,
                m.send_status,
                m.external_id,
                (m.meta or {}).get("dry_run"),
                (m.body or "")[:80],
            )

        if args.send_note:
            if not args.ticket_id:
                logger.error("--ticket-id required with --send-note")
                return 1
            if not conns:
                logger.error("no liveagent connection")
                return 1
            conn = conns[0]
            la = client_from_connection(conn)
            try:
                result = la.post_reply(args.ticket_id, "[midplatform] test note — ignore", as_note=True)
                logger.info("send-note result=%s", result)
            finally:
                la.close()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
