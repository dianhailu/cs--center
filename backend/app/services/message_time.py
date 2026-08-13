"""Resolve actual customer/agent message time from LiveAgent metadata.

Inbound import historically set ``messages.created_at`` to *import* time (e.g. a
history refresh on 2026-08-08), while the real consult time lives in
``meta.datecreated`` from LiveAgent. Stats and analytics must prefer LA time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_la_timestamp(raw: Any) -> datetime | None:
    """Parse LiveAgent ``datecreated``-style values as UTC-aware datetimes."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    # LA often sends "YYYY-MM-DD HH:MM:SS" (naive, treated as UTC).
    text = text.replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def consult_at_from_meta(meta: dict | None, *, fallback: datetime | None = None) -> datetime | None:
    """Prefer LA datecreated / occurred_at; else fallback (usually created_at)."""
    snap = meta if isinstance(meta, dict) else {}
    for key in ("datecreated", "occurred_at", "date_created", "created"):
        parsed = parse_la_timestamp(snap.get(key))
        if parsed is not None:
            return parsed
    if fallback is None:
        return None
    if fallback.tzinfo is None:
        return fallback.replace(tzinfo=timezone.utc)
    return fallback.astimezone(timezone.utc)


def message_consult_at(msg: Any) -> datetime:
    """Actual consult/event time for a Message row."""
    created = getattr(msg, "created_at", None)
    if created is not None and getattr(created, "tzinfo", None) is None:
        created = created.replace(tzinfo=timezone.utc)
    at = consult_at_from_meta(getattr(msg, "meta", None), fallback=created)
    if at is None:
        return datetime.now(timezone.utc)
    return at
