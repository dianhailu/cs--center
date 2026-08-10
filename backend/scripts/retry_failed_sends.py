#!/usr/bin/env python3
"""Retry failed / dry-run AI outbound messages to LiveAgent.

Usage:
  python scripts/retry_failed_sends.py
  python scripts/retry_failed_sends.py --limit 20
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import or_, select

from app.channels.liveagent import client_from_connection
from app.db import SessionLocal
from app.models import (
    ChannelConnection,
    Conversation,
    Message,
    MessageSendStatus,
    MessageSenderType,
    OutboxEvent,
    OutboxStatus,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retry_failed_sends")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Revive dead outbox rows
        dead = list(db.scalars(select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.dead).limit(args.limit)))
        for ev in dead:
            ev.status = OutboxStatus.pending
            ev.attempts = 0
            ev.last_error = None
            logger.info("requeued dead outbox %s", ev.id)
        db.commit()

        # Resend AI messages that were dry-run stubs or failed with no real LA id
        msgs = list(
            db.scalars(
                select(Message)
                .where(Message.sender_type == MessageSenderType.ai)
                .order_by(Message.created_at.desc())
                .limit(args.limit)
            )
        )
        sent = 0
        for msg in msgs:
            ext = str(msg.external_id or "")
            needs = msg.send_status == MessageSendStatus.failed or ext.startswith("dry-") or not ext
            if not needs:
                continue
            conv = db.get(Conversation, msg.conversation_id)
            conn = db.get(ChannelConnection, msg.channel_connection_id) if msg.channel_connection_id else None
            if not conv or not conn or not conv.external_id:
                logger.warning("skip msg %s missing conv/conn", msg.id)
                continue
            if conn.dry_run:
                logger.error("connection still dry_run; abort")
                return 1
            la = client_from_connection(conn)
            try:
                if la.config.auto_transfer and not la.config.dry_run:
                    try:
                        la.transfer_to_agent(conv.external_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "transfer_to_agent failed ticket=%s; continuing: %s",
                            conv.external_id,
                            exc,
                        )
                result = la.post_reply(conv.external_id, msg.body, as_note=False)
                logger.info("resent msg %s ticket=%s result=%s", msg.id, conv.external_id, result)
                stub = None
                if isinstance(result, dict):
                    stub = (
                        result.get("id")
                        or result.get("messageid")
                        or result.get("external_stub")
                        or (result.get("response") or {}).get("messageid")
                    )
                if stub:
                    msg.external_id = str(stub)
                msg.send_status = MessageSendStatus.sent
                msg.meta = {**(msg.meta or {}), "dry_run": False, "resent": True}
                sent += 1
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.exception("resent failed msg %s: %s", msg.id, exc)
                msg.send_status = MessageSendStatus.failed
                db.commit()
            finally:
                la.close()
        logger.info("done resent=%s", sent)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
