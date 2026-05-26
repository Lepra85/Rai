"""Tests for POST /webhook/whatsapp (Kapso inbound)."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rai.api.webhook import (
    KAPSO_SIGNATURE_HEADER,
    require_kapso_signed_request,
    verify_kapso_signature,
)
from rai.config import Settings, get_settings

SECRET = "kapso-webhook-secret-test-only"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _client(secret: str = SECRET) -> TestClient:
    """Tiny app that exercises the auth dep in isolation."""
    app = FastAPI()

    def fake_settings() -> Settings:
        return Settings(kapso_webhook_secret=secret)

    @app.post("/echo")
    async def echo(body: bytes = Depends(require_kapso_signed_request)) -> dict:
        return {"len": len(body)}

    app.dependency_overrides[get_settings] = fake_settings
    return TestClient(app)


# -- verify_kapso_signature unit tests --------------------------------------


def test_verify_accepts_correct_signature() -> None:
    body = b'{"hello":"world"}'
    assert verify_kapso_signature(body, _sign(body), SECRET) is True


def test_verify_is_case_insensitive_on_hex() -> None:
    body = b'{"hello":"world"}'
    sig_upper = _sign(body).upper()
    assert verify_kapso_signature(body, sig_upper, SECRET) is True


def test_verify_rejects_tampered_body() -> None:
    sig = _sign(b'{"a":1}')
    assert verify_kapso_signature(b'{"a":2}', sig, SECRET) is False


def test_verify_rejects_wrong_secret() -> None:
    body = b'{"a":1}'
    assert verify_kapso_signature(body, _sign(body), "different-secret") is False


def test_verify_rejects_empty_signature() -> None:
    assert verify_kapso_signature(b"{}", "", SECRET) is False


# -- dependency-level tests against a stand-in endpoint ---------------------


def test_dep_accepts_signed_body() -> None:
    client = _client()
    body = b'{"ping":true}'
    r = client.post("/echo", content=body, headers={KAPSO_SIGNATURE_HEADER: _sign(body)})
    assert r.status_code == 200
    assert r.json() == {"len": len(body)}


def test_dep_rejects_missing_header() -> None:
    client = _client()
    r = client.post("/echo", content=b"{}")
    assert r.status_code == 401


def test_dep_rejects_invalid_header() -> None:
    client = _client()
    r = client.post("/echo", content=b"{}", headers={KAPSO_SIGNATURE_HEADER: "deadbeef"})
    assert r.status_code == 401


def test_dep_500_when_secret_not_configured() -> None:
    client = _client(secret="")
    r = client.post("/echo", content=b"{}", headers={KAPSO_SIGNATURE_HEADER: "anything"})
    assert r.status_code == 500


# -- /webhook/whatsapp through the real app ---------------------------------


def test_webhook_accepts_meta_style_text_payload(client) -> None:
    """End-to-end: a Meta-style inbound text message passes signature
    check and returns a 200 with the count of summarized messages."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {
                                "display_phone_number": "5491100000000",
                                "phone_number_id": "PNID_123",
                            },
                            "messages": [
                                {
                                    "from": "5491199999999",
                                    "id": "wamid.abc",
                                    "type": "text",
                                    "text": {"body": "hola"},
                                    "timestamp": "1700000000",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    # Override the webhook secret on the shared client fixture for this test.
    from rai.config import get_settings as real_gs

    def gs() -> Settings:
        return Settings(kapso_webhook_secret=SECRET, flow_api_secret="ignored")

    client.app.dependency_overrides[real_gs] = gs
    try:
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        client.app.dependency_overrides.pop(real_gs, None)

    assert r.status_code == 200
    assert r.json() == {"received": 1}


def test_webhook_rejects_unsigned(client) -> None:
    r = client.post("/webhook/whatsapp", json={"object": "whatsapp_business_account"})
    # Either 401 (missing signature) or 500 (no secret) — both are "rejected".
    assert r.status_code in (401, 500)


def test_webhook_accepts_kapso_v2_inbound_text(client) -> None:
    """Kapso payload_version=v2: single-message envelope with `message`,
    `conversation`, `phone_number_id`, `is_new_conversation` at top level."""
    payload = {
        "message": {
            "id": "wamid.v2_test",
            "timestamp": "1779800000",
            "type": "text",
            "from": "5491100000000",
            "text": {"body": "hola"},
            "kapso": {"direction": "inbound", "content": "hola"},
        },
        "conversation": {"id": "conv_x", "phone_number": "5491100000000"},
        "is_new_conversation": True,
        "phone_number_id": "597907523413541",
    }
    body = json.dumps(payload).encode("utf-8")
    from rai.config import get_settings as real_gs

    def gs() -> Settings:
        return Settings(kapso_webhook_secret=SECRET, flow_api_secret="ignored")

    client.app.dependency_overrides[real_gs] = gs
    try:
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        client.app.dependency_overrides.pop(real_gs, None)

    assert r.status_code == 200
    assert r.json() == {"received": 1}


def test_webhook_handles_outbound_v2_payload(client) -> None:
    """whatsapp.message.sent events arrive as v2 with direction=outbound.
    They should still be accepted (received=1, gives observability)."""
    payload = {
        "message": {
            "id": "wamid.out",
            "type": "text",
            "from": "597907523413541",
            "text": {"body": "respuesta"},
            "kapso": {"direction": "outbound"},
        },
        "conversation": {"id": "conv_y", "phone_number": "5491100000000"},
        "is_new_conversation": False,
        "phone_number_id": "597907523413541",
    }
    body = json.dumps(payload).encode("utf-8")
    from rai.config import get_settings as real_gs

    def gs() -> Settings:
        return Settings(kapso_webhook_secret=SECRET, flow_api_secret="ignored")

    client.app.dependency_overrides[real_gs] = gs
    try:
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        client.app.dependency_overrides.pop(real_gs, None)

    assert r.status_code == 200
    assert r.json() == {"received": 1}


# --- Demo dispatcher (M' UX experiment) -------------------------------------


class _FakeWAClient:
    """Stand-in for WhatsAppClient that records calls without hitting Kapso."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def send_text(self, **kw):
        self.calls.append(("send_text", kw))

    def send_buttons(self, **kw):
        self.calls.append(("send_buttons", kw))

    def send_list(self, **kw):
        self.calls.append(("send_list", kw))


def _client_with_fake_wa(secret: str = SECRET) -> tuple[TestClient, _FakeWAClient]:
    from rai.api.webhook import get_default_client as wc_dep
    from rai.config import get_settings as real_gs
    from rai.main import app

    fake = _FakeWAClient()

    def fake_settings() -> Settings:
        return Settings(kapso_webhook_secret=secret, kapso_api_key="ignored")

    app.dependency_overrides[real_gs] = fake_settings
    app.dependency_overrides[wc_dep] = lambda: fake
    return TestClient(app), fake


def _v2_inbound_text(text: str = "hola") -> bytes:
    return json.dumps(
        {
            "message": {
                "id": "wamid.1",
                "type": "text",
                "from": "541159200080",
                "text": {"body": text},
                "kapso": {"direction": "inbound"},
            },
            "conversation": {"id": "c", "phone_number": "541159200080"},
            "is_new_conversation": True,
            "phone_number_id": "597907523413541",
        }
    ).encode()


def _v2_interactive_button_tap(button_id: str = "btn_pedidos") -> bytes:
    return json.dumps(
        {
            "message": {
                "id": "wamid.2",
                "type": "interactive",
                "from": "541159200080",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": button_id, "title": "Pedidos"},
                },
                "kapso": {"direction": "inbound"},
            },
            "conversation": {"id": "c", "phone_number": "541159200080"},
            "is_new_conversation": False,
            "phone_number_id": "597907523413541",
        }
    ).encode()


def test_demo_dispatch_text_sends_buttons_and_list() -> None:
    c, fake = _client_with_fake_wa()
    try:
        body = _v2_inbound_text("hola")
        r = c.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        from rai.main import app
        app.dependency_overrides.clear()

    assert r.status_code == 200
    methods = [m for m, _ in fake.calls]
    assert methods == ["send_buttons", "send_list"]
    btn_call = fake.calls[0][1]
    titles = [b["title"] for b in btn_call["buttons"]]
    assert titles == ["Pedidos", "Devolucion", "Comprobantes"]
    list_call = fake.calls[1][1]
    list_ids = [r["id"] for r in list_call["sections"][0]["rows"]]
    assert list_ids == [
        "animal_perro",
        "animal_gato",
        "animal_hamster",
        "animal_tortuga",
        "animal_cobaya",
    ]


def test_demo_dispatch_button_tap_echoes() -> None:
    c, fake = _client_with_fake_wa()
    try:
        body = _v2_interactive_button_tap("btn_devolucion")
        r = c.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        from rai.main import app
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert len(fake.calls) == 1
    method, kw = fake.calls[0]
    assert method == "send_text"
    assert "btn_devolucion" in kw["body"]


def test_demo_dispatch_pedidos_command_sends_report() -> None:
    """/pedidos slash command → single send_text with the chofer report."""
    c, fake = _client_with_fake_wa()
    try:
        body = _v2_inbound_text("/pedidos")
        r = c.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        from rai.main import app
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert len(fake.calls) == 1
    method, kw = fake.calls[0]
    assert method == "send_text"
    # Spot-check the report shape and known content.
    assert "INTERNO 6 - RIVERO JORGE" in kw["body"]
    assert "Total transferido" in kw["body"]
    assert "2.471.210,01" in kw["body"]
    # Should NOT also send buttons/list.
    assert all(m != "send_buttons" for m, _ in fake.calls)
    assert all(m != "send_list" for m, _ in fake.calls)


def test_demo_dispatch_pedidos_is_case_insensitive_and_trims() -> None:
    c, fake = _client_with_fake_wa()
    try:
        body = _v2_inbound_text("  /Pedidos  ")
        r = c.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        from rai.main import app
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "send_text"


def test_demo_dispatch_skips_outbound_messages() -> None:
    """We must NOT respond to our own outbound sends (would infinite-loop)."""
    c, fake = _client_with_fake_wa()
    try:
        payload = {
            "message": {
                "id": "wamid.out",
                "type": "text",
                "from": "597907523413541",
                "text": {"body": "hi"},
                "kapso": {"direction": "outbound"},
            },
            "phone_number_id": "597907523413541",
        }
        body = json.dumps(payload).encode()
        r = c.post(
            "/webhook/whatsapp",
            content=body,
            headers={KAPSO_SIGNATURE_HEADER: _sign(body)},
        )
    finally:
        from rai.main import app
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert fake.calls == []  # zero sends in response
