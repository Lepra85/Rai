"""Tests for the WhatsAppClient (Kapso outbound)."""
from __future__ import annotations

import json

import httpx
import pytest

from rai.whatsapp.client import (
    KAPSO_BASE_URL,
    KAPSO_GRAPH_VERSION,
    SendResult,
    WhatsAppClient,
)


# Bind the real Client BEFORE any monkeypatch so the lambda can call it
# without recursing into the patched version.
_REAL_HTTPX_CLIENT = httpx.Client


def _mock_transport(captured: dict) -> httpx.MockTransport:
    """Capture the outbound request and return Kapso's success shape."""
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "15551234567", "wa_id": "15551234567"}],
                "messages": [{"id": "wamid.XYZ"}],
            },
        )
    return httpx.MockTransport(handler)


def _patched_client_factory(transport: httpx.MockTransport):
    """Returns a callable usable as a drop-in replacement for httpx.Client."""
    def factory(**kw):
        return _REAL_HTTPX_CLIENT(transport=transport, **kw)
    return factory


def test_constructor_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="KAPSO_API_KEY"):
        WhatsAppClient(api_key="")


def test_send_text_hits_correct_url(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "rai.whatsapp.client.httpx.Client",
        _patched_client_factory(_mock_transport(captured)),
    )

    client = WhatsAppClient(api_key="secret-key")
    result = client.send_text(
        phone_number_id="110987654321",
        to="15551234567",
        body="hola",
    )

    assert result.wa_message_id == "wamid.XYZ"
    assert isinstance(result, SendResult)
    expected_url = f"{KAPSO_BASE_URL}/{KAPSO_GRAPH_VERSION}/110987654321/messages"
    assert captured["url"] == expected_url
    assert captured["method"] == "POST"
    assert captured["headers"]["x-api-key"] == "secret-key"
    sent = json.loads(captured["body"])
    assert sent["to"] == "15551234567"
    assert sent["type"] == "text"
    assert sent["text"]["body"] == "hola"
    assert sent["messaging_product"] == "whatsapp"


def test_send_text_propagates_http_errors(monkeypatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})
    monkeypatch.setattr(
        "rai.whatsapp.client.httpx.Client",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    client = WhatsAppClient(api_key="bad-key")
    with pytest.raises(httpx.HTTPStatusError):
        client.send_text(
            phone_number_id="110987654321", to="15551234567", body="hi"
        )


def test_mark_read_builds_correct_body(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "rai.whatsapp.client.httpx.Client",
        _patched_client_factory(_mock_transport(captured)),
    )

    client = WhatsAppClient(api_key="key")
    client.mark_read(phone_number_id="PNID", message_id="wamid.abc")

    sent = json.loads(captured["body"])
    assert sent["status"] == "read"
    assert sent["message_id"] == "wamid.abc"
    assert sent["messaging_product"] == "whatsapp"
