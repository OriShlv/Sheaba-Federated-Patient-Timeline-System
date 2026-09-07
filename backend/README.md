# Federated Patient Timeline Backend

This is the canonical backend architecture and decision document. It describes the
implemented state only.

## Current scope

The backend provides the complete assignment timeline flow. `GET /api/timeline` validates
the request, applies role and requested-type policy, selects only required sources, runs
those sources concurrently, filters normalized events again by the effective type
allowlist, and passes the authorized events to pure temporal grouping.

Expected source failures preserve successful-source data and return HTTP 206 with
`partial=true` and a deterministic source-name warning. If all selected sources fail, the
same assignment behavior returns an empty degraded timeline. A role/type combination with
no effective event types performs no external calls and returns an empty HTTP 200 result.
Unexpected defects return a safe HTTP 500 envelope. Retries, circuit breakers, caching,
pagination, and request-wide deadlines are not implemented.

## Local setup

Python 3.12 or newer is required.

From the repository root, `./start.sh` starts Docker infrastructure, bootstraps the backend
on first run, and launches Uvicorn on port `3000`.

Manual backend-only startup:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=src uvicorn timeline_api.main:app --reload --host 0.0.0.0 --port 3000
```

The application does not contact Postgres, MongoDB, or Vitals during import. Its asyncpg
pool starts with zero connections, and PyMongo connects lazily. The supplied infrastructure
is therefore not required merely to load the application or `/docs`.

Available endpoints:

- Timeline: `GET http://localhost:3000/api/timeline?patientId=1` with
  `X-User-Role: doctor`
- OpenAPI schema: `http://localhost:3000/openapi.json`
- Swagger UI: `http://localhost:3000/docs`

Configuration uses `TIMELINE_`-prefixed environment variables documented in
`.env.example`. Defaults match the supplied local Docker infrastructure.

## Package structure

```text
src/timeline_api/
├── adapters/
│   ├── pacs.py     # MongoDB imaging reads and normalization
│   ├── registry.py # Parameterized Registry reads and normalization
│   └── vitals.py   # HTTP Vitals reads, validation, filtering, and normalization
├── api/
│   ├── models.py   # Frontend-compatible grouped timeline response
│   ├── errors.py   # Validation and safe unexpected-error envelopes
│   ├── query.py    # Role-independent query parsing and validation
│   └── routes.py   # Thin dependency wiring and HTTP result translation
├── services/
│   ├── grouping.py # Pure deterministic temporal grouping
│   ├── policy.py   # Pure role/type policy and source selection
│   └── timeline.py # Concurrent federation and response construction
├── config.py        # Typed environment and source-timeout settings
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
and duration. Each selected source emits a success/unavailable completion record, and each
completed timeline emits selected-source and full/partial metadata. Unexpected request
failures emit only a static failure event before the safe HTTP 500 response.

The formatter never serializes arbitrary log message content and accepts an event name
only from the `OperationalEvent` enum. Clinical payloads, vitals values, radiology notes,
patient identifiers, raw upstream error text, and secrets are not serialized. HTTP client
and server access INFO logs are suppressed because their URLs can contain patient
identifiers.

## Verification

```bash
cd backend
pytest tests/unit/test_policy.py
pytest tests/test_timeline_service.py
pytest tests/test_timeline_api.py tests/test_main.py
pytest tests/unit/test_grouping.py
pytest tests/test_pacs.py tests/test_vitals.py
pytest
ruff check .
ruff format --check .
mypy
PYTHONPATH=src python -c "from timeline_api.main import app; print(app.title)"
```

The startup and docs tests enter the real application lifespan while external services are
absent, proving that foundation startup remains lazy.

To run the live Registry and source-adapter checks after starting the supplied
infrastructure:

```bash
cd backend
TIMELINE_RUN_LIVE_TESTS=1 pytest tests/test_registry_live.py
TIMELINE_RUN_LIVE_TESTS=1 pytest tests/test_source_adapters_live.py
TIMELINE_RUN_LIVE_TESTS=1 pytest tests/test_timeline_federation_live.py
curl -H "X-User-Role: doctor" \
  "http://localhost:3000/api/timeline?patientId=1"
```

The seed defines patient `1` with three surgeries and two emergency-room encounters. Live
tests verify those counts through the endpoint and exercise no bounds, each single bound,
both inclusive boundaries, non-overlap exclusion, and patient filtering through the real
adapter. The PACS seed contains 17 imaging documents for patient `1`, and the Vitals mock
returns 22 readings. The source-adapter live test verifies those counts, representative
normalized values, patient filtering, optional bounds, exact inclusive boundaries, and
stable PACS IDs.

The live federation check makes a real all-source doctor request, verifies the complete
seeded event counts after grouping, confirms that interns receive no imaging, and verifies
that `types=vitals` returns only Vitals events without Registry parents.

The supplied frontend's Vite `/api` proxy reaches port 3000 and consumes the existing
camelCase event aliases plus `partial` and `warning`; a runtime proxy smoke succeeds. The
backend also returns valid unmatched child events in `standalone`, but the supplied
frontend does not render that array. A vitals-only response can therefore appear as “No
events found” even though the API returned valid standalone events. This is a supplied
frontend presentation limitation; the backend implementation does not modify UI behavior.
The supplied frontend production build retains pre-existing TypeScript errors in
`Timeline.tsx`.

## Decisions

### FastAPI application framework

- **Decision:** Use FastAPI with an application factory and generated OpenAPI documentation.
- **Rationale:** It provides typed request/response integration and `/docs` with little
framework code.
- **Alternative considered:** A Node.js/TypeScript backend.
- **Why not selected for this assignment:** The implementation uses Python, and FastAPI fits
the required typed async integrations directly.
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



### PyMongo Async PACS access

- **Decision:** Use the asynchronous API in PyMongo to query the supplied
`pacs.imaging` collection through the lifespan-managed `AsyncMongoClient`.
- **Rationale:** Patient and inclusive timestamp predicates execute in MongoDB, and a
minimal projection limits each returned document to `_id`, `patientId`, `modality`,
`timestamp`, and `radiologistNote`.
- **Alternative considered:** Motor.
- **Why not selected for this assignment:** Motor is deprecated in favor of PyMongo
Async, while PyMongo already provides the required asynchronous cursor API and is the
selected dependency.
- **Production reconsideration trigger:** Reassess driver version and query indexes when
measured production load, supported MongoDB versions, or PyMongo Async API stability
requires it.



### HTTPX Vitals access

- **Decision:** Use the shared lifespan-managed HTTPX `AsyncClient` for
`GET /vitals/{patientId}`.
- **Rationale:** Reusing one asynchronous client preserves connection pooling and gives
the adapter a direct way to apply its bounded call timeout. The supplied service has no
date query parameters, so validated readings are filtered inside the adapter.
- **Alternative considered:** Construct a client per adapter call.
- **Why not selected for this assignment:** Per-call clients discard connection reuse and
add unnecessary lifecycle work.
- **Production reconsideration trigger:** Revisit client limits and timeout values from
measured dependency latency and concurrency.



### Child source adapter boundary

- **Decision:** Keep Mongo document fields and Vitals response models inside their
source-specific adapters; only `ImagingEvent` and `VitalsEvent` values cross into
application/domain code.
- **Rationale:** Strict source validation prevents raw dictionaries, Mongo documents, and
HTTP response objects from leaking into orchestration.
- **Alternative considered:** Return raw source values and map them in `TimelineService`.
- **Why not selected for this assignment:** It would couple application policy and
orchestration to two external schemas.
- **Production reconsideration trigger:** Preserve the boundary when upstream schemas
change; revise only the narrow source validators and normalized contract fields that
product requirements actually need.



### Child point-event filtering and timestamps

- **Decision:** Apply inclusive `timestamp >= from` and `timestamp <= to` predicates in
MongoDB for PACS. Validate all Vitals readings and then apply the same inclusive
comparisons in the adapter because the supplied endpoint accepts only a patient path.
Timezone-aware source values are converted to UTC; timezone-naive values are interpreted
as UTC at the adapter boundary.
- **Rationale:** Source-side PACS filtering avoids unnecessary transfer, while local
Vitals filtering matches the actual mock contract. No naive datetime enters the domain.
- **Alternative considered:** Load all PACS documents or require offsets on every supplied
source timestamp.
- **Why not selected for this assignment:** Loading all PACS data duplicates database
work, and the assignment-level UTC assumption explicitly accommodates naive source values.
- **Production reconsideration trigger:** Define explicit source timezone contracts before
handling real clinical timestamps and add server-side Vitals bounds if that API gains
them.



### Registry adapter boundary

- **Decision:** Keep asyncpg records, SQL column names, and Registry timestamp handling
inside `RegistryAdapter`; return only normalized typed parent events to `TimelineService`.
Malformed Registry rows raise `RegistryRowValidationError` at this boundary so schema/data
contract failures become typed unavailable outcomes instead of unexpected HTTP 500s.
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
- **Why not selected for this assignment:** The implementation consumes the provided schema and
must not silently migrate it or reinterpret seeded values.
- **Production reconsideration trigger:** Define an explicit source timezone contract and
use an appropriate timezone-aware database type before handling real clinical timestamps.



### Normalized event IDs

- **Decision:** Construct IDs as `<source>:<type>:<source-key>` with a small pure helper.
- **Rationale:** IDs are deterministic, stable, and unambiguous across sources. Registry
parents produce `registry:surgery:<id>` and `registry:emergency_room:<id>`. PACS uses its
stable Mongo `_id` as `pacs:imaging:<object-id>`. Because the Vitals response has no
identifier, it uses
`vitals:vitals:<patient-id>:<normalized-UTC-timestamp>` and assumes the supplied mock has
at most one reading for a patient at a timestamp.
- **Alternative considered:** A generic ID framework or generated UUIDs.
- **Why not selected for this assignment:** A framework adds abstraction without another
ID use case, while generated UUIDs are not stable across fetches.
- **Production reconsideration trigger:** Require a durable upstream Vitals identifier if
multiple readings per patient/timestamp become valid, or revisit if the API requires
opaque identifiers.



### Adapter timeout scope

- **Decision:** Configure positive Registry, PACS, and Vitals timeout values, defaulting to
five seconds. Registry wraps its asyncpg reads in `asyncio.wait_for`; PACS applies PyMongo's
operation deadline around complete cursor materialization; Vitals passes its timeout on the
HTTPX request.
- **Rationale:** Each source call is bounded without introducing federation policy into an
adapter.
- **Alternative considered:** A request-wide propagated deadline.
- **Why not selected for this assignment:** Remaining-budget propagation belongs to later
application orchestration and is intentionally outside the current scope.
- **Production reconsideration trigger:** Tune values and add request-wide deadline
propagation when production latency objectives and dependency budgets are defined.



### Access policy and source minimization

- **Decision:** `services/policy.py` is a pure policy boundary. Doctors may see all four
event types; nurses may see emergency-room, imaging, and Vitals events; interns may see
surgery, emergency-room, and Vitals events. Requested `types` are intersected with that
role allowlist and can never expand access.
- **Input behavior:** `types` is an optional comma-separated list of exact lowercase event
type values. Surrounding whitespace is removed, duplicate values retain their first
occurrence, and empty or unknown values return HTTP 400. If omitted, the role's full
allowlist applies.
- **Source plan:** Registry is selected for surgery or emergency-room types, PACS for
imaging, and Vitals for vitals. The deterministic execution/warning order is Registry,
PACS, then Vitals. Intern defaults therefore skip PACS, while `types=vitals` selects only
Vitals.
- **No selected sources:** If intersection leaves no effective event types, no adapter is
called and the API returns an empty HTTP 200 timeline with `partial=false`.
- **Rationale:** Applying policy before creating source operations both enforces visibility
and avoids unauthorized or irrelevant dependency access.
- **Alternative considered:** Fetch every source and filter only after grouping.
- **Why not selected for this assignment:** It performs unnecessary I/O and can expose
parent context that should have been removed before child assignment.
- **Production reconsideration trigger:** Replace the assignment header role with trusted
identity and patient authorization when a real authentication contract exists.


### Concurrent federation and failure isolation

- **Decision:** One `TimelineService` owns the application narrative. It asks policy for
the source plan, creates operations only for selected sources, and executes independent
operations concurrently with `asyncio.gather`.
- **Typed outcomes:** Named database, MongoDB, HTTP, timeout, and source-schema failures
become typed unavailable outcomes. Registry schema failures use
`RegistryRowValidationError`; PACS and Vitals use their adapter validation errors.
Successful outcomes carry only normalized events.
Unexpected exception types are not downgraded and reach the safe HTTP 500 boundary.
- **Degraded response:** Any unavailable selected source produces HTTP 206,
`partial=true`, successful-source data, and a warning containing deterministic unavailable
source names only. If every selected source is unavailable, the response remains an empty
HTTP 206 for assignment consistency.
- **Alternative considered:** Return HTTP 503 when all selected sources fail.
- **Why not selected for this assignment:** The supplied status contract emphasizes 206
for dependency failure, so the implementation applies it consistently.
- **Production reconsideration trigger:** Define availability and retry contracts before
choosing 503, retries, request deadlines, or circuit breakers for production.


### RBAC before grouping and defense in depth

- **Decision:** Filter normalized events by the effective role/requested-type allowlist
before calling `group_events`, even though source selection already minimizes possible
types. Authorized parents with no children are retained.
- **Rationale:** Source adapters remain role-independent, and the second allowlist check
protects against broad sources such as Registry returning both allowed and disallowed
types. If an unauthorized parent is removed, an authorized child remains eligible and may
become standalone or attach to another authorized parent.
- **Alternative considered:** Group all events and remove unauthorized nodes afterward.
- **Why not selected for this assignment:** Post-group filtering can silently discard an
authorized child with its unauthorized parent and violates the assignment's requirement
to filter both parent and child events.
- **Production reconsideration trigger:** Preserve policy-before-grouping unless the
product defines another explicit authorization-aware grouping rule.


### Timeline HTTP validation and status translation

- **Decision:** The route validates a positive `patientId`, required
`X-User-Role: doctor|nurse|intern`, optional valid ISO8601 bounds, date order, and requested
types before invoking the service. Aware dates normalize to UTC; valid naive dates are
interpreted as UTC for this assignment.
- **Status behavior:** Complete and no-selected-source results return 200; known source
degradation returns 206; request validation returns 400 with details; unexpected defects
return `{"detail":"Internal server error"}` with 500 and no raw exception text.
- **Validation contract:** FastAPI raises `RequestValidationError` for invalid query/header
input, but this application intentionally translates that to HTTP 400. The `/api/timeline`
OpenAPI contract documents 400/206/500 and omits the framework-default 422 response.
- **Rationale:** HTTP parsing and status translation stay at the API boundary while
policy, source selection, and grouping remain framework-independent.
- **Production reconsideration trigger:** Require an explicit timezone contract rather
than interpreting naive clinical timestamps when integrating real systems.


### Pure timeline grouping

- **Decision:** Use a pure `group_events` function that receives normalized parent and
child sequences and returns immutable parent groups plus standalone children without
mutating or copying event objects.
- **Rationale:** Temporal assignment can be tested independently from FastAPI, policy,
configuration, adapters, databases, and HTTP clients. The function receives only events
already authorized and selected by application orchestration.
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

- **Decision:** Use Cursor's coding agent to inspect requirements and existing code,
support scoped implementation, add tests and documentation, run validation, and review
changes.
- **Rationale:** The agent accelerates mechanical implementation and systematic checking
while the developer retains responsibility for scope and technical decisions.
- **Alternative considered:** Implement and review the repository without AI assistance.
- **Why not selected for this assignment:** AI assistance was explicitly available and its
actual use is documented for transparency.
- **Production reconsideration trigger:** Apply the organization's code provenance,
privacy, and review policy before using AI on production or sensitive repositories.
