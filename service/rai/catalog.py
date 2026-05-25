"""Operations catalog — single source of truth (SPEC §6).

Drives three things from one declaration: the role-filtered WhatsApp menu,
the agent-node tool schemas, and the authorization gate. No second list to
keep in sync.

This module is pure metadata: it must NOT import FastAPI, SQLAlchemy, or any
handler. Tests, codegen, and the future JS flow tooling all import it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from rai.ops import schemas
from rai.roles import Role

OperationKind = Literal["light", "heavy"]


@dataclass(frozen=True)
class Operation:
    """Static declaration of a domain operation.

    Handler resolution happens elsewhere — Task 5 keeps the handler registry
    separate so stubs are trivially distinguishable from real implementations.
    """

    id: str
    args_schema: type[BaseModel]
    menu_label: str
    agent_description: str
    allowed_roles: frozenset[Role]
    kind: OperationKind


def _op(
    op_id: str,
    args_schema: type[BaseModel],
    menu_label: str,
    agent_description: str,
    allowed_roles: frozenset[Role],
    kind: OperationKind,
) -> tuple[str, Operation]:
    return op_id, Operation(
        id=op_id,
        args_schema=args_schema,
        menu_label=menu_label,
        agent_description=agent_description,
        allowed_roles=allowed_roles,
        kind=kind,
    )


OPERATIONS: dict[str, Operation] = dict(
    [
        _op(
            "ayuda",
            schemas.EmptyArgs,
            "Ayuda",
            "Devuelve un texto de ayuda explicando cómo usar Rai.",
            frozenset(Role),
            "light",
        ),
        _op(
            "menu",
            schemas.EmptyArgs,
            "Menú",
            "Vuelve a mostrar el menú principal.",
            frozenset(Role),
            "light",
        ),
        _op(
            "factura_consultar",
            schemas.FacturaConsultarArgs,
            "Consultar facturas",
            "Consulta facturas de la empresa, con filtros opcionales por fechas y estado.",
            frozenset({Role.DUEÑO, Role.ENCARGADO}),
            "heavy",
        ),
        _op(
            "factura_crear",
            schemas.FacturaCrearArgs,
            "Crear factura",
            "Crea una nueva factura para la empresa.",
            frozenset({Role.DUEÑO, Role.ENCARGADO}),
            "heavy",
        ),
        _op(
            "factura_anular",
            schemas.FacturaAnularArgs,
            "Anular factura",
            "Anula una factura existente de la empresa.",
            frozenset({Role.DUEÑO}),
            "heavy",
        ),
        _op(
            "stock_consultar",
            schemas.StockConsultarArgs,
            "Consultar stock",
            "Consulta el stock actual de la empresa, opcionalmente filtrando por SKU.",
            frozenset({Role.DUEÑO, Role.ENCARGADO, Role.EMPLEADO}),
            "heavy",
        ),
        _op(
            "estadisticas",
            schemas.EstadisticasArgs,
            "Estadísticas",
            "Devuelve estadísticas del negocio para el período indicado.",
            frozenset({Role.DUEÑO}),
            "heavy",
        ),
    ]
)


def menu_for_role(rol: Role) -> list[Operation]:
    """Return operations the given role may invoke, in declaration order.

    Used to build the role-filtered WhatsApp menu (SPEC §7 /resolve output).
    """
    return [op for op in OPERATIONS.values() if rol in op.allowed_roles]


def tools_for_role(rol: Role) -> list[Operation]:
    """Return operations the given role may invoke, intended for LLM tool exposure.

    Same filter as `menu_for_role`; the distinction is semantic (callers know
    they are building tools, not menu items) and lets us diverge later if the
    agent surface needs different metadata.
    """
    return [op for op in OPERATIONS.values() if rol in op.allowed_roles]
