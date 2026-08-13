from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AuthContext, get_auth
from app.db import get_db
from app.models import Country, Product, Workspace
from app.rbac import (
    agent_country_codes,
    agent_product_codes,
    assert_workspace_access,
    can_edit_knowledge,
    can_manage_catalog,
    can_manage_users,
    list_accessible_workspaces,
    normalize_country,
    normalize_product,
    resolve_customer_reply_lang,
)
from app.schemas import LoginRequest, LoginResponse, ScopeOut, SwitchContextRequest, WorkspaceOut
from app.security import create_access_token, verify_password
from app.models import AgentUser
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _country_label(c: Country | None, code: str) -> str:
    if not c:
        return code
    return c.name_zh or c.name_local or c.name_en or code


def _build_scopes(db: Session, workspaces: list[Workspace]) -> list[ScopeOut]:
    products = {
        p.code: p
        for p in db.scalars(select(Product).where(Product.code.in_([w.product_code for w in workspaces] or ["__none__"])))
    }
    countries = {
        c.code: c
        for c in db.scalars(
            select(Country).where(Country.code.in_([w.country_code for w in workspaces] or ["__none__"]))
        )
    }
    settings = get_settings()
    out: list[ScopeOut] = []
    for ws in workspaces:
        product = products.get(ws.product_code)
        country = countries.get(ws.country_code)
        lang = (
            product.customer_reply_lang
            if product and product.customer_reply_lang
            else resolve_customer_reply_lang(db, ws.product_code, settings.default_reply_lang)
        )
        out.append(
            ScopeOut(
                workspace_id=ws.id,
                workspace_name=ws.name,
                product_code=ws.product_code,
                product_name=product.name if product else ws.product_code,
                country_code=ws.country_code,
                country_name=_country_label(country, ws.country_code),
                customer_reply_lang=lang,
            )
        )
    return out


def _pick_workspace(
    workspaces: list[Workspace],
    *,
    workspace_id: UUID | None = None,
    product_code: str | None = None,
    country_code: str | None = None,
) -> Workspace:
    if not workspaces:
        raise HTTPException(403, "no workspace")
    if workspace_id:
        ws = next((w for w in workspaces if w.id == workspace_id), None)
        if not ws:
            raise HTTPException(403, "workspace not allowed")
        return ws
    pc = normalize_product(product_code) if product_code else None
    cc = normalize_country(country_code) if country_code else None
    if pc or cc:
        matched = [
            w
            for w in workspaces
            if (not pc or w.product_code == pc) and (not cc or w.country_code == cc)
        ]
        if not matched:
            raise HTTPException(403, "scope not allowed")
        return matched[0]
    settings = get_settings()
    default_p = normalize_product(settings.default_product_code)
    default_c = normalize_country(settings.default_country_code)
    preferred = next(
        (w for w in workspaces if w.product_code == default_p and w.country_code == default_c),
        None,
    )
    return preferred or workspaces[0]


def _login_payload(db: Session, agent: AgentUser, ws: Workspace) -> LoginResponse:
    workspaces = list_accessible_workspaces(db, agent)
    scopes = _build_scopes(db, workspaces)
    product_codes = agent_product_codes(agent)
    country_codes = agent_country_codes(agent)
    settings = get_settings()
    reply_lang = resolve_customer_reply_lang(
        db, ws.product_code, fallback=settings.default_reply_lang or "id"
    )
    token = create_access_token(
        agent_id=agent.id,
        email=agent.email,
        workspace_id=ws.id,
        role=agent.role,
        product_codes=product_codes,
        country_codes=country_codes,
        product_code=ws.product_code,
        country_code=ws.country_code,
    )
    return LoginResponse(
        access_token=token,
        agent_id=agent.id,
        email=agent.email,
        name=agent.name,
        role=agent.role,
        workspace_id=ws.id,
        workspace_name=ws.name,
        product_code=ws.product_code,
        country_code=ws.country_code,
        customer_reply_lang=reply_lang,
        product_codes=product_codes,
        country_codes=country_codes,
        scopes=scopes,
        can_edit_knowledge=can_edit_knowledge(agent.role),
        can_manage_users=can_manage_users(agent.role),
        can_manage_catalog=can_manage_catalog(agent.role),
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    agent = db.scalar(
        select(AgentUser)
        .where(AgentUser.email == body.email.lower())
        .options(
            selectinload(AgentUser.products),
            selectinload(AgentUser.countries),
        )
    )
    if not agent or not verify_password(body.password, agent.password_hash):
        raise HTTPException(401, "invalid credentials")
    if not agent.is_active:
        raise HTTPException(401, "agent inactive")
    workspaces = list_accessible_workspaces(db, agent)
    ws = _pick_workspace(
        workspaces,
        workspace_id=body.workspace_id,
        product_code=body.product_code,
        country_code=body.country_code,
    )
    return _login_payload(db, agent, ws)


@router.get("/me")
def me(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> dict:
    workspaces = list_accessible_workspaces(db, auth.agent)
    scopes = _build_scopes(db, workspaces)
    return {
        "agent_id": auth.agent.id,
        "email": auth.agent.email,
        "name": auth.agent.name,
        "role": auth.role,
        "workspace_id": auth.workspace_id,
        "workspace_name": next((s.workspace_name for s in scopes if s.workspace_id == auth.workspace_id), None),
        "product_code": auth.product_code,
        "country_code": auth.country_code,
        "customer_reply_lang": auth.customer_reply_lang,
        "product_codes": auth.product_codes,
        "country_codes": auth.country_codes,
        "scopes": [s.model_dump() for s in scopes],
        "can_edit_knowledge": can_edit_knowledge(auth.role),
        "can_manage_users": can_manage_users(auth.role),
        "can_manage_catalog": can_manage_catalog(auth.role),
    }


@router.post("/switch", response_model=LoginResponse)
def switch_context(
    body: SwitchContextRequest,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> LoginResponse:
    agent = db.scalar(
        select(AgentUser)
        .where(AgentUser.id == auth.agent.id)
        .options(
            selectinload(AgentUser.products),
            selectinload(AgentUser.countries),
        )
    )
    assert agent
    workspaces = list_accessible_workspaces(db, agent)
    ws = _pick_workspace(
        workspaces,
        workspace_id=body.workspace_id,
        product_code=body.product_code,
        country_code=body.country_code,
    )
    assert_workspace_access(db, agent, ws.id)
    return _login_payload(db, agent, ws)


@router.get("/workspaces", response_model=list[WorkspaceOut])
def workspaces(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> list[Workspace]:
    return list_accessible_workspaces(db, auth.agent)


@router.get("/scopes", response_model=list[ScopeOut])
def scopes(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> list[ScopeOut]:
    return _build_scopes(db, list_accessible_workspaces(db, auth.agent))
