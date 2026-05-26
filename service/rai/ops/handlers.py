"""Handlers for the 7 catalog operations.

Each handler receives an OpContext and returns a JSON-serializable result.
Light ops (ayuda, menu) and factura_consultar are implemented end-to-end.
The other heavy ops are stubs that pass through both gates and return
{"status": "not_implemented"}.

Handlers MUST NOT read empresa_id from `args` — only from `ctx.empresa_id`.
Args are already validated by the dispatcher against the catalog's schema.
"""
from __future__ import annotations

from typing import Any, Callable

from rai.catalog import menu_for_role
from rai.models import Factura
from rai.ops.context import OpContext

Handler = Callable[[OpContext], Any]


# --- Light ops --------------------------------------------------------------


def _ayuda(ctx: OpContext) -> dict[str, str]:
    return {
        "texto": (
            "Soy Rai, tu asistente. Tocá un botón del menú o escribime lo que "
            "necesités. Si querés volver al menú principal, escribí /menu."
        )
    }


def _menu(ctx: OpContext) -> dict[str, list[dict[str, str]]]:
    return {
        "items": [
            {"id": op.id, "label": op.menu_label} for op in menu_for_role(ctx.rol)
        ]
    }


# --- Heavy ops: factura_consultar implemented end-to-end --------------------


def _factura_consultar(ctx: OpContext) -> dict[str, Any]:
    # ctx.args is FacturaConsultarArgs (validated by dispatcher).
    args = ctx.args
    q = ctx.db.query(Factura).filter(Factura.empresa_id == ctx.empresa_id)
    if getattr(args, "desde", None) is not None:
        q = q.filter(Factura.fecha >= args.desde)
    if getattr(args, "hasta", None) is not None:
        q = q.filter(Factura.fecha <= args.hasta)
    if getattr(args, "estado", None):
        q = q.filter(Factura.estado == args.estado)
    rows = q.order_by(Factura.fecha.desc()).limit(args.limit).all()

    return {
        "facturas": [
            {
                "id": str(f.id),
                "numero": f.numero,
                "fecha": f.fecha.isoformat(),
                "total": str(f.total),
                "estado": f.estado,
                "detalle": f.detalle,
            }
            for f in rows
        ],
        "count": len(rows),
    }


# --- Heavy ops: stubs -------------------------------------------------------
# Every stub returns the same shape after gates have already passed.


def _not_implemented(operation_id: str) -> dict[str, str]:
    return {"status": "not_implemented", "operation": operation_id}


def _factura_crear(ctx: OpContext) -> dict[str, str]:
    return _not_implemented("factura_crear")


def _factura_anular(ctx: OpContext) -> dict[str, str]:
    return _not_implemented("factura_anular")


def _stock_consultar(ctx: OpContext) -> dict[str, str]:
    return _not_implemented("stock_consultar")


def _estadisticas(ctx: OpContext) -> dict[str, str]:
    return _not_implemented("estadisticas")


# --- Registry ---------------------------------------------------------------

HANDLERS: dict[str, Handler] = {
    "ayuda": _ayuda,
    "menu": _menu,
    "factura_consultar": _factura_consultar,
    "factura_crear": _factura_crear,
    "factura_anular": _factura_anular,
    "stock_consultar": _stock_consultar,
    "estadisticas": _estadisticas,
}
