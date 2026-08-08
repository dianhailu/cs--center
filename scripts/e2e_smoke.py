#!/usr/bin/env python3
"""End-to-end smoke against local API + LiveAgent (dry-run safe)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import ChannelConnection  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services.inbound import import_ticket, poll_connection  # noqa: E402
from sqlalchemy import select  # noqa: E402

API = os.environ.get("API_BASE", "http://127.0.0.1:8080")


def http(method: str, path: str, body: dict | None = None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def main() -> int:
    settings = get_settings()
    print("seed…")
    seed()
    db = SessionLocal()
    try:
        conn = db.scalar(select(ChannelConnection).where(ChannelConnection.provider == "liveagent"))
        if not conn:
            print("no connection", file=sys.stderr)
            return 1
        print("connection", conn.id, conn.base_url, "dry_run", conn.dry_run)

        health = http("GET", "/health")
        print("health", health)

        login = http(
            "POST",
            "/api/auth/login",
            {"email": settings.seed_agent_email, "password": settings.seed_agent_password},
        )
        token = login["access_token"]
        print("login ok", login["workspace_name"])

        if not conn.api_v3_key:
            print("missing API key; skip LA poll")
            return 0

        imported = poll_connection(db, conn, limit=10)
        print("poll imported messages", imported)

        # webhook path simulation using first conversation external id if any
        from app.models import Conversation

        conv = db.scalar(select(Conversation).limit(1))
        if conv:
            req = urllib.request.Request(
                f"{API}/api/webhooks/liveagent/{conn.id}",
                data=json.dumps({"ticket_id": conv.external_id, "event": "smoke"}).encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Secret": conn.webhook_secret,
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                print("webhook", json.loads(resp.read().decode()))

        inbox = http("GET", "/api/conversations?queue=human", token=token)
        print("human queue", len(inbox))
        all_open = http("GET", "/api/conversations", token=token)
        print("all conversations", len(all_open))
        if all_open:
            detail = http("GET", f"/api/conversations/{all_open[0]['id']}", token=token)
            print("detail messages", len(detail.get("messages") or []), detail.get("subject"))
        print("SMOKE_OK")
        return 0
    except urllib.error.URLError as exc:
        print("API not reachable. Start uvicorn first:", exc, file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
