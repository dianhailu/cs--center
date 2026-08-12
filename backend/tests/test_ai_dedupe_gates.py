"""Unit tests for AI-first / human-skip gates and body normalization."""

from __future__ import annotations

from app.channels.liveagent import LiveAgentClient
from app.services.ai_loop import normalize_body


def test_normalize_body_collapses_whitespace():
    assert normalize_body("  a\n\tb  ") == "a b"
    assert normalize_body(None) == ""


def test_classify_sender_marks_known_ai_echo_not_agent():
    item = {
        "body": "Silakan  menunggu  sebentar, PinGo CS akan segera membantu Anda.",
        "userid": "agent-user-1",
        "user_email": "agent@example.com",
        "user_name": "PinGo CS",
    }
    known = {
        normalize_body(
            "Silakan menunggu sebentar, PinGo CS akan segera membantu Anda."
        )
    }
    direction, sender = LiveAgentClient.classify_sender(
        item,
        agent_user_ids={"agent-user-1"},
        agent_emails={"agent@example.com"},
        agent_names={"pingo cs"},
        agent_email="agent@example.com",
        known_ai_bodies=known,
    )
    assert direction == "outbound"
    assert sender == "ai"


def test_classify_sender_human_agent_when_not_ai_body():
    item = {
        "body": "Baik, saya bantu cek ya.",
        "userid": "agent-user-1",
        "user_email": "agent@example.com",
        "user_name": "PinGo CS",
    }
    direction, sender = LiveAgentClient.classify_sender(
        item,
        agent_user_ids={"agent-user-1"},
        agent_emails={"agent@example.com"},
        agent_names={"pingo cs"},
        agent_email="agent@example.com",
        known_ai_bodies=set(),
    )
    assert direction == "outbound"
    assert sender == "agent"
