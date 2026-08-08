from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Any
from uuid import UUID

from app.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL = "cs:events"

_memory_lock = threading.Lock()
_memory_queue: deque[str] = deque(maxlen=1000)
_redis_client = None
_redis_ok: bool | None = None


def get_redis():
    global _redis_client, _redis_ok
    if _redis_ok is False:
        return None
    try:
        import redis

        if _redis_client is None:
            _redis_client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
            _redis_client.ping()
            _redis_ok = True
        return _redis_client
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis unavailable, using memory bus: %s", exc)
        _redis_ok = False
        _redis_client = None
        return None


def publish_event(event_type: str, payload: dict[str, Any]) -> None:
    raw = json.dumps({"type": event_type, "payload": payload}, default=str)
    client = get_redis()
    if client is not None:
        try:
            client.publish(CHANNEL, raw)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis publish failed: %s", exc)
    with _memory_lock:
        _memory_queue.append(raw)


def pop_memory_events(max_items: int = 50) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with _memory_lock:
        for _ in range(min(max_items, len(_memory_queue))):
            raw = _memory_queue.popleft()
            try:
                items.append(json.loads(raw))
            except Exception:
                items.append({"raw": raw})
    return items


def conversation_event(conversation_id: UUID, event_type: str, extra: dict[str, Any] | None = None) -> None:
    body = {"conversation_id": str(conversation_id)}
    if extra:
        body.update(extra)
    publish_event(event_type, body)
