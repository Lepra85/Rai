"""End-to-end tests for POST /op/{op_id}.

Covers: HMAC, identity, role gate, tenant gate, args validation, dispatch,
cross-tenant isolation (#1 risk per SPEC §5+§13), stub return shape.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from rai.auth import SIGNATURE_HEADER, compute_signature
from rai.models import Factura, Usuario
from rai.roles import Role
from tests.conftest import TEST_FLOW_API_SECRET


def _signed(client: TestClient, path: str, payload: dict) -> tuple[str, bytes, dict]:
    body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body, TEST_FLOW_API_SECRET)
    headers = {SIGNATURE_HEADER: sig, "Content-Type": "application/json"}
    return path, body, headers


def _post_op(
    client: TestClient,
    op_id: str,
    *,
    phone_number_id: str,
    contacto: str,
    args: dict | None = None,
):
    path = f"/op/{op_id}"
    payload = {
        "phone_number_id": phone_number_id,
        "contacto": contacto,
        "args": args or {},
    }
    _, body, headers = _signed(client, path, payload)
    return client.post(path, content=body, headers=headers)


# -- Fixtures specific to op tests ------------------------------------------


@pytest.fixture()
def encargado_a(db_session: Session, empresa_with_users) -> Usuario:
    """Add an encargado user to empresa_a, not in the base fixture."""
    u = Usuario(
        id=uuid.uuid4(),
        empresa_id=empresa_with_users["empresa_a"].id,
        contacto=f"enc_a_{uuid.uuid4().hex[:8]}",
        nombre="Encargado A",
        rol=Role.ENCARGADO,
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def facturas_a(db_session: Session, empresa_with_users) -> list[Factura]:
    empresa_a = empresa_with_users["empresa_a"]
    rows = [
        Factura(
            id=uuid.uuid4(),
            empresa_id=empresa_a.id,
            numero=f"A-{i:04d}",
            fecha=date(2026, 5, i + 1),
            total=Decimal(f"{100 + i}.50"),
            estado="emitida" if i % 2 == 0 else "anulada",
        )
        for i in range(4)
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


@pytest.fixture()
def facturas_b(db_session: Session, empresa_with_users) -> list[Factura]:
    """Invoices for empresa_b — used to prove cross-tenant isolation."""
    empresa_b = empresa_with_users["empresa_b"]
    rows = [
        Factura(
            id=uuid.uuid4(),
            empresa_id=empresa_b.id,
            numero=f"B-{i:04d}",
            fecha=date(2026, 5, i + 1),
            total=Decimal("999.99"),
            estado="emitida",
        )
        for i in range(3)
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


# -- Light ops ---------------------------------------------------------------


def test_ayuda_for_dueno_returns_help_text(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(client, "ayuda", phone_number_id=e.phone_number_id, contacto=u.contacto)
    assert r.status_code == 200
    assert "Rai" in r.json()["texto"]


def test_menu_for_empleado_is_role_filtered(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["empleado_a"]
    r = _post_op(client, "menu", phone_number_id=e.phone_number_id, contacto=u.contacto)
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()["items"]}
    # Empleado sees only ops with EMPLEADO in allowed_roles.
    assert ids == {"ayuda", "menu", "stock_consultar"}


# -- factura_consultar end-to-end -------------------------------------------


def test_factura_consultar_dueno_returns_invoices(
    client, empresa_with_users, facturas_a
):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_consultar",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"limit": 100},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 4
    assert {f["numero"] for f in data["facturas"]} == {"A-0000", "A-0001", "A-0002", "A-0003"}


def test_factura_consultar_filters_by_estado(client, empresa_with_users, facturas_a):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_consultar",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"estado": "emitida"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert all(f["estado"] == "emitida" for f in data["facturas"])


def test_factura_consultar_filters_by_date_range(
    client, empresa_with_users, facturas_a
):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_consultar",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"desde": "2026-05-02", "hasta": "2026-05-03"},
    )
    assert r.status_code == 200
    nums = {f["numero"] for f in r.json()["facturas"]}
    assert nums == {"A-0001", "A-0002"}


# -- Cross-tenant isolation (#1 risk) ---------------------------------------


def test_factura_consultar_never_leaks_other_tenant_invoices(
    client, empresa_with_users, facturas_b
):
    """SPEC §13: dueño A asking for invoices when B has them must get []."""
    e_a = empresa_with_users["empresa_a"]
    u_a = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_consultar",
        phone_number_id=e_a.phone_number_id,
        contacto=u_a.contacto,
    )
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["facturas"] == []


# -- Role gate --------------------------------------------------------------


def test_factura_anular_blocked_for_empleado(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["empleado_a"]
    r = _post_op(
        client,
        "factura_anular",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"factura_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "unauthorized"


def test_estadisticas_blocked_for_encargado(client, empresa_with_users, encargado_a):
    e = empresa_with_users["empresa_a"]
    r = _post_op(
        client,
        "estadisticas",
        phone_number_id=e.phone_number_id,
        contacto=encargado_a.contacto,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "unauthorized"


def test_factura_anular_allowed_for_dueno(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_anular",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"factura_id": str(uuid.uuid4())},
    )
    # Stub is reached (gate passed); returns not_implemented marker.
    assert r.status_code == 200
    assert r.json() == {"status": "not_implemented", "operation": "factura_anular"}


# -- Stubs are gated BEFORE returning their marker --------------------------


def test_factura_crear_stub_returns_not_implemented_for_dueno(
    client, empresa_with_users
):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_crear",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"numero": "F-1", "fecha": "2026-05-26", "total": "150.00"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "not_implemented", "operation": "factura_crear"}


def test_factura_crear_stub_blocked_for_empleado(client, empresa_with_users):
    """Role gate must reject BEFORE the stub's not_implemented body runs."""
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["empleado_a"]
    r = _post_op(
        client,
        "factura_crear",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"numero": "F-1", "fecha": "2026-05-26", "total": "150.00"},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "unauthorized"


# -- Unknown op, tenant, sender, args ---------------------------------------


def test_unknown_operation_returns_404(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(client, "ñoño", phone_number_id=e.phone_number_id, contacto=u.contacto)
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_operation"


def test_unknown_tenant_returns_404(client):
    r = _post_op(client, "ayuda", phone_number_id="ghost-tenant", contacto="anyone")
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tenant"


def test_unknown_sender_returns_404(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    r = _post_op(
        client, "ayuda", phone_number_id=e.phone_number_id, contacto="5499999999999"
    )
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_sender"


def test_invalid_args_returns_422(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = _post_op(
        client,
        "factura_consultar",
        phone_number_id=e.phone_number_id,
        contacto=u.contacto,
        args={"limit": 9999},  # exceeds max=100
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_args"


# -- HMAC layer remains the first gate --------------------------------------


def test_unsigned_op_request_returns_401(client, empresa_with_users):
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["dueno_a"]
    r = client.post(
        "/op/ayuda",
        json={"phone_number_id": e.phone_number_id, "contacto": u.contacto},
    )
    assert r.status_code == 401


def test_signature_check_runs_before_role_gate(client, empresa_with_users):
    """Even calling an op the empleado CANNOT invoke, a missing signature
    must return 401, not 403 — the signature gate is first."""
    e = empresa_with_users["empresa_a"]
    u = empresa_with_users["empleado_a"]
    r = client.post(
        "/op/factura_anular",
        json={"phone_number_id": e.phone_number_id, "contacto": u.contacto},
    )
    assert r.status_code == 401
