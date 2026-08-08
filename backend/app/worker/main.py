from __future__ import annotations

import logging
import time

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import ChannelConnection
from app.seed import seed
from app.services.ai_loop import process_ai_jobs
from app.services.inbound import poll_connection
from app.services.outbox import process_outbox_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cs-worker")


def run() -> None:
    settings = get_settings()
    logger.info("worker starting dry_run=%s ai=%s", settings.liveagent_dry_run, settings.ai_enabled)
    try:
        seed()
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed failed: %s", exc)

    poll_every = 30
    ticks = 0
    while True:
        db = SessionLocal()
        try:
            outbox_n = process_outbox_batch(db, limit=30)
            ai_n = process_ai_jobs(db, limit=20)
            if outbox_n or ai_n:
                logger.info("processed outbox=%s ai=%s", outbox_n, ai_n)
            ticks += 1
            if ticks % poll_every == 0:
                conns = list(db.scalars(select(ChannelConnection).where(ChannelConnection.provider == "liveagent")))
                for conn in conns:
                    if not conn.api_v3_key:
                        continue
                    imported = poll_connection(db, conn, limit=20)
                    if imported:
                        logger.info("poll connection=%s imported=%s", conn.id, imported)
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker loop error: %s", exc)
        finally:
            db.close()
        time.sleep(1)


if __name__ == "__main__":
    run()
