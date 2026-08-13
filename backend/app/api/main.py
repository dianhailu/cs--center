from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, conversations, knowledge, webhooks, ws
from app.config import get_settings
from app.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cs-api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("starting api cors=%s", settings.cors_origin_list)
    try:
        seed()
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed on startup failed: %s", exc)
    yield


app = FastAPI(title="CS Midplatform API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(ws.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "cs-midplatform-api"}
