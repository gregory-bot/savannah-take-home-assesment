# Savannah Clinic API

A REST API for a clinic appointment booking system, with **Python 3.12 + FastAPI + PostgreSQL**.

> Submitted for the Savannah Informatics Backend Developer Take-Home Assessment.

---

## Table of Contents

1. [Section 1 — System Design](#section-1--system-design)
2. [Section 2 — API Reference](#section-2--api-reference)
3. [Frontend](#frontend)
4. [Running Locally](#running-locally)
5. [Section 3 — Deployment & CI/CD](#section-3--deployment--cicd)
6. [Section 4 — AI Reflection](#section-4--ai-reflection)

---

## Section 1 — System Design

### Models

**Doctor**
- `id`, `full_name`, `specialization`
- `work_start` (TIME), `work_end` (TIME) — stored as clock times in UTC
- Working hours are set per-doctor. The system treats these as UTC times; if the
  clinic later needs per-doctor timezones, a `timezone` column can be added.

**Patient**
- `id`, `full_name`, `email` (unique), `phone`
- No authentication is implemented (see decision below). The `email` uniqueness
  constraint prevents accidental duplicate registrations.

**Appointment**
- `id`, `doctor_id` (FK), `patient_id` (FK)
- `slot_time` (TIMESTAMPTZ) — stored in UTC
- `status` — `booked` or `cancelled`
- `cancellation_reason` — populated when cancelled
- `created_at`, `updated_at` — audit trail
- **UNIQUE constraint on `(doctor_id, slot_time)`** — the database-level guard
  against double-booking (see Concurrency section below)

### Slot Model Decision: On-the-Fly Grid vs. Pre-Generated Slots

I chose to compute slots **on the fly** from a doctor's `work_start`/`work_end`
rather than materialising every slot as a row.

- **Pro:** No slot management overhead. Adding a doctor, changing their hours, or
  supporting different slot lengths in future requires no data migration.
- **Con:** The availability query must reconstruct the full grid on each request
  and subtract booked appointments. For five doctors and modest traffic this is
  entirely acceptable; at scale a Redis cache on the booked-set would be trivial
  to add.

### Concurrency — Race Condition Prevention

The classic TOCTOU race:

```
request A: SELECT → slot free → ...
request B: SELECT → slot free → ...
request A: INSERT appointment ✓
request B: INSERT appointment ✓  ← double-booking
```

This is addressed with **two independent layers**:

1. **`SELECT FOR UPDATE` on the Doctor row (PostgreSQL only).** Before checking
   availability and inserting, we lock the doctor's row. Two concurrent requests
   for the same doctor are serialised at the database level, so only one will
   observe the slot as free.

2. **`UNIQUE (doctor_id, slot_time)` database constraint.** This is the
   unconditional backstop. Even if somehow two transactions bypass the row lock,
   the database will reject the second `INSERT` with an `IntegrityError` which
   the service catches and converts to a `409 Conflict`.

Rescheduling is also atomic: both the release of the old slot and the acquisition
of the new one happen inside a single transaction, so a patient cannot lose their
original slot if the new one turns out to be taken.

### Timezone Handling

All `slot_time` values are stored as `TIMESTAMPTZ` (UTC). The API accepts
ISO-8601 datetimes with timezone offsets and converts to UTC before persisting.
Doctor working hours are stored as plain `TIME` values also interpreted as UTC.

### Authentication — Intentional Omission

Authentication is not implemented. The scenario describes an internal booking
tool for a small clinic where trust assumptions differ from a public API.
Noted trade-off: without auth, any caller can book on behalf of any patient ID.
In production this would be addressed with JWT Bearer tokens (FastAPI's OAuth2
support makes this straightforward to retrofit).

### What happens if a doctor's working hours change

Existing `Appointment` rows are unaffected — they store the full `slot_time` and
are not derived from the doctor's current hours. The availability endpoint will
immediately reflect the new hours for future dates, which may leave some existing
bookings outside the new window. A migration flow for this (notify affected
patients, cancel or keep their appointments) is a product decision left outside
this implementation.

---

## Section 2 — API Reference

Interactive documentation is available at `/api/docs` (Swagger UI) and
`/api/redoc` (ReDoc) when the server is running.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness probe |
| POST | `/api/doctors` | Register a doctor |
| GET | `/api/doctors` | List all doctors |
| GET | `/api/doctors/{id}` | Get a doctor |
| GET | `/api/doctors/{id}/availability?date=YYYY-MM-DD` | Free 30-min slots |
| POST | `/api/patients` | Register a patient |
| GET | `/api/patients/{id}` | Get a patient |
| GET | `/api/patients/{id}/appointments` | Upcoming appointments (sorted) |
| POST | `/api/appointments` | Book a slot |
| GET | `/api/appointments/{id}` | Get an appointment |
| PATCH | `/api/appointments/{id}/cancel` | Cancel (with reason) |
| PATCH | `/api/appointments/{id}/reschedule` | Move to a new slot |

### Booking Validation Rules

A booking is rejected with `422 Unprocessable Entity` if:
- `slot_time` is in the past
- `slot_time` is within 1 hour of the current time
- `slot_time` does not fall on a 30-minute boundary (XX:00 or XX:30)
- `slot_time` falls outside the doctor's working hours

A booking is rejected with `409 Conflict` if:
- The slot is already taken by another active appointment

---

## Frontend

A frontend application is deployed at
**https://savannah-clinic-test.netlify.app**.

The frontend provides a user-friendly interface for the clinic booking system,
allowing patients to:

- Browse available doctors and their specializations
- View real-time slot availability for a selected date
- Book new appointments
- Cancel or reschedule existing appointments
- View upcoming appointments sorted by date

### Frontend Repository

The frontend source code is maintained in a separate repository:
**[savannah-take-home-assesment](https://github.com/gregory-bot/healthlink-scheduler)**

### Frontend Screenshots

> The screenshots below illustrate the key views of the deployed frontend at
> https://savannah-clinic-test.netlify.app.

#### 1. Home Page — Doctor Directory

![Home Page — Doctor Directory](docs/screenshots/homepage.png)

The landing page lists all registered doctors with their specializations and
working hours.

#### 2. Doctor Booking — Slot Selection

![Doctor Booking — Slot Selection](docs/screenshots/doctor-booking.png)

After selecting a doctor and a date, the patient sees a grid of 30-minute slots.
Available slots are highlighted; booked or past slots are disabled.

#### 3. Appointments — Patient Dashboard

![Appointments — Patient Dashboard](docs/screenshots/appointments.png)

The patient dashboard shows all upcoming appointments sorted by date, with
options to cancel or reschedule each one.

#### 4. API Documentation — Swagger UI

![API Documentation — Swagger UI](docs/screenshots/api-docs.png)

Interactive API documentation is auto-generated by FastAPI at `/api/docs`,
allowing testers to explore and try every endpoint directly from the browser.

---

## Running Locally

### Option A — Docker Compose (recommended)

```bash
# Start the database and API together
docker compose up --build

# The API is now available at http://localhost:8000
# Swagger UI: http://localhost:8000/api/docs
```

### Option B — Local Python environment

**Prerequisites:** Python 3.12+, PostgreSQL 14+

```bash
# 1. Clone and enter the project
cd clinic-backend

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements-dev.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env and set DATABASE_URL to your PostgreSQL connection string

# 5. Create the database schema
# Option A: let SQLAlchemy auto-create on first run (happens automatically)
# Option B: run the provided SQL file manually:
#   psql -U <user> -d <dbname> -f sql/init.sql

# 6. Run the API
uvicorn app.main:app --reload --port 8000
```

### Running Tests

Tests use an in-memory SQLite database by default — no PostgreSQL required.
When the `DATABASE_URL` environment variable is set (e.g. in CI), tests run
against that database instead.

```bash
# Local (SQLite, no setup needed)
pytest tests/ -v --cov=app

# Against a PostgreSQL instance
DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/testdb pytest tests/ -v --cov=app
```

### Database Queries

The `sql/init.sql` file contains the full schema with:
- `CREATE TABLE` statements for `doctors`, `patients`, `appointments`
- All indexes and the `UNIQUE (doctor_id, slot_time)` constraint
- Optional seed data (5 doctors, 3 patients)

To run manually:

```bash
psql -U clinic -d clinic_db -f sql/init.sql
```

---

## Section 3 — Deployment & CI/CD

### Deployed URL

> **https://healthlink-clinic-api.onrender.com**

Swagger UI: `https://healthlink-clinic-api.onrender.com/api/docs`

### Frontend URL

> **https://savannah-clinic-test.netlify.app**

### CI/CD Pipeline — GitHub Actions

File: `.github/workflows/ci.yml`

The pipeline has two jobs:

#### Job 1: `test` (runs on every PR and push to `main`)

1. Spins up a **PostgreSQL 15** service container with a test database.
2. Installs Python 3.12 and all dependencies (with pip caching).
3. Runs the full test suite **against PostgreSQL** with coverage reporting:
   ```
   pytest tests/ -v --cov=app --cov-report=term-missing
   ```
4. The PR check blocks merge if any test fails.

Using a real PostgreSQL service container in CI (rather than SQLite) ensures
that PostgreSQL-specific behaviour — `SELECT FOR UPDATE`, `TIMESTAMPTZ`,
the `UNIQUE` constraint backstop — is exercised in the same dialect that
production uses.

#### Job 2: `deploy` (runs only on push to `main`, after tests pass)

1. Calls the **Render Deploy API** via `curl` to trigger a re-deployment of
   the `main` branch.
2. The deploy only fires when all tests pass and the push is to `main`.

**Required GitHub Secrets:**
- `RENDER_API_KEY` — Render account API key
- `RENDER_SERVICE_ID` — ID of the Render web service

**Deploy branch:** `main`

---

## Section 4 — AI Reflection

### 1. What did I use AI for?

- **Section 1 (Design):** I described the TOCTOU race and asked whether my two-layer approach (SELECT FOR
  UPDATE + UNIQUE constraint) was sufficient. The AI confirmed the pattern and
  pointed out that SQLite does not support `FOR UPDATE`, which led me to the
  dialect-aware `_supports_for_update()` helper.

- **Section 2 (Implementation):** Used AI for boilerplate (Pydantic model
  scaffolding, FastAPI router structure). The core booking logic, slot validation,
  and concurrency handling were written by hand.

- **Section 3 (CI/CD):** generated the initial GitHub Actions workflow
  YAML and the Render deploy API call syntax by hand.

- **Section 4 (Reflection):** Written entirely by hand.

### 2. One example where AI improved my work

**Prompt:** "I have a FastAPI booking service that uses SELECT FOR UPDATE to
prevent race conditions. My tests use SQLite which doesn't support FOR UPDATE.
How should I structure the code so tests still exercise the booking logic
without crashing?"

The AI suggested checking the dialect at runtime (`db.bind.dialect.name`) rather
than a boolean flag or environment variable. This was cleaner than my initial
idea of a `DISABLE_LOCKING` env var because it's self-contained, requires no
test configuration, and will automatically work correctly if the test database is
ever upgraded to PostgreSQL.

### 3. One example where AI output was wrong

When I asked AI to generate the SQLAlchemy model for `Appointment`, it used the
older `Column` / `declarative_base()` style instead of the newer
`DeclarativeBase` + `Mapped[T]` pattern that is idiomatic in SQLAlchemy 2.0.
I caught this by comparing against the SQLAlchemy 2.0 migration guide and
rewrote the models using typed `Mapped` columns, which provide better IDE
autocompletion and type safety.

### 4. Two decisions I made without AI

1. **Fixed slot grid computed on the fly vs. pre-materialised slot table.** I
   chose on-the-fly generation because I have direct experience with the
   operational pain of managing materialised slot rows (re-generating them on
   schedule changes, purging old rows, etc.). AI was not consulted — this was a
   judgment call based on the stated scale ("5 doctors, starting small").

2. **Omitting authentication.** The scenario does not mention a login flow, and
   adding JWT auth would double the surface area of the submission without
   demonstrating what the assessment is testing. I explicitly noted the
   trade-off in the README rather than silently skipping it. This decision was
   mine to make because it required reading the intent of the brief, not just
   its literal words.
