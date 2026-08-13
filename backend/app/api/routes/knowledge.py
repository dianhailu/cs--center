"""Knowledge base endpoints for the agent console (multilang FAQ + unknowns)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.ai.kb_categories import (
    create_category,
    list_categories_with_counts,
    migrate_faq_codes,
)
from app.ai.kb_store import (
    create_faq,
    load_faq_raw,
    normalize_faq_item,
    normalize_lang_block,
    update_faq,
)
from app.ai.kb_translate import auto_translate_qa, detect_source_lang, normalize_source_lang
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
    category_slug: str | None = None
    code: str | None = None
    auto_translate: bool = True
    source_lang: str | None = None


class FaqUpdateBody(BaseModel):
    question: LangTriple | None = None
    answer: LangTriple | None = None
    category: LangTriple | None = None
    category_slug: str | None = None
    code: str | None = None
    auto_translate: bool = True
    source_lang: str | None = None


class CategoryCreateBody(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    label: LangTriple | None = None


class UnknownResolveBody(BaseModel):
    answer: LangTriple
    question: LangTriple | None = None
    category: LangTriple | None = None
    category_slug: str | None = None
    auto_translate: bool = True
    source_lang: str | None = None


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


def _maybe_translate(
    *,
    question: dict[str, str],
    answer: dict[str, str],
    auto_translate: bool,
    source_lang: str | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    if not auto_translate:
        return question, answer, []
    settings = get_settings()
    return auto_translate_qa(
        settings,
        question=question,
        answer=answer,
        source_lang=source_lang,
        overwrite=overwrite,
    )


@router.get("/categories")
def list_categories(auth: AuthContext = Depends(get_auth)) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    # Ensure codes exist so counts/slugs are stable for legacy rows
    migrate_faq_codes(settings.faq_path, settings.categories_path)
    items = list_categories_with_counts(settings.categories_path, settings.faq_path)
    return {"count": len(items), "items": items}


@router.post("/categories")
def post_category(
    body: CategoryCreateBody,
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    try:
        item = create_category(
            settings.categories_path,
            slug=body.slug,
            label=body.label.model_dump() if body.label else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"item": item}


@router.get("/faq")
def list_faq(auth: AuthContext = Depends(get_auth)) -> dict[str, Any]:
    _ = auth
    settings = get_settings()
    migrate_faq_codes(settings.faq_path, settings.categories_path)
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
    q = body.question.model_dump()
    a = body.answer.model_dump()
    q, a, warnings = _maybe_translate(
        question=q,
        answer=a,
        auto_translate=body.auto_translate,
        source_lang=normalize_source_lang(body.source_lang),
        overwrite=False,
    )
    try:
        item = create_faq(
            settings.faq_path,
            question=q,
            answer=a,
            category=body.category.model_dump() if body.category else None,
            category_slug=body.category_slug,
            code=body.code,
            source="console",
            categories_path=settings.categories_path,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"item": item, "warnings": warnings}


@router.put("/faq/{faq_id}")
def update_faq_item(
    faq_id: int,
    body: FaqUpdateBody,
    auth: AuthContext = Depends(get_auth),
) -> dict[str, Any]:
    _ = auth
    if (
        body.question is None
        and body.answer is None
        and body.category is None
        and body.category_slug is None
        and body.code is None
    ):
        raise HTTPException(400, "no fields to update")
    settings = get_settings()
    warnings: list[str] = []
    q = body.question.model_dump() if body.question else None
    a = body.answer.model_dump() if body.answer else None
    if body.auto_translate and (q is not None or a is not None):
        # Merge with existing, then re-translate from source into the other langs
        # and overwrite them (edit sync). Prefer client source_lang; else detect
        # which language the user actually changed.
        existing_rows = load_faq_raw(settings.faq_path)
        existing = next(
            (
                normalize_faq_item(x)
                for x in existing_rows
                if int(x.get("id") or 0) == faq_id
            ),
            None,
        )
        if not existing:
            raise HTTPException(404, "faq not found")
        old_q = {k: existing["question"].get(k, "") for k in ("zh", "id", "en")}
        old_a = {k: existing["answer"].get(k, "") for k in ("zh", "id", "en")}
        merged_q = {**old_q, **(q or {})}
        merged_a = {**old_a, **(a or {})}
        src = detect_source_lang(
            old_question=old_q,
            old_answer=old_a,
            new_question=merged_q,
            new_answer=merged_a,
            preferred=body.source_lang,
        )
        tq, ta, warnings = _maybe_translate(
            question=merged_q,
            answer=merged_a,
            auto_translate=True,
            source_lang=src,
            overwrite=True,
        )
        q, a = tq, ta
    try:
        item = update_faq(
            settings.faq_path,
            faq_id,
            question=q,
            answer=a,
            category=body.category.model_dump() if body.category else None,
            category_slug=body.category_slug,
            code=body.code,
            categories_path=settings.categories_path,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not item:
        raise HTTPException(404, "faq not found")
    return {"item": item, "warnings": warnings}


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
    q = body.question.model_dump() if body.question else None
    a = body.answer.model_dump()
    src = normalize_source_lang(body.source_lang)
    if body.auto_translate:
        if q is not None:
            if not src:
                src = detect_source_lang(new_question=q, new_answer=a)
            q, a, warnings = _maybe_translate(
                question=q,
                answer=a,
                auto_translate=True,
                source_lang=src,
                overwrite=True,
            )
        else:
            if not src:
                src = detect_source_lang(
                    new_question={"zh": "", "id": "", "en": ""},
                    new_answer=a,
                )
            _, a, warnings = _maybe_translate(
                question={"zh": "", "id": "", "en": ""},
                answer=a,
                auto_translate=True,
                source_lang=src,
                overwrite=False,
            )
            warnings = list(warnings)
    else:
        warnings = []
    try:
        faq_item, unknown = resolve_unknown(
            settings.unknown_questions_path,
            settings.faq_path,
            uq_id,
            answer=a,
            question=q,
            category=body.category.model_dump() if body.category else None,
        )
        # If resolve seeded question as single-lang and auto_translate, patch FAQ
        if body.auto_translate and faq_item:
            fq = {k: faq_item["question"].get(k, "") for k in ("zh", "id", "en")}
            fa = {k: faq_item["answer"].get(k, "") for k in ("zh", "id", "en")}
            patch_src = src or detect_source_lang(new_question=fq, new_answer=fa)
            tq, ta, w2 = _maybe_translate(
                question=fq,
                answer=fa,
                auto_translate=True,
                source_lang=patch_src,
                overwrite=True,
            )
            warnings.extend(w2)
            if any(tq[k] != faq_item["question"].get(k, "") for k in ("zh", "id", "en")) or any(
                ta[k] != faq_item["answer"].get(k, "") for k in ("zh", "id", "en")
            ):
                updated = update_faq(
                    settings.faq_path,
                    int(faq_item["id"]),
                    question=tq,
                    answer=ta,
                    category_slug=body.category_slug,
                    categories_path=settings.categories_path,
                )
                if updated:
                    faq_item = updated
        elif body.category_slug:
            updated = update_faq(
                settings.faq_path,
                int(faq_item["id"]),
                category_slug=body.category_slug,
                categories_path=settings.categories_path,
            )
            if updated:
                faq_item = updated
    except KeyError as exc:
        raise HTTPException(404, "unknown not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"faq": faq_item, "unknown": _unknown_item(unknown), "warnings": warnings}
