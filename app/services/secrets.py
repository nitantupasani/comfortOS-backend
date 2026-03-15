"""
Secrets resolution — thin abstraction over environment-based secrets.

Current implementation: reads secrets from environment variables.
Scaling path: swap the backend to HashiCorp Vault, AWS Secrets Manager,
GCP Secret Manager, or Azure Key Vault without changing callers.

Maps to the C4 'Secrets Manager' container in backend.puml.
"""

import os
import logging

logger = logging.getLogger("comfortos.secrets")


def resolve_secret(ref: str) -> str | None:
    """Resolve a secret reference to its plaintext value.

    Convention:
        ref = "env:MY_SECRET_VAR"  → reads os.environ["MY_SECRET_VAR"]
        ref = "value:literal"      → returns "literal" (only for dev/testing)

    In production, add handlers for:
        ref = "vault:secret/data/connector/xyz#api_key"
        ref = "gcp:projects/123/secrets/xyz/versions/latest"
    """
    if not ref:
        return None

    scheme, _, key = ref.partition(":")
    scheme = scheme.lower().strip()

    if scheme == "env":
        value = os.environ.get(key.strip())
        if value is None:
            logger.warning("Secret ref '%s': env var '%s' not set", ref, key.strip())
        return value

    if scheme == "value":
        # Plain literal — acceptable only in development
        return key

    # Future: vault, gcp, aws, azure
    logger.error("Unknown secret scheme '%s' in ref '%s'", scheme, ref)
    return None
