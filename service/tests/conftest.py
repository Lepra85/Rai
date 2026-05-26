"""Shared fixtures.

`db_session` runs each test inside a SAVEPOINT and rolls it back at the end,
so the seed/Supabase data is never mutated by tests. The fixture also
overrides FastAPI's `get_db` dependency to share the same session, so the
endpoint and the test see the same transactional state.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from rai.config import Settings, get_settings
from rai.db import Base, get_db, get_engine
from rai.main import app
from rai.models import Empresa, Usuario
from rai.roles import Role

TEST_FLOW_API_SECRET = "test-flow-api-secret"


@pytest.fixture(scope="session")
def engine():
    return get_engine()


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    """Per-test session wrapped in a SAVEPOINT that always rolls back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """TestClient that shares `db_session` and uses a known FLOW_API_SECRET."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_settings() -> Settings:
        return Settings(flow_api_secret=TEST_FLOW_API_SECRET)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_settings
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def empresa_with_users(db_session: Session) -> dict:
    """Two empresas (so cross-tenant assumptions are real) with users at every role."""
    empresa_a = Empresa(
        id=uuid.uuid4(), nombre="Café A", phone_number_id=f"phone_a_{uuid.uuid4().hex[:8]}"
    )
    empresa_b = Empresa(
        id=uuid.uuid4(), nombre="Café B", phone_number_id=f"phone_b_{uuid.uuid4().hex[:8]}"
    )
    db_session.add_all([empresa_a, empresa_b])
    db_session.flush()

    dueno_a = Usuario(
        id=uuid.uuid4(),
        empresa_id=empresa_a.id,
        contacto=f"due_a_{uuid.uuid4().hex[:8]}",
        nombre="Dueño A",
        rol=Role.DUEÑO,
    )
    empleado_a = Usuario(
        id=uuid.uuid4(),
        empresa_id=empresa_a.id,
        contacto=f"emp_a_{uuid.uuid4().hex[:8]}",
        nombre="Empleado A",
        rol=Role.EMPLEADO,
    )
    dueno_b = Usuario(
        id=uuid.uuid4(),
        empresa_id=empresa_b.id,
        contacto=f"due_b_{uuid.uuid4().hex[:8]}",
        nombre="Dueño B",
        rol=Role.DUEÑO,
    )
    db_session.add_all([dueno_a, empleado_a, dueno_b])
    db_session.flush()

    return {
        "empresa_a": empresa_a,
        "empresa_b": empresa_b,
        "dueno_a": dueno_a,
        "empleado_a": empleado_a,
        "dueno_b": dueno_b,
    }
