from datetime import date, datetime, timezone
from sqlalchemy import (
    String, Integer, Boolean, Date, DateTime, ForeignKey, Index,
    UniqueConstraint, Text, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    clients: Mapped[list["Client"]] = relationship(back_populates="tenant")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="write")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (CheckConstraint("role IN ('read', 'write', 'admin')", name="ck_api_key_role"),)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    tenant: Mapped[Tenant] = relationship(back_populates="clients")
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_ref", name="uq_client_per_tenant"),
        Index("ix_clients_tenant_ref", "tenant_id", "client_ref"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    signed_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(128))
    is_reversal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reverses_entry_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"))
    corrects_entry_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_idempotency_per_tenant"),
        CheckConstraint("amount_minor > 0", name="ck_ledger_positive_amount"),
        CheckConstraint("length(currency) = 3", name="ck_ledger_currency_length"),
        CheckConstraint("transaction_type IN ('deposit', 'withdrawal', 'fee', 'transfer')", name="ck_ledger_transaction_type"),
        Index("ix_ledger_tenant_client_date_id", "tenant_id", "client_id", "effective_date", "id"),
        Index("ix_ledger_tenant_currency_date", "tenant_id", "currency", "effective_date"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)
