"""Shared identity resolution. Both /resolve and /op/{id} call resolve_caller."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from rai.errors import UnknownTenantError
from rai.models import Empresa, Usuario


@dataclass(frozen=True)
class ResolvedCaller:
    empresa: Empresa
    usuario: Usuario


def resolve_caller(
    db: Session, phone_number_id: str, contacto: str
) -> ResolvedCaller | None:
    """Map (phone_number_id, contacto) → (empresa, usuario).

    Returns None if the tenant exists but the sender is not registered (the
    polite-rejection path from SPEC §11). Raises UnknownTenantError if the
    phone_number_id does not map to any empresa — that's an operational issue,
    not a normal flow.
    """
    empresa = (
        db.query(Empresa)
        .filter(Empresa.phone_number_id == phone_number_id)
        .one_or_none()
    )
    if empresa is None:
        raise UnknownTenantError(f"unknown phone_number_id={phone_number_id}")

    usuario = (
        db.query(Usuario)
        .filter(
            Usuario.empresa_id == empresa.id,
            Usuario.contacto == contacto,
        )
        .one_or_none()
    )
    if usuario is None:
        return None

    return ResolvedCaller(empresa=empresa, usuario=usuario)
