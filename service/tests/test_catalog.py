"""Catalog tests — covers the role-gating shape from SPEC §6 + §13."""
from __future__ import annotations

from pydantic import BaseModel

from rai.catalog import OPERATIONS, menu_for_role, tools_for_role
from rai.roles import Role

EXPECTED_OP_IDS = {
    "ayuda",
    "menu",
    "factura_consultar",
    "factura_crear",
    "factura_anular",
    "stock_consultar",
    "estadisticas",
}


def test_catalog_has_exactly_seven_operations() -> None:
    assert set(OPERATIONS) == EXPECTED_OP_IDS


def test_dueno_sees_all_seven_operations() -> None:
    visible = {op.id for op in menu_for_role(Role.DUEÑO)}
    assert visible == EXPECTED_OP_IDS


def test_empleado_does_not_see_owner_only_ops() -> None:
    visible = {op.id for op in menu_for_role(Role.EMPLEADO)}
    assert "factura_anular" not in visible
    assert "estadisticas" not in visible


def test_empleado_sees_help_menu_and_stock() -> None:
    visible = {op.id for op in menu_for_role(Role.EMPLEADO)}
    assert {"ayuda", "menu", "stock_consultar"} <= visible


def test_encargado_can_query_and_create_invoices_but_not_void() -> None:
    visible = {op.id for op in menu_for_role(Role.ENCARGADO)}
    assert "factura_consultar" in visible
    assert "factura_crear" in visible
    assert "factura_anular" not in visible


def test_allowed_roles_matches_spec_section_6() -> None:
    expected: dict[str, frozenset[Role]] = {
        "ayuda": frozenset(Role),
        "menu": frozenset(Role),
        "factura_consultar": frozenset({Role.DUEÑO, Role.ENCARGADO}),
        "factura_crear": frozenset({Role.DUEÑO, Role.ENCARGADO}),
        "factura_anular": frozenset({Role.DUEÑO}),
        "stock_consultar": frozenset({Role.DUEÑO, Role.ENCARGADO, Role.EMPLEADO}),
        "estadisticas": frozenset({Role.DUEÑO}),
    }
    for op_id, allowed in expected.items():
        assert OPERATIONS[op_id].allowed_roles == allowed, op_id


def test_tools_for_role_matches_menu_for_role() -> None:
    for rol in Role:
        assert [op.id for op in tools_for_role(rol)] == [
            op.id for op in menu_for_role(rol)
        ]


def test_every_op_has_pydantic_args_schema() -> None:
    for op in OPERATIONS.values():
        assert issubclass(op.args_schema, BaseModel), op.id


def test_kinds_match_spec() -> None:
    light_ids = {op.id for op in OPERATIONS.values() if op.kind == "light"}
    heavy_ids = {op.id for op in OPERATIONS.values() if op.kind == "heavy"}
    assert light_ids == {"ayuda", "menu"}
    assert heavy_ids == {
        "factura_consultar",
        "factura_crear",
        "factura_anular",
        "stock_consultar",
        "estadisticas",
    }


def test_menu_for_role_preserves_declaration_order() -> None:
    declaration_order = list(OPERATIONS)
    for rol in Role:
        visible = [op.id for op in menu_for_role(rol)]
        positions = [declaration_order.index(op_id) for op_id in visible]
        assert positions == sorted(positions), rol
