"""Ensure catalog + workspace + LiveAgent channel for a product."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ChannelConnection, Country, Organization, Product, Workspace
from app.rbac import normalize_country, normalize_product

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductChannelSpec:
    product_code: str
    product_name: str
    country_code: str
    customer_reply_lang: str
    workspace_name: str
    connection_name: str
    base_url: str
    api_v3_key: str
    api_v1_key: str
    agent_email: str
    dry_run: bool
    webhook_secret: str
    auto_transfer: bool
    panel_accept: bool


def ensure_product_channel(
    db: Session,
    spec: ProductChannelSpec,
    *,
    org: Organization | None = None,
) -> tuple[Product, Workspace, ChannelConnection]:
    product_code = normalize_product(spec.product_code)
    country_code = normalize_country(spec.country_code)

    country = db.get(Country, country_code)
    if not country:
        country = Country(
            code=country_code,
            name_zh="印尼" if country_code == "ID" else country_code,
            name_en="Indonesia" if country_code == "ID" else country_code,
            name_local="Indonesia" if country_code == "ID" else country_code,
        )
        db.add(country)
        db.flush()

    product = db.get(Product, product_code)
    if not product:
        product = Product(
            code=product_code,
            name=spec.product_name,
            customer_reply_lang=spec.customer_reply_lang.lower(),
            default_country_code=country_code,
        )
        db.add(product)
        db.flush()
    else:
        if spec.product_name:
            product.name = spec.product_name
        product.customer_reply_lang = spec.customer_reply_lang.lower()
        if not product.default_country_code:
            product.default_country_code = country_code

    if country not in (product.countries or []):
        product.countries = list({*(product.countries or []), country})

    if org is None:
        org = db.scalar(select(Organization).order_by(Organization.created_at))
    if not org:
        org = Organization(name="Smart-CS Center")
        db.add(org)
        db.flush()

    ws = db.scalar(
        select(Workspace).where(
            Workspace.organization_id == org.id,
            Workspace.product_code == product_code,
            Workspace.country_code == country_code,
        )
    )
    if not ws:
        ws = db.scalar(
            select(Workspace).where(
                Workspace.product_code == product_code,
                Workspace.country_code == country_code,
            )
        )
    if not ws:
        ws = Workspace(
            organization_id=org.id,
            name=spec.workspace_name,
            product_code=product_code,
            country_code=country_code,
        )
        db.add(ws)
        db.flush()
    else:
        ws.organization_id = org.id
        ws.name = spec.workspace_name or ws.name
        ws.product_code = product_code
        ws.country_code = country_code

    conn = db.scalar(
        select(ChannelConnection).where(
            ChannelConnection.workspace_id == ws.id,
            ChannelConnection.provider == "liveagent",
        )
    )
    config = {
        "auto_transfer": spec.auto_transfer,
        "panel_accept": spec.panel_accept,
    }
    if not conn:
        conn = ChannelConnection(
            workspace_id=ws.id,
            provider="liveagent",
            name=spec.connection_name,
            base_url=spec.base_url.rstrip("/"),
            api_v3_key=spec.api_v3_key,
            api_v1_key=spec.api_v1_key,
            agent_email=spec.agent_email.strip().lower(),
            dry_run=spec.dry_run,
            webhook_secret=spec.webhook_secret,
            config=config,
        )
        db.add(conn)
    else:
        conn.name = spec.connection_name or conn.name
        conn.base_url = spec.base_url.rstrip("/")
        if spec.api_v3_key:
            conn.api_v3_key = spec.api_v3_key
        if spec.api_v1_key:
            conn.api_v1_key = spec.api_v1_key
        if spec.agent_email:
            conn.agent_email = spec.agent_email.strip().lower()
        conn.dry_run = spec.dry_run
        if spec.webhook_secret:
            conn.webhook_secret = spec.webhook_secret
        merged = dict(conn.config or {})
        merged.update(config)
        conn.config = merged

    db.flush()
    logger.info(
        "product channel ready product=%s country=%s workspace=%s connection=%s base=%s",
        product_code,
        country_code,
        ws.id,
        conn.id,
        conn.base_url,
    )
    return product, ws, conn


def avantee_spec_from_settings(settings: Settings) -> ProductChannelSpec | None:
    base = (settings.avantee_liveagent_base_url or "").strip()
    v3 = (settings.avantee_liveagent_api_v3_key or "").strip()
    v1 = (settings.avantee_liveagent_api_v1_key or "").strip()
    email = (settings.avantee_liveagent_agent_email or "").strip()
    if not base or not v3 or not v1 or not email:
        return None
    return ProductChannelSpec(
        product_code=settings.avantee_product_code or "avantee",
        product_name=settings.avantee_product_name or "Avantee",
        country_code=settings.avantee_country_code or "ID",
        customer_reply_lang=settings.avantee_customer_reply_lang or "id",
        workspace_name=settings.avantee_workspace_name or "Avantee Indonesia",
        connection_name="avantee-ladesk",
        base_url=base,
        api_v3_key=v3,
        api_v1_key=v1,
        agent_email=email,
        dry_run=settings.avantee_liveagent_dry_run,
        webhook_secret=settings.webhook_secret,
        auto_transfer=settings.liveagent_auto_transfer,
        panel_accept=settings.liveagent_panel_accept,
    )
