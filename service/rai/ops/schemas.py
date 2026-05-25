"""Pydantic args schemas for each operation in the catalog.

Kept in a separate module so `rai.catalog` stays scannable (it references
schemas as class objects, not definitions).

Heavy ops that are stubbed for now still carry their full args schema so the
contract is fixed before the handler exists.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class EmptyArgs(BaseModel):
    """Operations that take no arguments (light helpers, menu re-render)."""


class FacturaConsultarArgs(BaseModel):
    """Query invoices for the caller's empresa."""

    desde: date | None = Field(
        default=None, description="Lower bound (inclusive) for the invoice date."
    )
    hasta: date | None = Field(
        default=None, description="Upper bound (inclusive) for the invoice date."
    )
    estado: str | None = Field(
        default=None, description="Filter by invoice status, e.g. 'emitida' or 'anulada'."
    )
    limit: int = Field(default=20, ge=1, le=100)


class FacturaCrearArgs(BaseModel):
    """Create a new invoice."""

    numero: str = Field(min_length=1, max_length=50)
    fecha: date
    total: Decimal = Field(gt=0)
    detalle: str | None = Field(default=None, max_length=500)


class FacturaAnularArgs(BaseModel):
    """Void an existing invoice belonging to the caller's empresa."""

    factura_id: str = Field(min_length=1, description="UUID of the invoice to void.")
    motivo: str | None = Field(default=None, max_length=500)


class StockConsultarArgs(BaseModel):
    """Check stock levels."""

    sku: str | None = Field(default=None, description="Specific SKU; omit for full inventory.")
    limit: int = Field(default=50, ge=1, le=200)


class EstadisticasArgs(BaseModel):
    """Business stats. The exact stats set is an open question (SPEC §14.5)."""

    periodo: str = Field(
        default="mes_actual",
        description="Reporting window. Pending spec confirmation.",
    )
