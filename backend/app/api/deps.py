from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AgentUser, Membership
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    agent: AgentUser
    workspace_id: UUID
    role: str


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
    agent = db.get(AgentUser, agent_id)
    if not agent or not agent.is_active:
        raise HTTPException(401, "agent inactive")
    membership = db.scalar(
        select(Membership).where(
            Membership.agent_id == agent.id,
            Membership.workspace_id == workspace_id,
        )
    )
    if not membership:
        raise HTTPException(403, "no workspace access")
    return AuthContext(agent=agent, workspace_id=workspace_id, role=membership.role)


def verify_webhook_secret(
    expected: str,
    x_webhook_secret: str | None = Header(default=None),
) -> None:
    if expected and x_webhook_secret != expected:
        raise HTTPException(401, "invalid webhook secret")
