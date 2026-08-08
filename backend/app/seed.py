from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine, Base
from app.models import (
    AgentUser,
    ChannelConnection,
    Membership,
    Organization,
    Workspace,
)
from app.security import hash_password

logger = logging.getLogger(__name__)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def seed() -> None:
    settings = get_settings()
    init_db()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.name == "PinGo"))
        if not org:
            org = Organization(name="PinGo")
            db.add(org)
            db.flush()

        ws = db.scalar(
            select(Workspace).where(
                Workspace.organization_id == org.id,
                Workspace.product_code == "pingo",
                Workspace.country_code == "id",
            )
        )
        if not ws:
            ws = Workspace(
                organization_id=org.id,
                name="PinGo Indonesia",
                product_code="pingo",
                country_code="id",
            )
            db.add(ws)
            db.flush()

        conn = db.scalar(
            select(ChannelConnection).where(
                ChannelConnection.workspace_id == ws.id,
                ChannelConnection.provider == "liveagent",
            )
        )
        if not conn:
            conn = ChannelConnection(
                workspace_id=ws.id,
                provider="liveagent",
                name="pingo-ladesk",
                base_url=settings.liveagent_base_url,
                api_v3_key=settings.liveagent_api_v3_key,
                api_v1_key=settings.liveagent_api_v1_key,
                agent_email=settings.liveagent_agent_email,
                dry_run=settings.liveagent_dry_run,
                webhook_secret=settings.webhook_secret,
            )
            db.add(conn)
        else:
            # refresh credentials from env on seed
            conn.base_url = settings.liveagent_base_url
            conn.api_v3_key = settings.liveagent_api_v3_key or conn.api_v3_key
            conn.api_v1_key = settings.liveagent_api_v1_key or conn.api_v1_key
            conn.agent_email = settings.liveagent_agent_email or conn.agent_email
            conn.dry_run = settings.liveagent_dry_run
            conn.webhook_secret = settings.webhook_secret

        agent = db.scalar(select(AgentUser).where(AgentUser.email == settings.seed_agent_email))
        if not agent:
            agent = AgentUser(
                email=settings.seed_agent_email,
                name="PinGo Agent",
                password_hash=hash_password(settings.seed_agent_password),
            )
            db.add(agent)
            db.flush()

        membership = db.scalar(
            select(Membership).where(
                Membership.agent_id == agent.id,
                Membership.workspace_id == ws.id,
            )
        )
        if not membership:
            db.add(Membership(agent_id=agent.id, workspace_id=ws.id, role="admin"))

        db.commit()
        logger.info(
            "seeded org=%s workspace=%s connection=%s agent=%s",
            org.id,
            ws.id,
            conn.id,
            agent.email,
        )
        print(f"SEED_WORKSPACE_ID={ws.id}")
        print(f"SEED_CONNECTION_ID={conn.id}")
        print(f"SEED_AGENT_EMAIL={agent.email}")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
