"""Append / teach unknown customer questions not confidently matched by FAQ/history."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_LOCK = threading.Lock()
JAKARTA = ZoneInfo("Asia/Jakarta")


def _today() -> str:
    return datetime.now(JAKARTA).date().isoformat()


def _now_iso() -> str:
    return datetime.now(JAKARTA).isoformat(timespec="seconds")


def append_unknown(
    path: Path,
    *,
    question: str,
    conversation_id: str | None = None,
    external_code: str | None = None,
    suggested_draft: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Append one open unknown-question record (JSONL). Dedupes same question same day."""
    q = (question or "").strip()
    if not q:
        return {}
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": f"uq_{datetime.now(JAKARTA).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        "date": _today(),
        "recorded_at": _now_iso(),
        "question": q,
        "conversation_id": conversation_id,
        "external_code": external_code,
        "suggested_draft": (suggested_draft or "").strip() or None,
        "status": "open",
        "answer": None,
        "reason": reason,
    }
    with _LOCK:
        # Skip duplicate open question on same calendar day (Jakarta)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    prev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    prev.get("status") == "open"
                    and prev.get("date") == record["date"]
                    and (prev.get("question") or "").strip() == q
                ):
                    return prev
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_unknowns(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def rewrite_unknowns(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def mark_answered(path: Path, uq_id: str, answer: str) -> dict[str, Any] | None:
    rows = load_unknowns(path)
    found: dict[str, Any] | None = None
    for row in rows:
        if row.get("id") == uq_id:
            row["status"] = "answered"
            row["answer"] = answer
            row["answered_at"] = _now_iso()
            found = row
            break
    if found:
        rewrite_unknowns(path, rows)
    return found


def append_faq_entry(
    faq_path: Path,
    *,
    question: str,
    answer: str,
    lang: str = "id",
    category_zh: str = "已教答",
) -> dict[str, Any]:
    """Append a taught Q&A into faq.json (trilingual shells; primary lang filled)."""
    items: list[dict] = []
    if faq_path.exists():
        items = json.loads(faq_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            items = []
    next_id = max((int(i.get("id") or 0) for i in items), default=0) + 1
    lang = (lang or "id").lower()
    q = {"id": "", "en": "", "zh": ""}
    a = {"id": "", "en": "", "zh": ""}
    if lang.startswith("zh"):
        q["zh"] = question
        a["zh"] = answer
    elif lang.startswith("en"):
        q["en"] = question
        a["en"] = answer
    else:
        q["id"] = question
        a["id"] = answer
        # also mirror into zh empty; id is primary for ID customers
    entry = {
        "id": next_id,
        "source": "taught",
        "category": {
            "id": "Diajarkan",
            "en": "Taught",
            "zh": category_zh,
        },
        "question": q,
        "answer": a,
    }
    items.append(entry)
    faq_path.parent.mkdir(parents=True, exist_ok=True)
    faq_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


def should_record_unknown(action: str, reason: str) -> bool:
    """True when KB/history confidence is low or handoff (not explicit customer handoff)."""
    reason = reason or ""
    if action == "handoff" and "explicit handoff" not in reason.lower():
        return True
    if "weak retrieval" in reason.lower():
        return True
    if reason.lower().startswith("uncertain"):
        return True
    return False
