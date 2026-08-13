"""Promote high-quality customer→human-agent history pairs into faq.json."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.faq import tokenize, _tf, _cosine
from app.ai.kb_categories import ensure_category
from app.ai.kb_store import create_faq, load_faq_raw, normalize_faq_item
from app.ai.phone import is_phone_like
from app.config import Settings

logger = logging.getLogger(__name__)

SOURCE_AI_LEARN = "ai_learn"
UPDATED_BY_SMART = "Smart"

GREETING_RE = re.compile(
    r"(?is)^\s*(?:"
    r"halo+|hai+|hi+|hello+|hey+|"
    r"selamat\s+(?:pagi|siang|sore|malam)|"
    r"assalamualaikum|salam|"
    r"你好|您好|在吗|在麼|早上好|下午好|晚上好|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"pagi|siang|sore|malam"
    r")[\s!.。！？~]*$",
)

GENERIC_HANDOFF_RE = re.compile(
    r"(?is)^\s*(?:"
    r"mohon\s+tunggu|silakan\s+menunggu|tunggu\s+sebentar|"
    r"akan\s+(?:segera\s+)?(?:dibantu|dihubungi)|"
    r"kami\s+(?:alihkan|transfer)|"
    r"please\s+wait|hold\s+on|"
    r"稍等|请稍等|转人工|已转人工|会有人工"
    r").{0,80}$",
)

LEARNED_LABEL = {
    "zh": "AI学习",
    "id": "Pembelajaran AI",
    "en": "AI learned",
}


def _now_iso(tz_name: str) -> str:
    return datetime.now(tz=ZoneInfo(tz_name)).isoformat(timespec="seconds")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _pair_key(question: str, answer: str) -> str:
    raw = f"{_clean(question).lower()}||{_clean(answer).lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _question_key(question: str) -> str:
    return _clean(question).lower()


def _is_greeting(text: str) -> bool:
    t = _clean(text)
    if len(t) <= 24 and GREETING_RE.match(t):
        return True
    if len(t) < 12 and GREETING_RE.match(t):
        return True
    return bool(GREETING_RE.match(t)) and len(t) <= 40


def _is_generic_handoff(answer: str) -> bool:
    a = _clean(answer)
    if GENERIC_HANDOFF_RE.match(a):
        return True
    lower = a.lower()
    soft = ("tunggu", "menunggu", "wait", "稍等", "人工")
    if len(a) < 60 and sum(1 for s in soft if s in lower) >= 2:
        return True
    return False


def _question_texts(item: dict[str, Any]) -> list[str]:
    q = item.get("question") if isinstance(item.get("question"), dict) else {}
    out: list[str] = []
    for k in ("zh", "id", "en"):
        t = _clean(str(q.get(k) or ""))
        if t:
            out.append(t)
    return out


def _similarity(a: str, b: str) -> float:
    ta = tokenize(a)
    tb = tokenize(b)
    if not ta or not tb:
        # fallback exact / containment for short strings
        al, bl = a.lower().strip(), b.lower().strip()
        if not al or not bl:
            return 0.0
        if al == bl:
            return 1.0
        if al in bl or bl in al:
            return 0.9
        return 0.0
    tf_a, tf_b = _tf(ta), _tf(tb)
    vocab = set(ta) | set(tb)
    idf = {t: 1.0 for t in vocab}
    # light IDF from pair only
    for t in vocab:
        df = (1 if t in ta else 0) + (1 if t in tb else 0)
        idf[t] = math.log((2 + 1) / (df + 1)) + 1.0
    return _cosine(tf_a, tf_b, idf)


def _faq_question_dup(question: str, faq_items: list[dict[str, Any]], threshold: float) -> bool:
    for item in faq_items:
        for existing in _question_texts(item):
            if _similarity(question, existing) >= threshold:
                return True
    return False


def _best_category_slug(
    question: str,
    faq_items: list[dict[str, Any]],
    *,
    min_score: float,
    fallback: str,
) -> str:
    best_slug = fallback
    best = 0.0
    for item in faq_items:
        slug = str(item.get("category_slug") or "").strip().lower()
        if not slug or slug in {"pingo-learned", "ai-learned", "pingo-taught", "pingo-reception"}:
            continue
        for existing in _question_texts(item):
            score = _similarity(question, existing)
            if score > best:
                best = score
                best_slug = slug
    if best >= min_score:
        return best_slug
    return fallback


def _load_promoted_keys(meta_path: Path) -> set[str]:
    if not meta_path.exists():
        return set()
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    keys = raw.get("promoted_keys") or []
    return {str(k) for k in keys if k}


def _save_promote_meta(meta_path: Path, *, keys: set[str], stamp: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    # Cap stored keys to avoid unbounded growth
    ordered = sorted(keys)
    if len(ordered) > 20000:
        ordered = ordered[-20000:]
    payload = {
        **stamp,
        "promoted_keys": ordered,
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _learned_slug(product_code: str) -> str:
    pc = (product_code or "pingo").strip().lower() or "pingo"
    return f"{pc}-learned"


def promote_history_to_faq(settings: Settings) -> dict[str, Any]:
    """Evaluate history_pairs and append qualifying rows into faq.json.

    Safe to run after nightly HISTORY_LEARN. Idempotent via promoted_keys meta.
    """
    tz = settings.history_learn_timezone
    stamp: dict[str, Any] = {
        "built_at": _now_iso(tz),
        "promoted": 0,
        "candidates": 0,
        "skipped_dup": 0,
        "skipped_quality": 0,
        "skipped_already": 0,
    }
    if not settings.faq_auto_promote:
        stamp["skipped"] = True
        stamp["reason"] = "FAQ_AUTO_PROMOTE=false"
        return stamp

    history_path = settings.history_path
    if not history_path.exists():
        stamp["skipped"] = True
        stamp["reason"] = "no history_pairs"
        return stamp

    try:
        pairs_raw = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stamp["skipped"] = True
        stamp["reason"] = "history_pairs unreadable"
        return stamp
    if not isinstance(pairs_raw, list):
        stamp["skipped"] = True
        stamp["reason"] = "history_pairs not a list"
        return stamp

    product_code = (settings.default_product_code or "pingo").strip().lower()
    learned_slug = _learned_slug(product_code)
    ensure_category(settings.categories_path, learned_slug, LEARNED_LABEL)

    meta_path = settings.faq_path.parent / "faq_promote.meta.json"
    promoted_keys = _load_promoted_keys(meta_path)

    min_ans = int(settings.faq_promote_min_answer_chars)
    max_ans = int(settings.faq_promote_max_answer_chars)
    min_q = int(settings.faq_promote_min_question_chars)
    min_repeat = int(settings.faq_promote_min_repeat)
    dup_thr = float(settings.faq_promote_dedupe_similarity)
    cat_thr = float(settings.faq_promote_category_similarity)
    max_n = int(settings.faq_promote_max_per_night)

    # Count question frequency (same cleaned question, any answer)
    q_counts: dict[str, int] = {}
    usable: list[dict[str, Any]] = []
    for raw in pairs_raw:
        if not isinstance(raw, dict):
            continue
        q = _clean(str(raw.get("question") or ""))
        a = _clean(str(raw.get("answer") or ""))
        if not q or not a:
            stamp["skipped_quality"] += 1
            continue
        if is_phone_like(q) or _is_greeting(q):
            stamp["skipped_quality"] += 1
            continue
        if len(q) < min_q:
            stamp["skipped_quality"] += 1
            continue
        if len(a) < min_ans or len(a) > max_ans:
            stamp["skipped_quality"] += 1
            continue
        if _is_generic_handoff(a):
            stamp["skipped_quality"] += 1
            continue
        qk = _question_key(q)
        q_counts[qk] = q_counts.get(qk, 0) + 1
        usable.append({**raw, "question": q, "answer": a, "_qk": qk, "_pk": _pair_key(q, a)})

    # Prefer repeated questions; allow solid singles
    candidates: list[dict[str, Any]] = []
    for row in usable:
        count = q_counts.get(row["_qk"], 1)
        if count >= min_repeat:
            row["_priority"] = 2 + min(count, 10)
            candidates.append(row)
        else:
            # single solid reply: longer, non-generic
            if len(row["answer"]) >= max(min_ans, 40) and not _is_generic_handoff(row["answer"]):
                row["_priority"] = 1
                candidates.append(row)
            else:
                stamp["skipped_quality"] += 1

    # Dedupe by pair key; keep highest priority / longest answer
    by_key: dict[str, dict[str, Any]] = {}
    for row in candidates:
        pk = row["_pk"]
        prev = by_key.get(pk)
        if not prev or row["_priority"] > prev["_priority"] or (
            row["_priority"] == prev["_priority"] and len(row["answer"]) > len(prev["answer"])
        ):
            by_key[pk] = row
    ranked = sorted(
        by_key.values(),
        key=lambda r: (r["_priority"], len(r["answer"]), -len(r["question"])),
        reverse=True,
    )
    stamp["candidates"] = len(ranked)

    faq_items = [normalize_faq_item(x) for x in load_faq_raw(settings.faq_path)]
    promoted = 0
    for row in ranked:
        if promoted >= max_n:
            break
        pk = row["_pk"]
        if pk in promoted_keys:
            stamp["skipped_already"] += 1
            continue
        q = row["question"]
        a = row["answer"]
        if _faq_question_dup(q, faq_items, dup_thr):
            stamp["skipped_dup"] += 1
            promoted_keys.add(pk)
            continue

        lang = str(row.get("lang") or "id").lower()
        if lang.startswith("zh"):
            lang_key = "zh"
        elif lang.startswith("en"):
            lang_key = "en"
        else:
            lang_key = "id"
        q_block = {"zh": "", "id": "", "en": ""}
        a_block = {"zh": "", "id": "", "en": ""}
        q_block[lang_key] = q
        a_block[lang_key] = a

        slug = _best_category_slug(q, faq_items, min_score=cat_thr, fallback=learned_slug)
        detail_bits = []
        if row.get("external_id"):
            detail_bits.append(f"external_id={row.get('external_id')}")
        if row.get("conversation_id"):
            detail_bits.append(f"conversation_id={row.get('conversation_id')}")
        source_detail = "; ".join(detail_bits) or None

        try:
            entry = create_faq(
                settings.faq_path,
                question=q_block,
                answer=a_block,
                category_slug=slug,
                product_code=product_code,
                source=SOURCE_AI_LEARN,
                updated_by=UPDATED_BY_SMART,
                updated_at=_now_iso(tz),
                source_detail=source_detail,
                categories_path=settings.categories_path,
            )
        except ValueError as exc:
            logger.warning("faq auto-promote create failed: %s", exc)
            continue

        faq_items.append(entry)
        promoted_keys.add(pk)
        promoted += 1

    stamp["promoted"] = promoted
    _save_promote_meta(meta_path, keys=promoted_keys, stamp=stamp)
    logger.info(
        "faq auto-promote promoted=%s candidates=%s dup=%s quality=%s already=%s",
        promoted,
        stamp["candidates"],
        stamp["skipped_dup"],
        stamp["skipped_quality"],
        stamp["skipped_already"],
    )
    return stamp
