#!/usr/bin/env python3
"""List unknown questions captured when AI cannot confidently match KB/history.

Usage:
  python scripts/list_unknown_questions.py
  python scripts/list_unknown_questions.py --status open
  python scripts/list_unknown_questions.py --days 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ai.unknown import load_unknowns  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="List unknown CS questions")
    parser.add_argument("--status", choices=["open", "answered", "all"], default="open")
    parser.add_argument("--days", type=int, default=0, help="Only last N days (0=all)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = get_settings().unknown_questions_path
    rows = load_unknowns(path)
    if args.status != "all":
        rows = [r for r in rows if r.get("status") == args.status]
    if args.days > 0:
        cutoff = (date.today() - timedelta(days=args.days)).isoformat()
        rows = [r for r in rows if (r.get("date") or "") >= cutoff]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print(f"(empty) path={path}")
        return 0

    for r in rows:
        print(
            f"{r.get('id')}\t{r.get('date')}\t{r.get('status')}\t"
            f"ext={r.get('external_code') or '-'}\t"
            f"q={(r.get('question') or '')[:100]}"
        )
        if r.get("suggested_draft"):
            print(f"  draft: {str(r['suggested_draft'])[:160]}")
        if r.get("answer"):
            print(f"  answer: {str(r['answer'])[:160]}")
    print(f"\ncount={len(rows)} file={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
