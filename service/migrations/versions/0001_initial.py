"""initial multi-tenant schema

Revision ID: 0001
Revises:
Create Date: 2026-05-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    rol_enum = sa.Enum(
        "dueño",
        "encargado",
        "empleado",
        name="rol",
    )
    rol_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "empresas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("phone_number_id", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("phone_number_id", name="uq_empresas_phone_number_id"),
    )
    op.create_index(
        "ix_empresas_phone_number_id", "empresas", ["phone_number_id"], unique=True
    )

    op.create_table(
        "usuarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "empresa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contacto", sa.String(length=100), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("rol", rol_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "empresa_id", "contacto", name="uq_usuarios_empresa_contacto"
        ),
    )
    op.create_index(
        "ix_usuarios_empresa_contacto", "usuarios", ["empresa_id", "contacto"]
    )

    op.create_table(
        "facturas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "empresa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("numero", sa.String(length=50), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "estado",
            sa.String(length=20),
            nullable=False,
            server_default="emitida",
        ),
        sa.Column("detalle", sa.String(length=500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("empresa_id", "numero", name="uq_facturas_empresa_numero"),
    )
    op.create_index("ix_facturas_empresa_id", "facturas", ["empresa_id"])

    op.create_table(
        "stock",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "empresa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("empresa_id", "sku", name="uq_stock_empresa_sku"),
    )
    op.create_index("ix_stock_empresa_id", "stock", ["empresa_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_empresa_id", table_name="stock")
    op.drop_table("stock")

    op.drop_index("ix_facturas_empresa_id", table_name="facturas")
    op.drop_table("facturas")

    op.drop_index("ix_usuarios_empresa_contacto", table_name="usuarios")
    op.drop_table("usuarios")

    op.drop_index("ix_empresas_phone_number_id", table_name="empresas")
    op.drop_table("empresas")

    sa.Enum(name="rol").drop(op.get_bind(), checkfirst=True)
