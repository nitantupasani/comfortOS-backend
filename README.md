# ComfortOS Production Backend

Production backend for the ComfortOS Smart Building Platform, implementing
the architecture described in `backend.puml`.

## Architecture (C4 Containers)

| Container | Technology | Description |
|-----------|-----------|-------------|
| **Platform API** | FastAPI (Python) | AuthZ, tenancy isolation, dashboard delivery, votes, tickets, dataset reads |
| **Identity Provider** | JWT / OAuth2 (built-in) | Login, tokens, roles/claims |
| **Connector Gateway** | Internal service module | Secure egress to external data services, secret resolution, normalization |
| **Platform DB** | PostgreSQL | Tenants, buildings, configs, votes, tickets, audit log |
| **Registry DB** | PostgreSQL (shared) | Connector Registry + Dataset Registry (versioned, approved) |
| **Telemetry Store** | TimescaleDB (optional) | Cached/normalized measurements |
| **Secrets Manager** | Environment / Vault | mTLS keys, OAuth secrets, HMAC keys |
| **Push Provider** | FCM/APNs adapter | Notification delivery |

## Quick Start

```bash
# 0. Create a local env file
copy .env.example .env

# 1. Start PostgreSQL, API, and pgAdmin
docker-compose up -d db api pgadmin

# 2. Install dependencies (optional if you run only in Docker)
pip install -r requirements.txt

# 3. Run migrations
alembic upgrade head

# 4. Seed demo data
python -m app.seed

# 5. Start the server
uvicorn app.main:app --reload --port 8000
```

## Local Secure Setup

For local development, prefer these defaults:

- Keep services bound to `127.0.0.1` only.
- Put secrets in `backend/.env` and never commit that file.
- Replace the default database, JWT, and pgAdmin passwords before first run.
- Restrict `CORS_ORIGINS` to your actual frontend origins instead of `*`.

The provided `docker-compose.yml` already binds PostgreSQL, the API, and pgAdmin to localhost only.

### Recommended local flow

1. Copy `.env.example` to `.env`.
2. Set strong values for:
	- `POSTGRES_PASSWORD`
	- `SECRET_KEY`
	- `PGADMIN_DEFAULT_PASSWORD`
3. Start the local stack:

	```bash
	docker-compose up -d db api pgadmin
	```

4. Open the API docs at `http://127.0.0.1:8000/docs`.
5. Open pgAdmin at `http://127.0.0.1:5050`.

### pgAdmin connection details

When adding the PostgreSQL server in pgAdmin, use:

- **Host**: `db` if pgAdmin is running in Docker, or `127.0.0.1` from your host machine
- **Port**: `5432` inside Docker, or the value of `POSTGRES_PORT` from `.env` on the host machine
- **Database**: value of `POSTGRES_DB`
- **Username**: value of `POSTGRES_USER`
- **Password**: value of `POSTGRES_PASSWORD`

### Visualizing the database

You have three practical options:

1. **pgAdmin** — browse schemas, inspect rows, and run SQL locally.
2. **DBeaver** — desktop client with a better ERD experience.
3. **Schema introspection in PostgreSQL** — useful later on the VM for audits and backups.

This backend currently models these core tables:

- `tenants`
- `users`
- `buildings`
- `building_configs`
- `votes`
- `presence_events`
- `beacons`
- `push_tokens`
- `audit_logs`
- `connector_definitions`
- `dataset_definitions`

`users` and `buildings` link back to `tenants`, which is the main tenancy boundary.

## Frontend Connection

The Flutter app already includes a local environment pointing at `http://localhost:8000`. See [ComfortOS/lib/data/app_environment.dart](../ComfortOS/lib/data/app_environment.dart#L28-L36).

For local integration, switch the app to `AppEnvironment.local` so it uses the FastAPI backend instead of the in-process dummy backend.

## API Endpoints

### Identity Provider
- `POST /auth/login` — Authenticate, receive JWT
- `POST /auth/refresh` — Refresh token
- `POST /auth/logout` — Invalidate token
- `GET  /auth/validate` — Validate current token

### Building & Config API
- `GET  /buildings?tenantId=` — List buildings for tenant
- `GET  /buildings/{id}/dashboard` — SDUI dashboard config
- `GET  /buildings/{id}/vote-form` — SDUI vote form schema  
- `GET  /buildings/{id}/location-form` — Floor/room hierarchy
- `GET  /buildings/{id}/config` — Full app config

### Vote Ingestion API
- `POST /votes` — Submit comfort vote (idempotent by voteUuid)
- `GET  /votes/history?userId=` — Vote history
- `GET  /buildings/{id}/comfort` — Aggregate comfort data

### Notification & Presence API
- `POST /presence/events` — Report presence event
- `GET  /presence/beacons?buildingId=` — BLE beacon registry
- `POST /notifications/register` — Register push token
- `POST /notifications/send` — Send push notification

### Connector Gateway (Dataset Reads)
- `POST /datasets/read` — Read external dataset (proxied)

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py             # Environment settings
│   ├── database.py           # SQLAlchemy engine & session
│   ├── seed.py               # Demo data seeder
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── api/                  # Route handlers
│   ├── services/             # Business logic services
│   └── middleware/           # Tenant isolation, rate limiting
├── alembic/                  # Database migrations
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://comfortos:comfortos@localhost:5432/comfortos` | PostgreSQL connection |
| `SECRET_KEY` | (random) | JWT signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token lifetime |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
