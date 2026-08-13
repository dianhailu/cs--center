"""Read-only knowledge base endpoints for the agent console."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.ai.unknown import load_unknowns
from app.api.deps import AuthContext, get_auth
from app.config import get_settings

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _lang_text(block: Any, prefer: str = "zh") -> str:
    if not isinstance(block, dict):
        return str(block or "").strip()
    for key in (prefer, "id", "en", "zh"):
        val = (block.get(key) or "").strip()
        if val:
            return val
    return ""


def _normalize_faq_item(item: dict[str, Any]) -> dict[str, Any]:
    cat = item.get("category") if isinstance(item.get("category"), dict) else {}
    q = item.get("question") if isinstance(item.get("question"), dict) else {}
    a = item.get("answer") if isinstance(item.get("answer"), dict) else {}
    return {
        "id": item.get("id"),
        "source": item.get("source"),
        "sheet": item.get("sheet"),
        "category": {
            "id": (cat or {}).get("id") or "",
            "en": (cat or {}).get("en") or "",
            "zh": (cat or {}).get("zh") or "",
            "label": _lang_text(cat, "zh"),
        },
        "question": {
            "id": (q or {}).get("id") or "",
            "en": (q or {}).get("en") or "",
            "zh": (q or {}).get("zh") or "",
            "label": _lang_text(q, "zh"),
        },
        "answer": {
            "id": (a or {}).get("id") or "",
            "en": (a or {}).get("en") or "",
            "zh": (a or {}).get("zh") or "",
            "label": _lang_text(a, "zh"),
        },
    }


@router.get("/faq")
def list_faq(auth: AuthContext = Depends(get_auth)) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    path = settings.faq_path
    if not path.exists():
        return {"count": 0, "items": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"count": 0, "items": []}
    items = raw if isinstance(raw, list) else []
    normalized = [_normalize_faq_item(x) for x in items if isinstance(x, dict)]
    return {"count": len(normalized), "items": normalized}


@router.get("/unknowns")
def list_unknowns(
    status: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    rows = load_unknowns(settings.unknown_questions_path)
    status_norm = (status or "").strip().lower()
    if status_norm and status_norm != "all":
        rows = [r for r in rows if (r.get("status") or "").lower() == status_norm]
    # Newest first
    rows = list(reversed(rows))
    sliced = rows[:limit]
    items = [
        {
            "id": r.get("id"),
            "date": r.get("date"),
            "recorded_at": r.get("recorded_at"),
            "question": r.get("question"),
            "status": r.get("status"),
            "external_code": r.get("external_code"),
            "conversation_id": r.get("conversation_id"),
            "reason": r.get("reason"),
        }
        for r in sliced
    ]
    return {"count": len(items), "total_matching": len(rows), "items": items}
