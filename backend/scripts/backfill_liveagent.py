#!/usr/bin/env python3
"""One-shot historical sync from LiveAgent into the midplatform DB.

Usage (inside api/worker container):
  python scripts/backfill_liveagent.py
  python scripts/backfill_liveagent.py --max-pages 200 --per-page 50
  python scripts/backfill_liveagent.py --channel B   # optional channel_type filter

Does NOT enqueue AI jobs by default (safe for old tickets).
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ChannelConnection
from app.services.inbound import backfill_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill LiveAgent tickets/messages")
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=100, help="Max ticket list pages (50*100=5000 tickets)")
    parser.add_argument("--channel", type=str, default="", help="Optional LiveAgent channel_type filter, e.g. B")
    parser.add_argument("--enqueue-ai", action="store_true", help="Also enqueue AI for imported tickets (not recommended for history)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        conns = list(db.scalars(select(ChannelConnection).where(ChannelConnection.provider == "liveagent")))
        if not conns:
            logger.error("no liveagent connections found")
            return 1
        for conn in conns:
            if not conn.api_v3_key:
                logger.warning("skip connection %s: empty api_v3_key", conn.id)
                continue
            logger.info(
                "backfill start connection=%s per_page=%s max_pages=%s channel=%r enqueue_ai=%s",
                conn.id,
                args.per_page,
                args.max_pages,
                args.channel or None,
                args.enqueue_ai,
            )
            stats = backfill_connection(
                db,
                conn,
                per_page=args.per_page,
                max_pages=args.max_pages,
                enqueue_ai=args.enqueue_ai,
                channel_type=args.channel or None,
            )
            logger.info("backfill done connection=%s stats=%s", conn.id, stats)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
