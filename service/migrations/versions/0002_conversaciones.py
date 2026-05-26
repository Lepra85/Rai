"""conversaciones table + conversation_state enum

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


CONVERSATION_STATE_VALUES = (
    "idle",
    "menu_shown",
    "awaiting_args",
    "agent_active",
    "human_handoff",
)


def upgrade() -> None:
    # Same defensive pattern as 0001 — explicit ENUM creation, then
    # reference it from the column with create_type=False so SQLAlchemy
    # does not re-emit DDL.
    conv_state = postgresql.ENUM(
        *CONVERSATION_STATE_VALUES,
        name="conversation_state",
        create_type=False,
    )
    postgresql.ENUM(
        *CONVERSATION_STATE_VALUES, name="conversation_state"
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "conversaciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "empresa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contacto", sa.String(length=100), nullable=False),
        sa.Column(
            "state",
            conv_state,
            nullable=False,
            server_default="idle",
        ),
        sa.Column("current_op_id", sa.String(length=64)),
        sa.Column(
            "history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "opt_in_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "empresa_id", "contacto", name="uq_conversaciones_empresa_contacto"
        ),
    )
    op.create_index(
        "ix_conversaciones_empresa_contacto",
        "conversaciones",
        ["empresa_id", "contacto"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversaciones_empresa_contacto", table_name="conversaciones")
    op.drop_table("conversaciones")
    postgresql.ENUM(name="conversation_state").drop(
        op.get_bind(), checkfirst=True
    )
