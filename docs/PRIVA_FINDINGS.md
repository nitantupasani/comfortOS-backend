# Priva → ComfortOS telemetry integration — findings & how-to

Everything learned reverse-engineering the **Priva Operator** cloud to stream a
building's sensor telemetry into ComfortOS, plus the design we built around it.

> **Status:** working end-to-end (validated live). Unofficial/unsupported — see
> [Legality & risk](#legality--risk). Operational setup lives in
> [`PRIVA_INGEST.md`](./PRIVA_INGEST.md); this file is the *why* and the protocol.

---

## 1. Context & the core problem

- The building is a Priva site (Operator app at `https://operator.priva.com`),
  tenant **MERIN**. Login is interactive with **2FA**.
- Priva offers official **Building Connectivity APIs** (Realtime + Historical
  Data API), OAuth2 client-credentials at `https://auth.priva.com/connect/token`.
  **But** these are a paid **add-on** (PDS Essentials/Plus). This subscription
  does **not** have it — Access Control shows only an **audit-log** view, no
  "external applications" screen to mint a `client_id`/`client_secret`.
- The interactive 2FA login is **not** usable for a headless poller, and there
  is no machine credential available.

**Conclusion:** with no API add-on, the only way in is to **replay the Operator
GUI's own private API** using the browser's authenticated session. That's what
the ComfortOS connector does.

---

## 2. Authentication model (the key discovery)

Priva Operator is a **SPA + BFF (Backend-for-Frontend)**:

- The browser holds **no bearer token**. JS storage (local/session) and
  IndexedDB contain **no** `oidc.user` / `access_token` / `refresh_token`.
- Auth is a single secure cookie **`__Host-bff`** (httpOnly, `__Host-` prefixed →
  HTTPS-only, host-locked, path `/`). The BFF backend exchanges it for the real
  OAuth token **server-side** and attaches it to upstream calls.
- API requests also carry a CSRF marker header **`x-csrf: 1`**.
- No `Authorization` header is ever present on API/XHR calls from the SPA.

So the **session bearer we can replay = the `__Host-bff` cookie** (+ `x-csrf: 1`).

The realtime stream itself rides **Azure SignalR Service**
(`*.service.signalr.net`). The token used on the websocket is a *separate*,
short-lived Azure-SignalR JWT that the BFF mints during negotiate — we never
handle it directly except to pass it back on the socket URL.

### Token lifetimes (decoded from a captured SignalR JWT)

| Layer | Claim | Lifetime |
|---|---|---|
| Azure SignalR service token (`access_token` on the wss URL) | `asrs.u.exp` | **~1 hour** |
| Underlying Priva user token (wrapped) | `exp` vs `iat` | **~30 days** |
| Scopes present | include `offline_access`, `priva.operator`, `priva.charts-service`, `priva.hdp-tss`, `priva.data-services` | — |
| `client_id` | `853bcc0e-…` (public Operator SPA client, PKCE) | — |

`offline_access` confirms refresh tokens exist server-side — but they live in the
BFF, not in the browser, so we cannot extract one. We rely on the **cookie**
instead (see [Cookie expiry](#8-cookie-expiry--renewal)).

---

## 3. Transport: SignalR over Azure SignalR Service

Live telemetry is an ASP.NET Core SignalR hub (`telemetryhub`) fronted by Azure
SignalR Service. Connecting takes a **two-hop negotiate**, then a websocket.

### Hop 1 — app negotiate (cookie auth)

```
POST https://operator.priva.com/operator/signalr/hubs/data/negotiate?negotiateVersion=1
Cookie: __Host-bff=…
x-csrf: 1
```

Returns an Azure SignalR **redirect** response:

```json
{ "url": "https://prd-operator-signalr.service.signalr.net/client/?hub=telemetryhub&asrs.op=%2Foperator%2Fsignalr%2Fhubs%2Fdata&negotiateVersion=1&asrs_request_id=…",
  "accessToken": "eyJ…" }
```

### Hop 2 — Azure service negotiate (bearer auth)

Insert `negotiate` into the **path** of the returned `url` (keep its query
intact — it already has `negotiateVersion=1`). Appending `&negotiateVersion=1` to
the query instead returns **400 Bad Request** (a bug we hit and fixed):

```
POST https://prd-operator-signalr.service.signalr.net/client/negotiate?hub=telemetryhub&asrs.op=…&negotiateVersion=1&asrs_request_id=…
Authorization: Bearer <accessToken from hop 1>
```

Returns `{ "connectionToken": "…", "availableTransports": [...] }`.

### Hop 3 — websocket

```
wss://prd-operator-signalr.service.signalr.net/client/?hub=telemetryhub&asrs.op=…&negotiateVersion=1&asrs_request_id=…&id=<connectionToken>&access_token=<accessToken>
```

### Hop 4 — SignalR JSON handshake

Messages are JSON terminated by the record separator byte **`0x1e`** (`\x1e`).

```
{"protocol":"json","version":1}\x1e      → server replies {}\x1e
```

---

## 4. Subscribing to variables

After the handshake, send one `subscribe` invocation. Captured shape:

```jsonc
{
  "type": 1,                      // 1 = invocation
  "invocationId": "0",
  "target": "subscribe",
  "arguments": [
    [ /* variable descriptors, one per sensor */
      {
        "siteId":         "<site GUID>",       // the building
        "deviceGroupId":  "<group, e.g. pNNNNN>",
        "serverId":       "<controller GUID>", // Priva Compri/controller
        "variableId":     "<sensor GUID>",
        "uniqueVariableId":"<group>.variable.<serverId>.<variableId>"
      }
      // … repeat for each variable on the floor/group
    ],
    "<controller-serial>",        // e.g. "AXYYYYMMDDNNN"; 2nd arg
    "<deviceGroupId>"             // same group string; 3rd arg
  ]
}
```

`uniqueVariableId` is always `"{deviceGroupId}.variable.{serverId}.{variableId}"`.

### ID hierarchy

```
siteId (building)
└── deviceGroupId  (e.g. p57560 — a controller "page"/group)
    └── serverId   (the physical Priva controller GUID; also has a serial like AX…)
        └── variableId  (an individual sensor/point GUID)
```

All four IDs come from the captured `subscribe` frame
(DevTools → Network → **Socket** → `telemetryhub` → **Messages**).

---

## 5. Receiving data — `telemetryChangedCallback`

The hub pushes **change-of-value (COV)** frames — only when a value changes (so
not on a fixed interval). Captured shape:

```jsonc
{
  "type": 1,
  "target": "telemetryChangedCallback",
  "arguments": [[
    {
      "variableNodeReference": { "siteId":…, "deviceGroupId":…, "serverId":…,
                                 "variableId":"55563579-…", "uniqueVariableId":… },
      "value": "23.000000",                 // STRING float — parse to number
      "valid": false,
      "modificationTime": "2026-05-31T11:10:35+00:00",  // ISO8601, real sensor time
      "state": "Valid",
      "level": "NotIntervened"
    }
    // … one object per changed variable
  ]]
}
```

Notes / gotchas observed live:
- `value` is a **string** → cast to `float`.
- `modificationTime` is the true capture time — use it for `recorded_at`.
- Keep-alive: server sends SignalR pings (`{"type":6}`); we send one every 15 s.
- Of 14 subscribed vars on the ground floor, **10 were temperatures** (~22–23 °C,
  changing every few seconds); **4 read `0`** with stale `modificationTime` —
  these are non-temperature points (setpoints/valves/inactive) and must be
  re-typed or dropped in the variable map.
- One floorplan tile showed `160.0 °C` in the GUI — sensor fault/placeholder;
  expect bad values and flag/clip them (`quality_flag`).

---

## 6. History / backfill (REST side)

The Operator history chart uses REST under `…/operator/api/`, gated by the same
cookie. Endpoints seen:

| Endpoint | Purpose |
|---|---|
| `GET /operator/api/hortidata/timeconfig/{siteId}` | site timezone/DST config |
| `GET /operator/api/hortidata/timeconfig/{siteId}/{serverId}` | controller time config |
| `GET /operator/api/customchart/{siteId}/{variableId}_{n}__{chartGuid}` | chart series (returned `[]` without a date window) |

The visible 3-day chart line is delivered over the **same SignalR socket**, not a
single tidy REST payload, so the clean backfill path is the **official Historical
Data API** (if/when the add-on is purchased). For now the user has a separate
backfill method; the live connector below covers ongoing ingestion.

---

## 7. ComfortOS integration — what we built

A dedicated service (the existing REST `telemetry_poller` can't speak SignalR):

| File | Role |
|---|---|
| [`app/services/priva_ingestion.py`](../app/services/priva_ingestion.py) | The connector: negotiate → subscribe → cache COV → 15-min flush |
| [`scripts/test_priva.py`](../scripts/test_priva.py) | Standalone validator, **no DB writes**; prints live pushes |
| [`priva_variables.json`](../priva_variables.json) | `variableId → {room, metric, unit, location_id}` map (gitignored) |
| `app/config.py` | `PRIVA_*` settings |
| `app/main.py` | launches `start_priva_ingestion()` in the FastAPI lifespan |

### Flow

1. Supervisor (`start_priva_ingestion`) runs only if `PRIVA_ENABLED=true`.
2. Opens a SignalR session (the 4 hops above), subscribes to every `variableId`
   in `priva_variables.json`.
3. Each `telemetryChangedCallback` updates an in-memory `latest[variableId]`.
4. Every `PRIVA_FLUSH_MINUTES` (default **15**) a flush loop writes **one
   `TelemetryReading` per variable** on a fixed grid:
   - `value` = parsed float, `recorded_at` = flush time (grid),
     `metadata.modificationTime` = true sensor time,
     `metric_type`/`unit`/`zone`/`location_id` from the map,
     `connector_id = "priva-signalr"`.
5. Auto-reconnect with exponential backoff (5 s → 300 s). On 401/403 it logs that
   the cookie expired.

### Why COV → 15-min snapshot

The stream is change-of-value, but ComfortOS wants a regular series. We cache the
latest value per variable and snapshot it every 15 min — giving a clean fixed grid
regardless of how often the sensor reports. (Switch to per-push storage later if
raw fidelity is needed.)

### Storage mapping (`telemetry_readings`)

| Priva | ComfortOS column |
|---|---|
| `value` (string→float) | `value` |
| `modificationTime` | `metadata.modificationTime` (+ `recorded_at` = grid time) |
| variable `metric` (from map) | `metric_type` (default `temperature`) |
| variable `unit` (from map) | `unit` (default `C`) |
| variable `room` (from map) | `zone` (legacy label) |
| variable `location_id` (from map) | `location_id` (FK to `locations`) |
| — | `connector_id = "priva-signalr"`, `source_level = "sensor"` |

**Deferred (not yet wired):** the `variableId → room/zone/location_id` mapping and
correct per-variable `metric_type`. The map file has the hooks; values are TBD.

---

## 8. Cookie expiry & renewal

- `__Host-bff` is a **sliding BFF session**. Continuous streaming keeps it warm.
- On expiry, negotiate hop 1 returns **401/403**; the supervisor backs off and
  retries. Fix = **re-copy the `__Host-bff` value** from a freshly logged-in
  browser into `.env`.
- For unattended long-running ingestion, the durable option is a **Playwright
  worker** that holds a real logged-in session and refreshes the cookie itself
  (future work). Until then, expect periodic manual cookie refresh.
- The proper long-term fix remains the **Historical Data API add-on**
  (OAuth2 client-credentials, no cookie, no expiry babysitting).

---

## 9. Setup (quick)

All secrets go in **`.env`** (gitignored) — never in `.env.example` or code.

```ini
PRIVA_ENABLED=false                     # flip to true once BUILDING_ID is set
PRIVA_BFF_COOKIE=__Host-bff=…           # DevTools → Network → /operator/api req → cookie
PRIVA_BUILDING_ID=                      # ComfortOS building to attach readings to
PRIVA_SITE_ID=…                         # from the subscribe frame
PRIVA_SERVER_ID=…
PRIVA_GROUP_ID=…
PRIVA_CONTROLLER=…                      # controller serial (2nd subscribe arg)
PRIVA_VAR_MAP_PATH=priva_variables.json
PRIVA_FLUSH_MINUTES=15
```

```bash
pip install "websockets>=12,<16"        # also needs httpx, sqlalchemy, asyncpg
python -m scripts.test_priva --seconds 90   # validate cookie + see live pushes (no DB)
```

Then fill `priva_variables.json`, set `PRIVA_BUILDING_ID`, `PRIVA_ENABLED=true`,
start the backend.

---

## 10. Gotchas / lessons learned

- **No token in JS** — Priva uses a BFF; don't hunt for `refresh_token`, replay
  the `__Host-bff` cookie + `x-csrf: 1`.
- **Two-hop negotiate** — Azure SignalR hop 2 needs `negotiate` in the **path**,
  query left intact. Appending `&negotiateVersion=1` → **400**.
- **`0x1e` framing** — SignalR JSON messages are `\x1e`-separated; one ws frame can
  carry several messages. Split before parsing.
- **`value` is a string** — cast to float.
- **COV, not polling** — data arrives on change; snapshot for a fixed grid.
- **Dead/garbage values** — some vars report `0` or absurd values (`160 °C`);
  filter by the variable map and `quality_flag`.
- **Cookie is a live secret** — treat like a password; it expires.

---

## 11. Legality & risk

This integration **rides the Operator GUI's private API with a copied browser
session cookie**. It is **unofficial, unsupported, and likely against Priva's
Terms of Service**, and can break on any Priva front-end update. Use only with
proper authorization for research ingestion. The supported, durable path is the
**Priva Historical Data / Realtime Data API** add-on (OAuth2 client-credentials
at `https://auth.priva.com/connect/token`); migrate to it when available — the
storage layer and variable map carry over unchanged.

---

## 12. Endpoint reference

| What | Method | URL |
|---|---|---|
| App SignalR negotiate | POST | `https://operator.priva.com/operator/signalr/hubs/data/negotiate?negotiateVersion=1` |
| Azure SignalR negotiate | POST | `https://prd-operator-signalr.service.signalr.net/client/negotiate?<query>` |
| Azure SignalR websocket | WS | `wss://prd-operator-signalr.service.signalr.net/client/?<query>&id=<connToken>&access_token=<token>` |
| Site time config | GET | `https://operator.priva.com/operator/api/hortidata/timeconfig/{siteId}` |
| Custom chart series | GET | `https://operator.priva.com/operator/api/customchart/{siteId}/{variableId}_{n}__{chartGuid}` |
| OAuth2 token (official API, if add-on) | POST | `https://auth.priva.com/connect/token` |
| Developer portal (official API) | — | `https://apiportal.priva.com/` |
