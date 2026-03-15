"""
Connector Gateway service — secure egress to external building data services.

Maps to the C4 'Connector Gateway' container in backend.puml.

Flow:
  Platform API → Connector Gateway (internal request with datasetKey + params)
  Connector Gateway → Registry DB (resolve connector + dataset definitions)
  Connector Gateway → Secrets Manager (fetch secrets by reference)
  Connector Gateway → External Building Data Service (HTTPS mTLS/OAuth/HMAC)
  Connector Gateway → Telemetry Store (cache/normalize results — optional)
"""

import ipaddress
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.connector_registry import ConnectorDefinition, DatasetDefinition
from .secrets import resolve_secret


def _is_ssrf_blocked(url: str) -> bool:
    """Return True if the URL resolves to a private/reserved/loopback address.

    Blocks direct IP literals (all RFC1918 + loopback + link-local + reserved)
    and known-dangerous hostnames.  DNS-resolved hostnames bypass this check;
    a dedicated allowlisted egress proxy is the recommended production complement.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return True  # malformed URL — block it

    if not host:
        return True

    # Try to parse the host as a bare IP address (catches all RFC1918 / loopback /
    # link-local / reserved / multicast ranges via the stdlib)
    try:
        addr = ipaddress.ip_address(host)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        )
    except ValueError:
        pass  # not a bare IP literal — check hostname patterns

    # Block well-known internal hostnames and TLDs
    blocked_exact = {"localhost", "metadata.google.internal", "instance-data"}
    if host in blocked_exact:
        return True
    if host.endswith(".internal") or host.endswith(".local"):
        return True

    return False


async def read_dataset(
    db: AsyncSession,
    building_id: str,
    dataset_key: str,
    params: dict | None = None,
) -> dict | None:
    """Resolve a dataset definition, fetch from the external service, and return
    normalised data.

    This is the core Connector Gateway logic:
    1. Look up DatasetDefinition by dataset_key in the Registry DB.
    2. Look up the associated ConnectorDefinition.
    3. Resolve secrets (placeholder — in production, fetch from Secrets Manager).
    4. Make an outbound HTTPS request to the external service.
    5. Apply response_mapping to normalise the result.
    6. Optionally cache in the Telemetry Store.
    """
    # Step 1: Resolve dataset
    ds_result = await db.execute(
        select(DatasetDefinition).where(
            DatasetDefinition.dataset_key == dataset_key,
            DatasetDefinition.is_approved == True,
        )
    )
    dataset = ds_result.scalar_one_or_none()
    if dataset is None:
        return None

    # Step 2: Resolve connector
    conn_result = await db.execute(
        select(ConnectorDefinition).where(
            ConnectorDefinition.id == dataset.connector_id,
            ConnectorDefinition.is_approved == True,
        )
    )
    connector = conn_result.scalar_one_or_none()
    if connector is None:
        return None

    # Step 3: Resolve secrets via Secrets Manager abstraction
    auth_headers: dict[str, str] = {}
    if connector.secret_ref:
        secret_value = resolve_secret(connector.secret_ref)
        if connector.auth_type == "bearer" and secret_value:
            auth_headers["Authorization"] = f"Bearer {secret_value}"
        elif connector.auth_type == "api_key" and secret_value:
            auth_headers["X-Api-Key"] = secret_value
        elif connector.auth_type == "oauth2" and secret_value:
            # secret_value = client_secret; full OAuth token exchange
            # would go here in production (token endpoint + caching)
            auth_headers["Authorization"] = f"Bearer {secret_value}"
        elif connector.auth_type == "hmac":
            # HMAC signing would use secret_value to compute signature
            pass
        # mTLS is configured at the httpx client level (cert= kwarg)

    # Step 4: Build URL with SSRF defenses
    url = f"{connector.base_url.rstrip('/')}/{dataset.endpoint_path.lstrip('/')}"

    # SSRF defense: reject private/loopback/reserved addresses
    # (in production: also use a dedicated egress proxy with allowlisting)
    if _is_ssrf_blocked(url):
        return None

    # Substitute template parameters
    if params:
        for key, value in params.items():
            url = url.replace(f"{{{key}}}", str(value))
    url = url.replace("{buildingId}", building_id)

    try:
        async with httpx.AsyncClient(
            timeout=settings.connector_gateway_timeout_seconds
        ) as client:
            response = await client.get(url, headers=auth_headers)
            response.raise_for_status()
            data = response.json()

            # Step 5: Apply response mapping
            if dataset.response_mapping:
                mapped = {}
                for target_key, source_path in dataset.response_mapping.items():
                    # Simple dot-notation path resolution
                    value = data
                    for part in str(source_path).split("."):
                        if isinstance(value, dict):
                            value = value.get(part)
                        else:
                            value = None
                            break
                    mapped[target_key] = value
                return mapped

            return data
    except Exception:
        return None
