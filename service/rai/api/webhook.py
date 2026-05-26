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
from rai.whatsapp.client import WhatsAppClient, get_default_client

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


def _summarize_kapso_v2(payload: dict[str, Any]) -> str | None:
    """Kapso payload_version=v2: flat single-message envelope.

    Shape (per https://docs.kapso.ai/docs/platform/webhooks/event-types):
        {
          "message": {"id":..., "from":..., "type":"text", "text":{"body":...},
                      "kapso": {"direction":"inbound"|"outbound", ...}},
          "conversation": {...},
          "phone_number_id": "...",
          "is_new_conversation": true|false
        }
    """
    msg = payload.get("message")
    if not isinstance(msg, dict) or "phone_number_id" not in payload:
        return None

    phone_id = payload.get("phone_number_id", "?")
    sender = msg.get("from", "?")
    kind = msg.get("type", "?")
    direction = (msg.get("kapso") or {}).get("direction", "?")
    new = payload.get("is_new_conversation")
    base = f"phone_id={phone_id} direction={direction} new={new} from={sender} type={kind}"

    if kind == "text":
        body = (msg.get("text") or {}).get("body", "")
        return f"{base} body={body!r}"
    if kind == "interactive":
        sub = (msg.get("interactive") or {}).get("type", "?")
        return f"{base} sub={sub}"
    return base


def _summarize_meta_native(payload: dict[str, Any]) -> list[str]:
    """Fallback: Meta-native batched payload (entry[].changes[].value.messages[])."""
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
                    sub = (msg.get("interactive") or {}).get("type", "?")
                    summaries.append(
                        f"phone_id={phone_id} from={sender} type=interactive sub={sub}"
                    )
                else:
                    summaries.append(
                        f"phone_id={phone_id} from={sender} type={kind}"
                    )
    return summaries


def _summarize_messages(payload: dict[str, Any]) -> list[str]:
    """Try Kapso v2 first, fall back to Meta-native batched payloads."""
    v2 = _summarize_kapso_v2(payload)
    if v2 is not None:
        return [v2]
    return _summarize_meta_native(payload)


# --- UX experiment (M' minimal) -------------------------------------------
# Until commit M wires the real router, every inbound text triggers a
# demo response: 3 reply buttons + a list with 5 animals. Taps echo back
# the row/button id. Purpose: validate WhatsApp interactive UX before
# committing to a routing architecture.

DEMO_BUTTONS = [
    {"id": "btn_pedidos", "title": "Pedidos"},
    {"id": "btn_devolucion", "title": "Devolucion"},
    {"id": "btn_comprobantes", "title": "Comprobantes"},
]

# Hardcoded /pedidos response — drops the "indica tu ID de chofer" turn;
# in real life the chofer is derived from the WhatsApp number sending the
# message. WhatsApp text formatting uses *bold* and emojis render inline.
PEDIDOS_REPORT = (
    "Chofer: *INTERNO 6 - RIVERO JORGE*\n"
    "Comprobantes de transferencias: *12 / 37*\n"
    "Detalle transferencias (Transferido / Saldo):\n"
    "-- 1375 - $ 18.790,00 / $ 18.790,19 ✅\n"
    "-- 1401 - $ 108.785,01 / $ 234.582,35 🟨\n"
    "-- 1543 - $ 286.341,00 / $ 286.341,15 ✅\n"
    "-- 1566 - $ 49.890,00 / $ 49.890,71 ✅\n"
    "-- 1594 - $ 74.235,00 / $ 74.235,87 ✅\n"
    "-- 2130 - $ 722.611,00 / $ 722.612,76 🟨\n"
    "-- 2194 - $ 47.576,00 / $ 47.576,20 ✅\n"
    "-- 3305 - $ 56.099,00 / $ 78.891,39 🟨\n"
    "-- 3314 - $ 851.490,00 / $ 851.491,87 🟨\n"
    "-- 3367 - $ 178.926,00 / $ 178.126,18 🟦\n"
    "-- 4458 - $ 21.033,00 / $ 21.033,55 ✅\n"
    "-- 5505 - $ 55.434,00 / $ 55.434,55 ✅\n"
    "Total transferido: *$ 2.471.210,01*"
)

DEMO_LIST_SECTIONS = [
    {
        "title": "Animales",
        "rows": [
            {"id": "animal_perro", "title": "Perro", "description": "Mamífero doméstico"},
            {"id": "animal_gato", "title": "Gato", "description": "Felino doméstico"},
            {"id": "animal_hamster", "title": "Hamster", "description": "Roedor pequeño"},
            {"id": "animal_tortuga", "title": "Tortuga", "description": "Reptil con caparazón"},
            {"id": "animal_cobaya", "title": "Cobaya", "description": "Roedor sudamericano"},
        ],
    }
]


def _dispatch_demo(
    client: WhatsAppClient, payload: dict[str, Any]
) -> dict[str, Any]:
    """Demo responder. Real router lands in commit M.

    Only handles Kapso v2 inbound messages with direction=inbound; skips
    outbound (whatsapp.message.sent) to avoid responding to our own sends.
    """
    msg = payload.get("message") or {}
    if not isinstance(msg, dict):
        return {"skipped": "no_message"}

    direction = (msg.get("kapso") or {}).get("direction")
    if direction != "inbound":
        return {"skipped": f"direction={direction}"}

    phone_number_id = payload.get("phone_number_id")
    to = msg.get("from")
    if not phone_number_id or not to:
        return {"skipped": "missing_phone_or_from"}

    kind = msg.get("type")

    if kind == "text":
        client.send_buttons(
            phone_number_id=phone_number_id,
            to=to,
            header="Rai · demo",
            body="¿Qué necesitás?",
            buttons=DEMO_BUTTONS,
        )
        client.send_list(
            phone_number_id=phone_number_id,
            to=to,
            header="Bestiario",
            body="Elegí un animal (es solo demo)",
            button_text="Ver animales",
            sections=DEMO_LIST_SECTIONS,
        )
        return {"sent": "buttons+list"}

    if kind == "interactive":
        inter = msg.get("interactive") or {}
        tapped_id, label = "?", "?"
        if inter.get("type") == "button_reply":
            br = inter.get("button_reply") or {}
            tapped_id, label = br.get("id", "?"), br.get("title", "?")
        elif inter.get("type") == "list_reply":
            lr = inter.get("list_reply") or {}
            tapped_id, label = lr.get("id", "?"), lr.get("title", "?")

        # Specific button → hardcoded /pedidos report (demo).
        if tapped_id == "btn_pedidos":
            client.send_text(
                phone_number_id=phone_number_id, to=to, body=PEDIDOS_REPORT
            )
            return {"sent": "pedidos_report"}

        # Default: echo what was tapped.
        client.send_text(
            phone_number_id=phone_number_id,
            to=to,
            body=f"Tapeaste: {label} (id={tapped_id})",
        )
        return {"sent": "echo", "id": tapped_id}

    return {"skipped": f"type={kind}"}


@router.post("/webhook/whatsapp", status_code=200)
async def whatsapp_webhook(
    body: bytes = Depends(require_kapso_signed_request),
    client: WhatsAppClient = Depends(get_default_client),
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
        log.info(
            "inbound: unrecognized payload keys=%s",
            sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        )

    # Demo response (commit M' — UX experiment).
    try:
        result = _dispatch_demo(client, payload)
        log.info("demo dispatch: %s", result)
    except Exception as e:  # pragma: no cover — keep webhook 200 even if send fails
        log.exception("demo dispatch failed: %s", e)

    return {"received": len(summaries)}
