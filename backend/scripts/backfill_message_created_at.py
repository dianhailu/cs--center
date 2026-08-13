#!/usr/bin/env python3
"""Backfill messages.created_at from LiveAgent meta.datecreated.

History refresh/import stamped created_at to import time (e.g. 2026-08-08)
while preserving the real consult time in meta.datecreated. This script realigns
created_at so inbox ordering and any created_at-based queries match LA time.

Usage (VPS / docker):
  python -m scripts.backfill_message_created_at
  python -m scripts.backfill_message_created_at --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Message  # noqa: E402
from app.services.message_time import parse_la_timestamp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--min-delta-sec",
        type=int,
        default=2,
        help="Only update when |created_at - datecreated| exceeds this many seconds",
    )
    args = parser.parse_args()

    db = SessionLocal()
    updated = 0
    scanned = 0
    skipped_no_la = 0
    try:
        rows = db.scalars(select(Message)).yield_per(500)
        for msg in rows:
            scanned += 1
            meta = msg.meta if isinstance(msg.meta, dict) else {}
            la_at = parse_la_timestamp(meta.get("datecreated") or meta.get("occurred_at"))
            if la_at is None:
                skipped_no_la += 1
                continue
            created = msg.created_at
            if created is None:
                msg.created_at = la_at
                updated += 1
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=la_at.tzinfo)
            if abs(created - la_at) < timedelta(seconds=args.min_delta_sec):
                continue
            msg.created_at = la_at
            # Keep an explicit occurred_at copy for clarity.
            msg.meta = {**meta, "datecreated": meta.get("datecreated"), "occurred_at": la_at.isoformat()}
            updated += 1
            if updated % 200 == 0:
                if not args.dry_run:
                    db.commit()
                print(f"… updated {updated}/{scanned}", flush=True)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(
        f"done scanned={scanned} updated={updated} skipped_no_la={skipped_no_la} dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
