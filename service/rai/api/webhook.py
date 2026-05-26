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

# --- /devolucion demo data --------------------------------------------------
# Stateless per-message: every interactive id carries the full context, so the
# router doesn't have to remember "which pedido did the user pick two turns
# ago". The real M+1 version reads from the DB; here we hardcode the same row
# the user showed in their screenshot.

DEV_DEMO_PEDIDOS = [
    {"id": "003249", "cliente": "FARINA FERNANDA",  "factura": "00007-00390007", "total": "$ 35.142,41"},
    {"id": "003250", "cliente": "PEREZ JUAN",       "factura": "00007-00390008", "total": "$ 28.500,00"},
    {"id": "003251", "cliente": "GOMEZ MARIA",      "factura": "00007-00390009", "total": "$ 92.350,00"},
    {"id": "003252", "cliente": "LOPEZ CARLOS",     "factura": "00007-00390010", "total": "$ 14.200,00"},
    {"id": "003253", "cliente": "RODRIGUEZ ANA",    "factura": "00007-00390011", "total": "$ 67.890,50"},
    {"id": "003254", "cliente": "MARTINEZ LUIS",    "factura": "00007-00390012", "total": "$ 41.700,00"},
    {"id": "003255", "cliente": "SANCHEZ LAURA",    "factura": "00007-00390013", "total": "$ 19.450,75"},
    {"id": "003256", "cliente": "DIAZ ROBERTO",     "factura": "00007-00390014", "total": "$ 53.880,00"},
]

DEV_DEMO_ITEMS_BY_PEDIDO = {
    "003249": [
        {"id": "7115", "nombre": "ANDES X12 1000RET",  "stock_devolvible": 1, "monto_unidad": "$ 35.142,41"},
        {"id": "7120", "nombre": "BRAHMA X6 730ML",    "stock_devolvible": 2, "monto_unidad": "$ 18.500,00"},
        {"id": "7125", "nombre": "QUILMES X12 1000RET","stock_devolvible": 1, "monto_unidad": "$ 32.800,00"},
    ],
    "003250": [
        {"id": "8230", "nombre": "COCA COLA X6 2.25L", "stock_devolvible": 3, "monto_unidad": "$ 9.500,00"},
        {"id": "8235", "nombre": "SPRITE X6 2.25L",    "stock_devolvible": 2, "monto_unidad": "$ 9.200,00"},
        {"id": "8240", "nombre": "FANTA X6 1.5L",      "stock_devolvible": 1, "monto_unidad": "$ 7.600,00"},
    ],
    "003251": [
        {"id": "7115", "nombre": "ANDES X12 1000RET",  "stock_devolvible": 5, "monto_unidad": "$ 35.142,41"},
        {"id": "7120", "nombre": "BRAHMA X6 730ML",    "stock_devolvible": 3, "monto_unidad": "$ 18.500,00"},
        {"id": "9001", "nombre": "AGUA VILLA X6 2L",   "stock_devolvible": 6, "monto_unidad": "$ 4.800,00"},
        {"id": "9005", "nombre": "BAGGIO NARANJA X8",  "stock_devolvible": 4, "monto_unidad": "$ 12.300,00"},
        {"id": "9010", "nombre": "LAYS PAPAS 250G",    "stock_devolvible": 2, "monto_unidad": "$ 6.500,00"},
        {"id": "9015", "nombre": "PRINGLES X12 124G",  "stock_devolvible": 1, "monto_unidad": "$ 28.000,00"},
    ],
    "003252": [
        {"id": "7125", "nombre": "QUILMES X12 1000RET","stock_devolvible": 1, "monto_unidad": "$ 32.800,00"},
        {"id": "7130", "nombre": "STELLA ARTOIS X6",   "stock_devolvible": 2, "monto_unidad": "$ 22.400,00"},
    ],
    "003253": [
        {"id": "8230", "nombre": "COCA COLA X6 2.25L", "stock_devolvible": 2, "monto_unidad": "$ 9.500,00"},
        {"id": "8245", "nombre": "PEPSI X6 2.25L",     "stock_devolvible": 3, "monto_unidad": "$ 8.900,00"},
        {"id": "9001", "nombre": "AGUA VILLA X6 2L",   "stock_devolvible": 4, "monto_unidad": "$ 4.800,00"},
        {"id": "9020", "nombre": "GATORADE X6 500ML",  "stock_devolvible": 5, "monto_unidad": "$ 11.200,00"},
        {"id": "9025", "nombre": "RED BULL X4 250ML",  "stock_devolvible": 1, "monto_unidad": "$ 9.800,00"},
    ],
    "003254": [
        {"id": "7115", "nombre": "ANDES X12 1000RET",  "stock_devolvible": 8, "monto_unidad": "$ 35.142,41"},
        {"id": "7140", "nombre": "CORONA X6 355ML",    "stock_devolvible": 3, "monto_unidad": "$ 21.300,00"},
        {"id": "7145", "nombre": "HEINEKEN X6 330ML",  "stock_devolvible": 2, "monto_unidad": "$ 24.800,00"},
        {"id": "8235", "nombre": "SPRITE X6 2.25L",    "stock_devolvible": 1, "monto_unidad": "$ 9.200,00"},
    ],
    "003255": [
        {"id": "9030", "nombre": "TERMA HIERBA X6",    "stock_devolvible": 2, "monto_unidad": "$ 7.800,00"},
        {"id": "9035", "nombre": "PASO DE LOS TOROS",  "stock_devolvible": 1, "monto_unidad": "$ 6.400,00"},
        {"id": "9040", "nombre": "MANAOS COLA X6",     "stock_devolvible": 1, "monto_unidad": "$ 5.200,00"},
    ],
    "003256": [
        {"id": "7115", "nombre": "ANDES X12 1000RET",  "stock_devolvible": 1,  "monto_unidad": "$ 35.142,41"},
        {"id": "9045", "nombre": "TWISTOS PIZZA 62G",  "stock_devolvible": 12, "monto_unidad": "$ 3.450,00"},
        {"id": "9050", "nombre": "DORITOS PIZZA 220G", "stock_devolvible": 4,  "monto_unidad": "$ 5.900,00"},
        {"id": "9055", "nombre": "OREO X3 117G",       "stock_devolvible": 2,  "monto_unidad": "$ 4.200,00"},
    ],
}


def _build_dev_pedidos_list() -> list[dict[str, object]]:
    rows = []
    for p in DEV_DEMO_PEDIDOS:
        rows.append(
            {
                "id": f"dev:pedido:{p['id']}",
                "title": f"{p['id']} {p['cliente']}"[:24],
                "description": f"{p['total']} · FACTURA {p['factura']}"[:72],
            }
        )
    rows.append(
        {
            "id": "dev:pedido:_search",
            "title": "🔎 Buscar por ID",
            "description": "Ingresar n° de pedido manualmente",
        }
    )
    return [{"title": "Pedidos del día", "rows": rows}]


def _build_dev_items_list(pedido_id: str) -> list[dict[str, object]]:
    items = DEV_DEMO_ITEMS_BY_PEDIDO.get(pedido_id, [])
    rows = []
    for it in items:
        stock = it["stock_devolvible"]
        unit = "bulto" if stock == 1 else "bultos"
        rows.append(
            {
                "id": f"dev:item:{pedido_id}:{it['id']}",
                "title": f"{it['id']} {it['nombre']}"[:24],
                "description": f"{stock} {unit} disp · {it['monto_unidad']}"[:72],
            }
        )
    return [{"title": "Items del pedido", "rows": rows}]


def _build_dev_qty(pedido_id: str, item_id: str) -> tuple[str, dict]:
    """Pick the right UI for selecting a quantity.

    Returns a tuple (mode, kwargs) where mode is "buttons" (stock ≤ 2;
    Meta caps at 3 reply buttons so we use [N] + [Cancelar]) or "list"
    (stock ≥ 3; we list 1..min(stock,9) bultos + a Cancelar row).
    """
    items = DEV_DEMO_ITEMS_BY_PEDIDO.get(pedido_id, [])
    item = next((i for i in items if i["id"] == item_id), None)
    stock = (item or {}).get("stock_devolvible", 0)
    nombre = (item or {}).get("nombre", "?")
    unit = "bulto" if stock == 1 else "bultos"
    body = (
        f"Item *{item_id} {nombre}*\n"
        f"Stock devolvible: *{stock} {unit}*\n"
        f"¿Cuántos devolvés?"
    )
    header = "Devolución · paso 3/3"

    if stock <= 2:
        buttons: list[dict[str, str]] = []
        for n in range(1, stock + 1):
            buttons.append(
                {"id": f"dev:qty:{pedido_id}:{item_id}:{n}", "title": str(n)}
            )
        buttons.append({"id": "dev:cancel", "title": "Cancelar"})
        return "buttons", {"header": header, "body": body, "buttons": buttons}

    # stock >= 3 → list (max 9 numeric rows + 1 cancel)
    rows: list[dict[str, object]] = []
    for n in range(1, min(stock, 9) + 1):
        u = "bulto" if n == 1 else "bultos"
        rows.append(
            {"id": f"dev:qty:{pedido_id}:{item_id}:{n}", "title": f"{n} {u}"}
        )
    rows.append({"id": "dev:cancel", "title": "❌ Cancelar"})
    return "list", {
        "header": header,
        "body": body,
        "button_text": "Elegir cantidad",
        "sections": [{"title": "Cantidad", "rows": rows}],
    }


def _build_dev_confirmation(pedido_id: str, item_id: str, qty: int) -> str:
    items = DEV_DEMO_ITEMS_BY_PEDIDO.get(pedido_id, [])
    item = next((i for i in items if i["id"] == item_id), None)
    pedido = next((p for p in DEV_DEMO_PEDIDOS if p["id"] == pedido_id), None)
    if item is None or pedido is None:
        return "⚠️ No se pudo registrar la devolución (item o pedido inválido)."
    unit = "bulto" if qty == 1 else "bultos"
    return (
        "✅ *Devolución registrada*\n"
        f"Pedido: *{pedido['id']} · {pedido['cliente']}*\n"
        f"Item: {item['id']} {item['nombre']}\n"
        f"Cantidad: *{qty} {unit}*\n"
        f"Importe unitario: *{item['monto_unidad']}*"
    )


# --- /comprobantes demo data + in-memory state -----------------------------
# Unlike pedidos and devolución which fit a stateless ID-encoded flow, the
# comprobantes flow needs to remember "this user picked client X" between
# the client tap and the subsequent image upload (images don't carry the
# client context). We hold the state in a process-local dict for the demo;
# real M+1 persists this in the Conversation table.
#
# Single-worker uvicorn is set in the systemd unit while we're in demo phase.

COMP_DEMO_CLIENTES = [
    {"id": "3115", "nombre": "DADAN JOSE",      "saldo": "$ 24.054,02"},
    {"id": "3249", "nombre": "FARINA FERNANDA", "saldo": "$ 35.142,41"},
    {"id": "3250", "nombre": "PEREZ JUAN",      "saldo": "$ 28.500,00"},
    {"id": "3251", "nombre": "GOMEZ MARIA",     "saldo": "$ 92.350,00"},
    {"id": "3252", "nombre": "LOPEZ CARLOS",    "saldo": "$ 14.200,00"},
    {"id": "3253", "nombre": "RODRIGUEZ ANA",   "saldo": "$ 67.890,50"},
    {"id": "3254", "nombre": "MARTINEZ LUIS",   "saldo": "$ 41.700,00"},
    {"id": "3255", "nombre": "SANCHEZ LAURA",   "saldo": "$ 19.450,75"},
]

COMP_DEMO_CLIENTE_BY_ID: dict[str, dict] = {c["id"]: c for c in COMP_DEMO_CLIENTES}

# (phone_number_id, contacto) → {"cliente_id": "...", "set_at": ts}
_COMP_DEMO_STATE: dict[tuple[str, str], dict] = {}


def _build_comp_clientes_list() -> list[dict[str, object]]:
    rows = []
    for c in COMP_DEMO_CLIENTES:
        rows.append(
            {
                "id": f"comp:cliente:{c['id']}",
                "title": f"{c['id']} {c['nombre']}"[:24],
                "description": f"Saldo {c['saldo']}"[:72],
            }
        )
    rows.append(
        {
            "id": "comp:cliente:_search",
            "title": "🔎 Buscar por N° cliente",
            "description": "Ingresar N° de cliente manualmente",
        }
    )
    return [{"title": "Clientes con saldo pendiente", "rows": rows}]


def _build_comp_confirmation(cliente_id: str) -> str:
    c = COMP_DEMO_CLIENTE_BY_ID.get(cliente_id)
    if c is None:
        return "⚠️ Comprobante recibido pero el cliente ya no está activo en esta sesión."
    # The "amount detected" is hardcoded to match exactly the saldo so the
    # demo always shows the happy path. Real M+1 reads it via OCR (Gemini
    # Vision / Claude Vision) against the uploaded media.
    monto = c["saldo"]
    return (
        "✅ *Comprobante recibido*\n"
        f"Cliente: *{c['nombre']}* ({c['id']})\n"
        f"Monto detectado: *{monto}*\n"
        f"Saldo pendiente: *{monto}*\n"
        "Diferencia: $ 0,00 ✓ coincide\n"
        "Estado: *Registrado*"
    )


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

    if kind == "image":
        state = _COMP_DEMO_STATE.get((phone_number_id, to))
        if state is None:
            client.send_text(
                phone_number_id=phone_number_id,
                to=to,
                body="Recibí una imagen pero no tengo un cliente activo. Tocá *Comprobantes* primero.",
            )
            return {"sent": "comp_image_without_state"}
        cliente_id = state["cliente_id"]
        client.send_text(
            phone_number_id=phone_number_id,
            to=to,
            body=_build_comp_confirmation(cliente_id),
        )
        _COMP_DEMO_STATE.pop((phone_number_id, to), None)
        return {"sent": "comp_image_acked", "cliente": cliente_id}

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

        # /comprobantes flow — uses in-memory state to bridge the gap
        # between client selection (tap) and receipt upload (image).
        if tapped_id == "btn_comprobantes":
            client.send_list(
                phone_number_id=phone_number_id,
                to=to,
                header="Comprobantes · paso 1/2",
                body="¿Para qué cliente es el pago?",
                button_text="Ver clientes",
                sections=_build_comp_clientes_list(),
            )
            return {"sent": "comp_clientes_list"}

        if tapped_id == "comp:cliente:_search":
            client.send_text(
                phone_number_id=phone_number_id,
                to=to,
                body="🔎 (demo) En producción acá te abrimos input para tipear N° de cliente.",
            )
            return {"sent": "comp_search_stub"}

        if tapped_id.startswith("comp:cliente:"):
            cliente_id = tapped_id.split(":", 2)[2]
            c = COMP_DEMO_CLIENTE_BY_ID.get(cliente_id)
            if c is None:
                client.send_text(
                    phone_number_id=phone_number_id,
                    to=to,
                    body="Cliente no encontrado. Volvé al menú con cualquier mensaje.",
                )
                return {"sent": "comp_unknown_client"}
            # Remember which client this user is loading a comprobante for.
            _COMP_DEMO_STATE[(phone_number_id, to)] = {"cliente_id": cliente_id}
            client.send_buttons(
                phone_number_id=phone_number_id,
                to=to,
                header="Comprobantes · paso 2/2",
                body=(
                    f"Cliente: *{c['nombre']}* ({cliente_id})\n"
                    f"Saldo pendiente: *{c['saldo']}*\n"
                    "Enviame foto o screenshot del comprobante de transferencia."
                ),
                buttons=[
                    {"id": "comp:cancel", "title": "Cancelar"},
                    {"id": "btn_comprobantes", "title": "Cambiar cliente"},
                ],
            )
            return {"sent": "comp_awaiting_image", "cliente": cliente_id}

        if tapped_id == "comp:cancel":
            _COMP_DEMO_STATE.pop((phone_number_id, to), None)
            client.send_text(
                phone_number_id=phone_number_id,
                to=to,
                body="Comprobantes cancelado. Volvé al menú con cualquier mensaje.",
            )
            return {"sent": "comp_cancelled"}

        # /devolucion flow — state is encoded in the row/button ids.
        if tapped_id == "btn_devolucion":
            client.send_list(
                phone_number_id=phone_number_id,
                to=to,
                header="Devolución · paso 1/3",
                body="¿De qué pedido?",
                button_text="Ver pedidos",
                sections=_build_dev_pedidos_list(),
            )
            return {"sent": "dev_pedidos_list"}

        if tapped_id == "dev:cancel":
            client.send_text(
                phone_number_id=phone_number_id,
                to=to,
                body="Devolución cancelada. Volvé al menú con cualquier mensaje.",
            )
            return {"sent": "dev_cancelled"}

        if tapped_id == "dev:pedido:_search":
            client.send_text(
                phone_number_id=phone_number_id,
                to=to,
                body="🔎 (demo) En producción, acá te abrimos input de texto para ingresar el ID de pedido.",
            )
            return {"sent": "dev_search_stub"}

        if tapped_id.startswith("dev:pedido:"):
            pedido_id = tapped_id.split(":", 2)[2]
            client.send_list(
                phone_number_id=phone_number_id,
                to=to,
                header=f"Devolución · paso 2/3",
                body=f"Pedido *{pedido_id}*\n¿Qué item devolvés?",
                button_text="Ver items",
                sections=_build_dev_items_list(pedido_id),
            )
            return {"sent": "dev_items_list", "pedido": pedido_id}

        if tapped_id.startswith("dev:item:"):
            _, _, pedido_id, item_id = tapped_id.split(":", 3)
            mode, kw = _build_dev_qty(pedido_id, item_id)
            if mode == "buttons":
                client.send_buttons(
                    phone_number_id=phone_number_id, to=to, **kw
                )
            else:
                client.send_list(
                    phone_number_id=phone_number_id, to=to, **kw
                )
            return {
                "sent": f"dev_qty_{mode}",
                "pedido": pedido_id,
                "item": item_id,
            }

        if tapped_id.startswith("dev:qty:"):
            _, _, pedido_id, item_id, qty_s = tapped_id.split(":", 4)
            try:
                qty = int(qty_s)
            except ValueError:
                qty = 0
            client.send_text(
                phone_number_id=phone_number_id,
                to=to,
                body=_build_dev_confirmation(pedido_id, item_id, qty),
            )
            return {"sent": "dev_confirmed", "qty": qty}

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
