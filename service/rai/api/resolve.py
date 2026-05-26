"""`POST /resolve` — identity → tenant + role + role-filtered menu (SPEC §7).

The Kapso flow calls this once at the start of every conversation to learn:
  - which empresa the message is for (resolved from `phone_number_id`)
  - whether the sender is registered for that empresa
  - if registered: the user's role and the menu they may see

Authorization is NOT enforced here — this endpoint only RESOLVES identity.
The two gates (role + tenant) run on every `/op/{id}` call (Task 5).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rai.auth import require_signed_request
from rai.catalog import menu_for_role
from rai.db import get_db
from rai.identity import resolve_caller
from rai.roles import Role

log = logging.getLogger(__name__)

router = APIRouter()


class ResolveRequest(BaseModel):
    phone_number_id: str = Field(min_length=1, description="Receiving WhatsApp number id (tenant key).")
    contacto: str = Field(min_length=1, description="Stable sender contact id from Kapso.")


class MenuItem(BaseModel):
    id: str
    label: str


class EmpresaInfo(BaseModel):
    id: uuid.UUID
    nombre: str


class UsuarioInfo(BaseModel):
    id: uuid.UUID
    nombre: str


class ResolveOk(BaseModel):
    registered: bool = True
    empresa: EmpresaInfo
    usuario: UsuarioInfo
    rol: Role
    menu: list[MenuItem]


class ResolveUnregistered(BaseModel):
    registered: bool = False


@router.post(
    "/resolve",
    response_model=ResolveOk | ResolveUnregistered,
    responses={
        401: {"description": "Missing or invalid signature."},
        404: {"description": "Tenant (phone_number_id) is not registered."},
    },
)
async def resolve(
    body: bytes = Depends(require_signed_request),
    db: Session = Depends(get_db),
) -> ResolveOk | ResolveUnregistered:
    req = ResolveRequest.model_validate_json(body)

    # UnknownTenantError → 404 via the global exception handler.
    resolved = resolve_caller(db, req.phone_number_id, req.contacto)
    if resolved is None:
        # Polite-rejection path from SPEC §11.
        return ResolveUnregistered()

    menu = [
        MenuItem(id=op.id, label=op.menu_label)
        for op in menu_for_role(resolved.usuario.rol)
    ]

    return ResolveOk(
        empresa=EmpresaInfo(id=resolved.empresa.id, nombre=resolved.empresa.nombre),
        usuario=UsuarioInfo(id=resolved.usuario.id, nombre=resolved.usuario.nombre),
        rol=resolved.usuario.rol,
        menu=menu,
    )
