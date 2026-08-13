"""FAQ category registry: slug + trilingual labels + entry codes `{slug}--{NN}`."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.ai.kb_store import (
    LANGS,
    atomic_write_text,
    empty_lang,
    file_lock,
    load_faq_raw,
    normalize_lang_block,
)

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CODE_RE = re.compile(r"^([a-z][a-z0-9]*(?:-[a-z0-9]+)*)--(\d{2,})$")

# Seed map: normalize existing category labels → pingo-* slugs
_LABEL_TO_SLUG: dict[str, str] = {
    "产品": "pingo-product",
    "product": "pingo-product",
    "produk": "pingo-product",
    "注册": "pingo-otp",
    "registration": "pingo-otp",
    "pendaftaran": "pingo-otp",
    "otp": "pingo-otp",
    "kyc": "pingo-kyc",
    "额度": "pingo-limit",
    "limit": "pingo-limit",
    "借款": "pingo-loan",
    "loan": "pingo-loan",
    "pinjaman": "pingo-loan",
    "还款": "pingo-repayment",
    "repayment": "pingo-repayment",
    "pembayaran": "pingo-repayment",
    "逾期": "pingo-overdue",
    "overdue": "pingo-overdue",
    "keterlambatan": "pingo-overdue",
    "安全": "pingo-security",
    "security": "pingo-security",
    "keamanan": "pingo-security",
    "投诉": "pingo-complaint",
    "complaint": "pingo-complaint",
    "komplain": "pingo-complaint",
    "填写资料": "pingo-profile",
    "profile information": "pingo-profile",
    "mengisi data": "pingo-profile",
    "风控审核": "pingo-risk",
    "verification & risk review": "pingo-risk",
    "verifikasi & penilaian risiko": "pingo-risk",
    "利息、费用与还款": "pingo-fees",
    "interest, fees & repayment": "pingo-fees",
    "bunga, biaya & pembayaran": "pingo-fees",
    "账号与应用": "pingo-account",
    "account & app": "pingo-account",
    "akun & aplikasi": "pingo-account",
    "借款与放款": "pingo-disbursement",
    "loan & disbursement": "pingo-disbursement",
    "pinjaman & pencairan": "pingo-disbursement",
    "安全与隐私": "pingo-privacy",
    "security & privacy": "pingo-privacy",
    "keamanan & privasi": "pingo-privacy",
    "已教答": "pingo-taught",
    "diajarkan": "pingo-taught",
    "taught": "pingo-taught",
    "接待": "pingo-reception",
    "reception": "pingo-reception",
    "greeting": "pingo-reception",
    "sapaan": "pingo-reception",
    "ai学习": "pingo-learned",
    "ai learned": "pingo-learned",
    "pembelajaran ai": "pingo-learned",
}

_DEFAULT_LABELS: dict[str, dict[str, str]] = {
    "pingo-product": {"zh": "产品", "id": "Produk", "en": "Product"},
    "pingo-otp": {"zh": "注册/OTP", "id": "Pendaftaran/OTP", "en": "Registration/OTP"},
    "pingo-kyc": {"zh": "KYC", "id": "KYC", "en": "KYC"},
    "pingo-limit": {"zh": "额度", "id": "Limit", "en": "Limit"},
    "pingo-loan": {"zh": "借款", "id": "Pinjaman", "en": "Loan"},
    "pingo-repayment": {"zh": "还款", "id": "Pembayaran", "en": "Repayment"},
    "pingo-overdue": {"zh": "逾期", "id": "Keterlambatan", "en": "Overdue"},
    "pingo-security": {"zh": "安全", "id": "Keamanan", "en": "Security"},
    "pingo-complaint": {"zh": "投诉", "id": "Komplain", "en": "Complaint"},
    "pingo-profile": {"zh": "填写资料", "id": "Mengisi data", "en": "Profile information"},
    "pingo-risk": {
        "zh": "风控审核",
        "id": "Verifikasi & penilaian risiko",
        "en": "Verification & risk review",
    },
    "pingo-fees": {
        "zh": "利息、费用与还款",
        "id": "Bunga, biaya & pembayaran",
        "en": "Interest, fees & repayment",
    },
    "pingo-account": {"zh": "账号与应用", "id": "Akun & aplikasi", "en": "Account & app"},
    "pingo-disbursement": {
        "zh": "借款与放款",
        "id": "Pinjaman & pencairan",
        "en": "Loan & disbursement",
    },
    "pingo-privacy": {
        "zh": "安全与隐私",
        "id": "Keamanan & privasi",
        "en": "Security & privacy",
    },
    "pingo-taught": {"zh": "已教答", "id": "Diajarkan", "en": "Taught"},
    "pingo-reception": {"zh": "接待", "id": "Sapaan", "en": "Reception"},
    "pingo-learned": {"zh": "AI学习", "id": "Pembelajaran AI", "en": "AI learned"},
    "ai-learned": {"zh": "AI学习", "id": "Pembelajaran AI", "en": "AI learned"},
}


def categories_path_for(faq_path: Path) -> Path:
    return faq_path.parent / "categories.json"


def slugify_category(raw: str, *, prefix: str = "pingo") -> str:
    text = (raw or "").strip().lower()
    if not text:
        return f"{prefix}-general"
    # ascii slug
    cleaned = re.sub(r"[^a-z0-9]+", "-", text)
    cleaned = cleaned.strip("-") or "general"
    if not cleaned.startswith(f"{prefix}-"):
        cleaned = f"{prefix}-{cleaned}"
    return cleaned[:64]


def normalize_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not s:
        raise ValueError("category slug required")
    if not _SLUG_RE.match(s):
        raise ValueError(
            "invalid category slug (use lowercase letters, digits, hyphens; e.g. pingo-product)"
        )
    return s


def parse_code(code: str) -> tuple[str, int] | None:
    m = _CODE_RE.match((code or "").strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def format_code(slug: str, num: int) -> str:
    return f"{normalize_slug(slug)}--{num:02d}"


def infer_slug_from_category(cat: dict[str, str] | Any | None) -> str:
    block = normalize_lang_block(cat) if cat is not None else empty_lang()
    for key in ("zh", "en", "id"):
        label = (block.get(key) or "").strip()
        if not label:
            continue
        mapped = _LABEL_TO_SLUG.get(label.lower()) or _LABEL_TO_SLUG.get(label)
        if mapped:
            return mapped
        # try without punctuation noise
        mapped = _LABEL_TO_SLUG.get(label.lower().replace("＆", "&"))
        if mapped:
            return mapped
    # fallback: slugify zh or en
    seed = block.get("zh") or block.get("en") or block.get("id") or "general"
    # Prefer ascii from en/id for slug
    ascii_seed = block.get("en") or block.get("id") or seed
    if re.search(r"[a-zA-Z]", ascii_seed):
        return slugify_category(ascii_seed)
    return "pingo-general"


def load_categories_raw(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict):
        items = raw.get("categories") or raw.get("items") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip().lower()
        if not slug:
            continue
        label = normalize_lang_block(item.get("label") or item.get("category"))
        out.append({"slug": slug, "label": label})
    return out


def save_categories_raw(path: Path, categories: list[dict[str, Any]]) -> None:
    import json

    payload = {
        "categories": [
            {
                "slug": c["slug"],
                "label": normalize_lang_block(c.get("label")),
            }
            for c in categories
            if c.get("slug")
        ]
    }
    with file_lock(path):
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def ensure_category(
    path: Path,
    slug: str,
    label: dict[str, str] | Any | None = None,
) -> dict[str, Any]:
    slug_n = normalize_slug(slug)
    label_n = normalize_lang_block(label) if label is not None else empty_lang()
    if not any(label_n.values()):
        label_n = dict(_DEFAULT_LABELS.get(slug_n) or {
            "zh": slug_n,
            "id": slug_n,
            "en": slug_n.replace("-", " ").title(),
        })

    with file_lock(path):
        cats = load_categories_raw(path)
        for c in cats:
            if c["slug"] == slug_n:
                # fill empty label slots from incoming
                merged = normalize_lang_block(c.get("label"))
                changed = False
                for k in LANGS:
                    if not merged.get(k) and label_n.get(k):
                        merged[k] = label_n[k]
                        changed = True
                if changed:
                    c["label"] = merged
                    import json

                    atomic_write_text(
                        path,
                        json.dumps(
                            {"categories": cats},
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                    )
                return {"slug": slug_n, "label": {**merged, "label": _pick(merged)}}
        cats.append({"slug": slug_n, "label": label_n})
        import json

        atomic_write_text(
            path,
            json.dumps({"categories": cats}, ensure_ascii=False, indent=2) + "\n",
        )
    return {"slug": slug_n, "label": {**label_n, "label": _pick(label_n)}}


def create_category(
    path: Path,
    *,
    slug: str,
    label: dict[str, str] | Any | None = None,
) -> dict[str, Any]:
    slug_n = normalize_slug(slug)
    cats = load_categories_raw(path)
    if any(c["slug"] == slug_n for c in cats):
        raise ValueError(f"category already exists: {slug_n}")
    return ensure_category(path, slug_n, label)


def list_categories_with_counts(
    categories_path: Path,
    faq_path: Path,
) -> list[dict[str, Any]]:
    cats = load_categories_raw(categories_path)
    by_slug = {c["slug"]: c for c in cats}
    items = load_faq_raw(faq_path)
    counts: dict[str, int] = {}
    for item in items:
        slug = str(item.get("category_slug") or "").strip().lower()
        if not slug:
            parsed = parse_code(str(item.get("code") or ""))
            slug = parsed[0] if parsed else infer_slug_from_category(item.get("category"))
        counts[slug] = counts.get(slug, 0) + 1
        if slug not in by_slug:
            by_slug[slug] = {
                "slug": slug,
                "label": normalize_lang_block(
                    _DEFAULT_LABELS.get(slug) or item.get("category")
                ),
            }
    out: list[dict[str, Any]] = []
    for slug, meta in sorted(by_slug.items(), key=lambda x: x[0]):
        label = normalize_lang_block(meta.get("label"))
        out.append(
            {
                "slug": slug,
                "label": {**label, "label": _pick(label)},
                "count": counts.get(slug, 0),
            }
        )
    return out


def next_code_for_slug(items: list[dict[str, Any]], slug: str) -> str:
    slug_n = normalize_slug(slug)
    max_n = 0
    for item in items:
        parsed = parse_code(str(item.get("code") or ""))
        if parsed and parsed[0] == slug_n:
            max_n = max(max_n, parsed[1])
            continue
        if str(item.get("category_slug") or "").strip().lower() == slug_n:
            # count even without code (migration edge)
            max_n = max(max_n, 0)
    return format_code(slug_n, max_n + 1)


def resolve_category_fields(
    *,
    category_slug: str | None,
    category: dict[str, str] | Any | None,
    categories_path: Path,
) -> tuple[str, dict[str, str]]:
    """Return (slug, label block). Creates category registry entry if needed."""
    label = normalize_lang_block(category) if category is not None else empty_lang()
    if category_slug:
        slug = normalize_slug(category_slug)
    elif any(label.values()):
        slug = infer_slug_from_category(label)
    else:
        slug = "pingo-taught"
        label = dict(_DEFAULT_LABELS["pingo-taught"])
    meta = ensure_category(categories_path, slug, label if any(label.values()) else None)
    final_label = normalize_lang_block(meta.get("label"))
    # Prefer explicit labels from request when provided
    for k in LANGS:
        if label.get(k):
            final_label[k] = label[k]
    if any(label.values()):
        ensure_category(categories_path, slug, final_label)
    return slug, final_label


def migrate_faq_codes(faq_path: Path, categories_path: Path) -> int:
    """Assign category_slug + code to all FAQ rows; seed categories.json. Returns changed count."""
    import json

    items = load_faq_raw(faq_path)
    if items and all(
        str(i.get("code") or "").strip() and str(i.get("category_slug") or "").strip()
        for i in items
    ):
        # Still ensure registry exists
        if not categories_path.exists() or not load_categories_raw(categories_path):
            for item in items:
                slug = str(item.get("category_slug") or "").strip().lower()
                if slug:
                    ensure_category(
                        categories_path,
                        slug,
                        item.get("category") or _DEFAULT_LABELS.get(slug),
                    )
        return 0

    # First pass: infer slug + collect labels (no locks nested)
    prepared: list[tuple[str, dict[str, str]]] = []
    for item in items:
        cat = normalize_lang_block(item.get("category"))
        existing_code = str(item.get("code") or "").strip()
        existing_slug = str(item.get("category_slug") or "").strip().lower()
        parsed = parse_code(existing_code)
        if parsed:
            slug = parsed[0]
        elif existing_slug:
            slug = existing_slug
        else:
            slug = infer_slug_from_category(cat)
        if not any(cat.values()) and slug in _DEFAULT_LABELS:
            cat = dict(_DEFAULT_LABELS[slug])
        prepared.append((slug, cat))

    for slug, cat in prepared:
        ensure_category(
            categories_path,
            slug,
            cat if any(cat.values()) else _DEFAULT_LABELS.get(slug),
        )

    counters: dict[str, int] = {}
    changed = 0
    with file_lock(faq_path):
        items = load_faq_raw(faq_path)
        for item in items:
            cat = normalize_lang_block(item.get("category"))
            existing_code = str(item.get("code") or "").strip()
            existing_slug = str(item.get("category_slug") or "").strip().lower()
            parsed = parse_code(existing_code)
            if parsed:
                slug = parsed[0]
            elif existing_slug:
                slug = existing_slug
            else:
                slug = infer_slug_from_category(cat)
            if not any(cat.values()) and slug in _DEFAULT_LABELS:
                cat = dict(_DEFAULT_LABELS[slug])
            counters[slug] = counters.get(slug, 0) + 1
            code = format_code(slug, counters[slug])
            before = (item.get("code"), item.get("category_slug"), json.dumps(item.get("category"), ensure_ascii=False, sort_keys=True))
            item["code"] = code
            item["category_slug"] = slug
            item["category"] = cat
            after = (item.get("code"), item.get("category_slug"), json.dumps(item.get("category"), ensure_ascii=False, sort_keys=True))
            if before != after:
                changed += 1
        atomic_write_text(faq_path, json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    return changed


def _pick(block: dict[str, str]) -> str:
    for key in ("zh", "id", "en"):
        val = (block.get(key) or "").strip()
        if val:
            return val
    return ""
