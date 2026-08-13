"""Auto-translate FAQ Q&A across zh / id / en via OpenAI when key is set."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.ai.kb_store import LANGS, empty_lang, normalize_lang_block
from app.config import Settings

logger = logging.getLogger(__name__)

LangCode = Literal["zh", "id", "en"]
_LANG_NAME = {"zh": "Chinese", "id": "Indonesian", "en": "English"}
_MISSING_KEY_WARN = (
    "auto_translate skipped: OPENAI_API_KEY not set; "
    "other languages were not updated"
)


def missing_langs(block: dict[str, str]) -> list[str]:
    return [k for k in LANGS if not (block.get(k) or "").strip()]


def filled_langs(block: dict[str, str]) -> list[str]:
    return [k for k in LANGS if (block.get(k) or "").strip()]


def needs_translate(*blocks: dict[str, str]) -> bool:
    return any(missing_langs(b) for b in blocks)


def normalize_source_lang(value: str | None) -> str | None:
    if not value:
        return None
    lang = str(value).strip().lower()
    return lang if lang in LANGS else None


def detect_source_lang(
    *,
    old_question: dict[str, str] | None = None,
    old_answer: dict[str, str] | None = None,
    new_question: dict[str, str],
    new_answer: dict[str, str],
    preferred: str | None = None,
) -> str | None:
    """Pick source language: explicit preferred, else the single changed lang, else first filled."""
    pref = normalize_source_lang(preferred)
    nq = normalize_lang_block(new_question)
    na = normalize_lang_block(new_answer)
    if pref and ((nq.get(pref) or "").strip() or (na.get(pref) or "").strip()):
        return pref

    oq = normalize_lang_block(old_question) if old_question is not None else empty_lang()
    oa = normalize_lang_block(old_answer) if old_answer is not None else empty_lang()
    changed: list[str] = []
    for k in LANGS:
        q_changed = (nq.get(k) or "").strip() != (oq.get(k) or "").strip()
        a_changed = (na.get(k) or "").strip() != (oa.get(k) or "").strip()
        if (q_changed or a_changed) and (
            (nq.get(k) or "").strip() or (na.get(k) or "").strip()
        ):
            changed.append(k)
    if len(changed) == 1:
        return changed[0]
    if changed:
        for k in ("zh", "id", "en"):
            if k in changed:
                return k

    for k in ("zh", "id", "en"):
        if (nq.get(k) or "").strip() or (na.get(k) or "").strip():
            return k
    return None


def auto_translate_qa(
    settings: Settings,
    *,
    question: dict[str, str] | Any,
    answer: dict[str, str] | Any,
    source_lang: str | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Translate FAQ Q&A.

    - overwrite=False (create): fill only empty language slots.
    - overwrite=True (edit / retranslate): translate from source_lang into the
      other two languages and overwrite them.
    """
    q = normalize_lang_block(question)
    a = normalize_lang_block(answer)
    warnings: list[str] = []
    src = normalize_source_lang(source_lang)

    if overwrite:
        if not src:
            src = detect_source_lang(new_question=q, new_answer=a)
        if not src:
            warnings.append("auto_translate skipped: no source language text")
            return q, a, warnings
        if not (q.get(src) or "").strip() and not (a.get(src) or "").strip():
            warnings.append(
                f"auto_translate skipped: source language '{src}' is empty"
            )
            return q, a, warnings
    else:
        if not needs_translate(q, a):
            return q, a, warnings
        if not src:
            src = detect_source_lang(new_question=q, new_answer=a)

    if not (settings.openai_api_key or "").strip():
        warnings.append(_MISSING_KEY_WARN)
        return q, a, warnings

    try:
        filled_q, filled_a = _openai_translate(
            settings, q, a, source_lang=src or "zh", overwrite=overwrite
        )
    except Exception as exc:  # noqa: BLE001 — surface as warning, keep partial
        logger.exception("FAQ auto-translate failed")
        warnings.append(f"auto_translate failed: {exc}")
        return q, a, warnings

    if overwrite and src:
        for k in LANGS:
            if k == src:
                continue
            if filled_q.get(k):
                q[k] = filled_q[k]
            if filled_a.get(k):
                a[k] = filled_a[k]
    else:
        for k in LANGS:
            if not q.get(k) and filled_q.get(k):
                q[k] = filled_q[k]
            if not a.get(k) and filled_a.get(k):
                a[k] = filled_a[k]

    still_missing = [f"question.{k}" for k in missing_langs(q)] + [
        f"answer.{k}" for k in missing_langs(a)
    ]
    if still_missing:
        warnings.append(
            "auto_translate incomplete; still empty: " + ", ".join(still_missing)
        )
    return q, a, warnings


def _openai_translate(
    settings: Settings,
    question: dict[str, str],
    answer: dict[str, str],
    *,
    source_lang: str,
    overwrite: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    from app.ai.openai_client import make_openai_client

    src_q = filled_langs(question)
    src_a = filled_langs(answer)
    if not src_q and not src_a:
        return empty_lang(), empty_lang()

    targets = [k for k in LANGS if k != source_lang]
    if overwrite:
        system = (
            "You are a CS knowledge-base translator for PinGo (Indonesian digital loan app). "
            f"The authoritative source language is {source_lang} "
            f"({_LANG_NAME.get(source_lang, source_lang)}). "
            f"Translate question and answer FROM {source_lang} into "
            f"{', '.join(targets)}. "
            "OVERWRITE the target language fields completely based on the source text. "
            "Keep the source language fields unchanged. "
            "Keep meaning accurate for customer service. "
            "Do not invent product facts beyond the source text. "
            "Return strict JSON: {\"question\":{\"zh\":\"\",\"id\":\"\",\"en\":\"\"},"
            "\"answer\":{\"zh\":\"\",\"id\":\"\",\"en\":\"\"}} with all six keys present."
        )
        fill_q = targets
        fill_a = targets
    else:
        system = (
            "You are a CS knowledge-base translator for PinGo (Indonesian digital loan app). "
            "Given question and answer fields in Chinese (zh), Indonesian (id), and English (en), "
            "fill ONLY the empty strings. Keep meaning accurate for customer service. "
            "Do not invent product facts beyond the source text. "
            "Return strict JSON: {\"question\":{\"zh\":\"\",\"id\":\"\",\"en\":\"\"},"
            "\"answer\":{\"zh\":\"\",\"id\":\"\",\"en\":\"\"}} with all six keys present."
        )
        fill_q = missing_langs(question)
        fill_a = missing_langs(answer)

    user = json.dumps(
        {
            "question": question,
            "answer": answer,
            "source_lang": source_lang,
            "overwrite": overwrite,
            "fill_question_langs": fill_q,
            "fill_answer_langs": fill_a,
            "source_question_langs": src_q,
            "source_answer_langs": src_a,
            "lang_names": _LANG_NAME,
        },
        ensure_ascii=False,
    )
    client = make_openai_client(settings)
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
