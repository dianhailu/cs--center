"""AI_SEND_TO_CUSTOMER gate: local Smart bubbles, no outbox when false."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models import MessageSenderType, MessageSendStatus, OutboxEvent
from app.services.conversations import send_outbound_message


def _fake_conv():
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        channel_connection_id=uuid4(),
        status="queued",
        assignee_id=None,
        last_message_at=None,
    )


def test_ai_reply_skipped_when_send_to_customer_false():
    db = MagicMock()
    conv = _fake_conv()
    settings = SimpleNamespace(ai_send_to_customer=False)

    with (
        patch("app.services.conversations.get_settings", return_value=settings),
        patch("app.services.conversations.conversation_event"),
    ):
        msg = send_outbound_message(
            db,
            conv,
            body="preview reply",
            sender_type=MessageSenderType.ai,
        )

    assert msg.send_status == MessageSendStatus.local_only
    assert (msg.meta or {}).get("deliver") == "skipped"
    # No OutboxEvent queued
    added = [c.args[0] for c in db.add.call_args_list]
    assert not any(isinstance(x, OutboxEvent) for x in added)


def test_ai_reply_queued_when_send_to_customer_true():
    db = MagicMock()
    conv = _fake_conv()
    settings = SimpleNamespace(ai_send_to_customer=True)

    with (
        patch("app.services.conversations.get_settings", return_value=settings),
        patch("app.services.conversations.conversation_event"),
    ):
        msg = send_outbound_message(
            db,
            conv,
            body="live reply",
            sender_type=MessageSenderType.ai,
        )

    assert msg.send_status == MessageSendStatus.pending
    added = [c.args[0] for c in db.add.call_args_list]
    assert any(isinstance(x, OutboxEvent) for x in added)


def test_agent_reply_still_delivers_when_ai_gate_off():
    db = MagicMock()
    conv = _fake_conv()
    settings = SimpleNamespace(ai_send_to_customer=False)

    with (
        patch("app.services.conversations.get_settings", return_value=settings),
        patch("app.services.conversations.conversation_event"),
    ):
        msg = send_outbound_message(
            db,
            conv,
            body="human reply",
            sender_type=MessageSenderType.agent,
            sender_id=uuid4(),
        )

    assert msg.send_status == MessageSendStatus.pending
    added = [c.args[0] for c in db.add.call_args_list]
    assert any(isinstance(x, OutboxEvent) for x in added)
