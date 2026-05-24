# Rai — WhatsApp Business Assistant on Kapso

> **Spec-Driven Development document.** This file is the single source of truth
> for the next implementation. It is written to be executed by another Claude Code
> instance with no prior context. Read it top to bottom, then work through
> **§12 Implementation Tasks** in order, validating against **§13 Acceptance
> Criteria**. When something is ambiguous, prefer the rule stated here over your
> own assumptions; if the spec is genuinely silent, see **§14 Open Questions** and
> ask the user before guessing.

---

## 1. Context & Goal

Rai is a multi-tenant WhatsApp assistant for small businesses (the first vertical
is a café with multiple branches in CABA: invoices, delivery notes, stock,
orders). Each business interacts with Rai entirely through **WhatsApp**.

- **Channel:** WhatsApp only, delivered through **Kapso** (a hosted platform that
  orchestrates WhatsApp conversations as a versioned workflow and can run a hosted
  LLM "agent node"). There is **no Telegram** in this target architecture.
- **Goal:** a user inside a business sends WhatsApp messages (taps menu buttons or
  types free text) and Rai performs domain operations — querying and creating
  invoices, checking stock, returning stats — scoped to that user's business and
  permitted by that user's role.
- **Outcome:** one Kapso workflow (multi-tenant at runtime) drives the
  conversation; a stateless Python service owns all domain logic and data; tenant
  isolation and role authorization are enforced server-side in Python.

### Relationship to the existing repository

The repo currently contains a **Telegram bot** (`agent/bot.py`, OpenAI Agents SDK,
in-RAM memory, DigitalOcean droplet infra under `infra/`). That implementation is
the previous phase and is **being superseded** by this spec. Do **not** extend the
Telegram bot. The new work is effectively greenfield (new Python domain service +
Kapso flow-as-code). Leave the existing `agent/` and `infra/` files in place
unless a task below explicitly says otherwise; new code goes in new directories
described in §15.

---

## 2. Scope

### In scope
- One **Kapso workflow** defined as code (flow-as-code) and versioned in this repo.
- A **stateless Python (FastAPI) domain service** exposing `resolve` + operation
  endpoints, called by the workflow's webhook nodes.
- **Multi-tenancy:** one WhatsApp number per business; tenant resolved from the
  receiving number.
- **Role-based authorization** with an explicit operation→roles matrix, enforced
  in Python.
- A **deterministic menu** (WhatsApp interactive buttons/lists) plus an **LLM agent
  node** for free text — both routed to the same domain operations.
- **Onboarding** a new business when its WhatsApp number is connected; user/role
  provisioning out-of-band (not inside the conversation).
- An initial set of operations: a few **lightweight** (query-style) operations
  implemented fully, and **heavy** operations (invoices, stock, stats) backed by a
  database (at least one implemented end-to-end, the rest stubbed with the correct
  contract + authorization).

### Out of scope (for this spec)
- Telegram or any non-WhatsApp channel.
- A full admin UI for user management (provisioning is CLI/seed/admin-endpoint).
- The complete café feature set — only the operations listed in §6 are required;
  the catalog is designed so more can be added without architectural change.
- Production infrastructure hardening beyond what §10 requires.

---

## 3. Architecture Overview

**Pattern: Hybrid — Kapso orchestrates the conversation; a stateless Python
service owns the domain.**

```
WhatsApp user
    │  (message / button tap / list selection)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Kapso Workflow  (ONE flow, multi-tenant at runtime)          │
│                                                              │
│  Start                                                       │
│    └─► webhook: POST /resolve ──────────────┐                │
│         (sends tenant + sender identity)    │                │
│    ◄────────────────────────────────────────┘                │
│         returns {empresa, usuario, rol, menu(role-filtered)} │
│    │                                                         │
│    ├─ unknown sender ─► polite rejection ─► end              │
│    │                                                         │
│    ├─ main menu (send-interactive, built by Python)          │
│    │     └─ decide ─► per-intent edges ─► webhook: POST /op/{id}
│    │                                                         │
│    └─ agent node (hosted LLM, tools = role-filtered ops)     │
│          └─ each tool call ─► webhook: POST /op/{id}         │
│                                                              │
│  handoff node ─► human                                       │
└───────────────────────────┬─────────────────────────────────┘
                            │  HTTPS + shared-secret auth
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Python Domain Service (FastAPI, stateless)                   │
│   POST /resolve        identity+tenant+role → menu           │
│   POST /op/{id}        execute one domain operation          │
│                                                              │
│   Operations Catalog  (single source of truth)              │
│   Authorization        role gate + tenant gate (deny-default)│
│   Domain logic + DB    (empresa_id on every business table)  │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
                    ┌───────────────┐
                    │   Database    │  (multi-tenant; empresa_id everywhere)
                    └───────────────┘
```

**Key convergence:** both the deterministic menu sub-flows and the agent node's
tools terminate at the **same** `POST /op/{id}` endpoints. Every operation has a
**single implementation**, reachable from the "tappy" path and the free-text path.
This eliminates drift between the two input modes.

**Division of responsibility**
- **Kapso** owns: conversation state (in flow variables), channel mechanics,
  rendering interactive messages, and running the LLM agent loop.
- **Python** owns: identity/tenant/role resolution, the operations catalog,
  authorization, domain logic, and the database. It is **stateless** — no
  conversation memory, no channel logic, no LLM loop.

---

## 4. Multi-Tenancy & Identity

- **Tenant = the receiving WhatsApp number** (`phone_number_id`). Each business has
  exactly one number. `phone_number_id → empresa_id`.
- **Identity = the stable sender id** that Kapso provides for the messaging
  contact. Do **not** assume a raw `phone_number` is always present; use whatever
  stable contact identifier Kapso exposes (see §14). Map `contacto → {usuario,
  empresa_id, rol}`.
- **Both `empresa_id` and the sender identity are ALWAYS derived from the
  authenticated webhook payload, never from flow variables or client-supplied
  input.** The flow may *carry* these values for UX, but Python re-derives/verifies
  them from the authenticated request on every call. Treat any tenant/identity
  value that originates from flow input as untrusted.
- An incoming message whose sender is not registered for the resolved tenant →
  **polite rejection** (see §11). No implicit self-registration.

---

## 5. Authorization Model

Authorization is the **security boundary** of this system and is enforced **only in
Python** — never in the flow and never by the LLM.

- **Roles:** a small fixed set per business. Start with `dueño` (owner), `encargado`
  (manager), `empleado` (employee). The exact role names/levels are confirmable
  (§14) but the mechanism does not depend on the specific set.
- **Operation→roles matrix:** every operation declares `allowed_roles` in the
  catalog (§6). This is the authoritative permission map.
- **Two gates on every `/op/{id}` call (deny-by-default):**
  1. **Role gate:** reject unless `rol ∈ op.allowed_roles`.
  2. **Tenant gate:** every resource the operation touches must belong to
     `empresa_id`; every query filters by `empresa_id` server-side.
- **Menu/tool filtering is UX, not security.** Python builds a role-filtered menu
  and exposes role-filtered tools to the agent so users only *see* what they can
  do. But because the LLM, the flow, or a malicious/buggy client could still emit
  an operation id the user isn't allowed to run, **Python re-verifies both gates on
  every call** and rejects independently. Defense in depth.
- **The LLM is never a permission barrier.** Prompt instructions that say "only
  owners can do X" are not enforcement; the Python gate is.
- A cross-tenant data leak is considered **as severe as** a permission bypass and
  must be covered by tests (§13).

**Rejection responses** must not leak existence of resources in other tenants or
operations the user can't see (generic "no tenés permiso para esa acción" /
"no encontré eso").

---

## 6. Operations Catalog — single source of truth

A single Python module declares every operation. From this one catalog the system
derives: (a) the **role-filtered menu**, (b) the **agent node tool schemas**
(role-filtered), and (c) the **authorization gate**. There is no second list to
keep in sync — zero drift between tappy, free-text, and permissions.

### Catalog entry schema

Each operation declares:

| Field | Meaning |
|---|---|
| `id` | Stable operation id, used as the WhatsApp button/list id, the agent tool name, and the `/op/{id}` path. |
| `endpoint` | Handler function that executes the operation. (May be `/op/{id}` generic dispatch.) |
| `args_schema` | Typed schema for the operation's arguments (use Pydantic). Drives validation and the agent tool's JSON schema. |
| `menu_label` | Human label shown in the WhatsApp menu (Spanish, user-facing). |
| `agent_description` | Natural-language description the LLM sees to decide when to call this tool. |
| `allowed_roles` | Roles permitted to invoke. The authorization matrix. |
| `kind` | `"light"` (trivial/no DB) or `"heavy"` (DB-backed). For organization/testing. |

### Initial operations

Implement these in the catalog. Lightweight ones fully; heavy ones must have the
correct contract + both authorization gates, with at least **`factura_consultar`**
implemented end-to-end against the DB and the others stubbed (return a typed
"not yet implemented" but still pass through auth + tenant scoping).

| `id` | kind | `allowed_roles` (initial) | Notes |
|---|---|---|---|
| `ayuda` | light | all | Returns help / how to use Rai. |
| `menu` | light | all | Re-renders the main menu. |
| `factura_consultar` | heavy | dueño, encargado | Query invoices for the business. **Implement end-to-end.** |
| `factura_crear` | heavy | dueño, encargado | Create an invoice. Stub w/ contract + auth. |
| `factura_anular` | heavy | dueño | Void an invoice. Stub w/ contract + auth. |
| `stock_consultar` | heavy | dueño, encargado, empleado | Check stock levels. Stub w/ contract + auth. |
| `estadisticas` | heavy | dueño | Business stats (which stats: §14). Stub w/ contract + auth. |

> Role assignments above are an initial proposal; confirm against §14. The
> *mechanism* (catalog-driven gates) is fixed regardless of the final matrix.

---

## 7. Python Domain Service (FastAPI)

A stateless FastAPI service. No conversation memory, no channel logic, no LLM loop.

### Endpoints

#### `POST /resolve`
Called by the Start node. Resolves identity, tenant, role, and the role-filtered
menu.

- **Auth:** verify the caller (shared secret / signature — see §10).
- **Input (from authenticated payload):** the receiving `phone_number_id` (tenant)
  and the sender's stable contact id.
- **Logic:**
  1. `phone_number_id → empresa_id`. If unknown tenant → error/closed (should not
     happen for a connected number; log it).
  2. `(contacto, empresa_id) → usuario, rol`. If the sender is not registered for
     this business → return a `registered: false` result so the flow takes the
     rejection branch.
  3. Build the **role-filtered menu** from the catalog (only ops whose
     `allowed_roles` include `rol`), respecting WhatsApp limits (§8).
- **Output (example):**
  ```json
  {
    "registered": true,
    "empresa": {"id": "...", "nombre": "..."},
    "usuario": {"id": "...", "nombre": "..."},
    "rol": "dueño",
    "menu": {
      "title": "¿Qué necesitás?",
      "items": [{"id": "factura_consultar", "label": "Consultar facturas"}, ...]
    }
  }
  ```
  For an unknown sender: `{"registered": false}` (plus a localized rejection
  message, or let the flow render it).

#### `POST /op/{id}`
Executes one domain operation. Single entry point for both menu sub-flows and agent
tool calls.

- **Auth:** verify the caller (§10).
- **Idempotency / dedup:** accept a message/request id and **dedup** so retried
  webhook deliveries don't double-execute side effects (especially `factura_crear`).
- **Resolution:** re-derive `empresa_id` and `rol` from the authenticated payload
  (never trust flow-passed values).
- **Authorization (deny-by-default):**
  1. `id` must be a known catalog operation, else reject.
  2. `rol ∈ op.allowed_roles`, else reject (403-style domain error).
  3. Every resource access filters by `empresa_id` (tenant gate).
- **Validation:** parse args against `op.args_schema`; reject on invalid.
- **Execute:** run the handler; lightweight ops return immediately; heavy ops hit
  the DB.
- **Output:** a typed result the flow can render as a WhatsApp message
  (text and/or a follow-up interactive payload).

### Error model
Return structured errors the flow can map to friendly messages:
`unauthorized` (role gate), `not_found` (tenant-scoped), `invalid_args`,
`unknown_operation`, `not_implemented` (stubs), `internal`.

---

## 8. Kapso Workflow (flow-as-code)

One workflow, multi-tenant at runtime, **defined as code** with `@kapso/workflows`
(JS/TS) and versioned in this repo. Deploy via the Kapso CLI. Defining the flow as
code mitigates platform lock-in and allows code review.

### Nodes / structure
1. **Start** → **webhook node `resolve`** → `POST /resolve`. Passes tenant
   (`phone_number_id`) + sender identity.
2. **Branch on `registered`:**
   - `false` → **polite rejection** message → end.
   - `true` → continue.
3. **Main menu:** `send-interactive` rendering the role-filtered `menu` returned by
   `/resolve` (Python builds it; Kapso only paints it). Respect WhatsApp limits:
   **≤3 buttons** or **a list with ≤10 rows**; **nest menus** when the operation
   set grows beyond the limit.
4. **`decide` + edges:** each button/list `id` routes to its sub-flow → a **webhook
   node** calling `POST /op/{id}` → render the result.
5. **`agent` node (hosted LLM)** for free text: system prompt + **tools = the
   role-filtered operations** (each tool maps to one `/op/{id}`). The set of tools
   the agent sees depends on the role (UX filtering; Python still enforces).
6. **handoff node:** hand the conversation to a human when needed. For messages
   outside WhatsApp's 24-hour window, use approved templates to (re)initiate.

### Convergence requirement
The webhook nodes used by menu sub-flows and the webhook calls made by agent tools
**must hit the same `/op/{id}` endpoints**. No operation logic lives in the flow.

### State
Conversation state lives in **Kapso flow variables**, not in Python. Carry
`empresa_id`/`rol` for UX if convenient, but Python always re-derives them.

---

## 9. Data Model

Multi-tenant relational schema. **Every business table carries `empresa_id`** and
every query filters by it.

Minimum tables (names indicative; adjust to chosen ORM/migrations):

- **`empresas`** — `id`, `nombre`, `phone_number_id` (unique; the Kapso receiving
  number that identifies the tenant), `created_at`.
- **`usuarios`** — `id`, `empresa_id` (FK), `contacto` (stable WhatsApp contact id),
  `nombre`, `rol`, `created_at`. Unique on `(empresa_id, contacto)`. Index on
  `contacto` for resolution.
- **`facturas`** — `id`, `empresa_id` (FK), invoice fields (number, date, total,
  status, etc.), `created_at`. The first heavy operation reads/writes here.
- **`stock`** — `id`, `empresa_id` (FK), item fields (sku, name, quantity, etc.).

Provide an **initial migration** creating these tables. Use a real migration tool
(e.g. Alembic) so the schema is reproducible. Add indexes supporting the hot paths:
`empresas.phone_number_id`, `usuarios(empresa_id, contacto)`, `facturas.empresa_id`.

**Tenant scoping is enforced in code**, not optional: a query for a resource without
an `empresa_id` filter is a bug.

---

## 10. Security Requirements

- **Caller authentication (flow → Python):** every webhook node call carries a
  shared secret (preferred: HMAC signature of the body, or at minimum a secret
  header injected via Kapso's `${ENV:KEY}`). Python rejects any unauthenticated or
  badly-signed request. Confirm Kapso's exact webhook-node auth options (§14) and
  pick the strongest available; the secret lives in environment config, never in
  the repo.
- **Tenant isolation is a security boundary.** `empresa_id` is always derived from
  the authenticated payload. Every business query filters by `empresa_id`
  server-side. A cross-tenant leak is treated as severe as an auth bypass.
- **The LLM is not a security barrier.** Role/tenant gates in Python are the only
  enforcement. Tool filtering and prompt instructions are UX/guidance only.
- **Deny-by-default** everywhere: unknown operation, unknown sender, missing role,
  invalid args → reject.
- **Idempotency** on side-effecting operations to survive webhook retries.
- **Secrets**: `.env` only, gitignored. Required keys at minimum:
  `DATABASE_URL`, the flow→API shared secret, and any `KAPSO_API_KEY` needed for
  deploying the flow. Document them in `.env.example`.
- Do not log full message contents or secrets; log tenant/op/decision metadata for
  audit.

---

## 11. Onboarding & Provisioning

- **Tenant onboarding:** handle the Kapso event `whatsapp.phone_number.created`
  (a business connects its WhatsApp number) → create the `empresa` row mapping
  `phone_number_id → empresa_id`. The initial owner (`dueño`) user is provisioned
  **out-of-band** (admin CLI / seed / admin endpoint), not inside the bot.
- **User & role management:** a minimal admin surface **outside the conversation**
  (CLI / seed / protected admin endpoint) creates and edits `usuarios` and roles.
  There is no self-service registration through WhatsApp.
- **Unknown sender:** a message from a contact not registered for the resolved
  tenant → the `/resolve` `registered:false` path → **polite rejection** message,
  no further action.

---

## 12. Implementation Tasks

Work through these in order. Each task should leave the repo in a working,
committed state.

1. **Scaffold the Python service.** New directory (see §15) with FastAPI,
   `pyproject.toml` (or `requirements.txt`), app entrypoint, config loading from
   `.env`, and `.env.example` listing `DATABASE_URL`, the flow→API shared secret,
   and `KAPSO_API_KEY`.
2. **Multi-tenant data model + initial migration.** Tables from §9 with `empresa_id`
   everywhere; migrations (e.g. Alembic); indexes for the hot paths. Add a seed
   script that creates one `empresa` + one `dueño` user for local testing.
3. **Operations catalog.** The single-source-of-truth module (§6) with the initial
   operations, `args_schema` (Pydantic), `allowed_roles`, labels, and agent
   descriptions. Provide helpers: `menu_for_role(rol)` and `tools_for_role(rol)`.
4. **`POST /resolve`.** Identity → tenant + role + role-filtered menu; `registered:
   false` for unknown senders; caller auth.
5. **`POST /op/{id}`.** Generic dispatch with: caller auth, dedup/idempotency,
   re-derivation of `empresa_id`/`rol` from the authenticated payload, the **two
   authorization gates** (role + tenant, deny-by-default), arg validation, handler
   execution. Implement `factura_consultar` end-to-end against the DB; stub the
   other heavy ops (correct contract + auth + tenant scoping, returning
   `not_implemented`). Implement the light ops (`ayuda`, `menu`) fully.
6. **Kapso workflow as code.** `@kapso/workflows` definition (§8): Start → resolve →
   menu/rejection → decide → webhook nodes to `/op/{id}` → agent node (role-filtered
   tools) → handoff. Webhook nodes authenticate to Python.
7. **Derive menu + tool schemas from the catalog.** A script/codegen step so the
   flow's tool schemas and any static menu come from the Python catalog (respecting
   role). No hand-maintained second list.
8. **Onboarding.** Handler for `whatsapp.phone_number.created` → create tenant.
   Document the out-of-band owner/user provisioning (CLI/seed/admin endpoint).
9. **Tests.** Unit tests per operation; **authorization tests** (role gate + cross-
   tenant isolation); caller-auth/signature verification tests. See §13.
10. **End-to-end validation on WhatsApp.** Run the scenarios in §13.
11. **Docs.** Update `README.md` to describe the new architecture (or add a section)
    so the WhatsApp/Kapso build is documented and the superseded Telegram phase is
    clearly marked.

---

## 13. Acceptance / Verification Criteria

The implementation is complete when all of the following pass.

### Automated tests
- **Role gate:** for each operation, a user whose role is **not** in `allowed_roles`
  receives an `unauthorized` error from `/op/{id}` — even when the `id` is supplied
  directly (simulating free-text/agent or a malicious client), bypassing the menu.
- **Tenant isolation (cross-tenant):** a user in business A cannot read or mutate
  any resource of business B. Construct two tenants with overlapping resource ids
  and assert that A's request scoped to B's resource returns `not_found` (never B's
  data). This is the **#1 risk** — cover it explicitly.
- **`empresa_id` provenance:** `/op/{id}` and `/resolve` derive `empresa_id`/identity
  from the authenticated payload; a request that tries to pass a different
  `empresa_id` as flow input does not change the effective tenant.
- **Caller auth:** unauthenticated or wrongly-signed requests to `/resolve` and
  `/op/{id}` are rejected.
- **Idempotency:** a duplicated side-effecting request (same message id) executes
  the effect once.
- **Catalog-driven derivation:** `menu_for_role`/`tools_for_role` return exactly the
  operations whose `allowed_roles` include the role — no more, no less.

### End-to-end (WhatsApp via Kapso)
- **Owner vs employee see different menus** (role-filtered). 
- **Heavy op end-to-end:** an owner runs `factura_consultar` and gets results scoped
  to their business.
- **Disallowed op via free text:** an employee asks (in free text) for an
  owner-only operation; the agent may attempt the tool, but Python **rejects** and
  the user gets a friendly "no permission" message.
- **Unknown sender:** a number not registered for the tenant gets the polite
  rejection and nothing else.
- **Handoff:** the handoff path routes the conversation to a human.

---

## 14. Open Questions (confirm before/while implementing)

These are genuinely undecided. Where a task depends on one, ask the user rather than
guessing.

1. **Kapso webhook-node auth:** what exact authentication mechanisms does the
   webhook node support (HMAC signature? custom headers via `${ENV:KEY}`? mTLS)?
   Pick the strongest. Drives §10.
2. **Stable contact identity:** what stable sender identifier does Kapso expose for
   a WhatsApp contact (and is a raw `phone_number` reliably present)? Drives §4 and
   the `usuarios.contacto` column.
3. **Agent node model & cost:** which LLM does the Kapso agent node run, and what
   are the cost implications? Confirm before relying heavily on free-text.
4. **Role set:** confirm the final roles and the operation→role matrix in §6
   (proposed: dueño / encargado / empleado).
5. **`estadisticas` scope:** which specific stats should the business stats
   operation return?
6. **Datastore choice:** confirm the database (Postgres assumed) and ORM/migration
   tooling (SQLAlchemy + Alembic assumed) before scaffolding §9.

---

## 15. Tech Stack & Conventions

- **Domain service:** Python 3.11+, **FastAPI**, Pydantic for schemas. Assume
  **PostgreSQL** + **SQLAlchemy** + **Alembic** unless §14.6 says otherwise.
- **Workflow:** `@kapso/workflows` (JS/TS) — declarative flow config, deployed via
  the Kapso CLI. This is the only JS/TS in the project (polyglot is intentional and
  bounded: domain in Python, flow definition in JS/TS).
- **Repo layout (proposed):**
  ```
  service/                 # NEW — Python FastAPI domain service
    rai/
      main.py              # FastAPI app, /resolve and /op/{id}
      catalog.py           # operations catalog (single source of truth)
      auth.py              # caller auth + role/tenant gates
      models.py            # ORM models (empresa_id everywhere)
      ops/                 # operation handlers
    migrations/            # Alembic
    tests/                 # unit + authz + cross-tenant tests
    pyproject.toml
    .env.example
  flow/                    # NEW — Kapso flow-as-code (@kapso/workflows)
    rai.flow.ts
    package.json
  agent/                   # EXISTING — superseded Telegram bot (do not extend)
  infra/                   # EXISTING — droplet infra (revisit if redeploying)
  SPEC.md                  # this document
  README.md
  ```
- **User-facing strings** (menu labels, rejection messages) in **Spanish**; code,
  identifiers, and this spec in English.
- **Deploy:** Python service needs a **public HTTPS endpoint** (the webhook nodes
  call it). DB is multi-tenant (`empresa_id` on every business table). Flow deployed
  via CLI; each business's number connected in Kapso.
- **Commits:** small, descriptive, one logical step per commit; keep the repo
  green at each task boundary.
```

---

## Appendix — Design rationale (for reviewers)

- **Why Hybrid (Kapso orchestrates, Python owns domain)?** Kapso handles the hard,
  channel-specific parts (WhatsApp interactive messages, the 24h window, hosted LLM
  agent loop, conversation state) while keeping all business logic, data, and —
  critically — authorization in our own stateless service that we fully control and
  test.
- **Why a single operations catalog?** The deterministic menu and the free-text
  agent are two front-ends to the *same* operations. A single catalog with
  `allowed_roles` makes the menu, the agent tools, and the authorization gate all
  derive from one declaration — no drift, and adding an operation is a one-place
  change.
- **Why enforce authorization only in Python?** The flow and the LLM can be steered
  (free text, prompt tricks, bugs). The only trustworthy gate is server-side, on
  every call, against values derived from the authenticated payload. Menu/tool
  filtering is a usability nicety layered on top.
- **Why is cross-tenant isolation called out as the top risk?** One number per
  business plus shared tables means a missing `empresa_id` filter silently exposes
  another business's data. It is treated with the same severity as a permission
  bypass and gets dedicated tests.
