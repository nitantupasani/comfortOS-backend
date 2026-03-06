# ComfortOS Backend — Step-by-Step Instructions

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone & Navigate](#2-clone--navigate)
3. [Environment Configuration](#3-environment-configuration)
4. [Running with Docker Compose (Recommended)](#4-running-with-docker-compose-recommended)
5. [Running without Docker (Local Python)](#5-running-without-docker-local-python)
6. [Database Migrations](#6-database-migrations)
7. [Seeding Demo Data](#7-seeding-demo-data)
8. [Verifying the API](#8-verifying-the-api)
9. [Visualizing the Database](#9-visualizing-the-database)
10. [Secrets & Production Checklist](#10-secrets--production-checklist)
11. [Frontend Connection](#11-frontend-connection)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Docker Desktop** | ≥ 4.x | Run PostgreSQL, API, and pgAdmin as containers |
| **Docker Compose** | ≥ 2.x (bundled with Docker Desktop) | Orchestrate multi-container setup |
| **Python** | ≥ 3.12 | Only needed if running the API outside Docker |
| **Git** | any | Clone the repository |

> If you only plan to run everything via Docker, Python is not required on the host.

---

## 2. Clone & Navigate

```powershell
git clone <repository-url>
cd smart-building-platform/backend
```

---

## 3. Environment Configuration

### 3.1 Create the `.env` file

The `.env` file holds all secrets and runtime configuration. A template is
provided; copy it and edit it before the first run:

```powershell
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### 3.2 Edit `.env`

Open `.env` in any editor and set values for **every variable**. Below is the
full list with explanations:

```dotenv
# ── PostgreSQL ────────────────────────────────────────────────────────
POSTGRES_DB=comfortos                    # Database name
POSTGRES_USER=comfortos                  # Database user
POSTGRES_PASSWORD=<STRONG_PASSWORD>      # ⚠️ CHANGE — database password
POSTGRES_PORT=55432                      # Host port mapped to Postgres (default 55432)

# ── SQLAlchemy connection string ──────────────────────────────────────
# Must match the credentials above.
# When running via Docker Compose the hostname is "db" (the service name).
# When running locally (Python on host), use 127.0.0.1.
DATABASE_URL=postgresql+asyncpg://comfortos:<STRONG_PASSWORD>@127.0.0.1:55432/comfortos

# ── API ───────────────────────────────────────────────────────────────
API_PORT=8000                            # Host port for the FastAPI server

# ── JWT / Identity Provider ───────────────────────────────────────────
SECRET_KEY=<STRONG_RANDOM_KEY>           # ⚠️ CHANGE — JWT signing key (≥ 32 chars)
ACCESS_TOKEN_EXPIRE_MINUTES=60           # Access token lifetime
REFRESH_TOKEN_EXPIRE_DAYS=7              # Refresh token lifetime

# ── pgAdmin ──────────────────────────────────────────────────────────
PGADMIN_PORT=5050                        # Host port for pgAdmin web UI
PGADMIN_DEFAULT_EMAIL=admin@comfortos.local   # ⚠️ CHANGE in production
PGADMIN_DEFAULT_PASSWORD=<STRONG_PASSWORD>    # ⚠️ CHANGE — pgAdmin login password

# ── CORS ─────────────────────────────────────────────────────────────
# Comma-separated list of origins allowed to call the API.
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000
```

> **Tip:** Generate a strong secret key with:
>
> ```powershell
> python -c "import secrets; print(secrets.token_urlsafe(48))"
> ```

---

## 4. Running with Docker Compose (Recommended)

This starts **PostgreSQL 16**, the **FastAPI** server, and **pgAdmin 4** — all
bound to `127.0.0.1` for security.

```powershell
# Start all three services in detached mode
docker-compose up -d

# Verify everything is running
docker-compose ps
```

| Service | URL | Description |
|---------|-----|-------------|
| **API** | http://127.0.0.1:8000 | FastAPI backend |
| **API Docs** | http://127.0.0.1:8000/docs | Interactive Swagger UI |
| **pgAdmin** | http://127.0.0.1:5050 | Database admin panel |
| **PostgreSQL** | `127.0.0.1:55432` | Raw TCP (use with psql or DBeaver) |

### Stopping

```powershell
docker-compose down          # Stop containers, keep data volumes
docker-compose down -v       # Stop containers AND delete data volumes (full reset)
```

---

## 5. Running without Docker (Local Python)

Use this approach if you prefer running the API directly on your machine (you
still need PostgreSQL — either via Docker or installed natively).

### 5.1 Start PostgreSQL only

```powershell
docker-compose up -d db pgadmin
```

### 5.2 Create a virtual environment

```powershell
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

### 5.3 Install dependencies

```powershell
pip install -r requirements.txt
```

### 5.4 Run database migrations

```powershell
alembic upgrade head
```

### 5.5 Seed demo data

```powershell
python -m app.seed
```

### 5.6 Start the server

```powershell
uvicorn app.main:app --reload --port 8000
```

The API is now available at http://127.0.0.1:8000/docs.

---

## 6. Database Migrations

Alembic manages schema versions. The configuration is in `alembic.ini` and
`alembic/env.py`.

```powershell
# Apply all pending migrations
alembic upgrade head

# Create a new migration after changing models
alembic revision --autogenerate -m "describe your change"

# Roll back the last migration
alembic downgrade -1
```

> **Note:** If you are running only via Docker Compose, the API container
> creates tables automatically on startup (`Base.metadata.create_all`). Alembic
> is still recommended for production migrations.

---

## 7. Seeding Demo Data

The seeder (`app/seed.py`) populates the database with sample tenants, users,
buildings, configs, and beacons matching the Flutter app's dummy backend.

```powershell
# From the backend/ directory (with venv activated)
python -m app.seed
```

Default demo credentials created by the seeder:

| Email | Password | Role |
|-------|----------|------|
| `alice@example.com` | `password123` | admin |
| `bob@example.com` | `password123` | occupant |

> Check `app/seed.py` for the exact demo data.

---

## 8. Verifying the API

### 8.1 Health check

```powershell
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok","service":"comfortos-platform-api"}
```

### 8.2 Login

```powershell
curl -X POST http://127.0.0.1:8000/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"email\":\"alice@example.com\",\"password\":\"password123\"}"
```

The response contains a JWT token. Use it in subsequent requests:

```powershell
curl http://127.0.0.1:8000/auth/validate ^
  -H "Authorization: Bearer <TOKEN>"
```

### 8.3 Interactive docs

Open http://127.0.0.1:8000/docs in a browser. Click **Authorize** and paste
the JWT token to test all endpoints interactively.

---

## 9. Visualizing the Database

### Option A — pgAdmin (included in Docker Compose)

1. Open http://127.0.0.1:5050 in your browser.
2. Log in with the credentials from your `.env`:
   - **Email:** value of `PGADMIN_DEFAULT_EMAIL`
   - **Password:** value of `PGADMIN_DEFAULT_PASSWORD`
3. **Add a new server** (right-click *Servers → Register → Server*):
   - **General → Name:** `ComfortOS Local`
   - **Connection → Host:** `db` (if pgAdmin is in Docker) or `127.0.0.1` (from host)
   - **Connection → Port:** `5432` (inside Docker) or value of `POSTGRES_PORT` (from host)
   - **Connection → Maintenance database:** value of `POSTGRES_DB` (e.g. `comfortos`)
   - **Connection → Username:** value of `POSTGRES_USER` (e.g. `comfortos`)
   - **Connection → Password:** value of `POSTGRES_PASSWORD`
4. Expand the server tree: **ComfortOS Local → Databases → comfortos → Schemas → public → Tables**.
5. Right-click any table → **View/Edit Data → All Rows** to browse data.
6. Use **Tools → Query Tool** to run arbitrary SQL.

#### Viewing the ERD in pgAdmin

pgAdmin 4.8+ supports generating an Entity-Relationship Diagram:

1. Navigate to the `comfortos` database in the tree.
2. Right-click → **Generate ERD**.
3. The diagram shows all tables, columns, foreign keys, and relationships.

### Option B — DBeaver (free desktop client)

1. Download and install [DBeaver Community](https://dbeaver.io/download/).
2. Create a new PostgreSQL connection:
   - **Host:** `127.0.0.1`
   - **Port:** value of `POSTGRES_PORT` (default `55432`)
   - **Database:** `comfortos`
   - **Username / Password:** from `.env`
3. Expand the schema tree to see tables.
4. Right-click any table → **View Diagram** for a visual ERD.
5. For a full database ERD: right-click the `public` schema → **View Diagram**.

### Option C — psql (CLI)

```powershell
# Connect to the database
docker exec -it backend-db-1 psql -U comfortos -d comfortos

# List all tables
\dt

# Describe a table
\d users

# Run a query
SELECT id, email, role FROM users;
```

### Option D — PostgreSQL schema introspection

```sql
-- List all tables with row counts
SELECT schemaname, relname, n_live_tup
FROM pg_stat_user_tables
ORDER BY relname;

-- List all foreign keys
SELECT
  tc.table_name, kcu.column_name,
  ccu.table_name AS foreign_table_name,
  ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY';
```

### Database Tables Overview

| Table | Description |
|-------|-------------|
| `tenants` | Multi-tenancy root; each organization is a tenant |
| `users` | User accounts with roles (admin, manager, occupant) |
| `buildings` | Physical buildings belonging to a tenant |
| `building_configs` | SDUI layout configs (dashboard, vote form, location form) |
| `votes` | Comfort votes submitted by occupants |
| `presence_events` | BLE/geofence check-in events |
| `beacons` | Registered BLE beacons per building |
| `push_tokens` | FCM/APNs device tokens for push notifications |
| `audit_logs` | Immutable audit trail of system events |
| `connector_definitions` | Registered external data connectors |
| `dataset_definitions` | Dataset schemas linked to connectors |

---

## 10. Secrets & Production Checklist

### Secrets that MUST be changed before production

| Variable | Location | Why it matters | Recommendation |
|----------|----------|----------------|----------------|
| `POSTGRES_PASSWORD` | `.env` | Database access credential | Use ≥ 24 chars, alphanumeric + symbols. Store in a secrets manager (e.g. AWS Secrets Manager, HashiCorp Vault). |
| `SECRET_KEY` | `.env` | Signs all JWT tokens. If leaked, attackers can forge tokens for any user. | Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Rotate periodically. |
| `PGADMIN_DEFAULT_PASSWORD` | `.env` | pgAdmin web UI login | Use a strong password. In production, consider disabling pgAdmin entirely. |
| `PGADMIN_DEFAULT_EMAIL` | `.env` | pgAdmin admin email | Change from the default `admin@comfortos.local`. |
| `DATABASE_URL` | `.env` | Full connection string (contains password) | Must match `POSTGRES_PASSWORD`. Never commit to version control. |

### Additional production hardening

| Item | Current State | Production Recommendation |
|------|---------------|--------------------------|
| **CORS_ORIGINS** | Allows `localhost` origins | Restrict to your actual frontend domain(s) only. Never use `*`. |
| **Rate limiter** | In-memory (`dict`) | Replace with Redis-backed sliding window for multi-instance deployments. |
| **Token blacklist** | In-memory (`set`) | Replace with Redis or database-backed blacklist so it survives restarts and works across instances. |
| **HTTPS** | Not configured | Terminate TLS at a reverse proxy (nginx, Caddy, or cloud load balancer). |
| **Connector secrets** | Placeholder (`secret_ref`) | Wire to HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault for mTLS keys, OAuth secrets, and HMAC keys. |
| **Database SSL** | Disabled | Enable `sslmode=require` in `DATABASE_URL` for production. |
| **Alembic URL** | Hardcoded in `alembic.ini` | Override via environment variable or use `env.py` to read from `DATABASE_URL`. |
| **Docker binding** | `127.0.0.1` only | Keep localhost binding or use a private network. Never expose DB ports to `0.0.0.0`. |
| **Log level** | `WARN` for SQLAlchemy | Appropriate for production. Consider structured JSON logging. |
| **Bcrypt rounds** | Default (~12) | Acceptable. Increase if hardware allows. |
| **ACCESS_TOKEN_EXPIRE_MINUTES** | 60 | Reduce to 15–30 minutes in production for tighter security. |
| **REFRESH_TOKEN_EXPIRE_DAYS** | 7 | Acceptable; ensure refresh tokens are stored securely on the client. |

### `.env` file security

- **Never commit `.env` to version control.** Ensure it is listed in `.gitignore`.
- In CI/CD, inject secrets via environment variables or a secrets manager — not files.
- Use file permissions (`chmod 600 .env`) to restrict access on Linux/macOS.

---

## 11. Frontend Connection

The Flutter app (ComfortOS) connects to this backend via REST over HTTP(S).

1. In the Flutter project, locate `lib/data/app_environment.dart`.
2. Switch to `AppEnvironment.local` which points at `http://localhost:8000`.
3. Ensure `CORS_ORIGINS` in `.env` includes your Flutter web dev server origin
   (e.g. `http://localhost:3000`).
4. The Flutter app authenticates via `POST /auth/login`, receives a JWT, and
   includes it as `Authorization: Bearer <token>` in all subsequent requests.

---

## 12. Troubleshooting

| Problem | Solution |
|---------|----------|
| `docker-compose up` fails with port conflict | Change `POSTGRES_PORT`, `API_PORT`, or `PGADMIN_PORT` in `.env`. |
| `alembic upgrade head` connection refused | Ensure PostgreSQL is running and `DATABASE_URL` in `.env` is correct. |
| pgAdmin can't connect to database | Use hostname `db` (not `localhost`) if pgAdmin runs in Docker. |
| CORS errors in the browser | Add your frontend origin to `CORS_ORIGINS` in `.env` and restart the API. |
| `ModuleNotFoundError` when running `python -m app.seed` | Activate the virtual environment first, or run inside the Docker container. |
| JWT token expired/invalid | Re-login via `POST /auth/login` to get a fresh token. |
| Rate limit exceeded (HTTP 429) | Wait for the rate limit window to reset (default 60 s) or increase `RATE_LIMIT_REQUESTS` in config. |
