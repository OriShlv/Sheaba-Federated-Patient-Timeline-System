# Federated Patient Timeline API

Python FastAPI backend for the Sheba Cortex take-home assignment. It federates a patient timeline from Postgres Registry, MongoDB PACS, and an HTTP Vitals service, then groups point events under overlapping parent intervals.

The original task specification is preserved in [ASSIGNMENT.md](ASSIGNMENT.md).

## Overview

The API is a small FastAPI application with one timeline route and one `TimelineService` orchestrator. Source-specific adapters normalize Registry surgeries and emergency-room intervals, PACS imaging studies, and Vitals readings into typed events. The service applies role and requested-type policy before I/O, fetches only the required sources concurrently, filters authorized events, and passes them to a pure grouping function. Expected source failures are isolated: healthy sources still return data, and the HTTP status becomes 206.

Grouping uses a sorted sweep over children with a heap of active parents. Inclusive interval membership and latest-start overlap resolution are the core of the algorithm. The strongest part of the solution is that grouping is independently tested and kept free of HTTP, policy, and database concerns. With more time, the main follow-ups would be trusted authentication, a request-wide deadline, and a durable upstream Vitals identifier—not changes to the assignment grouping contract.

## Quick Start

**Prerequisites:** Docker and Docker Compose, Python 3.12 or newer.

From the repository root:

```bash
./start.sh
```

`./start.sh` does not delete database data. A new MongoDB volume is seeded once by Docker init. To wipe PACS imaging and restore the assignment seed later:

```bash
./reset.sh
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| Backend | http://localhost:3000 |
| API docs | http://localhost:3000/docs |

`Ctrl+C` stops the backend. Stop infrastructure with:

```bash
docker compose down
```

## Architecture

```mermaid
flowchart LR
  Frontend --> Route[FastAPI route]
  Route --> Service[TimelineService]
  Service --> Policy[Access policy]
  Policy --> Adapters[Registry / PACS / Vitals adapters]
  Adapters --> Events[Normalized events]
  Events --> Filter[Authorization and type filtering]
  Filter --> Grouping
  Grouping --> Response
```

Adapters own external schemas. Application code operates on normalized events. Grouping has no FastAPI, role, configuration, or I/O dependencies.

## API

`GET /api/timeline`

| Parameter | Required | Description |
| --- | --- | --- |
| `patientId` | yes | Positive patient identifier |
| `X-User-Role` | yes | `doctor`, `nurse`, or `intern` |
| `from` | no | Inclusive ISO-8601 lower bound |
| `to` | no | Inclusive ISO-8601 upper bound |
| `types` | no | Comma-separated event types |
| `limit` | no | Max parent events after grouping, 1–100 |
| `offset` | no | Parent events to skip after grouping, ≥ 0 |

Unknown query parameters are rejected. Pagination applies only to sorted parents; standalone events are unchanged. Omitting `limit` and `offset` returns the full grouped result. The response shape is unchanged: no pagination metadata is added.

| Role | Visible types |
| --- | --- |
| doctor | surgery, emergency_room, imaging, vitals |
| nurse | emergency_room, imaging, vitals |
| intern | surgery, emergency_room, vitals |

| Status | Meaning |
| --- | --- |
| 200 | All selected sources succeeded |
| 206 | One or more selected sources were unavailable |
| 400 | Validation error |
| 500 | Unexpected internal failure |

```bash
curl -sS -H "X-User-Role: doctor" \
  "http://localhost:3000/api/timeline?patientId=1"
```

```json
{
  "parents": [
    {
      "id": "registry:surgery:1",
      "type": "surgery",
      "children": [{ "id": "vitals:vitals:1:2024-01-15T10:30:00Z", "type": "vitals" }]
    }
  ],
  "standalone": [],
  "partial": false
}
```

Interactive documentation is at `/docs`.

## Grouping Algorithm

Parent events are surgeries and emergency-room intervals. Child events are vitals and imaging points. A parent is eligible when:

`parent.start <= child.timestamp <= parent.end`

Boundaries are inclusive. If multiple parents overlap, the parent with the latest start wins. If none match, the child becomes standalone. Parents are returned newest-first; children within a parent are chronological.

The implementation sorts parents by start and children by timestamp, then sweeps children while maintaining a heap of active parents ordered by latest start. Exact start and end matches stay inclusive because a parent is activated when `start <= timestamp` and dropped only when `end < timestamp`. When two eligible parents share the same start, the lower normalized parent ID wins. That tie-breaker is assignment-undefined and is documented here only because the implementation needs a deterministic result.

After ordering inputs, heap assignment is `O((P + C) log P)`. For unsorted inputs the end-to-end cost is `O(P log P + C log C + (P + C) log P)` with `O(P + C)` space.

## RBAC

| Role | surgery | emergency_room | imaging | vitals |
| --- | --- | --- | --- | --- |
| Doctor | yes | yes | yes | yes |
| Nurse | no | yes | yes | yes |
| Intern | yes | yes | no | yes |

Requested `types` are intersected with the role allowlist and can never expand permissions. Filtering happens before grouping, and only required sources are called. If an unauthorized parent is removed, an authorized child may become standalone or attach to another authorized parent.

## Resilience

Selected sources are fetched concurrently. Expected database, MongoDB, HTTP, timeout, and source-schema failures are isolated. Healthy sources still contribute events. A degraded result returns HTTP 206 with `partial=true` and a warning that names unavailable sources only. Unexpected defects return a safe HTTP 500 without raw exception text.

## Validation

- `patientId` must be a positive integer
- `X-User-Role` must be `doctor`, `nurse`, or `intern`
- `from` and `to` must be ISO-8601 strings; numeric epochs are rejected
- timezone-aware bounds are converted to UTC; naive ISO timestamps are treated as UTC
- `from` must be earlier than or equal to `to`
- `types` must be a comma-separated list of `surgery`, `emergency_room`, `vitals`, or `imaging`
- `limit` must be between 1 and 100; `offset` must be ≥ 0
- unknown query parameters return HTTP 400

## Testing

```bash
cd backend
pytest
TIMELINE_RUN_LIVE_TESTS=1 pytest
ruff check .
ruff format --check .
mypy
```

Live infrastructure is required only for the live pytest run. The seeded patient is `1`. With live infrastructure enabled, 154 tests currently pass.

## Key Technical Decisions

- **FastAPI** provides typed request/response models and OpenAPI at `/docs` without extra framework code.
- **asyncpg** is used directly for two parameterized Registry queries instead of an ORM. The supplied schema does not benefit from mapping overhead.
- **PyMongo Async** reads PACS imaging documents through a lifespan-managed client.
- **HTTPX** reuses one async client for the Vitals mock, which has no date query parameters, so inclusive bounds are applied in the adapter.
- **Adapter boundaries** keep SQL rows, Mongo documents, and HTTP payloads out of application code.
- **One `TimelineService`** owns policy, source selection, concurrent federation, and response construction.
- **Concurrent source fetches** use `asyncio.gather` so independent sources overlap in time.
- **Pure grouping** keeps the scoring-critical algorithm testable without FastAPI, configuration, or I/O.

## Assumptions and Requirement Ambiguities

1. **Standalone contradiction.** The response example comments that `standalone` is always empty, but the grouping algorithm says unmatched children become standalone. The implementation follows the algorithm because grouping correctness is the core challenge.
2. **Naive ISO timestamps** in requests and supplied sources are treated as UTC.
3. **Vitals IDs.** The mock Vitals payload has no identifier, so IDs are `vitals:vitals:<patient-id>:<normalized-UTC-timestamp>`, assuming at most one reading per patient and timestamp.
4. **Frontend standalone display.** The supplied frontend does not render `standalone` events. Frontend UI and business logic were left unchanged because the assignment allows only a backend URL/proxy adjustment.

## Known Limitations / Production Follow-ups

These are production follow-ups, not missing assignment functionality:

- real authentication and patient-level authorization
- a request-wide remaining-budget deadline
- a durable upstream Vitals identifier
- workload-driven database and index tuning
- retries or circuit breakers only if production dependency behavior warrants them

## UX Improvements I Would Propose

The supplied frontend was intentionally left unchanged beyond backend connectivity. The assignment prohibits modifying frontend UI or business logic, so the items below are theoretical product/UX proposals for discussion, not implemented features.

### 1. Render standalone events

The backend returns child events with no eligible parent in `standalone`. The supplied frontend currently does not render that array, so a vitals-only response can contain valid data while the UI appears empty. I would surface standalone events directly in the timeline or in a dedicated section.

### 2. Add event-type filters

The backend already supports the `types` query parameter: `surgery`, `emergency_room`, `vitals`, and `imaging`. The frontend does not expose this capability. Simple event-type filter controls would let clinicians hide noise without a new API.

### 3. Make partial-data states explicit

The backend can return HTTP 206 with `partial=true` when some sources are unavailable and others still return data. Users should be able to distinguish “there is no data” from “some data could not be retrieved.” A contextual warning near the timeline, naming unavailable sources, would make that distinction obvious.

### 4. Improve timeline hierarchy and scanability

Parent encounters and child events could use a clearer visual hierarchy, with source indicators, child counts, and optionally collapsible encounters. That is an incremental scanability improvement, not a redesign.

### 5. Improve loading and refresh feedback

The timeline is federated from multiple independent sources whose response times may differ. A clearer loading/refresh state, and optionally source freshness where appropriate, would make that wait more understandable.

## AI Usage

AI tools were used for implementation assistance, design exploration, test generation and review, and code review. Architecture decisions, scope, validation, review, and final acceptance were evaluated manually.

## Assignment

The original provided task specification is in [ASSIGNMENT.md](ASSIGNMENT.md).
