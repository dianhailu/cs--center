from __future__ import annotations

import logging
import time

from sqlalchemy import select

from app.ai.learn_history import build_history_pairs, needs_initial_learn, should_run_nightly_learn
from app.config import get_settings
from app.db import SessionLocal
from app.models import ChannelConnection
from app.seed import seed
from app.services.ai_loop import process_ai_jobs
from app.services.inbound import poll_connection
from app.services.outbox import process_outbox_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cs-worker")


def _maybe_learn(*, force_initial: bool = False) -> None:
    """Run initial full learn and/or scheduled evening rebuild when due."""
    settings = get_settings()
    if not settings.history_learn_enabled:
        return
    run_initial = force_initial or needs_initial_learn(settings)
    run_nightly = should_run_nightly_learn(settings)
    if not run_initial and not run_nightly:
        return
    reason = "initial" if run_initial else "evening"
    logger.info(
        "history learn start reason=%s hour=%02d tz=%s",
        reason,
        settings.history_learn_hour,
        settings.history_learn_timezone,
    )
    db = SessionLocal()
    try:
        stamp = build_history_pairs(db, settings)
        logger.info(
            "history learn finished reason=%s pairs=%s conversations_scanned=%s built_at=%s",
            reason,
            stamp.get("pairs"),
            stamp.get("conversations_scanned"),
            stamp.get("built_at"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("history learn failed: %s", exc)
    finally:
        db.close()


def run() -> None:
    settings = get_settings()
    logger.info(
        "worker starting dry_run=%s ai=%s learn=%s@%02d:00 %s",
        settings.liveagent_dry_run,
        settings.ai_enabled,
        settings.history_learn_enabled,
        settings.history_learn_hour,
        settings.history_learn_timezone,
    )
    try:
        seed()
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed failed: %s", exc)

    # First boot / empty knowledge: full learn from all historical chats in DB
    try:
        _maybe_learn(force_initial=needs_initial_learn(settings))
    except Exception as exc:  # noqa: BLE001
        logger.warning("initial history learn skipped: %s", exc)

    poll_every = 30
    learn_every = 60  # check schedule about once per minute
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
            if ticks % learn_every == 0:
                _maybe_learn(force_initial=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker loop error: %s", exc)
        finally:
            db.close()
        time.sleep(1)


if __name__ == "__main__":
    run()
