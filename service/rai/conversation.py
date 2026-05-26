"""Per-(empresa_id, contacto) conversation state helpers.

Kept separate from the API/router so the same primitives can be used by
the webhook handler, the future agent loop, and admin tooling.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from rai.models import Conversation, ConversationState

# Short tail. The deterministic UX is the primary path; the LLM fallback
# only needs enough context for a coherent free-text turn.
HISTORY_MAX = 20

MessageRole = Literal["user", "assistant", "system"]


def get_or_create_conversation(
    db: Session,
    empresa_id: uuid.UUID,
    contacto: str,
) -> Conversation:
    """Return an existing conversation for the tuple or create a new IDLE one."""
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.empresa_id == empresa_id,
            Conversation.contacto == contacto,
        )
        .one_or_none()
    )
    if conv is not None:
        return conv

    conv = Conversation(
        id=uuid.uuid4(),
        empresa_id=empresa_id,
        contacto=contacto,
        state=ConversationState.IDLE,
        history=[],
    )
    db.add(conv)
    db.flush()
    return conv


def transition(
    conv: Conversation,
    new_state: ConversationState,
    current_op_id: str | None = None,
) -> None:
    """Move the conversation to a new state. `current_op_id` is overwritten
    every call (None clears it)."""
    conv.state = new_state
    conv.current_op_id = current_op_id
    conv.last_message_at = datetime.now(UTC)


def append_message(
    conv: Conversation,
    role: MessageRole,
    content: str,
) -> None:
    """Append to history, truncating to the last HISTORY_MAX entries.

    Uses SQLAlchemy's flag_modified pattern by rebinding the attribute,
    because JSONB columns don't track in-place list mutations.
    """
    entry = {
        "role": role,
        "content": content,
        "ts": datetime.now(UTC).isoformat(),
    }
    new_history = list(conv.history or [])
    new_history.append(entry)
    if len(new_history) > HISTORY_MAX:
        new_history = new_history[-HISTORY_MAX:]
    conv.history = new_history
    conv.last_message_at = datetime.now(UTC)


def reset(conv: Conversation) -> None:
    """Back to IDLE, clear history and current_op_id. Preserve opt_in_at."""
    conv.state = ConversationState.IDLE
    conv.history = []
    conv.current_op_id = None
    conv.last_message_at = datetime.now(UTC)
