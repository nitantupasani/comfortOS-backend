# Priva telemetry ingestion (unofficial SignalR)

Pulls live room telemetry from the **Priva Operator** GUI's private API and
stores it in `telemetry_readings`. There is **no public token** for this building
(no Historical Data API add-on on the subscription), so we replay the browser's
**BFF session cookie** (`__Host-bff`).

> ⚠️ **Unofficial / unsupported.** Rides the Operator GUI's private API with a
> copied session cookie. Can break on any Priva front-end update and is likely
> against Priva's ToS. Use only with authorization, for research ingestion.
> Supported alternative: the **Priva Historical Data API** add-on (OAuth2
> client-credentials at `https://auth.priva.com/connect/token`).

## How it works

Priva Operator is a SPA + BFF; live telemetry rides an **Azure SignalR Service**
hub. The service (`app/services/priva_ingestion.py`) reproduces the GUI flow:

1. **App negotiate** — `POST /operator/signalr/hubs/data/negotiate` (cookie + `x-csrf`)
   → `{ url, accessToken }` (Azure SignalR redirect).
2. **Service negotiate** — `POST <azure-url>&negotiateVersion=1` (Bearer)
   → `{ connectionToken }`.
3. **WebSocket** — `wss <azure-url>&id=<connToken>&access_token=<token>`.
4. **Handshake** `{"protocol":"json","version":1}` → **subscribe** (variable list).
5. Receive `telemetryChangedCallback` frames = **change-of-value** pushes.
6. Every `PRIVA_FLUSH_MINUTES` (default 15) → write one `TelemetryReading` per
   variable on a fixed grid (`connector_id="priva-signalr"`).

## Setup

1. **Credentials → `.env`** (gitignored; never `.env.example`):
   - `PRIVA_BFF_COOKIE=__Host-bff=...` — DevTools → Network → any `/operator/api`
     request → Request Headers → `cookie` → copy the `__Host-bff=...` pair.
   - `PRIVA_SITE_ID`, `PRIVA_SERVER_ID`, `PRIVA_GROUP_ID`, `PRIVA_CONTROLLER` —
     from the `subscribe` frame (Network → Socket → `telemetryhub` → Messages).
   - `PRIVA_BUILDING_ID` — the ComfortOS building to attach readings to.
2. **Variable map → `priva_variables.json`** (gitignored): `variableId →
   {room, metric, unit, location_id}`. Controls which variables are subscribed.
3. **Validate without DB:** `python -m scripts.test_priva --seconds 90` — prints
   live pushes so you can match each `variableId` to its room.
4. **Enable:** set `PRIVA_ENABLED=true`. Started from the FastAPI lifespan.

## Cookie expiry

`__Host-bff` is a sliding BFF session. Continuous streaming keeps it warm. On
expiry the app logs a 401/403 and retries with backoff — **re-copy the cookie**
from a freshly logged-in browser. For unattended long-run, replace the cookie
source with a Playwright worker that holds a live login (future work).
