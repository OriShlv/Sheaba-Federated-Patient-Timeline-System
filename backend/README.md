# Federated Patient Timeline Backend

This is the canonical backend architecture and decision document. It describes the
implemented state only; later branches update this file as behavior is added.

## Current scope

The backend currently provides a Registry vertical slice and a pure grouping module.
`GET /api/timeline` parses a positive `patientId` and optional inclusive `from`/`to`
bounds, calls `TimelineService`, reads surgery and emergency-room parents through
`RegistryAdapter`, and returns normalized events. The grouping module accepts
already-normalized authorized parents and children, but it is intentionally not wired into
the Registry-only service until the federation branch. API parents therefore still have
empty `children`, while `standalone` is empty and `partial` is `false`.

PACS, Vitals, grouping integration, RBAC, requested-type filtering, multi-source
federation, retries, and partial-failure HTTP behavior are intentionally not implemented
yet. `types` and `X-User-Role` therefore have no behavioral semantics in this slice and are
not advertised as implemented inputs.

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

Available endpoints:

- Registry timeline: `http://localhost:3000/api/timeline?patientId=1`
- OpenAPI schema: `http://localhost:3000/openapi.json`
- Swagger UI: `http://localhost:3000/docs`

Configuration uses `TIMELINE_`-prefixed environment variables documented in
`.env.example`. Defaults match the supplied local Docker infrastructure.

## Package structure

```text
src/timeline_api/
├── adapters/
│   └── registry.py # Parameterized Registry reads and normalization
├── api/
│   ├── models.py   # Current Registry-only HTTP response
│   ├── query.py    # Timeline query parsing and validation
│   └── routes.py   # Thin route, dependencies, and HTTP error translation
├── services/
│   ├── grouping.py # Pure deterministic temporal grouping
│   └── timeline.py # Registry-only application orchestration
├── config.py        # Typed environment settings
├── logging.py       # Privacy-safe JSON operational logging
├── main.py          # FastAPI application factory and application instance
├── resources.py     # Shared client creation, access, and shutdown
└── domain/
    ├── ids.py       # Normalized event ID construction
    ├── models.py    # Typed normalized event contracts
    └── outcomes.py  # Typed source success/unavailable contracts
```

The four normalized event variants are surgery, emergency room, imaging, and vitals.
Source-specific documents and responses do not belong in these contracts. Parent events
require valid inclusive intervals, all timestamps are timezone-aware and normalized to UTC,
and models are immutable. Grouping imports only these normalized contracts and standard
library utilities; it has no framework, policy, configuration, adapter, or I/O dependency.

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
pytest tests/unit/test_grouping.py
pytest
ruff check .
ruff format --check .
mypy
python -c "from timeline_api.main import app; print(app.title)"
```

The startup and docs tests enter the real application lifespan while external services are
absent, proving that foundation startup remains lazy.

To run the live Registry checks after starting the supplied PostgreSQL container:

```bash
cd backend
TIMELINE_RUN_LIVE_TESTS=1 pytest tests/test_registry_live.py
curl "http://localhost:3000/api/timeline?patientId=1"
```

The seed defines patient `1` with three surgeries and two emergency-room encounters. Live
tests verify those counts through the endpoint and exercise no bounds, each single bound,
both inclusive boundaries, non-overlap exclusion, and patient filtering through the real
adapter.

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



### asyncpg Registry access

- **Decision:** Use asyncpg directly with two fixed, parameterized Registry queries.
- **Rationale:** The supplied Registry slice needs only readable surgery and emergency-room
reads, and the shared asyncpg pool already fits FastAPI's asynchronous lifecycle.
- **Alternative considered:** SQLAlchemy with ORM or Core models.
- **Why not selected for this assignment:** Its mapping and abstraction overhead does not
improve two stable queries against a supplied schema.
- **Production reconsideration trigger:** Reconsider when the database domain grows,
schema migrations become application-owned, or composable queries outweigh the extra
layer.



### Registry adapter boundary

- **Decision:** Keep asyncpg records, SQL column names, and Registry timestamp handling
inside `RegistryAdapter`; return only normalized typed parent events to `TimelineService`.
- **Rationale:** Application behavior can depend on one source-independent event contract
instead of database result shapes.
- **Alternative considered:** Return asyncpg records to the service and normalize there.
- **Why not selected for this assignment:** It leaks source details across the adapter
boundary and gives the service both integration and orchestration responsibilities.
- **Production reconsideration trigger:** Keep the boundary even if persistence technology
changes; revise only the normalized contract when product requirements add real fields.



### Registry parent interval filtering

- **Decision:** Apply inclusive interval-overlap predicates in SQL:
`end_time >= from` and `start_time <= to`, omitting each predicate when its bound is absent.
- **Rationale:** A parent that starts before the requested range can still be active inside
it, and exact start/end boundaries belong to the requested timeline.
- **Alternative considered:** Filter only by parent start time or load all patient rows and
filter in Python.
- **Why not selected for this assignment:** Start-only filtering drops valid overlaps, and
application-side filtering transfers avoidable rows and duplicates database work.
- **Production reconsideration trigger:** Preserve overlap semantics; reconsider query
shape or add measured indexes when production volume and query plans require it.



### Registry timestamp assumption

- **Decision:** Interpret the supplied Registry's timezone-naive `TIMESTAMP` values as UTC
at the adapter boundary and immediately create timezone-aware UTC domain values. UTC API
bounds are converted back to naive UTC only when bound to those supplied columns.
- **Rationale:** Naive datetimes do not cross into the application/domain layer, while
comparisons remain compatible with the unmodified assignment schema.
- **Alternative considered:** Change the supplied columns to `TIMESTAMPTZ`.
- **Why not selected for this assignment:** This branch consumes the provided schema and
must not silently migrate it or reinterpret seeded values.
- **Production reconsideration trigger:** Define an explicit source timezone contract and
use an appropriate timezone-aware database type before handling real clinical timestamps.



### Normalized event IDs

- **Decision:** Construct IDs as `<source>:<type>:<source-key>` with a small pure helper.
- **Rationale:** IDs are deterministic, stable, and unambiguous across sources. Registry
parents currently produce `registry:surgery:<id>` and `registry:emergency_room:<id>`.
- **Alternative considered:** A generic ID framework or generated UUIDs.
- **Why not selected for this assignment:** A framework adds abstraction without another
ID use case, while generated UUIDs are not stable across fetches.
- **Production reconsideration trigger:** Revisit if a source lacks a stable key or the API
requires opaque identifiers.



### Pure timeline grouping

- **Decision:** Use a pure `group_events` function that receives normalized parent and
child sequences and returns immutable parent groups plus standalone children without
mutating or copying event objects.
- **Rationale:** Temporal assignment can be tested independently from FastAPI, policy,
configuration, adapters, databases, and HTTP clients. The function can later receive only
the events already authorized and selected by application orchestration.
- **Algorithm:** Sort copied parent entries by start and copied children chronologically,
then sweep the children. Activate parents whose start is at or before the child into a heap
ordered by latest start and then normalized ID ascending. Lazily remove candidates whose
end is before the child; the remaining heap winner contains the child. Exact start and end
matches are therefore inclusive.
- **Complexity:** After ordering inputs, heap assignment is
`O((P + C) log P)`. For arbitrary unsorted inputs, exact end-to-end time is
`O(P log P + C log C + (P + C) log P)` and space is `O(P + C)`. Sorting children is
required by the output contract and input-order independence.
- **Alternative considered:** For each child, scan every parent and choose the best match
in `O(P * C)` time. It is simpler as a small test oracle but is not used in application
code because the sweep remains readable while scaling better.
- **Overlap winner:** When intervals overlap, the eligible parent with the latest start
wins, directly following the assignment algorithm.
- **Equal-start assumption:** The assignment does not define identical parent starts.
Stable normalized parent ID ascending is the deterministic tie-breaker.
- **Standalone ambiguity:** The response-contract comment says `standalone` is always
empty, but the grouping algorithm and supplied PACS/Vitals seed cases explicitly mark
unmatched children as standalone. The implementation follows the algorithm and seeds.
- **Ordering:** Parents are newest first by `(start descending, ID ascending)`. Children
within a parent and standalone children are chronological by
`(timestamp ascending, ID ascending)`.
- **Production reconsideration trigger:** Revisit the deterministic tie only if the
product contract defines another clinical precedence rule.


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

- **Decision:** Use Cursor's coding agent to inspect the approved plan, assignment,
normalized domain contracts, and supplied seeds; implement the Registry vertical slice and
pure grouping algorithm; add focused tests and documentation; and run validation and
complete-diff reviews.
- **Rationale:** The agent accelerates mechanical implementation and systematic checking
while the developer retains responsibility for scope and technical decisions.
- **Alternative considered:** Implement and review the branch without AI assistance.
- **Why not selected for this assignment:** AI assistance was explicitly available and its
actual use is documented for transparency.
- **Production reconsideration trigger:** Apply the organization's code provenance,
privacy, and review policy before using AI on production or sensitive repositories.
