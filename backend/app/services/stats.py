"""Daily consultation stats for the agent console.

Metric definitions (Asia/Jakarta day boundaries):

- **consultations_count** (咨询次数): number of distinct conversations that had at
  least one *customer inbound* message that calendar day. Counts conversation
  activity that day (not raw message volume, not conversation.created_at alone).

- **unique_people** (咨询人数): distinct person keys among those conversations.
  Key priority: phone → email → owner_contactid / visitor_userid.
  Empty identity is skipped (no synthetic uniqueness).

- **categories**: each inbound customer message that day is classified once into
  FAQ category_slug (from AiJob FAQ hit), reception (phone-like / pingo-reception),
  unknown (logged unknown / weak retrieval / uncertain handoff), or other.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.kb_categories import _DEFAULT_LABELS, load_categories_raw, parse_code
from app.ai.kb_store import load_faq_raw, normalize_lang_block
from app.ai.phone import is_phone_like
from app.config import Settings, get_settings
from app.models import AiJob, Conversation, Message, MessageDirection, MessageSenderType

TZ_NAME = "Asia/Jakarta"
PHONE_LINE_RE = re.compile(
    r"(?im)^\s*(?:phone|tel|telephone|hp|wa|whatsapp|mobile|nomor(?:\s+hp)?|no\.?\s*hp|"
    r"contact|kontak|手机|电话|号码)\s*[:：#-]?\s*([+\d][\d\s\-()./]{6,})\s*$"
)


def jakarta_tz() -> ZoneInfo:
    return ZoneInfo(TZ_NAME)


def day_bounds_utc(day: date, tz: ZoneInfo | None = None) -> tuple[datetime, datetime]:
    """Inclusive start / exclusive end of a Jakarta calendar day, as UTC datetimes."""
    zone = tz or jakarta_tz()
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def parse_ymd(value: str) -> date:
    return date.fromisoformat((value or "").strip())


def _norm_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    compact = re.sub(r"[\s\-()./]+", "", str(raw).strip())
    if compact.startswith("+"):
        body = compact[1:]
    else:
        body = compact
    if not body.isdigit() or not (8 <= len(body) <= 15):
        return None
    return compact


def _norm_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = str(raw).strip().lower()
    if "@" not in email or len(email) < 5:
        return None
    return email


def extract_phone_from_text(body: str | None) -> str | None:
    if not body:
        return None
    m = PHONE_LINE_RE.search(body)
    if m:
        return _norm_phone(m.group(1))
    if is_phone_like(body):
        # Strip common prefixes then normalize digits.
        stripped = re.sub(
            r"(?is)^\s*(?:phone|tel|telephone|hp|wa|whatsapp|mobile|nomor(?:\s+hp)?|"
            r"no\.?\s*hp|contact|kontak|手机|电话|号码)\s*[:：#-]?\s*",
            "",
            body,
        )
        return _norm_phone(stripped or body)
    return None


def person_key_for_conversation(
    conv: Conversation,
    *,
    inbound_bodies: list[str] | None = None,
) -> str | None:
    """Stable identity key: phone OR email OR contact/visitor id. None if empty."""
    snap = conv.customer_snapshot if isinstance(conv.customer_snapshot, dict) else {}
    phone = _norm_phone(snap.get("phone") if snap else None)
    if not phone and inbound_bodies:
        for body in inbound_bodies:
            phone = extract_phone_from_text(body)
            if phone:
                break
    if phone:
        return f"phone:{phone}"

    email = _norm_email(conv.customer_email) or _norm_email(
        (snap or {}).get("owner_email")
    )
    if email:
        return f"email:{email}"

    contact = str((snap or {}).get("owner_contactid") or "").strip()
    if contact:
        return f"contact:{contact}"

    visitor = str((snap or {}).get("visitor_userid") or "").strip()
    if visitor:
        return f"visitor:{visitor}"

    return None


def _label_zh(slug: str, categories: dict[str, dict[str, Any]]) -> str:
    if slug == "unknown":
        return "未知问题"
    if slug == "other":
        return "其他"
    if slug == "reception":
        return "接待/电话问候"
    meta = categories.get(slug) or {}
    label = normalize_lang_block(meta.get("label") or _DEFAULT_LABELS.get(slug) or {})
    return label.get("zh") or label.get("id") or label.get("en") or slug


def _faq_id_to_slug(settings: Settings) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for item in load_faq_raw(settings.faq_path):
        try:
            fid = int(item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not fid:
            continue
        slug = str(item.get("category_slug") or "").strip().lower()
        if not slug:
            parsed = parse_code(str(item.get("code") or ""))
            slug = parsed[0] if parsed else ""
        if slug:
            mapping[fid] = slug
    return mapping


def _category_registry(settings: Settings) -> dict[str, dict[str, Any]]:
    cats = load_categories_raw(settings.categories_path)
    return {c["slug"]: c for c in cats}


def _classify_message(
    body: str,
    job: AiJob | None,
    faq_map: dict[int, str],
) -> str:
    """Return category bucket key for one inbound customer message."""
    text = (body or "").strip()
    if text and is_phone_like(text):
        return "reception"

    result = job.result if job and isinstance(job.result, dict) else {}
    reason = str(result.get("reason") or "").lower()

    if "phone-like reception" in reason:
        return "reception"

    if result.get("unknown_id") or "weak retrieval" in reason or reason.startswith("uncertain"):
        return "unknown"

    faq_hits = result.get("faq") or []
    if isinstance(faq_hits, list) and faq_hits:
        try:
            top_id = int((faq_hits[0] or {}).get("id") or 0)
        except (TypeError, ValueError, AttributeError):
            top_id = 0
        slug = faq_map.get(top_id)
        if slug:
            if slug == "pingo-reception":
                return "reception"
            return slug

    m = re.search(r"faq#(\d+)", reason)
    if m:
        slug = faq_map.get(int(m.group(1)))
        if slug:
            if slug == "pingo-reception":
                return "reception"
            return slug

    if "history#" in reason:
        # History-mimicked reply without a clear FAQ category.
        return "other"

    return "other"


def daily_stats(
    db: Session,
    workspace_id: UUID,
    *,
    from_day: date,
    to_day: date,
) -> list[dict[str, Any]]:
    """List daily {date, unique_people, consultations_count} inclusive."""
    if to_day < from_day:
        from_day, to_day = to_day, from_day
    # Cap range to avoid accidental huge scans
    if (to_day - from_day).days > 92:
        raise ValueError("date range too large (max 93 days)")

    zone = jakarta_tz()
    start_utc, _ = day_bounds_utc(from_day, zone)
    _, end_utc = day_bounds_utc(to_day, zone)

    rows = db.execute(
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.workspace_id == workspace_id,
            Message.direction == MessageDirection.inbound,
            Message.sender_type == MessageSenderType.customer,
            Message.created_at >= start_utc,
            Message.created_at < end_utc,
        )
        .order_by(Message.created_at.asc())
    ).all()

    # date_str -> {conv_id -> [bodies]}
    by_day: dict[str, dict[UUID, list[str]]] = defaultdict(lambda: defaultdict(list))
    conv_cache: dict[UUID, Conversation] = {}
    for msg, conv in rows:
        created = msg.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day_str = created.astimezone(zone).date().isoformat()
        by_day[day_str][conv.id].append(msg.body or "")
        conv_cache[conv.id] = conv

    out: list[dict[str, Any]] = []
    cur = from_day
    while cur <= to_day:
        day_str = cur.isoformat()
        conv_map = by_day.get(day_str, {})
        people: set[str] = set()
        for cid, bodies in conv_map.items():
            key = person_key_for_conversation(conv_cache[cid], inbound_bodies=bodies)
            if key:
                people.add(key)
        out.append(
            {
                "date": day_str,
                "unique_people": len(people),
                "consultations_count": len(conv_map),
            }
        )
        cur += timedelta(days=1)
    return out


def category_breakdown(
    db: Session,
    workspace_id: UUID,
    *,
    day: date,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    zone = jakarta_tz()
    start_utc, end_utc = day_bounds_utc(day, zone)

    rows = db.execute(
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.workspace_id == workspace_id,
            Message.direction == MessageDirection.inbound,
            Message.sender_type == MessageSenderType.customer,
            Message.created_at >= start_utc,
            Message.created_at < end_utc,
        )
        .order_by(Message.created_at.asc())
    ).all()

    msg_ids = [msg.id for msg, _ in rows]
    jobs_by_trigger: dict[UUID, AiJob] = {}
    if msg_ids:
        for job in db.scalars(
            select(AiJob).where(AiJob.trigger_message_id.in_(msg_ids))
        ).all():
            if job.trigger_message_id and job.trigger_message_id not in jobs_by_trigger:
                jobs_by_trigger[job.trigger_message_id] = job
            elif job.trigger_message_id:
                # Prefer newest non-skipped job
                prev = jobs_by_trigger[job.trigger_message_id]
                prev_skip = isinstance(prev.result, dict) and prev.result.get("skipped")
                cur_skip = isinstance(job.result, dict) and job.result.get("skipped")
                if prev_skip and not cur_skip:
                    jobs_by_trigger[job.trigger_message_id] = job
                elif job.created_at and prev.created_at and job.created_at > prev.created_at:
                    if not cur_skip or prev_skip:
                        jobs_by_trigger[job.trigger_message_id] = job

    faq_map = _faq_id_to_slug(settings)
    cats_reg = _category_registry(settings)
    counts: dict[str, int] = defaultdict(int)

    for msg, _conv in rows:
        bucket = _classify_message(msg.body or "", jobs_by_trigger.get(msg.id), faq_map)
        counts[bucket] += 1

    # Stable order: known FAQ cats by slug, then reception, unknown, other
    ordered_slugs = sorted(k for k in counts if k not in {"reception", "unknown", "other"})
    for special in ("reception", "unknown", "other"):
        if special in counts:
            ordered_slugs.append(special)

    categories = [
        {
            "key": slug,
            "label": _label_zh(slug, cats_reg),
            "count": counts[slug],
        }
        for slug in ordered_slugs
    ]
    categories.sort(key=lambda x: (-x["count"], x["label"]))

    return {
        "date": day.isoformat(),
        "timezone": TZ_NAME,
        "total_questions": sum(counts.values()),
        "categories": categories,
    }
