"""Auto-translate FAQ Q&A across zh / id / en via OpenAI when key is set."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.kb_store import LANGS, empty_lang, normalize_lang_block
from app.config import Settings

logger = logging.getLogger(__name__)

_LANG_NAME = {"zh": "Chinese", "id": "Indonesian", "en": "English"}


def missing_langs(block: dict[str, str]) -> list[str]:
    return [k for k in LANGS if not (block.get(k) or "").strip()]


def filled_langs(block: dict[str, str]) -> list[str]:
    return [k for k in LANGS if (block.get(k) or "").strip()]


def needs_translate(*blocks: dict[str, str]) -> bool:
    return any(missing_langs(b) for b in blocks)


def auto_translate_qa(
    settings: Settings,
    *,
    question: dict[str, str] | Any,
    answer: dict[str, str] | Any,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Fill missing language slots. Returns (question, answer, warnings)."""
    q = normalize_lang_block(question)
    a = normalize_lang_block(answer)
    warnings: list[str] = []

    if not needs_translate(q, a):
        return q, a, warnings

    if not (settings.openai_api_key or "").strip():
        warnings.append(
            "auto_translate skipped: OPENAI_API_KEY not set; empty language fields left blank"
        )
        return q, a, warnings

    try:
        filled_q, filled_a = _openai_fill(settings, q, a)
    except Exception as exc:  # noqa: BLE001 — surface as warning, keep partial
        logger.exception("FAQ auto-translate failed")
        warnings.append(f"auto_translate failed: {exc}")
        return q, a, warnings

    for k in LANGS:
        if not q.get(k) and filled_q.get(k):
            q[k] = filled_q[k]
        if not a.get(k) and filled_a.get(k):
            a[k] = filled_a[k]

    still_missing = missing_langs(q) + [f"answer.{k}" for k in missing_langs(a)]
    if still_missing:
        warnings.append(
            "auto_translate incomplete; still empty: " + ", ".join(still_missing)
        )
    return q, a, warnings


def _openai_fill(
    settings: Settings,
    question: dict[str, str],
    answer: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    from openai import OpenAI

    src_q = filled_langs(question)
    src_a = filled_langs(answer)
    if not src_q and not src_a:
        return empty_lang(), empty_lang()

    system = (
        "You are a CS knowledge-base translator for PinGo (Indonesian digital loan app). "
        "Given question and answer fields in Chinese (zh), Indonesian (id), and English (en), "
        "fill ONLY the empty strings. Keep meaning accurate for customer service. "
        "Do not invent product facts beyond the source text. "
        "Return strict JSON: {\"question\":{\"zh\":\"\",\"id\":\"\",\"en\":\"\"},"
        "\"answer\":{\"zh\":\"\",\"id\":\"\",\"en\":\"\"}} with all six keys present."
    )
    user = json.dumps(
        {
            "question": question,
            "answer": answer,
            "fill_question_langs": missing_langs(question),
            "fill_answer_langs": missing_langs(answer),
            "source_question_langs": src_q,
            "source_answer_langs": src_a,
            "lang_names": _LANG_NAME,
        },
        ensure_ascii=False,
    )
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    q = normalize_lang_block(data.get("question"))
    a = normalize_lang_block(data.get("answer"))
    return q, a
