"""HMAC signature verification for inbound webhook calls (SPEC §10).

The Kapso flow signs every webhook body with the shared FLOW_API_SECRET
and sends the digest as `X-Rai-Signature: sha256=<hex>`. Python verifies
the signature before running any handler logic. Deny-by-default: any
mismatch, missing header, or wrong format → 401.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Depends, HTTPException, Request, status

from rai.config import Settings, get_settings

SIGNATURE_HEADER = "X-Rai-Signature"
SIGNATURE_PREFIX = "sha256="


def compute_signature(body: bytes, secret: str) -> str:
    """Return the canonical `sha256=<hex>` signature for `body` under `secret`."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Timing-safe check of a `sha256=<hex>` signature against `body`."""
    if not signature.startswith(SIGNATURE_PREFIX):
        return False
    expected = compute_signature(body, secret)
    return hmac.compare_digest(expected, signature)


async def require_signed_request(
    request: Request, settings: Settings = Depends(get_settings)
) -> bytes:
    """FastAPI dependency: verify HMAC, return the raw body bytes on success.

    Returning the body lets the handler parse it itself with Pydantic instead
    of reading the request stream a second time (which would fail).
    """
    if not settings.flow_api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FLOW_API_SECRET not configured",
        )

    signature = request.headers.get(SIGNATURE_HEADER, "")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing signature",
        )

    body = await request.body()
    if not verify_signature(body, signature, settings.flow_api_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )

    return body
