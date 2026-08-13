"""Append / teach unknown customer questions not confidently matched by FAQ/history."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.faq import detect_lang
from app.ai.kb_store import (
    atomic_write_text,
    create_faq,
    empty_lang,
    file_lock,
    normalize_lang_block,
)

JAKARTA = ZoneInfo("Asia/Jakarta")


def _today() -> str:
    return datetime.now(JAKARTA).date().isoformat()


def _now_iso() -> str:
    return datetime.now(JAKARTA).isoformat(timespec="seconds")


def _read_unknown_rows(path: Path) -> list[dict[str, Any]]:
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
        "draft_answer": empty_lang(),
        "status": "open",
        "answer": None,
        "reason": reason,
    }
    with file_lock(path):
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
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
    return record


def load_unknowns(path: Path) -> list[dict[str, Any]]:
    return _read_unknown_rows(path)


def rewrite_unknowns(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        atomic_write_text(path, text)


def mark_answered(
    path: Path,
    uq_id: str,
    answer: str | dict[str, str] | None,
    *,
    faq_id: int | None = None,
) -> dict[str, Any] | None:
    with file_lock(path):
        rows = _read_unknown_rows(path)
        found: dict[str, Any] | None = None
        for row in rows:
            if row.get("id") == uq_id:
                row["status"] = "answered"
                if isinstance(answer, dict):
                    row["answer"] = normalize_lang_block(answer)
                else:
                    row["answer"] = answer
                row["answered_at"] = _now_iso()
                if faq_id is not None:
                    row["faq_id"] = faq_id
                found = row
                break
        if found:
            text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
            atomic_write_text(path, text)
        return found


def update_unknown(
    path: Path,
    uq_id: str,
    *,
    question: str | None = None,
    draft_answer: dict[str, str] | Any | None = None,
    suggested_draft: str | None = None,
) -> dict[str, Any] | None:
    with file_lock(path):
        rows = _read_unknown_rows(path)
        found: dict[str, Any] | None = None
        for row in rows:
            if row.get("id") != uq_id:
                continue
            if question is not None:
                row["question"] = question.strip()
            if draft_answer is not None:
                row["draft_answer"] = normalize_lang_block(draft_answer)
            if suggested_draft is not None:
                row["suggested_draft"] = suggested_draft.strip() or None
            row["updated_at"] = _now_iso()
            found = row
            break
        if found:
            text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
            atomic_write_text(path, text)
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
    lang_key = (lang or "id").lower()
    if lang_key.startswith("zh") or lang_key in {"cn", "chinese"}:
        key = "zh"
    elif lang_key.startswith("en"):
        key = "en"
    else:
        key = "id"
    q = empty_lang()
    a = empty_lang()
    q[key] = (question or "").strip()
    a[key] = (answer or "").strip()
    return create_faq(
        faq_path,
        question=q,
        answer=a,
        category={"zh": category_zh, "id": "Diajarkan", "en": "Taught"},
        source="taught",
    )


def resolve_unknown(
    unknown_path: Path,
    faq_path: Path,
    uq_id: str,
    *,
    answer: dict[str, str] | Any,
    question: dict[str, str] | Any | None = None,
    category: dict[str, str] | Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge multilang answer into FAQ and mark unknown answered."""
    rows = load_unknowns(unknown_path)
    row = next((r for r in rows if r.get("id") == uq_id), None)
    if not row:
        raise KeyError(uq_id)
    if (row.get("status") or "").lower() == "answered" and row.get("faq_id"):
        raise ValueError("unknown already resolved")

    a = normalize_lang_block(answer)
    if not any(a.values()):
        raise ValueError("answer required in at least one language")

    if question is None:
        captured = (row.get("question") or "").strip()
        draft_q = row.get("draft_question")
        if isinstance(draft_q, dict) and any(str(v or "").strip() for v in draft_q.values()):
            q = normalize_lang_block(draft_q)
        else:
            q = empty_lang()
            q[detect_lang(captured, "id")] = captured
    else:
        q = normalize_lang_block(question)
        if not any(q.values()):
            captured = (row.get("question") or "").strip()
            q[detect_lang(captured, "id")] = captured

    entry = create_faq(
        faq_path,
        question=q,
        answer=a,
        category=category,
        source="taught_unknown",
    )
    updated = mark_answered(
        unknown_path,
        uq_id,
        a,
        faq_id=int(entry.get("id") or 0),
    )
    if not updated:
        raise KeyError(uq_id)
    return entry, updated


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
