"""Knowledge base endpoints for the agent console (multilang FAQ + unknowns)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.ai.kb_store import (
    create_faq,
    load_faq_raw,
    normalize_faq_item,
    normalize_lang_block,
    update_faq,
)
from app.ai.unknown import load_unknowns, resolve_unknown, update_unknown
from app.api.deps import AuthContext, get_auth
from app.config import get_settings

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class LangTriple(BaseModel):
    zh: str = ""
    id: str = ""
    en: str = ""


class FaqWriteBody(BaseModel):
    question: LangTriple
    answer: LangTriple
    category: LangTriple | None = None


class FaqUpdateBody(BaseModel):
    question: LangTriple | None = None
    answer: LangTriple | None = None
    category: LangTriple | None = None


class UnknownResolveBody(BaseModel):
    answer: LangTriple
    question: LangTriple | None = None
    category: LangTriple | None = None


class UnknownUpdateBody(BaseModel):
    question: str | None = None
    draft_answer: LangTriple | None = None
    suggested_draft: str | None = None


def _unknown_item(r: dict[str, Any]) -> dict[str, Any]:
    draft = r.get("draft_answer")
    answer = r.get("answer")
    return {
        "id": r.get("id"),
        "date": r.get("date"),
        "recorded_at": r.get("recorded_at"),
        "question": r.get("question"),
        "status": r.get("status"),
        "external_code": r.get("external_code"),
        "conversation_id": r.get("conversation_id"),
        "reason": r.get("reason"),
        "suggested_draft": r.get("suggested_draft"),
        "draft_answer": normalize_lang_block(draft) if draft is not None else {
            "zh": "",
            "id": "",
            "en": "",
        },
        "answer": normalize_lang_block(answer)
        if isinstance(answer, dict)
        else answer,
        "faq_id": r.get("faq_id"),
        "answered_at": r.get("answered_at"),
        "updated_at": r.get("updated_at"),
    }


@router.get("/faq")
def list_faq(auth: AuthContext = Depends(get_auth)) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    items = load_faq_raw(settings.faq_path)
    # Normalize legacy / flat shapes in memory; disk rewrite happens on create/update.
    normalized = [normalize_faq_item(x) for x in items]
    return {"count": len(normalized), "items": normalized}


@router.post("/faq")
def create_faq_item(
    body: FaqWriteBody,
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    try:
        item = create_faq(
            settings.faq_path,
            question=body.question.model_dump(),
            answer=body.answer.model_dump(),
            category=body.category.model_dump() if body.category else None,
            source="console",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"item": item}


@router.put("/faq/{faq_id}")
def update_faq_item(
    faq_id: int,
    body: FaqUpdateBody,
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    if body.question is None and body.answer is None and body.category is None:
        raise HTTPException(400, "no fields to update")
    settings = get_settings()
    try:
        item = update_faq(
            settings.faq_path,
            faq_id,
            question=body.question.model_dump() if body.question else None,
            answer=body.answer.model_dump() if body.answer else None,
            category=body.category.model_dump() if body.category else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not item:
        raise HTTPException(404, "faq not found")
    return {"item": item}


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
    rows = list(reversed(rows))
    sliced = rows[:limit]
    items = [_unknown_item(r) for r in sliced]
    return {"count": len(items), "total_matching": len(rows), "items": items}


@router.put("/unknowns/{uq_id}")
def put_unknown(
    uq_id: str,
    body: UnknownUpdateBody,
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    if body.question is None and body.draft_answer is None and body.suggested_draft is None:
        raise HTTPException(400, "no fields to update")
    settings = get_settings()
    updated = update_unknown(
        settings.unknown_questions_path,
        uq_id,
        question=body.question,
        draft_answer=body.draft_answer.model_dump() if body.draft_answer else None,
        suggested_draft=body.suggested_draft,
    )
    if not updated:
        raise HTTPException(404, "unknown not found")
    return {"item": _unknown_item(updated)}


@router.post("/unknowns/{uq_id}/resolve")
def resolve_unknown_item(
    uq_id: str,
    body: UnknownResolveBody,
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    try:
        faq_item, unknown = resolve_unknown(
            settings.unknown_questions_path,
            settings.faq_path,
            uq_id,
            answer=body.answer.model_dump(),
            question=body.question.model_dump() if body.question else None,
            category=body.category.model_dump() if body.category else None,
        )
    except KeyError as exc:
        raise HTTPException(404, "unknown not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"faq": faq_item, "unknown": _unknown_item(unknown)}
