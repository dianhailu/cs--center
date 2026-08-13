"""Unit tests for phone-like detection and reception greeting routing."""

from __future__ import annotations

from pathlib import Path

from app.ai.agent import SupportAgent
from app.ai.faq import FaqIndex
from app.ai.history import HistoryIndex
from app.ai.phone import is_phone_like, reception_reply
from app.ai.unknown import append_unknown
from app.config import Settings


def test_is_phone_like_positive() -> None:
    assert is_phone_like("081234567890")
    assert is_phone_like("+62 812-3456-7890")
    assert is_phone_like("Phone: 0812 3456 7890")
    assert is_phone_like("phone：081234567890")
    assert is_phone_like("62-812-3456-7890")
    assert is_phone_like("  08-1234-5678  ")


def test_is_phone_like_negative() -> None:
    assert not is_phone_like("")
    assert not is_phone_like("123")  # too short
    assert not is_phone_like("Saya butuh bantuan pinjaman 081234567890")
    assert not is_phone_like("How do I change my phone number?")
    assert not is_phone_like("OTP tidak masuk ke HP saya")
    assert not is_phone_like("halo kak")


def test_reception_reply_prefers_faq() -> None:
    items = [
        {
            "code": "pingo-reception--01",
            "answer": {
                "id": "FAQ-ID",
                "zh": "FAQ-ZH",
                "en": "FAQ-EN",
            },
        }
    ]
    assert reception_reply("id", faq_items=items) == "FAQ-ID"
    assert reception_reply("zh", faq_items=items) == "FAQ-ZH"
    assert "PinGo" in reception_reply("id")


def test_agent_phone_like_reception(tmp_path: Path) -> None:
    faq_path = tmp_path / "faq.json"
    faq_path.write_text("[]", encoding="utf-8")
    hist_path = tmp_path / "history_pairs.json"
    hist_path.write_text("[]", encoding="utf-8")
    settings = Settings(
        faq_path=faq_path,
        history_path=hist_path,
        openai_api_key="",
        default_reply_lang="id",
    )
    agent = SupportAgent(settings, FaqIndex(faq_path), HistoryIndex(hist_path))
    d = agent.decide("081234567890")
    assert d.action == "reply"
    assert "phone-like" in d.reason
    assert "PinGo" in d.reply
    assert not append_unknown(tmp_path / "unknown_questions.jsonl", question="081234567890")
