"""Detect phone-number-like customer messages (greeting/reception, not KB unknowns)."""

from __future__ import annotations

import re

# Common prefixes before a bare number (ID/EN/ZH-ish).
_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"phone|tel|telephone|hp|wa|whatsapp|mobile|nomor(?:\s+hp)?|no\.?\s*hp|"
    r"contact|kontak|手机|电话|号码"
    r")\s*[:：#-]?\s*"
)

_SEP_RE = re.compile(r"[\s\-()./]+")


def is_phone_like(text: str) -> bool:
    """True when the message is primarily a phone number (not a question that mentions one).

    Matches e.g. ``0812…``, ``+62…``, ``Phone: 08…``, spaced/dashed digits.
    Rejects longer sentences that merely contain a number.
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 64:
        return False

    # Too much alphabetic / CJK content → real question / sentence.
    letters = sum(1 for c in raw if c.isalpha() or "\u4e00" <= c <= "\u9fff")
    if letters > 12:
        return False

    candidate = _PREFIX_RE.sub("", raw).strip()
    if not candidate:
        return False

    # Allow only digits, optional leading +, and common phone separators.
    if not re.fullmatch(r"\+?[\d\s\-()./]+", candidate):
        return False

    compact = _SEP_RE.sub("", candidate)
    if compact.startswith("+"):
        body = compact[1:]
    else:
        body = compact
    if not body.isdigit():
        return False
    return 8 <= len(body) <= 15


_RECEPTION: dict[str, str] = {
    "id": (
        "Halo! Terima kasih sudah menghubungi PinGo CS. "
        "Ada yang bisa kami bantu hari ini?"
    ),
    "zh": "您好！感谢联系 PinGo 客服，请问有什么可以帮您？",
    "en": "Hi! Thanks for contacting PinGo CS. How can we help you today?",
}


def reception_reply(lang: str, *, faq_items: list[dict] | None = None) -> str:
    """Standard PinGo reception greeting; prefer FAQ ``pingo-reception--01`` when present."""
    key = (lang or "id").lower()
    if key.startswith("zh") or key in {"cn", "chinese"}:
        key = "zh"
    elif key.startswith("en"):
        key = "en"
    else:
        key = "id"

    if faq_items:
        for item in faq_items:
            if str(item.get("code") or "") != "pingo-reception--01":
                continue
            answers = item.get("answer") or {}
            if isinstance(answers, dict):
                text = (
                    (answers.get(key) or "").strip()
                    or (answers.get("id") or "").strip()
                    or (answers.get("en") or "").strip()
                    or (answers.get("zh") or "").strip()
                )
                if text:
                    return text
            break

    return _RECEPTION[key]
