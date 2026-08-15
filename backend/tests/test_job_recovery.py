"""Unit checks for stale processing job recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from app.models import MessageSendStatus, OutboxStatus
from app.services.job_recovery import recover_stale_jobs


def test_recover_stale_outbox_sent_marks_done() -> None:
    now = datetime.now(timezone.utc)
    event = MagicMock()
    event.status = OutboxStatus.processing
    event.updated_at = now - timedelta(minutes=30)
    event.message_id = uuid4()
    event.last_error = None

    msg = MagicMock()
    msg.send_status = MessageSendStatus.sent

    db = MagicMock()
    db.scalars.return_value = [event]
    # First call: outbox; second: ai jobs empty
    db.scalars.side_effect = [[event], []]
    db.get.return_value = msg

    stats = recover_stale_jobs(db, older_than_minutes=15)
    assert stats["outbox_done"] == 1
    assert event.status == OutboxStatus.done
    db.commit.assert_called_once()


def test_recover_stale_outbox_unsent_requeues() -> None:
    now = datetime.now(timezone.utc)
    event = MagicMock()
    event.status = OutboxStatus.processing
    event.updated_at = now - timedelta(minutes=30)
    event.message_id = uuid4()
    event.last_error = None

    msg = MagicMock()
    msg.send_status = MessageSendStatus.pending

    db = MagicMock()
    db.scalars.side_effect = [[event], []]
    db.get.return_value = msg

    stats = recover_stale_jobs(db, older_than_minutes=15)
    assert stats["outbox_requeued"] == 1
    assert event.status == OutboxStatus.pending


def test_recover_stale_ai_jobs_complete() -> None:
    now = datetime.now(timezone.utc)
    job = MagicMock()
    job.status = "processing"
    job.updated_at = now - timedelta(minutes=40)
    job.result = {}

    db = MagicMock()
    db.scalars.side_effect = [[], [job]]

    stats = recover_stale_jobs(db, older_than_minutes=15)
    assert stats["ai_completed"] == 1
    assert job.status == "done"
    assert job.result["skipped"] == "stale_processing_recovered"
