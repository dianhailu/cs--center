"""Role-based access helpers for multi-product / multi-country RBAC."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ROLE_AGENT,
    ROLE_COUNTRY_ADMIN,
    ROLE_PRODUCT_ADMIN,
    ROLE_SYSTEM_ADMIN,
    AgentUser,
    Product,
    Workspace,
)

# Hierarchy: higher index = more privilege for "at least" checks
ROLE_RANK = {
    ROLE_AGENT: 1,
    ROLE_PRODUCT_ADMIN: 2,
    ROLE_COUNTRY_ADMIN: 3,
    ROLE_SYSTEM_ADMIN: 4,
}

VALID_ROLES = frozenset(ROLE_RANK.keys())

# Who may create which roles (creator_role -> allowed new roles)
CREATABLE_ROLES: dict[str, frozenset[str]] = {
    ROLE_SYSTEM_ADMIN: frozenset(
        {ROLE_SYSTEM_ADMIN, ROLE_COUNTRY_ADMIN, ROLE_PRODUCT_ADMIN, ROLE_AGENT}
    ),
    ROLE_COUNTRY_ADMIN: frozenset({ROLE_PRODUCT_ADMIN, ROLE_AGENT}),
    ROLE_PRODUCT_ADMIN: frozenset({ROLE_AGENT}),
    ROLE_AGENT: frozenset(),
}


def normalize_country(code: str | None) -> str:
    return (code or "").strip().upper()


def normalize_product(code: str | None) -> str:
    return (code or "").strip().lower()


def can_edit_knowledge(role: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[ROLE_PRODUCT_ADMIN]


def can_manage_users(role: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[ROLE_PRODUCT_ADMIN]


def can_manage_catalog(role: str) -> bool:
    """Countries / products CRUD."""
    return role == ROLE_SYSTEM_ADMIN


def can_access_admin_ui(role: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[ROLE_PRODUCT_ADMIN]


def require_role_at_least(role: str, minimum: str) -> None:
    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(minimum, 99):
        raise HTTPException(403, "insufficient role")


def require_knowledge_write(role: str) -> None:
    if not can_edit_knowledge(role):
        raise HTTPException(403, "knowledge is read-only for agents")


def agent_product_codes(agent: AgentUser) -> list[str]:
    return sorted({normalize_product(p.code) for p in (agent.products or [])})


def agent_country_codes(agent: AgentUser) -> list[str]:
    return sorted({normalize_country(c.code) for c in (agent.countries or [])})


def list_accessible_workspaces(db: Session, agent: AgentUser) -> list[Workspace]:
    """Workspaces the agent may switch into based on role + grants."""
    if agent.role == ROLE_SYSTEM_ADMIN:
        return list(db.scalars(select(Workspace).order_by(Workspace.name)))

    products = agent_product_codes(agent)
    countries = agent_country_codes(agent)
    if not products:
        return []

    q = select(Workspace).where(Workspace.product_code.in_(products))
    if agent.role == ROLE_COUNTRY_ADMIN:
        # Country admin must have explicit products AND countries
        if not countries:
            return []
        q = q.where(Workspace.country_code.in_(countries))
    elif countries:
        # Optional country filter for product_admin / agent
        q = q.where(Workspace.country_code.in_(countries))
    return list(db.scalars(q.order_by(Workspace.name)))


def workspace_allowed(db: Session, agent: AgentUser, workspace_id: UUID) -> bool:
    return any(w.id == workspace_id for w in list_accessible_workspaces(db, agent))


def assert_workspace_access(db: Session, agent: AgentUser, workspace_id: UUID) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "workspace not found")
    if agent.role != ROLE_SYSTEM_ADMIN and not workspace_allowed(db, agent, workspace_id):
        raise HTTPException(403, "workspace not allowed")
    return ws


def assert_product_access(agent: AgentUser, product_code: str) -> str:
    code = normalize_product(product_code)
    if agent.role == ROLE_SYSTEM_ADMIN:
        return code
    if code not in agent_product_codes(agent):
        raise HTTPException(403, "product not allowed")
    return code


def resolve_customer_reply_lang(db: Session, product_code: str, fallback: str = "id") -> str:
    code = normalize_product(product_code)
    product = db.get(Product, code)
    if product and product.customer_reply_lang:
        return product.customer_reply_lang.strip().lower()
    return (fallback or "id").strip().lower()


def validate_grants_for_role(
    *,
    role: str,
    product_codes: list[str],
    country_codes: list[str],
) -> tuple[list[str], list[str]]:
    products = sorted({normalize_product(p) for p in product_codes if p})
    countries = sorted({normalize_country(c) for c in country_codes if c})
    if role == ROLE_SYSTEM_ADMIN:
        return [], []
    if role == ROLE_COUNTRY_ADMIN:
        if not countries:
            raise HTTPException(400, "country_admin requires country_codes")
        if not products:
            raise HTTPException(400, "country_admin requires explicit product_codes")
    elif role in (ROLE_PRODUCT_ADMIN, ROLE_AGENT):
        if not products:
            raise HTTPException(400, f"{role} requires product_codes")
    else:
        raise HTTPException(400, f"invalid role: {role}")
    return products, countries


def assert_can_create_role(actor_role: str, new_role: str) -> None:
    allowed = CREATABLE_ROLES.get(actor_role, frozenset())
    if new_role not in allowed:
        raise HTTPException(403, f"cannot create role {new_role}")


def assert_scope_within_actor(
    actor: AgentUser,
    *,
    product_codes: list[str],
    country_codes: list[str],
) -> None:
    """Non-system admins may only grant subsets of their own scope."""
    if actor.role == ROLE_SYSTEM_ADMIN:
        return
    mine_p = set(agent_product_codes(actor))
    mine_c = set(agent_country_codes(actor))
    if set(product_codes) - mine_p:
        raise HTTPException(403, "product_codes outside your scope")
    if mine_c and set(country_codes) - mine_c:
        raise HTTPException(403, "country_codes outside your scope")
    if actor.role == ROLE_COUNTRY_ADMIN and not country_codes:
        raise HTTPException(400, "country scope required")
