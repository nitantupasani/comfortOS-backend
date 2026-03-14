# ComfortOS Backend

Backend API for the ComfortOS Smart Building Platform.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **API** | FastAPI (Python) on Uvicorn |
| **Auth** | Firebase Admin SDK (token verification) |
| **Database** | Supabase PostgreSQL (Session Pooler) |
| **ORM** | SQLAlchemy (async) + asyncpg |
| **Migrations** | Alembic |
| **Reverse Proxy** | Caddy (auto-HTTPS via Let's Encrypt) |
| **Hosting** | Oracle Cloud VM (Ubuntu 22.04) |
| **Domain** | https://api.scientify.in |

## Database Tables

`tenants`, `users`, `buildings`, `building_tenants`, `user_building_access`,
`building_configs`, `votes`, `presence_events`, `beacons`, `push_tokens`,
`audit_log`, `connector_definitions`, `dataset_definitions`

## Local Development

```bash
# 1. Create .env (see .env section below)
# 2. Place firebase-service-account.json in backend/

# 3. Install dependencies
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 4. Run migrations
alembic upgrade head

# 5. Start server
uvicorn app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

## Required Files (not in git)

| File | How to get it |
|------|---------------|
| `.env` | Create manually (see below) |
| `firebase-service-account.json` | Firebase Console → Project Settings → Service accounts → Generate new private key |

### .env

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres.XXXX:PASSWORD@aws-1-eu-central-1.pooler.supabase.com:5432/postgres
FIREBASE_SERVICE_ACCOUNT_KEY_PATH=firebase-service-account.json
FIREBASE_PROJECT_ID=comfortos
API_PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,https://api.scientify.in
DB_POOL_SIZE=3
DB_MAX_OVERFLOW=5
```

## VM Deployment (Oracle Cloud)

**VM:** 134.98.148.179 | **User:** ubuntu | **Domain:** api.scientify.in

### SSH into VM

```bash
ssh -i path/to/ssh-key.key ubuntu@134.98.148.179
```

### Restart backend

```bash
sudo systemctl restart comfortos
```

### Check backend status / logs

```bash
sudo systemctl status comfortos
sudo journalctl -u comfortos --no-pager -n 30
```

### Restart Caddy (reverse proxy)

```bash
sudo systemctl restart caddy
```

### Deploy code updates

```bash
# 1. Push from local
git add -A && git commit -m "message" && git push

# 2. On VM
cd ~/comfortOS-backend
git pull
sudo systemctl restart comfortos
```

### Copy .env / firebase key to VM (from local PowerShell)

```powershell
scp -i "path\to\ssh-key.key" backend\.env ubuntu@134.98.148.179:~/comfortOS-backend/
scp -i "path\to\ssh-key.key" backend\firebase-service-account.json ubuntu@134.98.148.179:~/comfortOS-backend/
```

### Run migrations on VM

```bash
cd ~/comfortOS-backend
source venv/bin/activate
export $(grep -v '^#' .env | xargs)
PYTHONPATH=/home/ubuntu/comfortOS-backend alembic upgrade head
```

### Service files on VM

| File | Purpose |
|------|---------|
| `/etc/systemd/system/comfortos.service` | Uvicorn systemd service |
| `/etc/caddy/Caddyfile` | Caddy reverse proxy config |

### Test

```bash
curl https://api.scientify.in/health
```

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
