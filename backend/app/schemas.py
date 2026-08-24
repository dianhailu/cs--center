from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_id: UUID | None = None
    product_code: str | None = None
    country_code: str | None = None


class ScopeOut(BaseModel):
    workspace_id: UUID
    workspace_name: str
    product_code: str
    product_name: str
    country_code: str
    country_name: str
    customer_reply_lang: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    agent_id: UUID
    email: str
    name: str
    role: str
    workspace_id: UUID
    workspace_name: str
    product_code: str
    country_code: str
    customer_reply_lang: str
    product_codes: list[str] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    scopes: list[ScopeOut] = Field(default_factory=list)
    can_edit_knowledge: bool = False
    can_manage_users: bool = False
    can_manage_catalog: bool = False


class SwitchContextRequest(BaseModel):
    workspace_id: UUID | None = None
    product_code: str | None = None
    country_code: str | None = None


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    product_code: str
    country_code: str

    model_config = {"from_attributes": True, "use_enum_values": True}


class CountryIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=8)
    name_zh: str = ""
    name_en: str = ""
    name_local: str = ""


class CountryOut(BaseModel):
    code: str
    name_zh: str
    name_en: str
    name_local: str

    model_config = {"from_attributes": True}


class ProductIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    customer_reply_lang: str = Field(default="id", min_length=2, max_length=8)
    default_country_code: str | None = None
    country_codes: list[str] = Field(default_factory=list)


class ProductOut(BaseModel):
    code: str
    name: str
    customer_reply_lang: str
    default_country_code: str | None
    country_codes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class UserCreateIn(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=6, max_length=128)
    role: str
    product_codes: list[str] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    is_active: bool = True


class UserUpdateIn(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: str | None = None
    product_codes: list[str] | None = None
    country_codes: list[str] | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    is_active: bool
    product_codes: list[str] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


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
    product_code: str | None = None
    product_name: str | None = None
    workspace_name: str | None = None

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
