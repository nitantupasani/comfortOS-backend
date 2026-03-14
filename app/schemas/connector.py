"""Pydantic schemas for Building Connector CRUD & polling API."""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Auth config sub-schemas (documented, not strictly validated) ──────────

class BearerTokenAuth(BaseModel):
    token: str = Field(..., description="Static bearer token")


class OAuth2ClientCredentialsAuth(BaseModel):
    tokenUrl: str = Field(..., description="OAuth2 token endpoint URL")
    clientId: str
    clientSecret: str
    scope: str = Field("", description="Space-separated scopes")


class MtlsAuth(BaseModel):
    clientCertPem: str = Field(..., description="PEM-encoded client certificate")
    clientKeyPem: str = Field(..., description="PEM-encoded client private key")
    caCertPem: str = Field("", description="Optional CA certificate for server verification")


class ApiKeyAuth(BaseModel):
    headerName: str = Field("X-Api-Key", description="Header name to send the key in")
    apiKey: str


class BasicAuthConfig(BaseModel):
    username: str
    password: str


class HmacAuth(BaseModel):
    secret: str = Field(..., description="HMAC shared secret")
    algorithm: str = Field("sha256", description="sha256 | sha512")
    headerName: str = Field("X-Signature", description="Header to send signature in")


# ── CRUD schemas ──────────────────────────────────────────────────────────

class ConnectorCreate(BaseModel):
    buildingId: str
    name: str
    description: str | None = None
    baseUrl: str = Field(..., description="Full URL to poll")
    httpMethod: str = Field("GET", description="GET or POST")
    requestHeaders: dict | None = None
    requestBody: dict | None = None
    authType: str = Field(
        "bearer_token",
        description="bearer_token | oauth2_client_credentials | mtls | api_key | basic_auth | hmac",
    )
    authConfig: dict = Field(default_factory=dict)
    responseMapping: dict | None = None
    availableMetrics: list[str] | None = Field(
        None,
        description="Metric types this connector provides, e.g. ['temperature','co2','humidity','noise']",
    )
    pollingIntervalMinutes: int = Field(15, ge=1, le=1440)
    isEnabled: bool = True


class ConnectorUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    baseUrl: str | None = None
    httpMethod: str | None = None
    requestHeaders: dict | None = None
    requestBody: dict | None = None
    authType: str | None = None
    authConfig: dict | None = None
    responseMapping: dict | None = None
    availableMetrics: list[str] | None = None
    pollingIntervalMinutes: int | None = Field(None, ge=1, le=1440)
    isEnabled: bool | None = None


class ConnectorResponse(BaseModel):
    id: str
    buildingId: str
    name: str
    description: str | None
    baseUrl: str
    httpMethod: str
    requestHeaders: dict | None
    requestBody: dict | None
    authType: str
    authConfig: dict  # secrets masked
    responseMapping: dict | None
    availableMetrics: list[str] | None
    pollingIntervalMinutes: int
    isEnabled: bool
    lastPolledAt: str | None
    lastStatus: str | None
    lastError: str | None
    consecutiveFailures: int
    totalPolls: int
    totalReadingsIngested: int
    createdAt: str
    updatedAt: str


class ConnectorTestResult(BaseModel):
    success: bool
    statusCode: int | None = None
    readingsFound: int = 0
    sampleData: list | None = None
    error: str | None = None


class PollResult(BaseModel):
    connectorId: str
    success: bool
    readingsIngested: int = 0
    error: str | None = None
