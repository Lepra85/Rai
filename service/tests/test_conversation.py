"""Tests for Conversation model + helpers (rai/conversation.py)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from rai.conversation import (
    HISTORY_MAX,
    append_message,
    get_or_create_conversation,
    reset,
    transition,
)
from rai.models import Conversation, ConversationState, Usuario


# --- get_or_create ---------------------------------------------------------


def test_get_or_create_creates_new_idle_conversation(
    db_session: Session, empresa_with_users
):
    empresa = empresa_with_users["empresa_a"]
    contacto = "541199999999"

    conv = get_or_create_conversation(db_session, empresa.id, contacto)

    assert conv.id is not None
    assert conv.empresa_id == empresa.id
    assert conv.contacto == contacto
    assert conv.state == ConversationState.IDLE
    assert conv.history == []
    assert conv.current_op_id is None


def test_get_or_create_reuses_existing(db_session: Session, empresa_with_users):
    empresa = empresa_with_users["empresa_a"]
    contacto = "541188888888"

    first = get_or_create_conversation(db_session, empresa.id, contacto)
    transition(first, ConversationState.MENU_SHOWN)
    db_session.flush()

    second = get_or_create_conversation(db_session, empresa.id, contacto)

    assert second.id == first.id
    assert second.state == ConversationState.MENU_SHOWN


# --- transition ------------------------------------------------------------


def test_transition_sets_state_and_op_id(db_session: Session, empresa_with_users):
    empresa = empresa_with_users["empresa_a"]
    conv = get_or_create_conversation(db_session, empresa.id, "541177777777")

    transition(conv, ConversationState.AWAITING_ARGS, current_op_id="factura_consultar")

    assert conv.state == ConversationState.AWAITING_ARGS
    assert conv.current_op_id == "factura_consultar"


def test_transition_clears_op_id_when_none(db_session: Session, empresa_with_users):
    empresa = empresa_with_users["empresa_a"]
    conv = get_or_create_conversation(db_session, empresa.id, "541166666666")
    transition(conv, ConversationState.AWAITING_ARGS, current_op_id="factura_crear")
    transition(conv, ConversationState.IDLE)

    assert conv.state == ConversationState.IDLE
    assert conv.current_op_id is None


# --- append_message --------------------------------------------------------


def test_append_message_appends_in_order(db_session: Session, empresa_with_users):
    empresa = empresa_with_users["empresa_a"]
    conv = get_or_create_conversation(db_session, empresa.id, "541155555555")

    append_message(conv, "user", "hola")
    append_message(conv, "assistant", "que tal")
    append_message(conv, "user", "bien")

    assert len(conv.history) == 3
    roles = [e["role"] for e in conv.history]
    contents = [e["content"] for e in conv.history]
    assert roles == ["user", "assistant", "user"]
    assert contents == ["hola", "que tal", "bien"]


def test_append_message_truncates_to_history_max(
    db_session: Session, empresa_with_users
):
    empresa = empresa_with_users["empresa_a"]
    conv = get_or_create_conversation(db_session, empresa.id, "541144444444")

    for i in range(HISTORY_MAX + 5):
        append_message(conv, "user", f"msg-{i}")

    assert len(conv.history) == HISTORY_MAX
    # Oldest dropped, newest preserved.
    assert conv.history[0]["content"] == f"msg-5"
    assert conv.history[-1]["content"] == f"msg-{HISTORY_MAX + 4}"


def test_append_message_records_iso_timestamp(
    db_session: Session, empresa_with_users
):
    empresa = empresa_with_users["empresa_a"]
    conv = get_or_create_conversation(db_session, empresa.id, "541133333333")
    before = datetime.now(UTC)

    append_message(conv, "user", "hola")

    ts = datetime.fromisoformat(conv.history[0]["ts"])
    after = datetime.now(UTC)
    assert before <= ts <= after


# --- reset -----------------------------------------------------------------


def test_reset_clears_state_and_history_but_keeps_opt_in_at(
    db_session: Session, empresa_with_users
):
    empresa = empresa_with_users["empresa_a"]
    conv = get_or_create_conversation(db_session, empresa.id, "541122222222")
    original_opt_in = conv.opt_in_at

    transition(conv, ConversationState.AGENT_ACTIVE, current_op_id="estadisticas")
    append_message(conv, "user", "stuff")
    db_session.flush()

    reset(conv)

    assert conv.state == ConversationState.IDLE
    assert conv.history == []
    assert conv.current_op_id is None
    assert conv.opt_in_at == original_opt_in


# --- cross-tenant safety --------------------------------------------------


def test_get_or_create_isolates_per_tenant(
    db_session: Session, empresa_with_users
):
    """Same `contacto` under empresa A and empresa B → two different rows."""
    empresa_a = empresa_with_users["empresa_a"]
    empresa_b = empresa_with_users["empresa_b"]
    shared_contacto = "541199900000"

    conv_a = get_or_create_conversation(db_session, empresa_a.id, shared_contacto)
    conv_b = get_or_create_conversation(db_session, empresa_b.id, shared_contacto)

    assert conv_a.id != conv_b.id
    assert conv_a.empresa_id == empresa_a.id
    assert conv_b.empresa_id == empresa_b.id


def test_query_filtered_by_other_tenant_returns_nothing(
    db_session: Session, empresa_with_users
):
    empresa_a = empresa_with_users["empresa_a"]
    empresa_b = empresa_with_users["empresa_b"]
    contacto = "541187654321"

    get_or_create_conversation(db_session, empresa_a.id, contacto)
    db_session.flush()

    found = (
        db_session.query(Conversation)
        .filter(
            Conversation.empresa_id == empresa_b.id,
            Conversation.contacto == contacto,
        )
        .one_or_none()
    )
    assert found is None
