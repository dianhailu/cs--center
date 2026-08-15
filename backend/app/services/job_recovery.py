"""Requeue or complete worker jobs stuck in ``processing`` after a crash/restart."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiJob, Message, MessageSendStatus, OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)

# Default: anything still "processing" after this age was abandoned mid-flight.
DEFAULT_STALE_MINUTES = 15


def recover_stale_jobs(db: Session, *, older_than_minutes: int = DEFAULT_STALE_MINUTES) -> dict[str, int]:
    """Safely clear stuck ``processing`` outbox / AI jobs older than N minutes.

    Outbox:
      - message already ``sent`` → mark outbox ``done`` (avoid duplicate send)
      - otherwise → ``pending`` for retry
    AI jobs:
      - mark ``done`` with skipped reason (avoid duplicate AI replies on old triggers)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(older_than_minutes)))
    outbox_done = 0
    outbox_requeued = 0
    ai_completed = 0

    stuck_outbox = list(
        db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.status == OutboxStatus.processing,
                OutboxEvent.updated_at < cutoff,
            )
        )
    )
    for event in stuck_outbox:
        msg = db.get(Message, event.message_id)
        if msg and msg.send_status == MessageSendStatus.sent:
            event.status = OutboxStatus.done
            event.last_error = None
            outbox_done += 1
        else:
            event.status = OutboxStatus.pending
            event.last_error = (event.last_error or "")[:500]
            if not (event.last_error or "").startswith("stale_processing"):
                event.last_error = f"stale_processing_requeued after {older_than_minutes}m"
            outbox_requeued += 1
        event.updated_at = datetime.now(timezone.utc)

    stuck_ai = list(
        db.scalars(
            select(AiJob).where(
                AiJob.status == "processing",
                AiJob.updated_at < cutoff,
            )
        )
    )
    for job in stuck_ai:
        job.status = "done"
        job.result = {
            **(job.result or {}),
            "skipped": "stale_processing_recovered",
            "recovered_after_minutes": older_than_minutes,
        }
        job.updated_at = datetime.now(timezone.utc)
        ai_completed += 1

    if outbox_done or outbox_requeued or ai_completed:
        db.commit()
        logger.info(
            "recovered stale jobs outbox_done=%s outbox_requeued=%s ai_completed=%s cutoff=%s",
            outbox_done,
            outbox_requeued,
            ai_completed,
            cutoff.isoformat(),
        )
    return {
        "outbox_done": outbox_done,
        "outbox_requeued": outbox_requeued,
        "ai_completed": ai_completed,
    }
