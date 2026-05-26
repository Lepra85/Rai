"""End-to-end tests for POST /resolve."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from rai.auth import SIGNATURE_HEADER, compute_signature
from tests.conftest import TEST_FLOW_API_SECRET


def _signed(client: TestClient, payload: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body, TEST_FLOW_API_SECRET)
    return body, {SIGNATURE_HEADER: sig, "Content-Type": "application/json"}


def test_resolve_dueno_returns_full_menu(client, empresa_with_users) -> None:
    empresa = empresa_with_users["empresa_a"]
    dueno = empresa_with_users["dueno_a"]

    body, headers = _signed(
        client, {"phone_number_id": empresa.phone_number_id, "contacto": dueno.contacto}
    )
    r = client.post("/resolve", content=body, headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["registered"] is True
    assert data["empresa"]["nombre"] == "Café A"
    assert data["usuario"]["nombre"] == "Dueño A"
    assert data["rol"] == "dueño"

    menu_ids = {item["id"] for item in data["menu"]}
    assert menu_ids == {
        "ayuda",
        "menu",
        "factura_consultar",
        "factura_crear",
        "factura_anular",
        "stock_consultar",
        "estadisticas",
    }


def test_resolve_empleado_gets_role_filtered_menu(client, empresa_with_users) -> None:
    empresa = empresa_with_users["empresa_a"]
    empleado = empresa_with_users["empleado_a"]

    body, headers = _signed(
        client,
        {"phone_number_id": empresa.phone_number_id, "contacto": empleado.contacto},
    )
    r = client.post("/resolve", content=body, headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["rol"] == "empleado"

    menu_ids = {item["id"] for item in data["menu"]}
    assert "factura_anular" not in menu_ids
    assert "estadisticas" not in menu_ids
    assert "factura_crear" not in menu_ids
    assert {"ayuda", "menu", "stock_consultar"} <= menu_ids


def test_resolve_unknown_contacto_returns_registered_false(
    client, empresa_with_users
) -> None:
    empresa = empresa_with_users["empresa_a"]

    body, headers = _signed(
        client,
        {"phone_number_id": empresa.phone_number_id, "contacto": "5491999999999"},
    )
    r = client.post("/resolve", content=body, headers=headers)

    assert r.status_code == 200
    assert r.json() == {"registered": False}


def test_resolve_unknown_tenant_returns_404(client) -> None:
    body, headers = _signed(
        client,
        {"phone_number_id": "phone_does_not_exist", "contacto": "anyone"},
    )
    r = client.post("/resolve", content=body, headers=headers)

    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tenant"


def test_resolve_rejects_unsigned_request(client, empresa_with_users) -> None:
    empresa = empresa_with_users["empresa_a"]

    r = client.post(
        "/resolve",
        json={"phone_number_id": empresa.phone_number_id, "contacto": "x"},
    )

    assert r.status_code == 401


def test_resolve_does_not_leak_other_tenant_users(client, empresa_with_users) -> None:
    """Cross-tenant safety: a contacto registered in empresa B must NOT resolve
    when phone_number_id points to empresa A."""
    empresa_a = empresa_with_users["empresa_a"]
    dueno_b = empresa_with_users["dueno_b"]

    body, headers = _signed(
        client,
        {"phone_number_id": empresa_a.phone_number_id, "contacto": dueno_b.contacto},
    )
    r = client.post("/resolve", content=body, headers=headers)

    assert r.status_code == 200
    assert r.json() == {"registered": False}
