from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(*, agent_id: UUID, email: str, workspace_id: UUID, expires_hours: int = 24) -> str:
    settings = get_settings()
    payload = {
        "sub": str(agent_id),
        "email": email,
        "workspace_id": str(workspace_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
