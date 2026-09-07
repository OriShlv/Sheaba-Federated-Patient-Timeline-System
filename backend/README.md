# Federated Patient Timeline Backend

Backend architecture notes for the FastAPI timeline API. The root [README](../README.md) covers reviewer-facing setup, grouping, RBAC, and API behavior. This document records backend-specific structure, contracts, and trade-offs.

## Setup

Python 3.12 or newer is required. From the repository root, `./start.sh` starts Docker infrastructure, creates `backend/.venv` on first run, and launches Uvicorn on port `3000`.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=src uvicorn timeline_api.main:app --reload --host 0.0.0.0 --port 3000
```

The application does not contact Postgres, MongoDB, or Vitals during import. The asyncpg pool starts with zero connections, and PyMongo connects lazily, so `/docs` works without infrastructure. Configuration uses `TIMELINE_`-prefixed variables from `.env.example`; defaults match the supplied Docker services.

## Module structure

```text
src/timeline_api/
├── adapters/
│   ├── pacs.py
│   ├── registry.py
│   └── vitals.py
├── api/
│   ├── models.py
│   ├── errors.py
│   ├── query.py
│   └── routes.py
├── services/
│   ├── grouping.py
│   ├── policy.py
│   └── timeline.py
├── domain/
│   ├── ids.py
│   ├── models.py
│   └── outcomes.py
├── config.py
├── logging.py
├── main.py
└── resources.py
```

The HTTP route is thin: it validates the query, calls `TimelineService`, and translates `partial` into HTTP 200 or 206. FastAPI's default 422 is replaced by HTTP 400 with the same validation envelope.

One resource set is created per process lifespan: an asyncpg pool (`min_size=0`), a timezone-aware PyMongo `AsyncMongoClient`, and an HTTPX `AsyncClient`. All three are closed on shutdown.

## Domain model

Normalized events are strict immutable Pydantic models: surgery, emergency room, imaging, and vitals. Source-specific documents do not cross adapter boundaries. Parent events require valid inclusive intervals. All domain timestamps are timezone-aware UTC.

IDs are `<source>:<type>:<source-key>`. Registry uses table IDs, PACS uses Mongo `_id`, and Vitals uses `<patient-id>:<normalized-UTC-timestamp>` because the mock payload has no identifier.

## Adapters

Each adapter fetches, validates, and normalizes one source. Timeout values default to five seconds and stay inside the adapter: `asyncio.wait_for` for Registry, PyMongo's operation deadline for PACS, and HTTPX request timeout for Vitals.

**Registry (asyncpg).** Two parameterized SQL queries return surgeries and emergency-room rows. Inclusive overlap is `end_time >= from` and `start_time <= to`, omitting a predicate when its bound is absent. The supplied columns are naive `TIMESTAMP` values; they are interpreted as UTC at the adapter boundary. Malformed rows raise `RegistryRowValidationError` and become a typed unavailable outcome.

**PACS (PyMongo Async).** Patient and inclusive `timestamp` predicates run in MongoDB. The projection is `_id`, `patientId`, `modality`, `timestamp`, and `radiologistNote`. Motor was not used because PyMongo Async is the supported asynchronous API.

**Vitals (HTTPX).** `GET /vitals/{patientId}` has no date query parameters, so readings are validated and then filtered in the adapter with the same inclusive comparisons. Naive timestamps are treated as UTC.

## TimelineService

`TimelineService` owns the application narrative: build an access plan, fetch only selected sources concurrently with `asyncio.gather`, filter normalized events by the effective type allowlist, group, then optionally paginate parents.

`services/policy.py` is a pure policy boundary. Doctors see all four types; nurses see emergency-room, imaging, and vitals; interns see surgery, emergency-room, and vitals. Requested `types` intersect that allowlist and cannot expand access. Registry is selected for surgery or emergency-room, PACS for imaging, and Vitals for vitals. Execution and warning order is Registry, PACS, then Vitals. If intersection leaves no types, no adapter is called and the API returns an empty HTTP 200.

Adapters remain role-independent. A second allowlist filter before grouping protects against a broad source returning mixed types. Authorized parents with no children are kept. An authorized child whose parent was removed may become standalone.

Optional `limit` and `offset` slice the already grouped, newest-first parent tuple. Standalone events are not sliced. The response contract is unchanged.

## Grouping

`group_events` receives already-authorized parent and child sequences and returns immutable groups plus standalone children without mutating inputs. It sorts copied parent entries by start and children chronologically, then sweeps children.

Parents whose start is at or before the child enter a heap ordered by latest start and then normalized ID ascending. Candidates whose end is before the child are removed; the remaining heap winner receives the child. Exact start and end matches are inclusive.

After ordering, heap assignment is `O((P + C) log P)`. For unsorted inputs the end-to-end cost is `O(P log P + C log C + (P + C) log P)` and space is `O(P + C)`. A nested `O(P * C)` scan exists only as a conceptual alternative; it is not used in application code.

The assignment does not define identical parent starts. Stable parent-ID ascending is the deterministic tie-breaker. Parents are newest first by `(start descending, ID ascending)`. Children within a parent, and standalone children, are chronological by `(timestamp ascending, ID ascending)`.

The response-example comment says `standalone` is always empty, but the grouping algorithm marks unmatched children as standalone. The implementation follows the algorithm.

## Failure classification and HTTP status

Named database, MongoDB, HTTP, timeout, and source-schema failures become typed unavailable outcomes. Unexpected exception types are not downgraded.

Any unavailable selected source produces HTTP 206, `partial=true`, successful-source data, and a warning containing deterministic source names only. If every selected source is unavailable, the response remains an empty HTTP 206. Unexpected defects return `{"detail":"Internal server error"}` with HTTP 500.

Complete results and the no-selected-source case return 200. Invalid query or header input returns 400. Unknown query parameters are rejected (`extra="forbid"`). `limit` must be 1–100 and `offset` must be ≥ 0.

## Logging and privacy

Logs are JSON records with a static `OperationalEvent` name and an allowlist of operational context: source, outcome, selected sources, partial status, and duration. The formatter does not serialize arbitrary message content. Clinical payloads, vitals values, radiology notes, patient identifiers, raw upstream error text, and secrets are not logged. HTTP access INFO logs are suppressed because URLs can contain patient identifiers.

## Testing

```bash
cd backend
pytest
TIMELINE_RUN_LIVE_TESTS=1 pytest
ruff check .
ruff format --check .
mypy
```

Unit tests cover policy, grouping, adapters, service federation, pagination, and HTTP translation without live infrastructure. Live tests, gated by `TIMELINE_RUN_LIVE_TESTS=1`, exercise seeded Registry, PACS, Vitals, and the full endpoint. The seed defines patient `1` with three surgeries, two emergency-room encounters, 17 imaging studies, and 22 vitals readings.

The supplied frontend Vite `/api` proxy targets port 3000. The backend returns unmatched children in `standalone`, but the supplied frontend does not render that array, so a vitals-only response can appear empty in the UI even when the API returned valid events. The supplied frontend production build also retains pre-existing TypeScript errors in `Timeline.tsx`. Neither is fixed here because frontend UI/business logic is out of scope; see the root README UX proposals for theoretical follow-ups.

## Assumptions

- Naive ISO-8601 request bounds and naive source timestamps are UTC.
- Unmatched children are standalone events, following the grouping algorithm rather than the “always empty” response-example comment.
- Vitals readings are unique per patient and timestamp in the supplied mock.
- Header `X-User-Role` is a trusted assignment stand-in, not authentication.

## Production follow-ups

Not missing assignment functionality:

- trusted identity and patient authorization
- request-wide remaining-budget deadlines
- a durable upstream Vitals identifier
- measured pool, timeout, and index tuning
- retries or circuit breakers only if production dependency behavior warrants them
