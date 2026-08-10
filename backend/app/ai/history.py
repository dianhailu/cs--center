from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.ai.faq import _cosine, _tf, tokenize


@dataclass
class HistoryHit:
    pair_id: int
    score: float
    question: str
    answer: str
    lang: str


class HistoryIndex:
    """TF-IDF index over mined customer→agent reply pairs."""

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
            q = str(item.get("question") or "")
            a = str(item.get("answer") or "")
            tokens = tokenize(f"{q} {a}")
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

    def search(self, query: str, top_k: int = 5) -> list[HistoryHit]:
        self.maybe_reload()
        q_tokens = tokenize(query)
        if not q_tokens or not self._docs:
            return []
        q_tf = _tf(q_tokens)
        scored: list[HistoryHit] = []
        ql = query.lower().strip()
        for doc in self._docs:
            score = _cosine(q_tf, doc["tf"], self._idf)
            item = doc["item"]
            q = str(item.get("question") or "")
            if ql and ql in q.lower():
                score += 0.35
            if score <= 0:
                continue
            scored.append(
                HistoryHit(
                    pair_id=int(item.get("id") or 0),
                    score=score,
                    question=q,
                    answer=str(item.get("answer") or ""),
                    lang=str(item.get("lang") or "id"),
                )
            )
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]
