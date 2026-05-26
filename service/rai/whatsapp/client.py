"""Outbound WhatsApp client.

Thin wrapper over Kapso's Meta-proxy REST API. Kapso is used here as a
WhatsApp gateway only — we own the conversation logic and just hand
Kapso the formatted messages to deliver.

Endpoint shape:
    POST https://api.kapso.ai/meta/whatsapp/v{N}/{phone_number_id}/messages
    Headers: X-API-Key: <KAPSO_API_KEY>
    Body:    standard WhatsApp Cloud API JSON
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

KAPSO_BASE_URL = "https://api.kapso.ai/meta/whatsapp"
KAPSO_GRAPH_VERSION = "v24.0"


@dataclass(frozen=True)
class SendResult:
    """Outcome of an outbound message send."""

    wa_message_id: str | None
    raw: dict[str, Any]


class WhatsAppClient:
    """Synchronous client. One instance per service process is fine."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = KAPSO_BASE_URL,
        graph_version: str = KAPSO_GRAPH_VERSION,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("KAPSO_API_KEY is empty — cannot send WhatsApp messages.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._graph_version = graph_version
        self._timeout = timeout

    def _url(self, phone_number_id: str) -> str:
        return f"{self._base_url}/{self._graph_version}/{phone_number_id}/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

    def _post(self, phone_number_id: str, body: dict[str, Any]) -> SendResult:
        url = self._url(phone_number_id)
        with httpx.Client(timeout=self._timeout) as http:
            r = http.post(url, headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
        msgs = data.get("messages") or []
        wa_id = msgs[0]["id"] if msgs else None
        return SendResult(wa_message_id=wa_id, raw=data)

    def send_text(self, *, phone_number_id: str, to: str, body: str) -> SendResult:
        """Send a plain text message. `to` is the recipient WhatsApp number (E.164, no +)."""
        return self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
        )

    def mark_read(self, *, phone_number_id: str, message_id: str) -> SendResult:
        """Mark an incoming message as read (the blue check)."""
        return self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            },
        )

    def send_buttons(
        self,
        *,
        phone_number_id: str,
        to: str,
        body: str,
        buttons: list[dict[str, str]],
        header: str | None = None,
        footer: str | None = None,
    ) -> SendResult:
        """Send an interactive "reply buttons" message (max 3 buttons).

        Each item in `buttons` is `{"id": "...", "title": "..."}` — title
        max 20 chars. When the user taps, Kapso fires a webhook with
        message.type="interactive" and interactive.button_reply.id = our id.
        """
        if not 1 <= len(buttons) <= 3:
            raise ValueError("buttons must have between 1 and 3 items")
        action = {
            "buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                for b in buttons
            ]
        }
        interactive: dict[str, object] = {
            "type": "button",
            "body": {"text": body},
            "action": action,
        }
        if header:
            interactive["header"] = {"type": "text", "text": header}
        if footer:
            interactive["footer"] = {"text": footer}
        return self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": interactive,
            },
        )

    def send_list(
        self,
        *,
        phone_number_id: str,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict[str, object]],
        header: str | None = None,
        footer: str | None = None,
    ) -> SendResult:
        """Send an interactive "list" message.

        `sections` shape: list of `{"title": "...", "rows": [{"id":..,
        "title":.., "description":..}, ...]}`. Limits enforced by Meta:
        max 10 rows total across sections; row title 24 chars; description
        72 chars; button_text 20 chars.
        """
        interactive: dict[str, object] = {
            "type": "list",
            "body": {"text": body},
            "action": {"button": button_text, "sections": sections},
        }
        if header:
            interactive["header"] = {"type": "text", "text": header}
        if footer:
            interactive["footer"] = {"text": footer}
        return self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": interactive,
            },
        )


def get_default_client() -> "WhatsAppClient":
    """FastAPI dependency — build a client from current settings."""
    from rai.config import get_settings

    settings = get_settings()
    return WhatsAppClient(api_key=settings.kapso_api_key)
