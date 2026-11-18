"""Schémas Pydantic des endpoints `/access/*`.

Access ne reçoit jamais la plaque : `AccessRequestIn` porte le code
véhicule attribué par Vehicles (qui a identifié la plaque), et seul
`vehicleId` (pseudonymisé, le `pseudoId` de Vehicles) circule ensuite.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    RequestStatus,
    RequestType,
)

# Borne haute du code véhicule (entier 32 bits signé) : rejette en 422 les
# valeurs absurdes avant tout appel à Vehicles.
MAX_VEHICLE_CODE = 2_147_483_647
# Taille max d'une photo encodée en base64 (~3 Mo de photo une fois décodée).
MAX_PHOTO_BASE64_LENGTH = 4_000_000


class AccessRequestIn(BaseModel):
    """Requête entrante, identifiée par le code véhicule de Vehicles."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "vehicleCode": 1,
                    "type": 1,
                    "date": "2026-09-02T10:15:00Z",
                    "source": 3,
                    "photoBase64": None,
                }
            ]
        },
    )

    vehicle_code: int = Field(
        alias="vehicleCode",
        ge=0,
        le=MAX_VEHICLE_CODE,
        description="Code du véhicule attribué par Vehicles (entier ≥ 0)",
    )
    type: RequestType = Field(description="1=ENTRY, 2=EXIT")
    date: datetime
    source: DetectionSource = Field(description="1=CAMERA, 2=TERMINAL, 3=LPR, 4=MOBILE_APP")
    photo_base64: str | None = Field(
        default=None, alias="photoBase64", max_length=MAX_PHOTO_BASE64_LENGTH
    )

    @field_validator("date")
    @classmethod
    def _normalize_to_utc(cls, value: datetime) -> datetime:
        """Toute date sans fuseau est considérée comme UTC — évite les
        comparaisons naive/aware plus loin dans le traitement (Pricing)."""

        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AuthorizationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    result: AuthorizationResult = Field(
        description="1=AUTHORIZED, 2=REFUSED, 3=CONFIRMATION_REQUIRED"
    )
    reason: str | None = None
    vehicle_type_check_ok: bool | None = Field(default=None, alias="vehicleTypeCheckOk")
    disability_check_ok: bool | None = Field(default=None, alias="disabilityCheckOk")
    payment_amount: float | None = Field(default=None, alias="paymentAmount")


class AccessRequestOut(BaseModel):
    """Réponse de `POST /access/requests`."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "requestId": "b3a1f7b0-0000-4000-8000-000000000000",
                    "vehicleId": "301b7c98-3634-4842-8ff5-baf503c53302",
                    "type": 1,
                    "status": 2,
                    "authorization": {
                        "result": 1,
                        "reason": "Accès autorisé",
                        "vehicleTypeCheckOk": True,
                        "disabilityCheckOk": None,
                    },
                }
            ]
        },
    )

    request_id: str = Field(alias="requestId")
    vehicle_id: str | None = Field(alias="vehicleId")
    type: RequestType
    status: RequestStatus = Field(description="1=IN_PROGRESS, 2=PROCESSED, 3=REJECTED")
    authorization: AuthorizationOut | None = None


class AccessRequestDetailOut(AccessRequestOut):
    """Réponse de `GET /access/requests/{id}` — ajoute date/source/aiCheck."""

    date: datetime
    source: DetectionSource
    ai_check: dict | None = Field(default=None, alias="aiCheck")


class AccessRequestListItemOut(BaseModel):
    """Un élément de `GET /access/requests` (audit), avec sa décision."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    vehicle_id: str | None = Field(alias="vehicleId")
    type: RequestType
    date: datetime
    source: DetectionSource
    status: RequestStatus
    result: AuthorizationResult | None = Field(
        default=None, description="1=AUTHORIZED, 2=REFUSED, 3=CONFIRMATION_REQUIRED"
    )
    reason: str | None = None
    payment_amount: float | None = Field(default=None, alias="paymentAmount")


class PlaceTypeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: int = Field(description="1=TWO_WHEELER, 2=FOUR_WHEELER")
    is_xl: bool = Field(alias="isXl")
    is_electric: bool = Field(alias="isElectric")
    is_handicap: bool = Field(alias="isHandicap")


class PresentVehicleOut(BaseModel):
    """Un véhicule actuellement présent (`GET /access/presences`)."""

    model_config = ConfigDict(populate_by_name=True)

    vehicle_id: str = Field(alias="vehicleId")
    entry_request_id: str | None = Field(default=None, alias="entryRequestId")
    entered_at: datetime | None = Field(default=None, alias="enteredAt")
    place_id: str | None = Field(default=None, alias="placeId")
    place_type: PlaceTypeOut | None = Field(default=None, alias="placeType")
    reservation: bool


class VehicleKnownOut(BaseModel):
    """Réponse de `GET /access/vehicles/{vehicle_code}/known`."""

    model_config = ConfigDict(populate_by_name=True)

    known: bool
    vehicle_id: str | None = Field(default=None, alias="vehicleId")


class EventOut(BaseModel):
    """Un événement publié, tel que renvoyé par `GET /access/events`."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: int = Field(description="1=VEHICLE_ENTERED, 2=VEHICLE_EXITED, 3=ACCESS_REFUSED, 4=OTHER")
    request_id: str = Field(alias="requestId")
    payload: dict
    created_at: datetime = Field(alias="createdAt")


class HealthOut(BaseModel):
    status: str = Field(examples=["ok"])
    database: str = Field(examples=["connected"])
    uptime_seconds: int = Field(alias="uptimeSeconds", examples=[1234])
    version: str = Field(examples=["3.3.0"])
    commit: str = Field(examples=["b742756d0c1e9f4a8b3c2d1e0f9a8b7c6d5e4f3a"])

    model_config = ConfigDict(populate_by_name=True)
