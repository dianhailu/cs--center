#!/usr/bin/env python3
"""Mine customer→human-agent reply pairs from DB into knowledge/history_pairs.json.

Usage:
  python scripts/build_history_knowledge.py
  python scripts/build_history_knowledge.py --limit-conversations 8000
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.ai.learn_history import build_history_pairs
from app.ai.promote_faq import promote_history_to_faq
from app.config import get_settings
from app.db import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_history_knowledge")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-conversations", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--skip-promote",
        action="store_true",
        help="Only rebuild history_pairs.json; skip FAQ auto-promote",
    )
    args = parser.parse_args()
    settings = get_settings()
    db = SessionLocal()
    try:
        stamp = build_history_pairs(
            db,
            settings,
            limit_conversations=args.limit_conversations,
            out_path=args.out,
        )
        logger.info("history learn done %s", stamp)
        if not args.skip_promote:
            promo = promote_history_to_faq(settings)
            logger.info("faq auto-promote done %s", promo)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
