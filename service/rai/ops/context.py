"""OpContext — what every handler receives.

empresa_id lives here (NOT in args schemas) so handlers cannot accidentally
use a client-supplied tenant. The dispatcher derives empresa_id from the
authenticated payload and constructs the context.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.orm import Session

from rai.roles import Role


@dataclass(frozen=True)
class OpContext:
    db: Session
    empresa_id: uuid.UUID
    usuario_id: uuid.UUID
    rol: Role
    args: BaseModel
    message_id: str | None = None
