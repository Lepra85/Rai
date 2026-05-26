"""HMAC auth dependency tests."""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rai.auth import (
    SIGNATURE_HEADER,
    compute_signature,
    require_signed_request,
    verify_signature,
)
from rai.config import Settings


SECRET = "test-secret-do-not-use-in-prod"


def _app_with_settings(secret: str = SECRET) -> TestClient:
    """Build a tiny app whose only route requires a signed body."""
    from rai.config import get_settings

    app = FastAPI()

    def fake_settings() -> Settings:
        return Settings(flow_api_secret=secret)

    @app.post("/echo")
    async def echo(body: bytes = Depends(require_signed_request)) -> dict:
        return {"len": len(body)}

    app.dependency_overrides[get_settings] = fake_settings
    return TestClient(app)


def test_verify_signature_accepts_correct_signature() -> None:
    body = b'{"hello": "world"}'
    sig = compute_signature(body, SECRET)
    assert verify_signature(body, sig, SECRET) is True


def test_verify_signature_rejects_tampered_body() -> None:
    sig = compute_signature(b'{"a": 1}', SECRET)
    assert verify_signature(b'{"a": 2}', sig, SECRET) is False


def test_verify_signature_rejects_wrong_secret() -> None:
    body = b'{"a": 1}'
    sig = compute_signature(body, SECRET)
    assert verify_signature(body, sig, "different-secret") is False


def test_verify_signature_rejects_missing_prefix() -> None:
    body = b'{}'
    digest = compute_signature(body, SECRET).removeprefix("sha256=")
    # Without "sha256=" prefix it must fail.
    assert verify_signature(body, digest, SECRET) is False


def test_endpoint_accepts_signed_body() -> None:
    client = _app_with_settings()
    body = b'{"ping": true}'
    sig = compute_signature(body, SECRET)
    r = client.post("/echo", content=body, headers={SIGNATURE_HEADER: sig})
    assert r.status_code == 200
    assert r.json() == {"len": len(body)}


def test_endpoint_rejects_missing_header() -> None:
    client = _app_with_settings()
    r = client.post("/echo", content=b'{}')
    assert r.status_code == 401
    assert r.json()["detail"] == "missing signature"


def test_endpoint_rejects_invalid_signature() -> None:
    client = _app_with_settings()
    r = client.post("/echo", content=b'{}', headers={SIGNATURE_HEADER: "sha256=deadbeef"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid signature"


def test_endpoint_rejects_tampered_body() -> None:
    client = _app_with_settings()
    sig = compute_signature(b'{"a": 1}', SECRET)
    # Send a different body with the original signature.
    r = client.post("/echo", content=b'{"a": 999}', headers={SIGNATURE_HEADER: sig})
    assert r.status_code == 401


def test_endpoint_500_when_secret_not_configured() -> None:
    client = _app_with_settings(secret="")
    r = client.post(
        "/echo", content=b"{}", headers={SIGNATURE_HEADER: "sha256=anything"}
    )
    assert r.status_code == 500
    assert "FLOW_API_SECRET" in r.json()["detail"]
