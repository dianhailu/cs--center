#!/usr/bin/env python3
"""Teach an answer for a captured unknown question id → merge into faq.json.

Usage:
  python scripts/teach_unknown.py uq_20260813_abcd1234 --answer "Jawaban resmi..."
  python scripts/teach_unknown.py uq_... --answer "..." --lang id
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
    parser = argparse.ArgumentParser(description="Teach answer for unknown question id")
    parser.add_argument("id", help="unknown id, e.g. uq_20260813_abcd1234")
    parser.add_argument("--answer", required=True, help="Official answer to teach")
    parser.add_argument("--lang", default="", help="id|zh|en (default: detect from question)")
    args = parser.parse_args()

    settings = get_settings()
    rows = load_unknowns(settings.unknown_questions_path)
    row = next((r for r in rows if r.get("id") == args.id), None)
    if not row:
        print(f"not found: {args.id}", file=sys.stderr)
        return 1
    if row.get("status") == "answered" and row.get("answer"):
        print(f"already answered: {args.id}")
        return 0

    question = (row.get("question") or "").strip()
    answer = args.answer.strip()
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
    updated = mark_answered(settings.unknown_questions_path, args.id, answer)
    print(f"taught faq_id={entry['id']} unknown={updated and updated.get('id')}")
    print(f"faq={settings.faq_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
