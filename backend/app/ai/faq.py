from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    return [t for t in _TOKEN_RE.findall(text) if len(t) > 1]


@dataclass
class FaqHit:
    faq_id: int
    score: float
    question: str
    answer: str
    lang: str
    category: str


class FaqIndex:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict] = []
        self._docs: list[dict] = []
        self._idf: dict[str, float] = {}
        self.mtime: float = 0.0
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.items = []
            self._docs = []
            self._idf = {}
            self.mtime = 0.0
            return
        self.mtime = self.path.stat().st_mtime
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.items = raw if isinstance(raw, list) else []
        self._docs = []
        for item in self.items:
            bag = " ".join(
                [
                    item.get("question", {}).get("id", "") or "",
                    item.get("question", {}).get("en", "") or "",
                    item.get("question", {}).get("zh", "") or "",
                    item.get("answer", {}).get("id", "") or "",
                    item.get("answer", {}).get("en", "") or "",
                    item.get("answer", {}).get("zh", "") or "",
                    (item.get("category") or {}).get("id", "") or "",
                    (item.get("category") or {}).get("en", "") or "",
                    (item.get("category") or {}).get("zh", "") or "",
                ]
            )
            tokens = tokenize(bag)
            self._docs.append({"item": item, "tokens": tokens, "tf": _tf(tokens)})

        df: dict[str, int] = {}
        for doc in self._docs:
            for t in set(doc["tokens"]):
                df[t] = df.get(t, 0) + 1
        n = max(len(self._docs), 1)
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}

    def maybe_reload(self) -> None:
        if not self.path.exists():
            if self.items:
                self.reload()
            return
        mtime = self.path.stat().st_mtime
        if mtime != self.mtime:
            self.reload()

    def search(self, query: str, lang: str = "id", top_k: int = 3) -> list[FaqHit]:
        self.maybe_reload()
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        q_tf = _tf(q_tokens)
        scored: list[FaqHit] = []
        for doc in self._docs:
            score = _cosine(q_tf, doc["tf"], self._idf)
            # light boost for literal substring hits
            item = doc["item"]
            q_zh = item.get("question", {}).get("zh", "") or ""
            q_id = item.get("question", {}).get("id", "") or ""
            q_en = item.get("question", {}).get("en", "") or ""
            ql = query.lower()
            if ql and (ql in q_zh.lower() or ql in q_id.lower() or ql in q_en.lower()):
                score += 0.35
            if score <= 0:
                continue
            lang_key = _lang_key(lang)
            scored.append(
                FaqHit(
                    faq_id=int(item.get("id") or 0),
                    score=score,
                    question=item.get("question", {}).get(lang_key)
                    or item.get("question", {}).get("id")
                    or item.get("question", {}).get("zh")
                    or "",
                    answer=item.get("answer", {}).get(lang_key)
                    or item.get("answer", {}).get("id")
                    or item.get("answer", {}).get("zh")
                    or "",
                    lang=lang_key,
                    category=(item.get("category") or {}).get(lang_key)
                    or (item.get("category") or {}).get("id")
                    or "",
                )
            )
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


def detect_lang(text: str, default: str = "id") -> str:
    raw = text or ""
    if re.search(r"[\u4e00-\u9fff]", raw):
        return "zh"
    lower = raw.lower()
    en_hits = len(
        re.findall(
            r"\b(the|is|are|what|how|can|please|my|account|want|talk|human|agent|loan|register)\b",
            lower,
        )
    )
    id_hits = len(
        re.findall(
            r"\b(apa|bagaimana|saya|pinjaman|akun|cara|tidak|bisa|yang|dengan|untuk|apakah)\b",
            lower,
        )
    )
    if en_hits > id_hits and en_hits >= 1:
        return "en"
    if id_hits >= 1:
        return "id"
    return default


def _lang_key(lang: str) -> str:
    lang = (lang or "id").lower()
    if lang.startswith("zh") or lang in {"cn", "chinese"}:
        return "zh"
    if lang.startswith("en"):
        return "en"
    return "id"


def _tf(tokens: list[str]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0
    n = float(len(tokens) or 1)
    return {k: v / n for k, v in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float], idf: dict[str, float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for k in keys:
        wa = a.get(k, 0.0) * idf.get(k, 1.0)
        wb = b.get(k, 0.0) * idf.get(k, 1.0)
        dot += wa * wb
        na += wa * wa
        nb += wb * wb
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
