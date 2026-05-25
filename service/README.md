# Rai Domain Service

Stateless FastAPI service that owns all domain logic for Rai (multi-tenant
WhatsApp business assistant). The Kapso workflow calls into this service via
two webhook endpoints: `POST /resolve` and `POST /op/{id}`.

Spec: see `../SPEC.md`.

## Layout

```
service/
  rai/
    __init__.py        # version
    config.py          # Settings (pydantic-settings)
    roles.py           # Role enum — shared source of truth
    main.py            # FastAPI app + /healthz
    catalog.py         # operations catalog (Task 3)
    ops/
      schemas.py       # Pydantic args schemas
    models.py          # SQLAlchemy ORM models (Task 2)
    db.py              # engine + session (Task 2)
  migrations/          # Alembic (Task 2)
  scripts/
    seed.py            # local seed (Task 2)
  tests/
    test_catalog.py
  pyproject.toml
  .env.example
```

## Local setup

```powershell
cd service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env   # then fill in DATABASE_URL etc.
uvicorn rai.main:app --reload
```

Healthcheck: `GET http://localhost:8000/healthz` → `{"status": "ok"}`.

## Tests

```powershell
pytest
```
