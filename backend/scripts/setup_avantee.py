#!/usr/bin/env python3
"""Idempotent Avantee product + LiveAgent channel setup (no password reset)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import get_settings
from app.db import SessionLocal
from app.product_setup import avantee_spec_from_settings, ensure_product_channel


def main() -> int:
    settings = get_settings()
    spec = avantee_spec_from_settings(settings)
    if not spec:
        print(
            "Missing AVANTEE_* env vars (need BASE_URL, API keys, AGENT_EMAIL)",
            file=sys.stderr,
        )
        return 1

    with SessionLocal() as db:
        product, ws, conn = ensure_product_channel(db, spec)
        db.commit()
        print(f"product={product.code} name={product.name} lang={product.customer_reply_lang}")
        print(f"workspace_id={ws.id} workspace={ws.name}")
        print(f"connection_id={conn.id} base_url={conn.base_url} agent={conn.agent_email}")
        print(
            f"webhook_url=https://cs-api.originmount.com/api/webhooks/liveagent/{conn.id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
