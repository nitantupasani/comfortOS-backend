"""Building-related schemas matching the Flutter Building model."""

from pydantic import BaseModel


class BuildingResponse(BaseModel):
    """Matches Building.fromJson() in the Flutter frontend."""
    id: str
    name: str
    address: str
    tenantId: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    requiresAccessPermission: bool = False
    dailyVoteLimit: int = 10
    metadata: dict | None = None


class AppConfigResponse(BaseModel):
    """Matches AppConfig.fromJson() in the Flutter frontend."""
    schemaVersion: int
    dashboardLayout: dict | None = None
    voteFormSchema: dict | None = None
    fetchedAt: str


class LocationComfortResponse(BaseModel):
    floor: str
    floorLabel: str
    room: str | None = None
    roomLabel: str | None = None
    comfortScore: float
    voteCount: int
    breakdown: dict = {}


class BuildingComfortResponse(BaseModel):
    """Matches BuildingComfortData.fromJson() in the Flutter frontend."""
    buildingId: str
    buildingName: str
    overallScore: float
    totalVotes: int
    computedAt: str
    locations: list[LocationComfortResponse] = []
    sduiConfig: dict | None = None
