from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session, selectinload

from app.ai.kb_store import load_faq_raw, save_faq_raw
from app.config import get_settings
from app.db import SessionLocal, engine, Base
from app.models import (
    ROLE_AGENT,
    ROLE_SYSTEM_ADMIN,
    AgentUser,
    ChannelConnection,
    Country,
    Membership,
    Organization,
    Product,
    Workspace,
)
from app.product_setup import avantee_spec_from_settings, ensure_product_channel
from app.rbac import normalize_country, normalize_product
from app.security import hash_password

logger = logging.getLogger(__name__)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """Add columns introduced after initial create_all (SQLite / Postgres)."""
    insp = inspect(engine)
    if "agent_users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("agent_users")}
    with engine.begin() as conn:
        if "role" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE agent_users ADD COLUMN role VARCHAR(32) "
                    f"NOT NULL DEFAULT '{ROLE_AGENT}'"
                )
            )
            logger.info("migrated agent_users.role")


def _backfill_faq_product_code(faq_path: Path, product_code: str) -> None:
    if not faq_path.exists():
        return
    items = load_faq_raw(faq_path)
    changed = False
    for item in items:
        if not str(item.get("product_code") or "").strip():
            item["product_code"] = product_code
            changed = True
    if changed:
        save_faq_raw(faq_path, items)
        logger.info("backfilled product_code=%s on %s FAQ rows", product_code, len(items))


def _set_agent_grants(
    db: Session,
    agent: AgentUser,
    *,
    role: str,
    products: list[Product],
    countries: list[Country],
) -> None:
    agent.role = role
    agent.products = list(products)
    agent.countries = list(countries)


def _ensure_membership(db: Session, agent: AgentUser, workspace: Workspace, role: str) -> None:
    membership = db.scalar(
        select(Membership).where(
            Membership.agent_id == agent.id,
            Membership.workspace_id == workspace.id,
        )
    )
    if not membership:
        db.add(Membership(agent_id=agent.id, workspace_id=workspace.id, role=role))
    else:
        membership.role = role


def seed() -> None:
    settings = get_settings()
    init_db()
    product_code = normalize_product(settings.default_product_code or "pingo")
    country_code = normalize_country(settings.default_country_code or "ID")
    db = SessionLocal()
    try:
        # --- Catalog ---
        country = db.get(Country, country_code)
        if not country:
            country = Country(
                code=country_code,
                name_zh="印尼",
                name_en="Indonesia",
                name_local="Indonesia",
            )
            db.add(country)
            db.flush()

        product = db.get(Product, product_code)
        if not product:
            product = Product(
                code=product_code,
                name="PinGo",
                customer_reply_lang=(settings.default_reply_lang or "id").lower(),
                default_country_code=country_code,
            )
            db.add(product)
            db.flush()
        else:
            if not product.customer_reply_lang:
                product.customer_reply_lang = (settings.default_reply_lang or "id").lower()
            if not product.default_country_code:
                product.default_country_code = country_code

        if country not in (product.countries or []):
            product.countries = list({*(product.countries or []), country})

        org = db.scalar(select(Organization).where(Organization.name == "PinGo"))
        if not org:
            org = Organization(name="PinGo")
            db.add(org)
            db.flush()

        # Normalize legacy lowercase country on workspaces
        for ws_row in db.scalars(select(Workspace)).all():
            norm = normalize_country(ws_row.country_code)
            if ws_row.country_code != norm:
                ws_row.country_code = norm
            pc = normalize_product(ws_row.product_code)
            if ws_row.product_code != pc:
                ws_row.product_code = pc

        ws = db.scalar(
            select(Workspace).where(
                Workspace.organization_id == org.id,
                Workspace.product_code == product_code,
                Workspace.country_code == country_code,
            )
        )
        # Also match legacy lowercase country workspace
        if not ws:
            ws = db.scalar(
                select(Workspace).where(
                    Workspace.organization_id == org.id,
                    Workspace.product_code == product_code,
                )
            )
            if ws:
                ws.country_code = country_code
                ws.product_code = product_code
                if not ws.name:
                    ws.name = "PinGo Indonesia"
        if not ws:
            ws = Workspace(
                organization_id=org.id,
                name="PinGo Indonesia",
                product_code=product_code,
                country_code=country_code,
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
                config={"auto_transfer": settings.liveagent_auto_transfer},
            )
            db.add(conn)
        else:
            conn.base_url = settings.liveagent_base_url
            conn.api_v3_key = settings.liveagent_api_v3_key or conn.api_v3_key
            conn.api_v1_key = settings.liveagent_api_v1_key or conn.api_v1_key
            conn.agent_email = settings.liveagent_agent_email or conn.agent_email
            conn.dry_run = settings.liveagent_dry_run
            conn.webhook_secret = settings.webhook_secret
            merged = dict(conn.config or {})
            merged["auto_transfer"] = settings.liveagent_auto_transfer
            conn.config = merged

        # --- Seed agent (product agent on pingo/ID) ---
        agent = db.scalar(
            select(AgentUser)
            .where(AgentUser.email == settings.seed_agent_email)
            .options(
                selectinload(AgentUser.products),
                selectinload(AgentUser.countries),
            )
        )
        if not agent:
            agent = AgentUser(
                email=settings.seed_agent_email,
                name="PinGo Agent",
                password_hash=hash_password(settings.seed_agent_password),
                role=ROLE_AGENT,
            )
            db.add(agent)
            db.flush()
        else:
            agent.password_hash = hash_password(settings.seed_agent_password)
            if not agent.name:
                agent.name = "PinGo Agent"
            # Migrate legacy admin membership → product agent (unless already elevated)
            if not agent.role or agent.role in ("admin", "viewer", ROLE_AGENT):
                if agent.role != ROLE_SYSTEM_ADMIN:
                    agent.role = ROLE_AGENT

        if agent.role == ROLE_AGENT:
            _set_agent_grants(
                db, agent, role=ROLE_AGENT, products=[product], countries=[country]
            )
        _ensure_membership(db, agent, ws, agent.role)

        # --- Optional system admin ---
        admin_email = (settings.seed_admin_email or "").strip().lower()
        admin_password = settings.seed_admin_password or ""
        if admin_email and admin_password:
            admin = db.scalar(
                select(AgentUser)
                .where(AgentUser.email == admin_email)
                .options(
                    selectinload(AgentUser.products),
                    selectinload(AgentUser.countries),
                )
            )
            if not admin:
                admin = AgentUser(
                    email=admin_email,
                    name="System Admin",
                    password_hash=hash_password(admin_password),
                    role=ROLE_SYSTEM_ADMIN,
                )
                db.add(admin)
                db.flush()
            else:
                admin.password_hash = hash_password(admin_password)
                admin.role = ROLE_SYSTEM_ADMIN
            _set_agent_grants(db, admin, role=ROLE_SYSTEM_ADMIN, products=[], countries=[])
            _ensure_membership(db, admin, ws, ROLE_SYSTEM_ADMIN)
            logger.info("seeded system_admin=%s", admin.email)

        avantee_spec = avantee_spec_from_settings(settings)
        avantee_conn = None
        if avantee_spec:
            _, avantee_ws, avantee_conn = ensure_product_channel(db, avantee_spec, org=org)
            logger.info(
                "seeded avantee workspace=%s connection=%s",
                avantee_ws.id,
                avantee_conn.id,
            )

        db.commit()
        _backfill_faq_product_code(settings.faq_path, product_code)
        logger.info(
            "seeded org=%s workspace=%s product=%s country=%s agent=%s role=%s",
            org.id,
            ws.id,
            product_code,
            country_code,
            agent.email,
            agent.role,
        )
        print(f"SEED_WORKSPACE_ID={ws.id}")
        print(f"SEED_CONNECTION_ID={conn.id}")
        print(f"SEED_AGENT_EMAIL={agent.email}")
        print(f"SEED_PRODUCT_CODE={product_code}")
        print(f"SEED_COUNTRY_CODE={country_code}")
        if avantee_conn:
            print(f"SEED_AVANTEE_CONNECTION_ID={avantee_conn.id}")
            print(f"SEED_AVANTEE_WORKSPACE_ID={avantee_conn.workspace_id}")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
