from __future__ import annotations

import enum
from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# RBAC roles (stored on AgentUser.role)
ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_COUNTRY_ADMIN = "country_admin"
ROLE_PRODUCT_ADMIN = "product_admin"
ROLE_AGENT = "agent"


product_countries = Table(
    "product_countries",
    Base.metadata,
    Column("product_code", String(64), ForeignKey("products.code"), primary_key=True),
    Column("country_code", String(8), ForeignKey("countries.code"), primary_key=True),
)


agent_products = Table(
    "agent_products",
    Base.metadata,
    Column("agent_id", Uuid(as_uuid=True), ForeignKey("agent_users.id"), primary_key=True),
    Column("product_code", String(64), ForeignKey("products.code"), primary_key=True),
)


agent_countries = Table(
    "agent_countries",
    Base.metadata,
    Column("agent_id", Uuid(as_uuid=True), ForeignKey("agent_users.id"), primary_key=True),
    Column("country_code", String(8), ForeignKey("countries.code"), primary_key=True),
)


class Country(Base):
    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # e.g. ID
    name_zh: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    name_en: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    name_local: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    products: Mapped[list[Product]] = relationship(
        secondary=product_countries, back_populates="countries"
    )


class Product(Base):
    __tablename__ = "products"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. pingo
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Forced customer-facing reply language (zh / id / en)
    customer_reply_lang: Mapped[str] = mapped_column(String(8), nullable=False, default="id")
    default_country_code: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("countries.code"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    countries: Mapped[list[Country]] = relationship(
        secondary=product_countries, back_populates="products"
    )


class ConversationStatus(str, enum.Enum):
    queued = "queued"
    assigned = "assigned"
    ai_pending = "ai_pending"
    closed = "closed"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"
    note = "note"


class MessageSenderType(str, enum.Enum):
    customer = "customer"
    agent = "agent"
    ai = "ai"
    system = "system"


class MessageSendStatus(str, enum.Enum):
    local = "local"
    local_only = "local_only"  # AI preview: midplatform only, not delivered to LA/visitor
    pending = "pending"
    sent = "sent"
    failed = "failed"


class OutboxStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"
    dead = "dead"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspaces: Mapped[list[Workspace]] = relationship(back_populates="organization")


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "product_code", "country_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped[Organization] = relationship(back_populates="workspaces")
    channels: Mapped[list[ChannelConnection]] = relationship(back_populates="workspace")


class ChannelConnection(Base):
    __tablename__ = "channel_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="liveagent")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_v3_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    api_v1_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_secret: Mapped[str] = mapped_column(String(128), nullable=False, default="dev-secret")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="channels")


class AgentUser(Base):
    __tablename__ = "agent_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # system_admin | country_admin | product_admin | agent
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_AGENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list[Membership]] = relationship(back_populates="agent")
    products: Mapped[list[Product]] = relationship(secondary=agent_products)
    countries: Mapped[list[Country]] = relationship(secondary=agent_countries)


class Membership(Base):
    """Legacy workspace link; access is primarily role + product/country grants."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("agent_id", "workspace_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_users.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_AGENT)

    agent: Mapped[AgentUser] = relationship(back_populates="memberships")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("channel_connection_id", "external_id", name="uq_conv_external"),
        Index("ix_conversations_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_code: Mapped[Optional[str]] = mapped_column(String(64))
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status", native_enum=False),
        default=ConversationStatus.queued,
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(255))
    customer_email: Mapped[Optional[str]] = mapped_column(String(255))
    customer_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("agent_users.id"))
    channel_type: Mapped[Optional[str]] = mapped_column(String(32))
    la_status: Mapped[Optional[str]] = mapped_column(String(8))
    ai_handled: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[Message]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "channel_connection_id",
            "external_id",
            name="uq_msg_external",
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    channel_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("channel_connections.id"))
    external_id: Mapped[Optional[str]] = mapped_column(String(128))
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection, name="message_direction", native_enum=False))
    sender_type: Mapped[MessageSenderType] = mapped_column(
        Enum(MessageSenderType, name="message_sender_type", native_enum=False)
    )
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    send_status: Mapped[MessageSendStatus] = mapped_column(
        Enum(MessageSendStatus, name="message_send_status", native_enum=False),
        default=MessageSendStatus.local,
    )
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="send_message")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status", native_enum=False), default=OutboxStatus.pending
    )
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AiJob(Base):
    __tablename__ = "ai_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    trigger_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("messages.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
