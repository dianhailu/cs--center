#!/usr/bin/env python3
"""Teach a Q&A directly into faq.json (no unknown id required).

Usage:
  python scripts/teach_kb.py --question "Bagaimana cara bayar?" --answer "Gunakan VA di App."
  python scripts/teach_kb.py --question "..." --answer "..." --lang id
  python scripts/teach_kb.py --unknown-id uq_... --answer "..."   # same as teach_unknown.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ai.faq import detect_lang  # noqa: E402
from app.ai.unknown import append_faq_entry, load_unknowns, mark_answered  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Teach KB Q&A")
    parser.add_argument("--question", default="", help="Customer question")
    parser.add_argument("--answer", required=True, help="Official answer")
    parser.add_argument("--lang", default="", help="id|zh|en")
    parser.add_argument("--unknown-id", default="", help="Optional: mark unknown row answered")
    args = parser.parse_args()

    settings = get_settings()
    answer = args.answer.strip()
    question = args.question.strip()

    if args.unknown_id:
        rows = load_unknowns(settings.unknown_questions_path)
        row = next((r for r in rows if r.get("id") == args.unknown_id), None)
        if not row:
            print(f"unknown not found: {args.unknown_id}", file=sys.stderr)
            return 1
        question = question or (row.get("question") or "").strip()

    if not question:
        print("need --question or --unknown-id", file=sys.stderr)
        return 1
    if not answer:
        print("empty answer", file=sys.stderr)
        return 1

    lang = args.lang or detect_lang(question, "id")
    entry = append_faq_entry(
        settings.faq_path,
        question=question,
        answer=answer,
        lang=lang,
    )
    if args.unknown_id:
        mark_answered(settings.unknown_questions_path, args.unknown_id, answer)

    print(f"ok faq_id={entry['id']} lang={lang}")
    print(f"faq={settings.faq_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
