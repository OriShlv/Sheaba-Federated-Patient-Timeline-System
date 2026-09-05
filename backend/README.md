# Federated Patient Timeline Backend

This is the canonical backend architecture and decision document. It describes the
implemented state only; later branches update this file as behavior is added.

## Current scope

The backend currently provides a typed FastAPI application skeleton, environment-based
settings, lifespan-managed shared clients, normalized domain contracts, deterministic ID
construction, privacy-safe JSON logging, and development tooling.

The timeline endpoint, source adapters, access policy, grouping, federation, and partial
failure HTTP behavior are intentionally not implemented in this foundation branch.

## Local setup

Python 3.12 or newer is required.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
uvicorn timeline_api.main:app --reload --port 3000
```

The application does not contact Postgres, MongoDB, or Vitals during import. Its asyncpg
pool starts with zero connections, and PyMongo connects lazily. The supplied infrastructure
is therefore not required merely to load the application or `/docs`.

Available foundation endpoints:

- OpenAPI schema: `http://localhost:3000/openapi.json`
- Swagger UI: `http://localhost:3000/docs`

Configuration uses `TIMELINE_`-prefixed environment variables documented in
`.env.example`. Defaults match the supplied local Docker infrastructure.

## Package structure

```text
src/timeline_api/
├── config.py       # Typed environment settings
├── logging.py      # Privacy-safe JSON operational logging
├── main.py         # FastAPI application factory and application instance
├── resources.py    # Shared client creation, access, and shutdown
└── domain/
    ├── ids.py      # Normalized event ID construction
    ├── models.py   # Typed normalized event contracts
    └── outcomes.py # Typed source success/unavailable contracts
```

The four normalized event variants are surgery, emergency room, imaging, and vitals.
Source-specific documents and responses do not belong in these contracts. Parent events
require valid inclusive intervals, all timestamps are timezone-aware and normalized to UTC,
and models are immutable.

One resource set is created per FastAPI lifespan:

- one asyncpg pool with `min_size=0`
- one timezone-aware PyMongo `AsyncMongoClient`
- one HTTPX `AsyncClient`

All three are closed during lifespan shutdown.

## Operational logging

Application logs are JSON records with an explicit static `OperationalEvent` name and an
allowlist of safe operational context: source, outcome, selected sources, partial status,
and duration. The formatter never serializes arbitrary log message content and accepts an
event name only from the `OperationalEvent` enum. Clinical payloads, vitals values,
radiology notes, patient identifiers, raw upstream error text, and secrets are not
serialized. HTTP client and server access INFO logs are suppressed because their URLs can
contain patient identifiers.

## Verification

```bash
cd backend
pytest
ruff check .
ruff format --check .
mypy
python -c "from timeline_api.main import app; print(app.title)"
```

The startup and docs tests enter the real application lifespan while external services are
absent, proving that foundation startup remains lazy.

## Decisions

### FastAPI application framework

- **Decision:** Use FastAPI with an application factory and generated OpenAPI documentation.
- **Rationale:** It provides typed request/response integration and `/docs` with little
framework code.
- **Alternative considered:** A Node.js/TypeScript backend.
- **Why not selected for this assignment:** The approved plan selects Python, and FastAPI
fits the required typed async integrations directly.
- **Production reconsideration trigger:** Reconsider only if the owning team or deployment
platform standardizes on another runtime.



### Pydantic domain contracts

- **Decision:** Represent each normalized event type as a strict, immutable Pydantic model
and expose a discriminated union.
- **Rationale:** Type-specific data, source/type combinations, UTC timestamps, and parent
interval invariants are validated without loose dictionaries.
- **Alternative considered:** One model with optional fields for every event type.
- **Why not selected for this assignment:** It permits invalid combinations and weakens
static narrowing.
- **Production reconsideration trigger:** Revisit the fields when an upstream or API
contract adds a real event variant.



### Lifespan-managed shared clients

- **Decision:** Create one asyncpg pool, PyMongo async client, and HTTPX async client per
process through FastAPI lifespan.
- **Rationale:** Clients are reused and have one explicit shutdown path. Zero-minimum/lazy
database connectivity keeps skeleton startup independent of external services.
- **Alternative considered:** Construct a client for each request.
- **Why not selected for this assignment:** Per-request clients waste connection resources
and make cleanup harder.
- **Production reconsideration trigger:** Tune pool sizes and timeouts from measured
concurrency and dependency behavior.



### Normalized event IDs

- **Decision:** Construct IDs as `<source>:<type>:<source-key>` with a small pure helper.
- **Rationale:** IDs are deterministic, stable, and unambiguous across sources.
- **Alternative considered:** A generic ID framework or generated UUIDs.
- **Why not selected for this assignment:** A framework adds abstraction without another
ID use case, while generated UUIDs are not stable across fetches.
- **Production reconsideration trigger:** Revisit if a source lacks a stable key or the API
requires opaque identifiers.



### Privacy-safe operational logging

- **Decision:** Use the standard logging library with a JSON formatter that serializes only
explicitly allowlisted operational fields.
- **Rationale:** Later source/federation events can be diagnosed without exposing clinical
or sensitive values.
- **Alternative considered:** Add a full observability/logging stack.
- **Why not selected for this assignment:** It is disproportionate to the foundation and
supplied runtime.
- **Production reconsideration trigger:** Add protected audit and telemetry systems when
production compliance and operations requirements are defined.



### AI usage

- **Decision:** Use Cursor's coding agent to inspect the approved plan and supplied
infrastructure, create the foundation code/tests/documentation, run validation, and
perform branch review.
- **Rationale:** The agent accelerates mechanical implementation and systematic checking
while the developer retains responsibility for scope and technical decisions.
- **Alternative considered:** Implement and review the branch without AI assistance.
- **Why not selected for this assignment:** AI assistance was explicitly available and its
actual use is documented for transparency.
- **Production reconsideration trigger:** Apply the organization's code provenance,
privacy, and review policy before using AI on production or sensitive repositories.
