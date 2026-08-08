from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.redis_bus import CHANNEL, get_redis, pop_memory_events
from app.security import decode_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await websocket.send_json({"type": "connected"})

    client = get_redis()
    pubsub = None
    if client is not None:
        try:
            pubsub = client.pubsub()
            pubsub.subscribe(CHANNEL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pubsub failed, memory fallback: %s", exc)
            pubsub = None

    try:
        while True:
            if pubsub is not None:
                message = await asyncio.to_thread(
                    pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message.get("type") == "message":
                    data = message.get("data")
                    try:
                        payload = json.loads(data) if isinstance(data, str) else data
                    except Exception:
                        payload = {"raw": data}
                    await websocket.send_json(payload)
            else:
                for payload in pop_memory_events():
                    await websocket.send_json(payload)
                await asyncio.sleep(0.5)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if pubsub is not None:
            try:
                pubsub.unsubscribe(CHANNEL)
                pubsub.close()
            except Exception:
                pass
