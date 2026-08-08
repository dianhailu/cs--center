from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AgentUser, Membership, Workspace
from app.schemas import LoginRequest, LoginResponse, WorkspaceOut
from app.security import create_access_token, verify_password
from app.api.deps import AuthContext, get_auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    agent = db.scalar(select(AgentUser).where(AgentUser.email == body.email.lower()))
    if not agent or not verify_password(body.password, agent.password_hash):
        raise HTTPException(401, "invalid credentials")
    memberships = list(db.scalars(select(Membership).where(Membership.agent_id == agent.id)))
    if not memberships:
        raise HTTPException(403, "no workspace")
    membership = memberships[0]
    if body.workspace_id:
        membership = next((m for m in memberships if m.workspace_id == body.workspace_id), None)
        if not membership:
            raise HTTPException(403, "workspace not allowed")
    ws = db.get(Workspace, membership.workspace_id)
    assert ws
    token = create_access_token(agent_id=agent.id, email=agent.email, workspace_id=ws.id)
    return LoginResponse(
        access_token=token,
        agent_id=agent.id,
        email=agent.email,
        name=agent.name,
        workspace_id=ws.id,
        workspace_name=ws.name,
    )


@router.get("/me")
def me(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> dict:
    ws = db.get(Workspace, auth.workspace_id)
    return {
        "agent_id": auth.agent.id,
        "email": auth.agent.email,
        "name": auth.agent.name,
        "workspace_id": auth.workspace_id,
        "workspace_name": ws.name if ws else None,
        "role": auth.role,
    }


@router.get("/workspaces", response_model=list[WorkspaceOut])
def workspaces(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> list[Workspace]:
    ids = list(db.scalars(select(Membership.workspace_id).where(Membership.agent_id == auth.agent.id)))
    return list(db.scalars(select(Workspace).where(Workspace.id.in_(ids))))
