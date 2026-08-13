"""Archive phone-number-like rows from unknown_questions.jsonl (and optional FAQ purge).

  PYTHONPATH=/app python scripts/cleanup_phone_unknowns.py
  PYTHONPATH=/app python scripts/cleanup_phone_unknowns.py --dry-run
  PYTHONPATH=/app python scripts/cleanup_phone_unknowns.py --also-faq
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.kb_store import atomic_write_text, file_lock, load_faq_raw  # noqa: E402
from app.ai.phone import is_phone_like  # noqa: E402
from app.ai.unknown import load_unknowns, rewrite_unknowns  # noqa: E402
from app.config import get_settings  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

JAKARTA = ZoneInfo("Asia/Jakarta")


def _faq_question_text(item: dict) -> str:
    q = item.get("question") or {}
    if isinstance(q, dict):
        return " ".join(str(q.get(k) or "") for k in ("id", "en", "zh")).strip()
    return str(q or "").strip()


def _faq_is_phone_pollution(item: dict) -> bool:
    if str(item.get("code") or "") == "pingo-reception--01":
        return False
    q = item.get("question") or {}
    if isinstance(q, dict):
        texts = [str(q.get(k) or "").strip() for k in ("id", "en", "zh")]
        nonempty = [t for t in texts if t]
        return bool(nonempty) and all(is_phone_like(t) for t in nonempty)
    return is_phone_like(str(q or ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive phone-like unknown questions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--also-faq",
        action="store_true",
        help="Remove FAQ entries whose questions are themselves phone-like",
    )
    args = parser.parse_args()
    settings = get_settings()
    unknown_path = settings.unknown_questions_path
    rows = load_unknowns(unknown_path)
    keep: list[dict] = []
    archived: list[dict] = []
    for row in rows:
        q = (row.get("question") or "").strip()
        if is_phone_like(q):
            archived.append(row)
        else:
            keep.append(row)

    print(f"unknown_total={len(rows)} phone_like={len(archived)} keep={len(keep)}")

    archive_path = unknown_path.with_name("unknown_questions_phone_archive.jsonl")
    if not args.dry_run and archived:
        stamp = datetime.now(JAKARTA).isoformat(timespec="seconds")
        with file_lock(archive_path):
            with archive_path.open("a", encoding="utf-8") as f:
                for row in archived:
                    out = dict(row)
                    out["archived_at"] = stamp
                    out["archive_reason"] = "phone_like"
                    f.write(json.dumps(out, ensure_ascii=False) + "\n")
        rewrite_unknowns(unknown_path, keep)
        print(f"archived_to={archive_path}")

    faq_removed = 0
    if args.also_faq:
        faq_path = settings.faq_path
        items = load_faq_raw(faq_path)
        kept_faq = []
        removed_faq = []
        for item in items:
            if _faq_is_phone_pollution(item):
                removed_faq.append(item)
            else:
                kept_faq.append(item)
        faq_removed = len(removed_faq)
        print(f"faq_phone_pollution={faq_removed}")
        if not args.dry_run and removed_faq:
            bak = faq_path.with_name(
                f"faq_phone_purge_{datetime.now(JAKARTA).strftime('%Y%m%d_%H%M%S')}.json"
            )
            bak.write_text(
                json.dumps(removed_faq, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with file_lock(faq_path):
                atomic_write_text(
                    faq_path,
                    json.dumps(kept_faq, ensure_ascii=False, indent=2) + "\n",
                )
            print(f"faq_purge_backup={bak}")

    if args.dry_run:
        for row in archived[:20]:
            print(f"  would_archive id={row.get('id')} q={row.get('question')!r}")
        if len(archived) > 20:
            print(f"  ... and {len(archived) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
