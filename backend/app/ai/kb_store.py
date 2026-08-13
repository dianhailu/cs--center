"""Safe FAQ / unknown-question persistence with multilang fields and file locks."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.ai.faq import detect_lang

_THREAD_LOCK = threading.Lock()
LANGS = ("zh", "id", "en")


def empty_lang() -> dict[str, str]:
    return {"zh": "", "id": "", "en": ""}


def normalize_lang_block(raw: Any, *, prefer_fill: str | None = None) -> dict[str, str]:
    """Normalize nested / flat / q_zh-style language blocks to {zh,id,en}."""
    out = empty_lang()
    if raw is None:
        return out
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return out
        key = prefer_fill or detect_lang(text, "id")
        if key not in LANGS:
            key = "id"
        out[key] = text
        return out
    if not isinstance(raw, dict):
        return out
    # Nested {zh,id,en}
    for k in LANGS:
        val = raw.get(k)
        if val is None and k == "id":
            val = raw.get("in")  # rare typo
        out[k] = str(val or "").strip()
    # Flat q_zh / a_zh style mixed into same dict
    for k in LANGS:
        if out[k]:
            continue
        for prefix in ("q_", "a_", "question_", "answer_", "cat_", "category_"):
            alt = raw.get(f"{prefix}{k}")
            if alt:
                out[k] = str(alt).strip()
                break
    # Single-field legacy: {"text": "...", "lang": "zh"}
    if not any(out.values()):
        text = str(raw.get("text") or raw.get("label") or raw.get("q") or raw.get("a") or "").strip()
        if text:
            lang = str(raw.get("lang") or prefer_fill or detect_lang(text, "id")).lower()
            if lang.startswith("zh") or lang in {"cn", "chinese"}:
                out["zh"] = text
            elif lang.startswith("en"):
                out["en"] = text
            else:
                out["id"] = text
    return out


def _pick_label(block: dict[str, str], prefer: str = "zh") -> str:
    for key in (prefer, "id", "en", "zh"):
        val = (block.get(key) or "").strip()
        if val:
            return val
    return ""


def normalize_faq_item(item: dict[str, Any]) -> dict[str, Any]:
    """Coerce one FAQ row (any legacy shape) into nested multilang form + labels."""
    if not isinstance(item, dict):
        return {
            "id": None,
            "code": None,
            "category_slug": None,
            "source": None,
            "sheet": None,
            "category": {**empty_lang(), "label": ""},
            "question": {**empty_lang(), "label": ""},
            "answer": {**empty_lang(), "label": ""},
        }

    # Flat q_zh / a_zh top-level
    if any(k in item for k in ("q_zh", "q_id", "q_en", "a_zh", "a_id", "a_en")):
        q = normalize_lang_block(
            {"zh": item.get("q_zh"), "id": item.get("q_id"), "en": item.get("q_en")}
        )
        a = normalize_lang_block(
            {"zh": item.get("a_zh"), "id": item.get("a_id"), "en": item.get("a_en")}
        )
    else:
        q_raw = item.get("question")
        a_raw = item.get("answer")
        prefer = None
        if isinstance(item.get("lang"), str):
            prefer = item["lang"]
        if isinstance(q_raw, str) and isinstance(a_raw, str):
            q = normalize_lang_block(q_raw, prefer_fill=prefer)
            a = normalize_lang_block(a_raw, prefer_fill=prefer or detect_lang(q_raw, "id"))
        else:
            q = normalize_lang_block(q_raw, prefer_fill=prefer)
            a = normalize_lang_block(a_raw, prefer_fill=prefer)

    cat = normalize_lang_block(item.get("category"))
    code = str(item.get("code") or "").strip() or None
    category_slug = str(item.get("category_slug") or "").strip().lower() or None
    if not category_slug and code:
        from app.ai.kb_categories import parse_code

        parsed = parse_code(code)
        if parsed:
            category_slug = parsed[0]
    return {
        "id": item.get("id"),
        "code": code,
        "category_slug": category_slug,
        "source": item.get("source"),
        "sheet": item.get("sheet"),
        "note": item.get("note"),
        "category": {**cat, "label": _pick_label(cat, "zh")},
        "question": {**q, "label": _pick_label(q, "zh")},
        "answer": {**a, "label": _pick_label(a, "zh")},
    }


def faq_persist_shape(item: dict[str, Any]) -> dict[str, Any]:
    """Strip UI-only labels for disk storage."""
    cat = normalize_lang_block(item.get("category"))
    q = normalize_lang_block(item.get("question"))
    a = normalize_lang_block(item.get("answer"))
    out: dict[str, Any] = {
        "id": item.get("id"),
        "source": item.get("source") or "console",
        "category": cat,
        "question": q,
        "answer": a,
    }
    if item.get("code"):
        out["code"] = item["code"]
    if item.get("category_slug"):
        out["category_slug"] = item["category_slug"]
    if item.get("sheet"):
        out["sheet"] = item["sheet"]
    if item.get("note") is not None:
        out["note"] = item.get("note")
    return out


def has_any_text(*blocks: dict[str, str]) -> bool:
    for b in blocks:
        if any((b.get(k) or "").strip() for k in LANGS):
            return True
    return False


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        with open(lock_path, "a+", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_faq_raw(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def save_faq_raw(path: Path, items: list[dict[str, Any]]) -> None:
    with file_lock(path):
        payload = json.dumps(items, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(path, payload)


def next_faq_id(items: list[dict[str, Any]]) -> int:
    return max((int(i.get("id") or 0) for i in items), default=0) + 1


def create_faq(
    path: Path,
    *,
    question: dict[str, str] | Any,
    answer: dict[str, str] | Any,
    category: dict[str, str] | Any | None = None,
    category_slug: str | None = None,
    code: str | None = None,
    source: str = "console",
    categories_path: Path | None = None,
) -> dict[str, Any]:
    from app.ai.kb_categories import (
        categories_path_for,
        format_code,
        next_code_for_slug,
        normalize_slug,
        parse_code,
        resolve_category_fields,
    )

    q = normalize_lang_block(question)
    a = normalize_lang_block(answer)
    if not has_any_text(q):
        raise ValueError("question required in at least one language")
    if not has_any_text(a):
        raise ValueError("answer required in at least one language")

    cat_path = categories_path or categories_path_for(path)
    slug, cat = resolve_category_fields(
        category_slug=category_slug,
        category=category,
        categories_path=cat_path,
    )

    with file_lock(path):
        items = load_faq_raw(path)
        entry_code = (code or "").strip() or None
        if entry_code:
            parsed = parse_code(entry_code)
            if not parsed:
                raise ValueError("invalid code; expected {slug}--{NN}")
            if parsed[0] != slug:
                # moving code into selected category slug: re-number
                entry_code = next_code_for_slug(items, slug)
            else:
                # reject duplicate
                if any(str(i.get("code") or "") == entry_code for i in items):
                    raise ValueError(f"code already exists: {entry_code}")
                entry_code = format_code(slug, parsed[1])
        else:
            entry_code = next_code_for_slug(items, slug)

        entry = {
            "id": next_faq_id(items),
            "code": entry_code,
            "category_slug": normalize_slug(slug),
            "source": source,
            "category": cat,
            "question": q,
            "answer": a,
        }
        items.append(entry)
        atomic_write_text(path, json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    return normalize_faq_item(entry)


def update_faq(
    path: Path,
    faq_id: int,
    *,
    question: dict[str, str] | Any | None = None,
    answer: dict[str, str] | Any | None = None,
    category: dict[str, str] | Any | None = None,
    category_slug: str | None = None,
    code: str | None = None,
    categories_path: Path | None = None,
) -> dict[str, Any] | None:
    from app.ai.kb_categories import (
        categories_path_for,
        next_code_for_slug,
        normalize_slug,
        parse_code,
        resolve_category_fields,
    )

    cat_path = categories_path or categories_path_for(path)
    move_slug: str | None = None
    move_cat: dict[str, str] | None = None
    if category_slug is not None or category is not None:
        move_slug, move_cat = resolve_category_fields(
            category_slug=category_slug,
            category=category,
            categories_path=cat_path,
        )

    with file_lock(path):
        items = load_faq_raw(path)
        found: dict[str, Any] | None = None
        for item in items:
            try:
                iid = int(item.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if iid != faq_id:
                continue
            if question is not None:
                item["question"] = normalize_lang_block(question)
            if answer is not None:
                item["answer"] = normalize_lang_block(answer)
            if move_slug is not None and move_cat is not None:
                old_slug = str(item.get("category_slug") or "").strip().lower()
                item["category"] = move_cat
                item["category_slug"] = normalize_slug(move_slug)
                if old_slug != move_slug:
                    # re-number into new category unless explicit code provided
                    if code is None:
                        item["code"] = next_code_for_slug(
                            [x for x in items if x is not item],
                            move_slug,
                        )
            if code is not None:
                code_s = code.strip()
                parsed = parse_code(code_s)
                if not parsed:
                    raise ValueError("invalid code; expected {slug}--{NN}")
                slug_now = str(item.get("category_slug") or parsed[0])
                if parsed[0] != slug_now:
                    raise ValueError("code slug must match category_slug")
                if any(
                    str(i.get("code") or "") == code_s and i is not item for i in items
                ):
                    raise ValueError(f"code already exists: {code_s}")
                item["code"] = code_s
            # Ensure persisted shape is nested multilang
            item["question"] = normalize_lang_block(item.get("question"))
            item["answer"] = normalize_lang_block(item.get("answer"))
            item["category"] = normalize_lang_block(item.get("category"))
            if not has_any_text(item["question"]) or not has_any_text(item["answer"]):
                raise ValueError("question and answer required in at least one language")
            found = item
            break
        if not found:
            return None
        atomic_write_text(path, json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    return normalize_faq_item(found)


def migrate_faq_file(path: Path) -> int:
    """Rewrite faq.json into nested multilang if any row needs coercion. Returns changed count."""
    with file_lock(path):
        items = load_faq_raw(path)
        changed = 0
        migrated: list[dict[str, Any]] = []
        for item in items:
            norm = normalize_faq_item(item)
            disk = faq_persist_shape(norm)
            # preserve original id/source/sheet/note already in disk
            before_q = item.get("question") if isinstance(item.get("question"), dict) else None
            before_a = item.get("answer") if isinstance(item.get("answer"), dict) else None
            needs = (
                before_q is None
                or before_a is None
                or any(k in item for k in ("q_zh", "q_id", "q_en", "lang"))
                or not all(k in (before_q or {}) for k in LANGS)
                or not all(k in (before_a or {}) for k in LANGS)
            )
            if needs:
                changed += 1
            migrated.append(disk)
        if changed:
            atomic_write_text(path, json.dumps(migrated, ensure_ascii=False, indent=2) + "\n")
        return changed
