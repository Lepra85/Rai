"""POST /webhook/whatsapp — inbound from Kapso.

Kapso signs every webhook with HMAC-SHA256 over the raw body using the
secret configured in the Kapso dashboard, sending the hex digest in the
`X-Webhook-Signature` header.

This commit focuses on the receiver mechanics only: verify signature,
parse payload, log a one-line summary of each message. The actual
business logic (state machine, menu rendering, agent loop) lands in
later commits.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from rai.config import Settings, get_settings

log = logging.getLogger(__name__)

router = APIRouter()

KAPSO_SIGNATURE_HEADER = "X-Webhook-Signature"


def verify_kapso_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Timing-safe verify of Kapso's webhook signature.

    Kapso sends just the hex digest (no `sha256=` prefix), computed as
    HMAC-SHA256(secret, raw_body).
    """
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


async def require_kapso_signed_request(
    request: Request, settings: Settings = Depends(get_settings)
) -> bytes:
    """FastAPI dependency: validate Kapso's HMAC, return raw body bytes."""
    if not settings.kapso_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KAPSO_WEBHOOK_SECRET not configured",
        )

    signature = request.headers.get(KAPSO_SIGNATURE_HEADER, "")
    body = await request.body()
    if not verify_kapso_signature(body, signature, settings.kapso_webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid kapso webhook signature",
        )
    return body


def _summarize_messages(payload: dict[str, Any]) -> list[str]:
    """Produce one short log line per inbound message in the payload.

    Kapso's normalized payload (after passing through their proxy) keeps
    the Meta shape but adds normalized fields. We log against the Meta
    structure for resilience: entry[].changes[].value.messages[].
    """
    summaries: list[str] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            phone_id = (value.get("metadata") or {}).get("phone_number_id") or "?"
            for msg in value.get("messages", []) or []:
                kind = msg.get("type", "?")
                sender = msg.get("from", "?")
                if kind == "text":
                    text = (msg.get("text") or {}).get("body", "")
                    summaries.append(
                        f"phone_id={phone_id} from={sender} type=text body={text!r}"
                    )
                elif kind == "interactive":
                    inter = msg.get("interactive") or {}
                    sub = inter.get("type", "?")
                    summaries.append(
                        f"phone_id={phone_id} from={sender} type=interactive sub={sub}"
                    )
                else:
                    summaries.append(
                        f"phone_id={phone_id} from={sender} type={kind}"
                    )
    return summaries


@router.post("/webhook/whatsapp", status_code=200)
async def whatsapp_webhook(
    body: bytes = Depends(require_kapso_signed_request),
) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        log.warning("webhook: invalid JSON: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid json",
        )

    summaries = _summarize_messages(payload)
    if summaries:
        for s in summaries:
            log.info("inbound: %s", s)
    else:
        # Statuses, contacts updates, etc. We accept them silently for now.
        log.debug("inbound: non-message payload (statuses/contacts/...)")

    # Kapso considers any 2xx an ACK and will not retry. Real handling
    # belongs in a later commit; for now we accept and move on.
    return {"received": len(summaries)}
