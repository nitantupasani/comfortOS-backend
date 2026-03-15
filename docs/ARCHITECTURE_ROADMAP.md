# ComfortOS Architecture — Current State, Sprint Changes & Contribution Guide

> Companion document for [`comfortos_architecture_roadmap.puml`](../pumlfilespaper4/comfortos_architecture_roadmap.puml)
>
> ComfortOS is an open-source smart building platform. Contributions are welcome at any level — from fixing a known limitation to building out an entire subsystem. This document maps the current architecture, what was recently changed, and where contributors can help most.

---

## 1. Current State (what is live today)

| Component | Technology | Status |
|-----------|-----------|--------|
| **Mobile App** | Flutter (SDUI dashboards, voting, offline queue) | ✅ Live |
| **FM/Admin Web App** | React SPA (Vite + Tailwind) | ✅ Live |
| **Identity Provider** | Firebase Auth (OIDC/OAuth2, email/password + Google) | ✅ Live |
| **Platform API** | FastAPI on Oracle Cloud VM (Ubuntu 22.04) | ✅ Live |
| **Reverse Proxy** | Caddy — auto-HTTPS at `api.scientify.in` | ✅ Live |
| **Database** | Supabase PostgreSQL (single DB for everything) | ✅ Live |
| **Connector Gateway** | httpx-based module inside API (SSRF-protected) | ✅ Live |
| **Telemetry Poller** | Background asyncio task polling connectors | ✅ Live |
| **Push Token Registration** | `POST /notifications/register` stores FCM/APNs tokens | ✅ Live |
| **Push Notification Service** | `firebase_admin.messaging` — FCM/APNs batch delivery | ✅ Live |
| **Secrets Resolver** | `env:VAR` ref scheme, Vault/GCP/AWS schemes ready to plug in | ✅ Live |
| **Registry DB** | Connector + Dataset definitions stored in main DB | ⚠️ Co-located |
| **Telemetry Store** | `telemetry_readings` table in main DB | ⚠️ Co-located |
| **Rate Limiter** | In-memory per-IP sliding window | ⚠️ Single-instance only |

### Database Tables (all in Supabase PostgreSQL)

```
tenants, users, buildings, building_tenants, user_building_access,
building_configs, votes, presence_events, beacons, push_tokens,
audit_log, telemetry_readings, building_connectors,
connector_definitions, dataset_definitions, fm_role_requests
```

---

## 2. Recent Additions

### 2.1 Push Notification Service (FCM/APNs)

Push delivery is implemented in `app/services/notification_service.py` using `firebase_admin.messaging` — the same Firebase Admin SDK already used for auth, so no extra credentials are needed.

**Files:**

| File | Purpose |
|------|---------|
| `app/services/notification_service.py` | FCM batch delivery (`send_to_users`, `send_broadcast`) |
| `app/api/presence.py` | `POST /notifications/send` endpoint |
| `app/schemas/presence.py` | `SendNotificationRequest` / `SendNotificationResponse` |

**How it works:**

1. Admin/FM calls `POST /notifications/send` with `{ title, body, userIds?, data? }`
2. Device tokens are resolved from the `push_tokens` table
3. FCM `Message` objects are built with Android (high priority + channel) and APNs (sound + badge) config
4. Sent via `send_each()` in batches of up to 500
5. Returns `{ status, sent, failed }`

**Tips for further development:**
- FCM calls are currently synchronous — adding a queue (Redis, Cloud Tasks) would make delivery non-blocking with automatic retries
- iOS push requires a `.p8` APNs auth key uploaded to Firebase Console → Project Settings → Cloud Messaging → Apple app
- The Flutter app should call `POST /notifications/register` on startup and after any FCM token rotation

---

### 2.2 Secrets Resolver

`app/services/secrets.py` provides a `resolve_secret(ref)` function that decouples secret *references* stored in the database from their actual values.

**Secret reference format:**

```
env:MY_SECRET_VAR    → reads os.environ["MY_SECRET_VAR"]
value:literal        → returns "literal" (dev/testing only)
vault:path/to/key    → handler not yet implemented
gcp:projects/X/...   → handler not yet implemented
```

**How the Connector Gateway uses it:**

| `auth_type` | Behaviour |
|-------------|-----------|
| `bearer` | `resolve_secret(secret_ref)` → `Authorization: Bearer <token>` |
| `api_key` | `resolve_secret(secret_ref)` → `X-Api-Key: <key>` |
| `oauth2` | resolves client secret; full token-endpoint exchange not yet implemented |
| `hmac` | secret resolved; HMAC-SHA256 signing not yet implemented |
| `mTLS` | cert loading via `httpx` not yet implemented |

**Tips for further development:**
- Add `vault:` and `gcp:` scheme handlers in `app/services/secrets.py` to support proper KMS backends
- The `oauth2`, `hmac`, and `mTLS` auth types each need their own signing/exchange logic in `app/services/connector_gateway.py`

---

## 3. Contributing — Where Help is Needed

All contributions are welcome. Areas are grouped by domain; pick whatever interests you. Each item links to the relevant file(s) in the codebase.

---

### 🔧 Backend / API

| Area | Current gap | Where to start |
|------|------------|----------------|
| **Audit logging** | `AuditLog` model and table exist but nothing writes to them. Config changes, access grants, connector edits, and vote-form updates should all produce audit records. | `app/models/audit.py`, every write operation in `app/api/` |
| **Rate limiter (Redis)** | `RateLimitMiddleware` uses an in-process dict — broken across multiple workers. Needs a Redis-backed sliding window. | `app/middleware/rate_limiter.py` |
| **Notification queue** | `/notifications/send` calls FCM synchronously, blocking the API response. Should enqueue and return immediately, with a worker retrying failures. | `app/services/notification_service.py`, `app/api/presence.py` |
| **OAuth2 token exchange** | Connector Gateway resolves the client secret but doesn't implement the full `client_credentials` flow (token endpoint call, token caching, refresh). | `app/services/connector_gateway.py`, `app/services/secrets.py` |
| **HMAC request signing** | `auth_type = "hmac"` connectors have a placeholder. Needs canonical request signing (HMAC-SHA256 over method + path + timestamp + body). | `app/services/connector_gateway.py` |
| **mTLS outbound connections** | `auth_type = "mTLS"` connectors don't configure `httpx` with a client certificate yet. | `app/services/connector_gateway.py` |
| **Test coverage** | No unit or integration tests exist. Any test contributions (pytest + httpx `AsyncClient`) are high-value. | `test/` (to be created) |

---

### 📊 Data Layer

| Area | Current gap | Where to start |
|------|------------|----------------|
| **Telemetry Store separation** | `telemetry_readings` is a time-series workload sitting in the general-purpose Supabase DB. A TimescaleDB or InfluxDB adapter would give compression, time-based partitioning, and retention policies. | `app/models/telemetry.py`, `app/api/telemetry.py`, `app/services/telemetry_poller.py` |
| **Registry DB separation** | `connector_definitions` + `dataset_definitions` are a versioned catalog. Moving them to a separate schema (or DB) with its own access controls enables independent governance. | `app/models/connector_registry.py`, `alembic/` |
| **Alembic migration coverage** | Tables are created via `create_all` on startup. Proper Alembic migrations for every model are needed for safe production deploys. | `alembic/versions/` |

---

### 🔐 Security

| Area | Current gap | Where to start |
|------|------------|----------------|
| **Secrets Manager backend** | `secrets.py` resolves `env:` refs today. Adding a `vault:` or `gcp:` handler would let deployments store connector secrets in a proper KMS instead of environment variables. | `app/services/secrets.py` |
| **Token revocation** | Firebase tokens are validated on every request but there is no revocation list. A Redis-backed denylist would allow immediate session termination. | `app/services/auth_service.py`, `app/api/deps.py` |
| **SSRF DNS rebinding** | `_is_ssrf_blocked()` blocks IP literals but not DNS-rebinding attacks. DNS resolution at request time + re-validation would close this. | `app/services/connector_gateway.py` |

---

### 📱 Mobile / Flutter

| Area | Current gap | Where to start |
|------|------------|----------------|
| **FCM token lifecycle** | The Flutter app needs to register/refresh its FCM token on startup and after token rotation, calling `POST /notifications/register`. | `ComfortOS/lib/` |
| **APNs configuration** | iOS push requires uploading a `.p8` APNs auth key to Firebase Console → Project Settings → Cloud Messaging → Apple app. | Firebase Console (no code change) |
| **Offline vote sync** | `offline_vote_queue.dart` exists but the sync-on-reconnect logic needs review and testing against the idempotent `POST /votes` endpoint. | `ComfortOS/lib/data/offline_vote_queue.dart` |

---

### 🌐 Web App

| Area | Current gap | Where to start |
|------|------------|----------------|
| **Audit log viewer** | The backend records (once audit logging is active) but the web app has no UI to browse or filter the audit trail. | `comfortos-web/src/pages/` |
| **Connector registry UI** | Admins must currently use the raw API to approve/reject connector and dataset definitions. A UI for this workflow is missing. | `comfortos-web/src/pages/`, `comfortos-web/src/api/` |
| **Telemetry dashboard** | The SDUI system delivers dashboard configs but there is no static telemetry chart/table view for FM users in the web app. | `comfortos-web/src/components/` |

---

### 🏗️ Infrastructure / DevOps

| Area | Current gap | Where to start |
|------|------------|----------------|
| **CI/CD pipeline** | No automated tests or deploy pipeline. A GitHub Actions workflow (lint → test → deploy to VM on merge) would help contributors iterate safely. | `.github/workflows/` (to be created) |
| **Docker Compose for full local stack** | `docker-compose.yml` only runs the API. Adding a local PostgreSQL + Redis + (optionally) a mock FCM sink would make onboarding contributors easier. | `docker-compose.yml` |
| **Deployment documentation** | The VM deploy steps are in `README.md` but there is no guide for first-time contributors setting up a fully local environment from scratch. | `README.md`, `instructions.md` |

---

## 4. Architecture Diagram Legend

The PUML diagram (`comfortos_architecture_roadmap.puml`) uses color-coded tags:

| Color | Tag | Meaning |
|-------|-----|---------|
| 🟢 Green | `live` | Currently deployed and operational |
| 🔵 Blue | `new` | Added in the most recent contribution sprint |
| 🟡 Yellow | `contribution` | Not yet built — open for contributors |
| 🔴 Red | `external` | External third-party systems (Firebase, Supabase, building systems) |

---

## 5. File Reference

### Added

```
app/services/notification_service.py   — FCM push notification service
app/services/secrets.py                — Secret reference resolver
pumlfilespaper4/comfortos_architecture_roadmap.puml — Architecture diagram
docs/ARCHITECTURE_ROADMAP.md           — This document
```

### Modified

```
app/api/presence.py                    — /notifications/send wired to FCM service
app/schemas/presence.py                — SendNotificationRequest/Response added
app/services/connector_gateway.py      — Secrets resolver wired for connector auth
```
