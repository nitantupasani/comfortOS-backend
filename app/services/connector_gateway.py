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

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.connector_registry import ConnectorDefinition, DatasetDefinition


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

    # Step 3: Resolve secrets (placeholder)
    # In production: fetch from Vault / KMS using connector.secret_ref
    auth_headers: dict[str, str] = {}
    if connector.auth_type == "oauth2" and connector.secret_ref:
        # Would fetch OAuth token from Secrets Manager and token endpoint
        pass
    elif connector.auth_type == "hmac" and connector.secret_ref:
        # Would compute HMAC signature
        pass
    # mTLS would be configured at the httpx client level

    # Step 4: Build URL with SSRF defenses
    url = f"{connector.base_url.rstrip('/')}/{dataset.endpoint_path.lstrip('/')}"

    # Basic SSRF defense: reject private IPs
    # (in production: use a dedicated egress proxy with allowlisting)
    if any(prefix in url for prefix in ["localhost", "127.0.0.1", "0.0.0.0", "169.254"]):
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
