"""SQLAlchemy ORM models — multi-tenant. Every business table carries `empresa_id`.

Per SPEC §9: tenant scoping is enforced in code. A query for a business
resource without an `empresa_id` filter is a bug.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rai.db import Base
from rai.roles import Role


class Empresa(Base):
    """One business / tenant. Identified by its receiving WhatsApp number."""

    __tablename__ = "empresas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="empresa")


class Usuario(Base):
    """A WhatsApp contact registered to operate on behalf of one empresa."""

    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint("empresa_id", "contacto", name="uq_usuarios_empresa_contacto"),
        Index("ix_usuarios_empresa_contacto", "empresa_id", "contacto"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False
    )
    contacto: Mapped[str] = mapped_column(String(100), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    rol: Mapped[Role] = mapped_column(
        SAEnum(Role, name="rol", values_callable=lambda enum: [m.value for m in enum]),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    empresa: Mapped[Empresa] = relationship(back_populates="usuarios")


class Factura(Base):
    """An invoice belonging to one empresa."""

    __tablename__ = "facturas"
    __table_args__ = (
        UniqueConstraint("empresa_id", "numero", name="uq_facturas_empresa_numero"),
        Index("ix_facturas_empresa_id", "empresa_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False
    )
    numero: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha: Mapped[Date] = mapped_column(Date, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="emitida")
    detalle: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Stock(Base):
    """Stock item belonging to one empresa."""

    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("empresa_id", "sku", name="uq_stock_empresa_sku"),
        Index("ix_stock_empresa_id", "empresa_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
