from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_db
from app.models import ROLE_SYSTEM_ADMIN, AgentUser
from app.rbac import (
    agent_country_codes,
    agent_product_codes,
    assert_workspace_access,
    resolve_customer_reply_lang,
)
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    agent: AgentUser
    workspace_id: UUID
    role: str
    product_codes: list[str] = field(default_factory=list)
    country_codes: list[str] = field(default_factory=list)
    product_code: str | None = None
    country_code: str | None = None
    customer_reply_lang: str = "id"


def _load_agent(db: Session, agent_id: UUID) -> AgentUser | None:
    return db.scalar(
        select(AgentUser)
        .where(AgentUser.id == agent_id)
        .options(
            selectinload(AgentUser.products),
            selectinload(AgentUser.countries),
        )
    )


def get_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not creds:
        raise HTTPException(401, "missing token")
    try:
        payload = decode_token(creds.credentials)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, "invalid token") from exc
    agent_id = UUID(payload["sub"])
    workspace_id = UUID(payload["workspace_id"])
    agent = _load_agent(db, agent_id)
    if not agent or not agent.is_active:
        raise HTTPException(401, "agent inactive")

    ws = assert_workspace_access(db, agent, workspace_id)
    role = agent.role or str(payload.get("role") or "agent")
    if role == ROLE_SYSTEM_ADMIN:
        product_codes = list(payload.get("product_codes") or [])
        country_codes = list(payload.get("country_codes") or [])
    else:
        product_codes = agent_product_codes(agent)
        country_codes = agent_country_codes(agent)

    settings = get_settings()
    reply_lang = resolve_customer_reply_lang(
        db, ws.product_code, fallback=settings.default_reply_lang or "id"
    )
    return AuthContext(
        agent=agent,
        workspace_id=workspace_id,
        role=role,
        product_codes=product_codes,
        country_codes=country_codes,
        product_code=ws.product_code,
        country_code=ws.country_code,
        customer_reply_lang=reply_lang,
    )


def verify_webhook_secret(
    expected: str,
    x_webhook_secret: str | None = Header(default=None),
) -> None:
    if expected and x_webhook_secret != expected:
        raise HTTPException(401, "invalid webhook secret")
