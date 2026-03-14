"""
Telemetry Poller — background service that pulls data from registered building connectors.

Runs as an asyncio background task inside the FastAPI lifespan.
Each enabled BuildingConnector is polled at its configured interval.

Security
--------
Supports all auth types: bearer_token, oauth2_client_credentials, mtls,
api_key, basic_auth, hmac.

SSRF protection is applied via the existing connector_gateway._is_ssrf_blocked
helper — private/loopback/reserved addresses are rejected.
"""

import asyncio
import base64
import hashlib
import hmac as hmac_lib
import logging
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import async_session_factory
from ..models.building_connector import BuildingConnector
from ..models.telemetry import TelemetryReading
from ..schemas.connector import ConnectorTestResult
from ..services.connector_gateway import _is_ssrf_blocked

logger = logging.getLogger("comfortos.poller")

# Circuit-breaker: disable connector after this many consecutive failures
_MAX_CONSECUTIVE_FAILURES = 10


# ── Authentication helpers ────────────────────────────────────────────────

# In-memory cache for OAuth2 tokens: connector_id → (token, expires_at)
_oauth2_token_cache: dict[str, tuple[str, float]] = {}


async def _get_oauth2_token(connector: BuildingConnector) -> str:
    """Obtain an OAuth2 access token using the Client Credentials grant.

    Caches tokens in memory until they expire.
    """
    cfg = connector.auth_config
    cache_key = connector.id

    # Check cache
    if cache_key in _oauth2_token_cache:
        token, expires_at = _oauth2_token_cache[cache_key]
        if datetime.now(timezone.utc).timestamp() < expires_at - 30:
            return token

    token_url = cfg.get("tokenUrl", "")
    client_id = cfg.get("clientId", "")
    client_secret = cfg.get("clientSecret", "")
    scope = cfg.get("scope", "")

    if _is_ssrf_blocked(token_url):
        raise ValueError(f"OAuth2 token URL blocked by SSRF protection: {token_url}")

    async with httpx.AsyncClient(timeout=15) as client:
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scope:
            data["scope"] = scope

        resp = await client.post(
            token_url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()

    access_token = body["access_token"]
    expires_in = body.get("expires_in", 3600)
    _oauth2_token_cache[cache_key] = (
        access_token,
        datetime.now(timezone.utc).timestamp() + expires_in,
    )
    return access_token


def _build_hmac_signature(body_bytes: bytes, secret: str, algorithm: str) -> str:
    """Compute HMAC signature of the request body."""
    algo = hashlib.sha256 if algorithm == "sha256" else hashlib.sha512
    return hmac_lib.new(secret.encode(), body_bytes, algo).hexdigest()


async def _build_httpx_client(connector: BuildingConnector) -> httpx.AsyncClient:
    """Build an httpx client with the appropriate auth configuration."""
    auth_type = connector.auth_type
    cfg = connector.auth_config or {}
    kwargs: dict = {"timeout": settings.connector_gateway_timeout_seconds}

    if auth_type == "mtls":
        # Write PEM certs to temp files for httpx SSL context
        cert_pem = cfg.get("clientCertPem", "")
        key_pem = cfg.get("clientKeyPem", "")
        ca_pem = cfg.get("caCertPem", "")

        cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        cert_file.write(cert_pem.encode())
        cert_file.flush()

        key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        key_file.write(key_pem.encode())
        key_file.flush()

        ssl_context = ssl.create_default_context()
        if ca_pem:
            ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            ca_file.write(ca_pem.encode())
            ca_file.flush()
            ssl_context.load_verify_locations(ca_file.name)

        ssl_context.load_cert_chain(cert_file.name, key_file.name)
        kwargs["verify"] = ssl_context

    return httpx.AsyncClient(**kwargs)


async def _build_request_headers(connector: BuildingConnector) -> dict[str, str]:
    """Build the full set of request headers including authentication."""
    headers: dict[str, str] = {"Accept": "application/json"}

    # Add custom static headers
    if connector.request_headers:
        headers.update(connector.request_headers)

    auth_type = connector.auth_type
    cfg = connector.auth_config or {}

    if auth_type == "bearer_token":
        headers["Authorization"] = f"Bearer {cfg.get('token', '')}"

    elif auth_type == "oauth2_client_credentials":
        token = await _get_oauth2_token(connector)
        headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "api_key":
        header_name = cfg.get("headerName", "X-Api-Key")
        headers[header_name] = cfg.get("apiKey", "")

    elif auth_type == "basic_auth":
        username = cfg.get("username", "")
        password = cfg.get("password", "")
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    elif auth_type == "hmac":
        # HMAC signature is computed over the request body when sending
        pass  # handled in _make_poll_request

    # mTLS is handled at the transport level, not headers

    return headers


# ── Response parsing ──────────────────────────────────────────────────────

def _resolve_dot_path(data: dict, path: str):
    """Resolve a dot-notation path like 'data.sensors' in a nested dict."""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


def _parse_response(
    data: dict | list,
    connector: BuildingConnector,
) -> list[dict]:
    """Extract telemetry readings from the API response.

    If no response_mapping is set, expects the ComfortOS standard format:
    { "readings": [ { "metricType": ..., "value": ..., ... } ] }

    With response_mapping, transforms custom formats into readings.
    """
    mapping = connector.response_mapping

    if mapping is None:
        # Standard format
        if isinstance(data, dict):
            readings_raw = data.get("readings", [])
        elif isinstance(data, list):
            readings_raw = data
        else:
            return []

        readings = []
        for r in readings_raw:
            if not isinstance(r, dict):
                continue
            if "metricType" not in r or "value" not in r:
                continue
            readings.append({
                "metricType": str(r["metricType"]),
                "value": float(r["value"]),
                "unit": str(r.get("unit", "")),
                "floor": r.get("floor"),
                "zone": r.get("zone"),
                "recordedAt": r.get("recordedAt", datetime.now(timezone.utc).isoformat()),
                "metadata": r.get("metadata"),
            })
        return readings

    # Custom mapping
    readings_path = mapping.get("readingsPath", "readings")
    field_map = mapping.get("fields", {})

    readings_raw = _resolve_dot_path(data, readings_path) if isinstance(data, dict) else data
    if not isinstance(readings_raw, list):
        return []

    mt_field = field_map.get("metricType", "metricType")
    val_field = field_map.get("value", "value")
    unit_field = field_map.get("unit", "unit")
    floor_field = field_map.get("floor", "floor")
    zone_field = field_map.get("zone", "zone")
    ts_field = field_map.get("recordedAt", "recordedAt")

    readings = []
    for r in readings_raw:
        if not isinstance(r, dict):
            continue
        mt_val = _resolve_dot_path(r, mt_field) if "." in mt_field else r.get(mt_field)
        v_val = _resolve_dot_path(r, val_field) if "." in val_field else r.get(val_field)
        if mt_val is None or v_val is None:
            continue
        try:
            v_val = float(v_val)
        except (ValueError, TypeError):
            continue

        readings.append({
            "metricType": str(mt_val),
            "value": v_val,
            "unit": str(
                (_resolve_dot_path(r, unit_field) if "." in unit_field else r.get(unit_field)) or ""
            ),
            "floor": _resolve_dot_path(r, floor_field) if "." in floor_field else r.get(floor_field),
            "zone": _resolve_dot_path(r, zone_field) if "." in zone_field else r.get(zone_field),
            "recordedAt": str(
                (_resolve_dot_path(r, ts_field) if "." in ts_field else r.get(ts_field))
                or datetime.now(timezone.utc).isoformat()
            ),
            "metadata": {
                k: r.get(k)
                for k in (mapping.get("metadataFields") or [])
                if r.get(k) is not None
            } or None,
        })

    return readings


# ── Polling core ──────────────────────────────────────────────────────────

async def poll_single_connector(
    connector: BuildingConnector,
    db: AsyncSession,
    *,
    dry_run: bool = False,
) -> ConnectorTestResult:
    """Execute a single poll of a building connector.

    If dry_run=True, data is fetched and parsed but NOT stored in DB.
    Returns a ConnectorTestResult with sample data for testing.
    """
    url = connector.base_url

    # SSRF protection
    if _is_ssrf_blocked(url):
        return ConnectorTestResult(
            success=False,
            error=f"URL blocked by SSRF protection: {url}",
        )

    try:
        headers = await _build_request_headers(connector)
        client = await _build_httpx_client(connector)

        async with client:
            body_bytes = b""
            if connector.http_method == "POST" and connector.request_body:
                import json
                body_bytes = json.dumps(connector.request_body).encode()
                headers["Content-Type"] = "application/json"

            # HMAC signature (computed over body)
            if connector.auth_type == "hmac":
                cfg = connector.auth_config or {}
                sig = _build_hmac_signature(
                    body_bytes,
                    cfg.get("secret", ""),
                    cfg.get("algorithm", "sha256"),
                )
                headers[cfg.get("headerName", "X-Signature")] = sig

            if connector.http_method == "POST":
                response = await client.post(url, content=body_bytes, headers=headers)
            else:
                params = {}
                if connector.available_metrics:
                    params["metrics"] = ",".join(connector.available_metrics)
                response = await client.get(url, headers=headers, params=params)

            response.raise_for_status()
            resp_data = response.json()

        # Parse response
        readings = _parse_response(resp_data, connector)

        # Filter to declared metric types (if configured)
        if connector.available_metrics:
            allowed = set(connector.available_metrics)
            readings = [r for r in readings if r["metricType"] in allowed]

        if dry_run:
            return ConnectorTestResult(
                success=True,
                statusCode=response.status_code,
                readingsFound=len(readings),
                sampleData=readings[:5],
            )

        # Store readings
        rows = []
        for r in readings:
            ts = r["recordedAt"]
            if isinstance(ts, str):
                try:
                    recorded_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    recorded_at = datetime.now(timezone.utc)
            else:
                recorded_at = datetime.now(timezone.utc)

            rows.append(TelemetryReading(
                building_id=connector.building_id,
                metric_type=r["metricType"],
                value=r["value"],
                unit=r.get("unit", ""),
                floor=r.get("floor"),
                zone=r.get("zone"),
                recorded_at=recorded_at,
                metadata_=r.get("metadata"),
            ))

        if rows:
            db.add_all(rows)

        # Update connector status
        connector.last_polled_at = datetime.now(timezone.utc)
        connector.last_status = "success"
        connector.last_error = None
        connector.consecutive_failures = 0
        connector.total_polls += 1
        connector.total_readings_ingested += len(rows)

        await db.commit()

        return ConnectorTestResult(
            success=True,
            statusCode=response.status_code,
            readingsFound=len(rows),
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.warning("Poll failed for connector %s: %s", connector.id, error_msg)

        if not dry_run:
            connector.last_polled_at = datetime.now(timezone.utc)
            connector.last_status = "error"
            connector.last_error = error_msg[:500]
            connector.consecutive_failures += 1
            connector.total_polls += 1

            # Circuit breaker: auto-disable after too many failures
            if connector.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                connector.is_enabled = False
                logger.error(
                    "Connector %s disabled after %d consecutive failures",
                    connector.id, _MAX_CONSECUTIVE_FAILURES,
                )

            await db.commit()

        return ConnectorTestResult(
            success=False,
            error=error_msg[:500],
        )


# ── Background polling loop ──────────────────────────────────────────────

async def _poll_due_connectors():
    """Poll all connectors that are due (based on their interval and last poll)."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(BuildingConnector).where(
                BuildingConnector.is_enabled == True,  # noqa: E712
            )
        )
        connectors = result.scalars().all()

        now = datetime.now(timezone.utc)
        for connector in connectors:
            # Check if this connector is due for polling
            if connector.last_polled_at is not None:
                elapsed_minutes = (now - connector.last_polled_at).total_seconds() / 60
                if elapsed_minutes < connector.polling_interval_minutes:
                    continue

            logger.info("Polling connector: %s (%s)", connector.name, connector.id)
            await poll_single_connector(connector, db, dry_run=False)


async def start_polling_loop():
    """Background asyncio task: checks for due connectors every 60 seconds."""
    logger.info("Telemetry poller started")
    while True:
        try:
            await _poll_due_connectors()
        except Exception:
            logger.exception("Error in polling loop")
        await asyncio.sleep(60)  # Check every minute for due connectors
