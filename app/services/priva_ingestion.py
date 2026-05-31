"""
Priva Operator telemetry ingestion via SignalR (reverse-engineered GUI API).

Priva Cloud's Operator front-end is a SPA backed by a BFF (Backend-for-Frontend):
the browser holds **no** bearer token — auth is the secure `__Host-bff` session
cookie, and the BFF attaches the real OAuth token to upstream calls server-side.
Live telemetry streams over an Azure SignalR Service hub (`telemetryhub`).

This service replays that flow headlessly:

  1. App negotiate    POST /operator/signalr/hubs/data/negotiate?negotiateVersion=1
                      (cookie + x-csrf auth)            -> { url, accessToken }
  2. Service negotiate POST <azure-url>&negotiateVersion=1
                      (Bearer accessToken)              -> { connectionToken }
  3. WebSocket        wss <azure-url>&id=<connToken>&access_token=<accessToken>
  4. Handshake        {"protocol":"json","version":1}\x1e
  5. subscribe        invocation with the variable descriptors
  6. receive          telemetryChangedCallback frames   (change-of-value pushes)
  7. every FLUSH_MIN  write one TelemetryReading per variable (15-minute grid)

WARNING -- UNOFFICIAL / UNSUPPORTED
-----------------------------------
This rides the Operator GUI's private API using a copied browser session cookie.
It can break on any Priva front-end update and is likely against Priva's Terms of
Service. Use only with authorization, for research ingestion. The supported path
is the Priva **Historical Data API** add-on (OAuth2 client-credentials against
https://auth.priva.com/connect/token); switch to it when the subscription has it.

The session cookie also expires (sliding BFF session). Continuous polling keeps it
warm; if it dies you must re-copy `__Host-bff` from a freshly logged-in browser,
or run a Playwright worker that holds a live session. See docs/PRIVA_INGEST.md.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover - optional dep until enabled
    websockets = None

from ..config import settings
from ..database import async_session_factory
from ..models.telemetry import TelemetryReading

logger = logging.getLogger("comfortos.priva")

# SignalR JSON-protocol record separator
RS = "\x1e"

# Plausible room-temperature range (°C). Readings outside are dropped as faults
# (e.g. disconnected sensors report a stuck 160 °C).
PLAUSIBLE_MIN = -10.0
PLAUSIBLE_MAX = 60.0


def is_plausible(value: float) -> bool:
    return PLAUSIBLE_MIN <= value <= PLAUSIBLE_MAX

# App-side hub endpoint (the Azure SignalR "upstream"); asrs.op in the captured
# ws URL confirms the path /operator/signalr/hubs/data.
APP_HUB_URL = "https://operator.priva.com/operator/signalr/hubs/data"


# ── Building config ────────────────────────────────────────────────────────

def _resolve_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / path  # backend package root
    return p


def load_building(path: str) -> dict:
    """Load a per-building Priva config file.

    Returns a dict with: buildingName, comfortosBuildingId, siteId, serverId,
    controller, groups, variables ({variableId: {room, metric, unit, ...}}).
    """
    p = _resolve_path(path)
    if not p.exists():
        logger.error("Priva building file not found: %s", p)
        return {}
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("variables", {})
    return data


def _load_var_map(path: str) -> dict[str, dict]:
    """Back-compat helper: return just the variable map from a building file."""
    return load_building(path).get("variables", {})


def _descriptor(site_id: str, group_id: str, server_id: str, variable_id: str) -> dict:
    return {
        "siteId": site_id,
        "deviceGroupId": group_id,
        "serverId": server_id,
        "variableId": variable_id,
        "uniqueVariableId": f"{group_id}.variable.{server_id}.{variable_id}",
    }


def build_subscribe_frames(
    var_map: dict[str, dict],
    site_id: str,
    group_id: str,
    servers: dict[str, dict],
    default_server: str = "",
) -> list[dict]:
    """Build one SignalR `subscribe` invocation per controller (server).

    A building can span several Priva controllers (each variable carries its own
    `server` in the scheme metadata). Each controller needs its own subscribe
    frame whose 2nd argument is that controller's serial. Variables whose server
    has no known serial are skipped with a warning.
    """
    by_server: dict[str, list[dict]] = {}
    for variable_id, info in var_map.items():
        srv = info.get("server") or default_server
        if not srv:
            continue
        by_server.setdefault(srv, []).append(
            _descriptor(site_id, group_id, srv, variable_id)
        )

    frames: list[dict] = []
    for srv, descriptors in by_server.items():
        controller = (servers.get(srv) or {}).get("controller", "")
        if not controller:
            logger.warning(
                "Priva: %d variables on server %s skipped — no controller serial "
                "in building file 'servers' map", len(descriptors), srv,
            )
            continue
        frames.append({
            "arguments": [descriptors, controller, group_id],
            "target": "subscribe",
            "type": 1,
            "invocationId": str(len(frames)),
        })
    return frames


# ── Negotiate (two-hop, Azure SignalR Service) ─────────────────────────────

async def negotiate(cookie: str) -> str:
    """Run the two-hop negotiate and return the fully-formed wss URL.

    Hop 1 is authenticated by the BFF session cookie; hop 2 by the bearer token
    that hop 1 returns. Raises on any non-2xx or unexpected response.
    """
    headers = {
        "Cookie": cookie,
        "x-csrf": "1",
        "Accept": "application/json",
        "Origin": "https://operator.priva.com",
        "Referer": "https://operator.priva.com/",
    }
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # Hop 1 — app negotiate (cookie auth) -> Azure SignalR redirect
        r1 = await client.post(f"{APP_HUB_URL}/negotiate?negotiateVersion=1")
        r1.raise_for_status()
        j1 = r1.json()
        azure_url = j1.get("url")
        access_token = j1.get("accessToken")
        if not azure_url or not access_token:
            raise RuntimeError(
                f"Unexpected app negotiate response (no url/accessToken): {j1}"
            )

        # Hop 2 — Azure service negotiate (bearer auth) -> connectionToken.
        # The redirect `url` is the client CONNECT url (path .../client/, query
        # already carries negotiateVersion + asrs.*). Azure's negotiate endpoint
        # is the same query with `negotiate` inserted into the PATH.
        parts = urlsplit(azure_url)
        negotiate_url = urlunsplit((
            parts.scheme, parts.netloc,
            parts.path.rstrip("/") + "/negotiate",
            parts.query, "",
        ))
        r2 = await client.post(
            negotiate_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r2.raise_for_status()
        j2 = r2.json()
        connection_token = j2.get("connectionToken") or j2.get("connectionId")
        if not connection_token:
            raise RuntimeError(
                f"Unexpected service negotiate response (no connectionToken): {j2}"
            )

    ws_base = azure_url.replace("https://", "wss://", 1)
    sep = "&" if "?" in ws_base else "?"
    return f"{ws_base}{sep}id={connection_token}&access_token={access_token}"


# ── Frame parsing ──────────────────────────────────────────────────────────

def _parse_telemetry_frame(msg: dict, latest: dict[str, dict]) -> int:
    """Update `latest` from a telemetryChangedCallback frame. Returns # updated."""
    args = msg.get("arguments") or []
    if not args or not isinstance(args[0], list):
        return 0
    n = 0
    for item in args[0]:
        ref = item.get("variableNodeReference") or {}
        vid = ref.get("variableId")
        raw_val = item.get("value")
        if vid is None or raw_val is None:
            continue
        try:
            value = float(raw_val)
        except (TypeError, ValueError):
            continue
        if not is_plausible(value):
            continue  # drop faulty sensor (e.g. disconnected -> stuck 160 °C)
        latest[vid] = {
            "value": value,
            "modtime": item.get("modificationTime"),
            "state": item.get("state"),
        }
        n += 1
    return n


# ── WebSocket session ──────────────────────────────────────────────────────

async def _run_session(
    cookie: str,
    frames: list[dict],
    latest: dict[str, dict],
) -> None:
    """Open one SignalR session: negotiate, handshake, subscribe, stream.

    `frames` is one or more `subscribe` invocations (one per controller).
    Returns (raises) when the connection closes; the supervisor reconnects.
    """
    ws_url = await negotiate(cookie)
    logger.info("Priva negotiate OK, connecting websocket")

    async with websockets.connect(ws_url, max_size=None, ping_interval=None) as ws:
        # SignalR handshake
        await ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
        await ws.recv()  # handshake ack: "{}\x1e"

        # subscribe — one frame per controller; each:
        #   [ [descriptors...], "<controller-serial>", "<deviceGroupId>" ]
        total = 0
        for frame in frames:
            await ws.send(json.dumps(frame) + RS)
            total += len(frame["arguments"][0])
        logger.info("Priva subscribed to %d variables across %d controller(s)",
                    total, len(frames))

        # SignalR-level keepalive (server expects periodic pings)
        async def _ping():
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({"type": 6}) + RS)

        ping_task = asyncio.create_task(_ping())
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "ignore")
                for part in raw.split(RS):
                    if not part:
                        continue
                    try:
                        msg = json.loads(part)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == 1 and msg.get("target") == "telemetryChangedCallback":
                        _parse_telemetry_frame(msg, latest)
                    # type 6 = ping, type 3 = completion, type 7 = close
                    elif msg.get("type") == 7:
                        logger.warning("Priva server closed: %s", msg.get("error"))
                        return
        finally:
            ping_task.cancel()


# ── 15-minute flush loop ───────────────────────────────────────────────────

async def _flush_loop(
    latest: dict[str, dict],
    var_map: dict[str, dict],
    building_id: str,
    flush_minutes: int,
) -> None:
    """Every `flush_minutes`, write one reading per variable from `latest`."""
    while True:
        await asyncio.sleep(flush_minutes * 60)
        if not latest:
            logger.info("Priva flush: no values cached yet")
            continue

        now = datetime.now(timezone.utc)
        rows = []
        for vid, meta in list(latest.items()):
            info = var_map.get(vid, {})
            modtime = meta.get("modtime")
            rows.append(TelemetryReading(
                building_id=building_id,
                location_id=info.get("location_id"),
                metric_type=info.get("metric", "temperature"),
                value=meta["value"],
                unit=info.get("unit", "C"),
                recorded_at=now,           # snapshot on the fixed 15-min grid
                source_level="sensor",
                connector_id="priva-signalr",
                floor=info.get("floor"),   # legacy floor label
                zone=info.get("room"),     # legacy room label
                metadata_={
                    "variableId": vid,
                    "modificationTime": modtime,
                    "state": meta.get("state"),
                    "floor": info.get("floor"),
                },
            ))

        async with async_session_factory() as db:
            db.add_all(rows)
            await db.commit()
        logger.info("Priva flush: stored %d readings", len(rows))


# ── Supervisor ─────────────────────────────────────────────────────────────

async def start_priva_ingestion(force: bool = False) -> None:
    """Entry point: launch the flush loop + auto-reconnecting SignalR session.

    No-op unless settings.priva_enabled (or force=True for the standalone
    worker, scripts/priva_run.py). Wired into the FastAPI lifespan.
    """
    if not settings.priva_enabled and not force:
        return
    if websockets is None:
        logger.error("Priva ingestion enabled but `websockets` not installed")
        return
    if not settings.priva_bff_cookie:
        logger.error("Priva ingestion enabled but PRIVA_BFF_COOKIE is empty")
        return

    building = load_building(settings.priva_building_file)
    var_map = building.get("variables", {})
    site_id = building.get("siteId", "")
    servers = building.get("servers") or {}
    groups = building.get("groups") or []
    group_id = groups[0] if groups else ""
    comfortos_building_id = building.get("comfortosBuildingId", "")

    if not var_map:
        logger.error("Priva building file has no variables: %s", settings.priva_building_file)
        return
    if not (site_id and group_id and servers):
        logger.error("Priva building file missing siteId/groups/servers")
        return
    if not comfortos_building_id:
        logger.error("Priva building file has no comfortosBuildingId — set it to attach readings")
        return

    frames = build_subscribe_frames(var_map, site_id, group_id, servers)
    if not frames:
        logger.error("Priva: no subscribe frames built (no controller serials?)")
        return

    latest: dict[str, dict] = {}
    asyncio.create_task(_flush_loop(
        latest, var_map, comfortos_building_id, settings.priva_flush_minutes,
    ))

    logger.info(
        "Priva ingestion started: %s (%d variables, %d controller(s))",
        building.get("buildingName", "?"), len(var_map), len(frames),
    )
    backoff = 5
    while True:
        try:
            await _run_session(settings.priva_bff_cookie, frames, latest)
            backoff = 5
        except Exception as exc:
            logger.warning(
                "Priva session ended (%s: %s); reconnect in %ds. "
                "If 401/403, the BFF cookie expired -- re-copy __Host-bff.",
                type(exc).__name__, exc, backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
