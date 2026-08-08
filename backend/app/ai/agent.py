from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.ai.faq import FaqHit, FaqIndex, detect_lang
from app.config import Settings

logger = logging.getLogger(__name__)

HANDOFF_PATTERNS = [
    r"人工",
    r"客服",
    r"投诉",
    r"律师",
    r"报警",
    r"hapus\s*akun",
    r"delete\s*account",
    r"human\s*agent",
    r"speak\s*to\s*(a\s*)?human",
    r"agent\s*manusia",
    r"bicara\s*dengan\s*agen",
    r"komplain",
]


@dataclass
class AgentDecision:
    action: str  # reply | handoff | skip
    reply: str
    lang: str
    faq_hits: list[FaqHit]
    reason: str


class SupportAgent:
    def __init__(self, settings: Settings, faq: FaqIndex):
        self.settings = settings
        self.faq = faq

    def decide(self, customer_text: str) -> AgentDecision:
        text = (customer_text or "").strip()
        if not text:
            return AgentDecision("skip", "", self.settings.default_reply_lang, [], "empty message")

        lang = detect_lang(text, self.settings.default_reply_lang)
        if any(re.search(p, text, flags=re.I) for p in HANDOFF_PATTERNS):
            return AgentDecision("handoff", _handoff_text(lang), lang, [], "explicit handoff request")

        hits = self.faq.search(text, lang=lang, top_k=3)
        best = hits[0] if hits else None
        if not best or best.score < self.settings.min_faq_score:
            llm = self._llm_answer(text, lang, hits)
            if llm:
                return AgentDecision("reply", llm, lang, hits, "llm answer with weak faq")
            return AgentDecision(
                "handoff",
                _handoff_text(lang),
                lang,
                hits,
                f"low faq score best={best.score if best else 0:.3f}",
            )

        answer = best.answer
        llm = self._llm_polish(text, lang, hits)
        if llm:
            answer = llm
        return AgentDecision("reply", answer, lang, hits, f"faq#{best.faq_id} score={best.score:.3f}")

    def _llm_answer(self, question: str, lang: str, hits: list[FaqHit]) -> str | None:
        if not self.settings.openai_api_key:
            return None
        context = "\n\n".join([f"Q: {h.question}\nA: {h.answer}" for h in hits if h.answer]) or "(no faq)"
        system = (
            "You are PinGo customer support. Answer ONLY from the FAQ context. "
            "If the FAQ does not contain the answer, reply with exactly HANDOFF. "
            f"Reply language: {lang}."
        )
        text = _openai_chat(self.settings, system, f"FAQ:\n{context}\n\nCustomer:\n{question}")
        if not text or text.strip().upper() == "HANDOFF":
            return None
        return text.strip()

    def _llm_polish(self, question: str, lang: str, hits: list[FaqHit]) -> str | None:
        if not self.settings.openai_api_key or not hits:
            return None
        system = (
            "You are PinGo customer support. Rewrite the FAQ answer to be concise and faithful. "
            f"Reply language: {lang}."
        )
        text = _openai_chat(self.settings, system, f"Customer: {question}\n\nFAQ:\n{hits[0].answer}")
        return text.strip() if text else None


def _openai_chat(settings: Settings, system: str, user: str) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (resp.choices[0].message.content or "").strip()


def _handoff_text(lang: str) -> str:
    if lang == "zh":
        return "已为您转接人工客服，请稍候，坐席会尽快接手处理。"
    if lang == "en":
        return "I'm connecting you to a human agent. Please wait a moment."
    return "Saya akan menghubungkan Anda ke agen manusia. Mohon tunggu sebentar."
