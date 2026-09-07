# SHEBA CORTEX R&D Center

## Tel HaShomer Information Technology & Digital Department

  

# Backend Developer Assignment

## Federated Patient Timeline API

  

**Time Investment:** ~8-10 hours

  
<img width="2570" height="1440" alt="image" src="https://github.com/user-attachments/assets/79eb694c-4876-47ba-96ab-a2d65b513c9d" />

---

  

## Objective

  

Build the backend API for a Federated Patient Timeline System that demonstrates your:

  

- **System Integration**: Ability to aggregate data from multiple disparate sources (SQL, NoSQL, external APIs)

- **Algorithmic Logic**: Implementation of complex hierarchical data grouping and temporal merging

- **Resilience Patterns**: Handling service failures gracefully in a distributed system

- **API Design**: Creating a clean, documented, and type-safe RESTful interface

  

---

  

## What's Provided

  

You will receive:

- ✅ **Frontend application** (React + TypeScript) - already built

- ✅ **Docker Compose setup** with Postgres, MongoDB, Mock Vitals service

- ✅ **Database seed data** (init.sql, MongoDB seed scripts)

- ✅ **API contract specification** (what the frontend expects)

  

**Your task**: Implement the backend API that makes the frontend work.

  

**Important**: You may only change the frontend to point it to your backend base URL (e.g., `http://localhost:3000`). Please don't modify UI or business logic – we're evaluating backend skills only.

  
The link: https://github.com/edengby/Federated-Patient-Timeline-System

---

  

## Getting Started

### Prerequisites

- Docker and Docker Compose installed and running
- Python 3.12 or newer (for running the backend)
- Node.js with npm or yarn (only for running the frontend outside Docker)

### How to Run the System

From the repository root:

```bash
./start.sh
```

This single script will:
- Start all Docker services and wait for them to become healthy
- Seed the MongoDB database
- Create the backend virtual environment on first run
- Install backend dependencies on first run
- Copy `backend/.env.example` to `backend/.env` if needed
- Start the backend on port `3000`

Open the app at `http://localhost:5173`. Press `Ctrl+C` to stop the backend; Docker
services keep running until you run `docker compose down`.

To run the backend manually instead:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=src uvicorn timeline_api.main:app --reload --host 0.0.0.0 --port 3000
```

### Service URLs

Once everything is running, the services will be available at:

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:3000 (when backend is running)
- **API Docs**: http://localhost:3000/docs (when backend is running)
- **Mock Vitals Service**: http://localhost:3001
- **Postgres**: localhost:5432
- **MongoDB**: localhost:27017
- **Redis**: localhost:6379

### Stopping Services

To stop the infrastructure services:

```bash
docker compose down
```

`Ctrl+C` stops the backend. The detached frontend and infrastructure services stop with
`docker compose down`.

### Testing Database Data

A test script is provided to verify that all databases have been seeded correctly with the expected data:

```bash
./test.sh
```

This script will:
- ✅ Verify PostgreSQL has the correct number of patients, surgeries, and emergency room visits
- ✅ Verify MongoDB has the correct number of imaging studies
- ✅ Verify the Mock Vitals Service is running and returning the expected number of vitals

**Expected Results:**
- PostgreSQL - Patients: 1
- PostgreSQL - Surgeries: 3
- PostgreSQL - Emergency Rooms: 2
- MongoDB - Imaging Studies: 17
- Mock Vitals Service - Health check: ✓ PASS
- Mock Vitals Service - Vitals for patient 1: 22

All tests should pass if the infrastructure is set up correctly. If any tests fail, check that:
1. All Docker services are running (`docker compose ps`)
2. The databases have been seeded properly
3. The Mock Vitals Service is accessible at `http://localhost:3001`

---

  

## Core Requirements

  

### 1. API Endpoint Specification

  

You must implement this exact endpoint:

  

```

GET /api/timeline?patientId={number}&from={ISO8601}&to={ISO8601}&types={comma-separated}

```

  

**Headers:**

```

X-User-Role: doctor | nurse | intern

```

  

**Response Format:**

```typescript

{

parents: Array<{

id: string;

type: 'surgery' | 'emergency_room';

timestamp: string; // ISO8601

patientId: number;

start: string; // ISO8601

end: string; // ISO8601

data: {

surgeonName?: string;

procedure?: string;

attendingPhysician?: string;

chiefComplaint?: string;

};

source: 'registry';

children: Array<{

id: string;

type: 'vitals' | 'imaging';

timestamp: string; // ISO8601

patientId: number;

data: {

bpm?: number;

bp?: string;

modality?: string;

radiologistNote?: string;

};

source: 'vitals' | 'pacs';

}>;

}>;

standalone: Array<...>; // Always empty array

partial: boolean;

warning?: string;

}

```

  

**Status Codes:**

- `200`: Full data retrieved

- `206`: Partial content (some services unavailable)

- `400`: Validation error

- `500`: Internal server error

  

### 2. Backend API Implementation (Python or Node.js)

  

#### Required Implementation

  

**1. Adapter Pattern**

Create adapters for each data source:

- `RegistryAdapter`: Fetch from Postgres (surgeries, emergency_rooms)

- `PACSAdapter`: Fetch from MongoDB (imaging studies)

- `VitalsAdapter`: Fetch from Mock Vitals API

  

Each adapter should:

- Normalize data to common `TimelineEvent` interface

- Handle date range filtering (`from`, `to`)

- Handle errors gracefully

  

**Note**: You are free to choose any suitable ORM/DB client (e.g., Prisma, TypeORM, Mongoose, SQLAlchemy, asyncpg, pymongo, etc.), as long as the adapters expose a clean interface and return normalized `TimelineEvent` objects.

  

**2. Data Fetching**
- Find the best way and choose according your choice.

  

**3. Resilience Pattern**

- If any service fails (500 error, timeout, etc.):

- **Do NOT fail the entire request**

- Return data from other sources

- Return HTTP status `206` (Partial Content)

  

**4. Data Normalization**

Convert all sources to this interface:

```typescript

interface TimelineEvent {

id: string;

type: 'surgery' | 'emergency_room' | 'vitals' | 'imaging';

timestamp: Date;

patientId: number;

data: { ... }; // Type-specific fields

source: 'registry' | 'pacs' | 'vitals';

start?: Date; // For parents only

end?: Date; // For parents only

}

```

  

**5. Request Validation**

- Use Zod (or similar) to validate query parameters

- Return `400` with error details if validation fails

- Handle invalid dates, missing required params, etc.

  

### 3. Hierarchical Event Grouping Algorithm (Critical)

  

This is the **core challenge**. Implement a grouping algorithm that:

  

**Step 1: Classify Events**

- **Parents**: Surgeries, Emergency Rooms (have `start` and `end` times)

- **Children**: Vitals, Imaging (have single `timestamp`)

  

**Step 2: Assignment Logic (Merge AsOf)**

For each child event:

1. Find all parents that are "open" at the child's timestamp

- Condition: `parent.start <= child.timestamp <= parent.end`

- Use **inclusive boundaries** (start and end times are included)

2. If multiple parents are open:

- Choose the parent that started **most recently**

- This handles overlapping parents

3. If no parent found:

- Mark as "standalone"

  

**Step 3: Sorting**

- Parents: Sort by start time, **latest to earliest** (newest first)

- Children within each parent: Sort by timestamp, **earliest to latest** (chronological)

   

**Example:**

```typescript

// Input events:

Surgery: 10:00-12:00

ER: 11:00-13:00

Vitals: 11:30

  

// Result: Vitals assigned to ER (most recent parent at 11:30)

```

  

### 4. Role-Based Access Control (RBAC)

  

Implement RBAC filtering via `X-User-Role` header:

  

**Rules:**

- **Doctor** (`role: 'doctor'`): Full timeline access (no filtering)

- **Nurse** (`role: 'nurse'`): Hide **surgery** events completely (remove from parents array, remove from children)

- **Intern** (`role: 'intern'`): Hide **imaging** events completely (remove from children arrays)

  

**Important:**

- Filter both parent events AND child events

- If a parent has no children after filtering, you can keep it or remove it (your choice)

  

### 5. Additional Backend Features (Your Choice)

  

**We particularly value:**

- **Clear API documentation** (Swagger/OpenAPI at `/docs` endpoint)

- **Proper request validation** (comprehensive schemas with detailed error messages)

  

**Other optional features:**

- **Error Handling**: Proper error types, logging, and user-friendly messages

- **Type Safety**: Full TypeScript coverage, no `any` types (or Python type hints)

- **Code Organization**: Clean architecture, separation of concerns

- **Performance**: Optimize database queries, efficient algorithms

- **Logging**: Structured logging for debugging

- **Caching Strategy**: Implement Redis caching (Redis is already in docker-compose)

  

**Note**: Partial or incomplete implementations are okay – just document what's missing and how you would complete it with more time.

  

---

  

## Technical Implementation

  

### Backend Architecture

  

1. **Technology Stack** (Choose One)

  

**Option A: Node.js/TypeScript**
**Option B: Python**
  

**Note**: Choose the stack you're most comfortable with. Both are equally acceptable.

  

**Port Configuration**: Your backend should run on port `3000` (or update the frontend's API base URL to match your port).

  

2. **API Design Requirements**

- RESTful endpoint

- Consistent error response format

- Proper HTTP status codes (200, 206, 400, 500)

- Request validation with clear error messages

- Type-safe request/response handling (TypeScript types or Pydantic models)

  

### Database Schema (Provided)

  

**Postgres (Registry):**

- `patients` table: `id`, `name`, `dob`

- `surgeries` table: `id`, `patient_id`, `surgeon_name`, `procedure`, `start_time`, `end_time`

- `emergency_rooms` table: `id`, `patient_id`, `attending_physician`, `chief_complaint`, `start_time`, `end_time`

  

**MongoDB (PACS):**

- `imaging` collection: `patientId`, `modality`, `timestamp`, `radiologistNote`

  

**Mock Vitals Service:**

- Endpoint: `GET http://localhost:3001/vitals/:patientId`

- Returns: `Array<{ bpm: number, bp: string, timestamp: string }>`

  

---

  

## Deliverables

  

### 1. Source Code

- Well-organized backend codebase

- Clear README with:

- **Setup Instructions**: How to run the backend locally

- **Architecture Decisions**: Why you chose certain approaches

- **Features Implemented**: What you built

- **Edge Cases Handled**: How you solved them

- **Known Limitations**: What you didn't have time for

  

### 2. Documentation

- **API Documentation**: Endpoint description, request/response examples

- **Algorithm Explanation**: How the grouping logic works (with examples)

- **Error Handling**: How you handle service failures

- **Code Comments**: Key functions should be well-documented

  

---

  

## Evaluation Criteria

  

### 1. Code Quality (25%)

- Clean, maintainable, readable code

- Proper error handling and logging

- Type safety (TypeScript types or Python type hints)

- Code organization and structure

- Security considerations (input validation, SQL injection prevention)

  

### 2. Architecture (25%)

- Adapter pattern implementation

- Separation of concerns (adapters, services, routes)

- API structure and design

- Error handling strategy

- Code reusability

  

### 3. Algorithm Implementation (30%) ⭐ **Most Important**

- **Correctness** of grouping logic

- **Edge case handling** (boundaries, overlapping parents)

- Performance considerations

- Code clarity and documentation

  

### 4. Technical Decisions (5%)

- Technology choices and justification

- Problem-solving approach

- Trade-offs made

- Best practices followed

  

---

  

## Tips for Success

  

1. **Start with Core Functionality**

- Get basic data fetching from all 3 sources working

- Test with the provided frontend

- Then implement grouping algorithm

- Finally add RBAC and polish

  

2. **Scope Management**

- **You can cut scope if needed** - as long as you explain trade-offs in your README

- Focus on core requirements first (grouping algorithm, data aggregation, resilience)

- Document what you didn't implement and why

- This prevents perfectionism and overwork - we value clear thinking over complete implementation

  

3. **Test with Provided Frontend**

- The frontend is already built - use it to verify your API works

- Test all filter combinations

- Test different roles (doctor, nurse, intern)

- Verify edge cases visually

  

4. **Focus on Algorithm Correctness**

- The grouping algorithm is the **core challenge**

- Test boundary conditions thoroughly

- Verify overlapping parents work correctly

- Document your logic clearly

- Language choice (Python vs Node.js) doesn't matter - focus on correctness

  

5. **Handle Errors Gracefully**

- Don't let one service failure break everything

- Return partial data with proper status codes

- Log errors for debugging

  

6. **Document Key Decisions**

- Why you chose certain approaches

- How the grouping algorithm works

- What edge cases you handle

- What you would improve with more time

  

7. **Code Quality Matters**

- Clean, readable code is easier to evaluate

- Use type safety properly (TypeScript types or Python type hints)

- Organize code logically

- Add comments for complex logic

- Follow language-specific best practices

  

---

  

## Bonus Points

  

- **Caching**: Implement Redis caching with proper TTL

- **API Documentation**: Swagger/OpenAPI at `/docs`

- **Performance**: Optimize database queries, efficient algorithms

- **Logging**: Structured logging for debugging and monitoring

  

---

  

## Extra Challenges (Optional)

  

These are **optional stretch goals** for candidates who want to go above and beyond. They keep the core requirements the same but let strong candidates shine.

  

### A. Pagination or Windowing

  

Add optional query parameters to support pagination:

  

```

GET /api/timeline?patientId=1&limit=10&offset=0

```

  

**Parameters:**

- `limit` (number, optional): Maximum number of parent events to return

- `offset` (number, optional): Number of parent events to skip (for pagination)

  

**Behavior:**

- Apply pagination **after** grouping and sorting

- Return parents in chunks

- Consider adding metadata: `{ total: number, limit: number, offset: number }`

  

### B. Rate Limiting

  

Implement a simple rate limit to prevent abuse:

  

**Requirements:**

- Per-IP or per-API-key rate limiting

- Max 60 requests per minute (configurable)

- Return `429 Too Many Requests` when limit exceeded

- Include `Retry-After` header with seconds until reset

  

**Implementation Options:**

- Simple in-memory map (for single-instance deployments)

- Redis-based (bonus - tests Redis integration)

  

**Response when rate limited:**

```json

{

"error": "Rate limit exceeded",

"message": "Too many requests. Please try again later.",

"retryAfter": 30

}

```

  

**Status Code:** `429 Too Many Requests`

  

**Headers:**

```

Retry-After: 30

```

  

This tests:

- Understanding of throttling/rate limiting concepts

- Using Redis effectively (if chosen)

- Proper HTTP status codes and headers

  

---

  

## What We're Looking For

  

We want to see:

- ✅ **Problem-solving skills**: How you approach the grouping algorithm

- ✅ **Clean code**: Readable, maintainable, well-organized

- ✅ **Error handling**: Graceful degradation, proper status codes

- ✅ **Type safety**: Proper TypeScript usage

- ✅ **Architecture**: Good separation of concerns, adapter pattern

- ✅ **Edge cases**: Thoughtful handling of boundary conditions

  

**Not required:**

- ❌ Frontend development

- ❌ DevOps/deployment

- ❌ Perfect implementation (we understand time constraints)

  

---

  

## Deadline

  

**14 days** from assignment receipt

  

---

  

## Submission

  

Please provide:

1. **GitHub/GitLab Repository URL** (public or access granted)

2. **Clear README** with setup instructions

3. **Brief Summary** (1-2 paragraphs) of:

- How you implemented the grouping algorithm

- Key technical decisions

- What you're most proud of

- What you would improve with more time

  

---

  

## Questions?

  

If you have any questions about the requirements, please reach out. We're looking for:

- **Problem-solving skills** over perfect implementation

- **Clear thinking** over complex code

- **Working solution** that integrates with the provided frontend

  

**Remember**: This assignment focuses on **backend skills** - API design, data aggregation, algorithms, and error handling. The frontend is provided to help you test your implementation.

  

Good luck! 🚀

  

---

  

*SHEBA CORTEX R&D Center - Building the future of healthcare technology*
