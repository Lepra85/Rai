"""Seed script — create one empresa + one dueño user for local testing.

Idempotent: re-running uses lookup-by-`phone_number_id` (NOT a hardcoded UUID).
"""
from __future__ import annotations

import os
import sys
import uuid

# Allow running as `python service/scripts/seed.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rai.db import get_session_factory  # noqa: E402
from rai.models import Empresa, Usuario  # noqa: E402
from rai.roles import Role  # noqa: E402

SEED_PHONE_NUMBER_ID = "RAI_LOCAL_TEST_TENANT"
SEED_CONTACTO = "5491100000000"  # placeholder local contact id


def main() -> int:
    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        empresa = (
            db.query(Empresa)
            .filter(Empresa.phone_number_id == SEED_PHONE_NUMBER_ID)
            .one_or_none()
        )
        if empresa is None:
            empresa = Empresa(
                id=uuid.uuid4(),
                nombre="Café de prueba",
                phone_number_id=SEED_PHONE_NUMBER_ID,
            )
            db.add(empresa)
            db.flush()
            print(f"[seed] created empresa {empresa.id} ({empresa.nombre})")
        else:
            print(f"[seed] empresa already exists: {empresa.id} ({empresa.nombre})")

        usuario = (
            db.query(Usuario)
            .filter(
                Usuario.empresa_id == empresa.id,
                Usuario.contacto == SEED_CONTACTO,
            )
            .one_or_none()
        )
        if usuario is None:
            usuario = Usuario(
                id=uuid.uuid4(),
                empresa_id=empresa.id,
                contacto=SEED_CONTACTO,
                nombre="Romeo (dueño de prueba)",
                rol=Role.DUEÑO,
            )
            db.add(usuario)
            print(f"[seed] created usuario {usuario.id} (rol={usuario.rol.value})")
        else:
            print(f"[seed] usuario already exists: {usuario.id} (rol={usuario.rol.value})")

        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
