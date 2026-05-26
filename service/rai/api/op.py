"""POST /op/{op_id} — single dispatcher for all catalog operations (SPEC §7).

Order on every call (any step failing terminates with the appropriate error):
  1. HMAC signature (the `require_signed_request` dependency).
  2. Identity resolution: phone_number_id → empresa, contacto → usuario+rol.
     Tenant unknown → UnknownTenantError.
     Sender unknown → UnknownSenderError.
  3. Operation lookup: op_id ∈ catalog. Else UnknownOperationError.
  4. Role gate: rol ∈ op.allowed_roles. Else UnauthorizedError.
  5. Args validation against op.args_schema. Else InvalidArgsError.
  6. Dispatch to HANDLERS[op_id] with an OpContext.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from rai.auth import require_signed_request
from rai.catalog import OPERATIONS
from rai.db import get_db
from rai.errors import (
    InvalidArgsError,
    UnauthorizedError,
    UnknownOperationError,
    UnknownSenderError,
)
from rai.identity import resolve_caller
from rai.ops.context import OpContext
from rai.ops.handlers import HANDLERS

router = APIRouter()


class OpRequest(BaseModel):
    phone_number_id: str = Field(min_length=1)
    contacto: str = Field(min_length=1)
    args: dict = Field(default_factory=dict)
    message_id: str | None = None


@router.post("/op/{op_id}")
async def dispatch(
    op_id: str = Path(..., min_length=1),
    body: bytes = Depends(require_signed_request),
    db: Session = Depends(get_db),
) -> Any:
    req = OpRequest.model_validate_json(body)

    # 1. Lookup op (before identity so we fail fast on bad URLs).
    op = OPERATIONS.get(op_id)
    if op is None:
        raise UnknownOperationError(f"unknown operation: {op_id}")

    # 2. Identity (also runs the implicit tenant gate via DB scoping).
    resolved = resolve_caller(db, req.phone_number_id, req.contacto)
    if resolved is None:
        raise UnknownSenderError("sender is not registered for this tenant")

    # 3. Role gate.
    if resolved.usuario.rol not in op.allowed_roles:
        raise UnauthorizedError(
            f"role {resolved.usuario.rol.value} cannot invoke {op_id}"
        )

    # 4. Args validation against catalog schema.
    try:
        args_model = op.args_schema.model_validate(req.args)
    except ValidationError as e:
        raise InvalidArgsError(str(e))

    # 5. Dispatch.
    ctx = OpContext(
        db=db,
        empresa_id=resolved.empresa.id,
        usuario_id=resolved.usuario.id,
        rol=resolved.usuario.rol,
        args=args_model,
        message_id=req.message_id,
    )
    handler = HANDLERS[op_id]
    return handler(ctx)
