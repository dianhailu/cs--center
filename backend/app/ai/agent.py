from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.ai.faq import FaqHit, FaqIndex, detect_lang
from app.ai.history import HistoryHit, HistoryIndex
from app.ai.phone import is_phone_like, reception_reply
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
    history_hits: list[HistoryHit]
    reason: str


class SupportAgent:
    def __init__(self, settings: Settings, faq: FaqIndex, history: HistoryIndex | None = None):
        self.settings = settings
        self.faq = faq
        self.history = history or HistoryIndex(settings.history_path)

    def decide(
        self, customer_text: str, *, forced_reply_lang: str | None = None
    ) -> AgentDecision:
        text = (customer_text or "").strip()
        forced = (forced_reply_lang or "").strip().lower() or None
        if forced and forced not in {"zh", "id", "en"}:
            forced = None
        default_lang = forced or self.settings.default_reply_lang
        if not text:
            return AgentDecision("skip", "", default_lang, [], [], "empty message")

        # Product policy: customer-facing replies use forced market language.
        # Detection still helps FAQ retrieval; reply lang is overridden when forced.
        detected = detect_lang(text, default_lang)
        lang = forced or detected
        if any(re.search(p, text, flags=re.I) for p in HANDOFF_PATTERNS):
            return AgentDecision(
                "handoff",
                _explicit_handoff_text(lang),
                lang,
                [],
                [],
                "explicit handoff request",
            )

        # Phone-number-only inbound = reception greeting (never KB unknown).
        if is_phone_like(text):
            return AgentDecision(
                "reply",
                reception_reply(lang, faq_items=self.faq.items),
                lang,
                [],
                [],
                "phone-like reception greeting",
            )

        history_hits = self.history.search(text, top_k=5)
        faq_hits = self.faq.search(text, lang=detected, top_k=3)
        best_history = history_hits[0] if history_hits else None
        best_faq = faq_hits[0] if faq_hits else None

        # 1) Strong historical human reply match → mimic agent answer
        if best_history and best_history.score >= self.settings.min_history_score:
            mimicked = self._llm_mimic(text, lang, history_hits, faq_hits)
            answer = mimicked or best_history.answer
            return AgentDecision(
                "reply",
                answer,
                lang,
                faq_hits,
                history_hits,
                f"history#{best_history.pair_id} score={best_history.score:.3f}",
            )

        # 2) FAQ match
        if best_faq and best_faq.score >= self.settings.min_faq_score:
            answer = best_faq.answer
            polished = self._llm_polish(text, lang, faq_hits, history_hits)
            if polished:
                answer = polished
            return AgentDecision(
                "reply",
                answer,
                lang,
                faq_hits,
                history_hits,
                f"faq#{best_faq.faq_id} score={best_faq.score:.3f}",
            )

        # 3) Weak retrieval → LLM with history+FAQ context, else handoff wait message
        llm = self._llm_answer(text, lang, faq_hits, history_hits)
        if llm:
            return AgentDecision("reply", llm, lang, faq_hits, history_hits, "llm with weak retrieval")

        return AgentDecision(
            "handoff",
            _unrecognized_handoff_text(lang),
            lang,
            faq_hits,
            history_hits,
            f"uncertain history={best_history.score if best_history else 0:.3f} faq={best_faq.score if best_faq else 0:.3f}",
        )

    def _llm_mimic(
        self,
        question: str,
        lang: str,
        history_hits: list[HistoryHit],
        faq_hits: list[FaqHit],
    ) -> str | None:
        if not self.settings.openai_api_key or not history_hits:
            return None
        examples = "\n\n".join(
            [f"Customer: {h.question}\nAgent: {h.answer}" for h in history_hits[:4] if h.answer]
        )
        faq_bits = "\n".join([f"- {h.answer}" for h in faq_hits[:2] if h.answer])
        system = (
            "You are PinGo CS (human customer support style). "
            "Reply like the Agent examples: short, polite, practical Bahasa/Chinese/English matching the customer. "
            "Do not invent policies not present in examples/FAQ. "
            "If examples/FAQ cannot answer, reply exactly HANDOFF. "
            f"Reply language: {lang}."
        )
        user = f"Examples:\n{examples}\n\nFAQ hints:\n{faq_bits or '(none)'}\n\nNew customer:\n{question}"
        text = _openai_chat(self.settings, system, user)
        if not text or text.strip().upper() == "HANDOFF":
            return None
        return text.strip()

    def _llm_answer(
        self,
        question: str,
        lang: str,
        hits: list[FaqHit],
        history_hits: list[HistoryHit],
    ) -> str | None:
        if not self.settings.openai_api_key:
            return None
        faq_ctx = "\n\n".join([f"Q: {h.question}\nA: {h.answer}" for h in hits if h.answer]) or "(no faq)"
        hist_ctx = "\n\n".join(
            [f"Customer: {h.question}\nAgent: {h.answer}" for h in history_hits[:4] if h.answer]
        ) or "(no history)"
        system = (
            "You are PinGo CS. Prefer mimicking historical Agent replies. "
            "Use FAQ only as supporting facts. "
            "If you cannot answer confidently, reply exactly HANDOFF. "
            f"Reply language: {lang}."
        )
        text = _openai_chat(
            self.settings,
            system,
            f"History examples:\n{hist_ctx}\n\nFAQ:\n{faq_ctx}\n\nCustomer:\n{question}",
        )
        if not text or text.strip().upper() == "HANDOFF":
            return None
        return text.strip()

    def _llm_polish(
        self,
        question: str,
        lang: str,
        hits: list[FaqHit],
        history_hits: list[HistoryHit],
    ) -> str | None:
        if not self.settings.openai_api_key or not hits:
            return None
        style = history_hits[0].answer if history_hits else ""
        system = (
            "You are PinGo CS. Rewrite the FAQ answer in the tone of a human PinGo agent. "
            "Keep facts faithful; be concise. "
            f"Reply language: {lang}."
        )
        user = f"Customer: {question}\n\nFAQ answer:\n{hits[0].answer}\n\nStyle example:\n{style or '(none)'}"
        text = _openai_chat(self.settings, system, user)
        return text.strip() if text else None


def _openai_chat(settings: Settings, system: str, user: str) -> str | None:
    try:
        from app.ai.openai_client import make_openai_client

        client = make_openai_client(settings)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.3,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    except ImportError:
        return None
    return (resp.choices[0].message.content or "").strip()


def _explicit_handoff_text(lang: str) -> str:
    """Customer explicitly asked for a human (keep distinct from unrecognized path)."""
    if lang == "zh":
        return "好的，已为您转接人工客服，请稍候。"
    if lang == "en":
        return "Sure — I've connected you to a human agent. Please wait a moment."
    return "Baik, kami sedang menghubungkan Anda ke agen manusia. Mohon menunggu sebentar."


def _unrecognized_handoff_text(lang: str) -> str:
    """Low-confidence / unrecognized question → waiting-for-human script (forced product lang)."""
    if lang == "zh":
        return "您的问题需要人工服务，已帮您找空闲客服，请耐心等待"
    if lang == "en":
        return (
            "Your question needs a human agent. "
            "We've found an available agent for you — please wait patiently."
        )
    # PinGo default forced reply lang = id
    return (
        "Pertanyaan Anda perlu ditangani oleh agen manusia. "
        "Kami sudah mencarikan agen yang tersedia, mohon menunggu dengan sabar."
    )


def _handoff_text(lang: str) -> str:
    """Backward-compatible alias (unrecognized waiting script)."""
    return _unrecognized_handoff_text(lang)
