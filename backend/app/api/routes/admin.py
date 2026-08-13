"""Admin APIs: countries, products, users (RBAC scoped)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AuthContext, get_auth
from app.db import get_db
from app.models import (
    ROLE_SYSTEM_ADMIN,
    AgentUser,
    Country,
    Membership,
    Organization,
    Product,
    Workspace,
)
from app.rbac import (
    VALID_ROLES,
    agent_country_codes,
    agent_product_codes,
    assert_can_create_role,
    assert_scope_within_actor,
    can_access_admin_ui,
    can_manage_catalog,
    can_manage_users,
    normalize_country,
    normalize_product,
    validate_grants_for_role,
)
from app.schemas import (
    CountryIn,
    CountryOut,
    ProductIn,
    ProductOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from app.security import hash_password
from app.models import ROLE_PRODUCT_ADMIN

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin_ui(auth: AuthContext) -> None:
    if not can_access_admin_ui(auth.role):
        raise HTTPException(403, "admin UI not allowed")


def _user_out(agent: AgentUser) -> UserOut:
    return UserOut(
        id=agent.id,
        email=agent.email,
        name=agent.name,
        role=agent.role,
        is_active=agent.is_active,
        product_codes=agent_product_codes(agent),
        country_codes=agent_country_codes(agent),
    )


def _product_out(p: Product) -> ProductOut:
    return ProductOut(
        code=p.code,
        name=p.name,
        customer_reply_lang=p.customer_reply_lang,
        default_country_code=p.default_country_code,
        country_codes=[c.code for c in (p.countries or [])],
    )


def _load_products(db: Session, codes: list[str]) -> list[Product]:
    if not codes:
        return []
    rows = list(db.scalars(select(Product).where(Product.code.in_(codes))))
    missing = set(codes) - {r.code for r in rows}
    if missing:
        raise HTTPException(400, f"unknown products: {sorted(missing)}")
    return rows


def _load_countries(db: Session, codes: list[str]) -> list[Country]:
    if not codes:
        return []
    rows = list(db.scalars(select(Country).where(Country.code.in_(codes))))
    missing = set(codes) - {r.code for r in rows}
    if missing:
        raise HTTPException(400, f"unknown countries: {sorted(missing)}")
    return rows


def _sync_memberships(db: Session, agent: AgentUser) -> None:
    """Ensure Membership rows exist for every accessible workspace."""
    from app.rbac import list_accessible_workspaces

    workspaces = list_accessible_workspaces(db, agent)
    existing = {
        m.workspace_id: m
        for m in db.scalars(select(Membership).where(Membership.agent_id == agent.id))
    }
    keep: set[UUID] = set()
    for ws in workspaces:
        keep.add(ws.id)
        if ws.id in existing:
            existing[ws.id].role = agent.role
        else:
            db.add(Membership(agent_id=agent.id, workspace_id=ws.id, role=agent.role))
    # Drop stale memberships for non-system admins
    if agent.role != ROLE_SYSTEM_ADMIN:
        for wid, m in existing.items():
            if wid not in keep:
                db.delete(m)


def _ensure_workspace_for_product_country(
    db: Session, product: Product, country_code: str
) -> Workspace:
    cc = normalize_country(country_code)
    ws = db.scalar(
        select(Workspace).where(
            Workspace.product_code == product.code,
            Workspace.country_code == cc,
        )
    )
    if ws:
        return ws
    org = db.scalar(select(Organization).order_by(Organization.created_at))
    if not org:
        org = Organization(name="Default")
        db.add(org)
        db.flush()
    country = db.get(Country, cc)
    label = country.name_zh if country else cc
    ws = Workspace(
        organization_id=org.id,
        name=f"{product.name} {label}",
        product_code=product.code,
        country_code=cc,
    )
    db.add(ws)
    db.flush()
    return ws


# ----- Countries -----


@router.get("/countries", response_model=list[CountryOut])
def list_countries(
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> list[Country]:
    _require_admin_ui(auth)
    return list(db.scalars(select(Country).order_by(Country.code)))


@router.post("/countries", response_model=CountryOut)
def create_country(
    body: CountryIn,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> Country:
    if not can_manage_catalog(auth.role):
        raise HTTPException(403, "catalog manage requires system_admin")
    code = normalize_country(body.code)
    if db.get(Country, code):
        raise HTTPException(400, "country already exists")
    row = Country(
        code=code,
        name_zh=body.name_zh or code,
        name_en=body.name_en or code,
        name_local=body.name_local or body.name_en or code,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/countries/{code}", response_model=CountryOut)
def update_country(
    code: str,
    body: CountryIn,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> Country:
    if not can_manage_catalog(auth.role):
        raise HTTPException(403, "catalog manage requires system_admin")
    row = db.get(Country, normalize_country(code))
    if not row:
        raise HTTPException(404, "country not found")
    row.name_zh = body.name_zh or row.name_zh
    row.name_en = body.name_en or row.name_en
    row.name_local = body.name_local or row.name_local
    db.commit()
    db.refresh(row)
    return row


# ----- Products -----


@router.get("/products", response_model=list[ProductOut])
def list_products(
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> list[ProductOut]:
    _require_admin_ui(auth)
    q = select(Product).options(selectinload(Product.countries)).order_by(Product.code)
    rows = list(db.scalars(q))
    if auth.role != ROLE_SYSTEM_ADMIN:
        allowed = set(auth.product_codes)
        rows = [p for p in rows if p.code in allowed]
    return [_product_out(p) for p in rows]


@router.post("/products", response_model=ProductOut)
def create_product(
    body: ProductIn,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> ProductOut:
    if not can_manage_catalog(auth.role):
        raise HTTPException(403, "catalog manage requires system_admin")
    code = normalize_product(body.code)
    if db.get(Product, code):
        raise HTTPException(400, "product already exists")
    lang = (body.customer_reply_lang or "id").strip().lower()
    if lang not in {"zh", "id", "en"}:
        raise HTTPException(400, "customer_reply_lang must be zh|id|en")
    default_cc = normalize_country(body.default_country_code) if body.default_country_code else None
    country_codes = [normalize_country(c) for c in body.country_codes]
    if default_cc and default_cc not in country_codes:
        country_codes.append(default_cc)
    countries = _load_countries(db, country_codes)
    product = Product(
        code=code,
        name=body.name.strip(),
        customer_reply_lang=lang,
        default_country_code=default_cc,
    )
    product.countries = countries
    db.add(product)
    db.flush()
    for c in countries:
        _ensure_workspace_for_product_country(db, product, c.code)
    db.commit()
    product = db.scalar(
        select(Product).where(Product.code == code).options(selectinload(Product.countries))
    )
    assert product
    return _product_out(product)


@router.put("/products/{code}", response_model=ProductOut)
def update_product(
    code: str,
    body: ProductIn,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> ProductOut:
    if not can_manage_catalog(auth.role):
        raise HTTPException(403, "catalog manage requires system_admin")
    product = db.scalar(
        select(Product)
        .where(Product.code == normalize_product(code))
        .options(selectinload(Product.countries))
    )
    if not product:
        raise HTTPException(404, "product not found")
    lang = (body.customer_reply_lang or product.customer_reply_lang or "id").strip().lower()
    if lang not in {"zh", "id", "en"}:
        raise HTTPException(400, "customer_reply_lang must be zh|id|en")
    product.name = body.name.strip() or product.name
    product.customer_reply_lang = lang
    default_cc = (
        normalize_country(body.default_country_code) if body.default_country_code else product.default_country_code
    )
    product.default_country_code = default_cc
    if body.country_codes is not None:
        codes = [normalize_country(c) for c in body.country_codes]
        if default_cc and default_cc not in codes:
            codes.append(default_cc)
        product.countries = _load_countries(db, codes)
    for c in product.countries or []:
        _ensure_workspace_for_product_country(db, product, c.code)
    db.commit()
    product = db.scalar(
        select(Product)
        .where(Product.code == product.code)
        .options(selectinload(Product.countries))
    )
    assert product
    return _product_out(product)


# ----- Users -----


@router.get("/users", response_model=list[UserOut])
def list_users(
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    if not can_manage_users(auth.role):
        raise HTTPException(403, "user manage not allowed")
    rows = list(
        db.scalars(
            select(AgentUser)
            .options(
                selectinload(AgentUser.products),
                selectinload(AgentUser.countries),
            )
            .order_by(AgentUser.email)
        )
    )
    if auth.role == ROLE_SYSTEM_ADMIN:
        return [_user_out(u) for u in rows]
    # Scoped: users who share at least one product (and country for country_admin)
    mine_p = set(auth.product_codes)
    mine_c = set(auth.country_codes)
    out: list[UserOut] = []
    for u in rows:
        if u.role == ROLE_SYSTEM_ADMIN:
            continue
        up = set(agent_product_codes(u))
        if not (up & mine_p):
            continue
        if auth.role == "country_admin" and mine_c:
            uc = set(agent_country_codes(u))
            if uc and not (uc & mine_c):
                continue
        if auth.role == ROLE_PRODUCT_ADMIN and u.role not in ("agent", ROLE_PRODUCT_ADMIN):
            # product_admin mainly manages agents
            if u.id != auth.agent.id:
                continue
        out.append(_user_out(u))
    return out


@router.post("/users", response_model=UserOut)
def create_user(
    body: UserCreateIn,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> UserOut:
    if not can_manage_users(auth.role):
        raise HTTPException(403, "user manage not allowed")
    role = (body.role or "").strip()
    if role not in VALID_ROLES:
        raise HTTPException(400, f"invalid role; expected one of {sorted(VALID_ROLES)}")
    assert_can_create_role(auth.role, role)
    products, countries = validate_grants_for_role(
        role=role,
        product_codes=body.product_codes,
        country_codes=body.country_codes,
    )
    assert_scope_within_actor(auth.agent, product_codes=products, country_codes=countries)
    email = str(body.email).lower()
    if db.scalar(select(AgentUser).where(AgentUser.email == email)):
        raise HTTPException(400, "email already exists")
    agent = AgentUser(
        email=email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        role=role,
        is_active=body.is_active,
    )
    agent.products = _load_products(db, products)
    agent.countries = _load_countries(db, countries)
    db.add(agent)
    db.flush()
    _sync_memberships(db, agent)
    db.commit()
    agent = db.scalar(
        select(AgentUser)
        .where(AgentUser.id == agent.id)
        .options(
            selectinload(AgentUser.products),
            selectinload(AgentUser.countries),
        )
    )
    assert agent
    return _user_out(agent)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    body: UserUpdateIn,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> UserOut:
    if not can_manage_users(auth.role):
        raise HTTPException(403, "user manage not allowed")
    agent = db.scalar(
        select(AgentUser)
        .where(AgentUser.id == user_id)
        .options(
            selectinload(AgentUser.products),
            selectinload(AgentUser.countries),
        )
    )
    if not agent:
        raise HTTPException(404, "user not found")
    if agent.role == ROLE_SYSTEM_ADMIN and auth.role != ROLE_SYSTEM_ADMIN:
        raise HTTPException(403, "cannot edit system_admin")

    new_role = body.role or agent.role
    if body.role and body.role != agent.role:
        if body.role not in VALID_ROLES:
            raise HTTPException(400, "invalid role")
        assert_can_create_role(auth.role, body.role)
        agent.role = body.role
        new_role = body.role

    products = (
        [normalize_product(p) for p in body.product_codes]
        if body.product_codes is not None
        else agent_product_codes(agent)
    )
    countries = (
        [normalize_country(c) for c in body.country_codes]
        if body.country_codes is not None
        else agent_country_codes(agent)
    )
    products, countries = validate_grants_for_role(
        role=new_role, product_codes=products, country_codes=countries
    )
    assert_scope_within_actor(auth.agent, product_codes=products, country_codes=countries)

    if body.name is not None:
        agent.name = body.name.strip() or agent.name
    if body.password:
        agent.password_hash = hash_password(body.password)
    if body.is_active is not None:
        agent.is_active = body.is_active
    if body.product_codes is not None or body.role:
        agent.products = _load_products(db, products)
    if body.country_codes is not None or body.role:
        agent.countries = _load_countries(db, countries)

    _sync_memberships(db, agent)
    db.commit()
    agent = db.scalar(
        select(AgentUser)
        .where(AgentUser.id == user_id)
        .options(
            selectinload(AgentUser.products),
            selectinload(AgentUser.countries),
        )
    )
    assert agent
    return _user_out(agent)
