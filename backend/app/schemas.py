from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_id: UUID | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    agent_id: UUID
    email: str
    name: str
    workspace_id: UUID
    workspace_name: str


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    product_code: str
    country_code: str

    model_config = {"from_attributes": True, "use_enum_values": True}


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: str
    sender_type: str
    body: str
    send_status: str
    external_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True, "use_enum_values": True}


class ConversationOut(BaseModel):
    id: UUID
    workspace_id: UUID
    external_id: str
    external_code: str | None
    subject: str | None
    status: str
    customer_name: str | None
    customer_email: str | None
    tags: list
    assignee_id: UUID | None
    channel_type: str | None
    la_status: str | None
    ai_handled: bool
    needs_human: bool
    last_message_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True, "use_enum_values": True}


class ConversationDetail(ConversationOut):
    customer_snapshot: dict
    messages: list[MessageOut] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    body: str = Field(..., min_length=1)
    as_note: bool = False


class AssignRequest(BaseModel):
    agent_id: UUID | None = None


class WebhookAck(BaseModel):
    ok: bool
    conversation_id: UUID | None = None
    imported_messages: int = 0
    ai_enqueued: bool = False
