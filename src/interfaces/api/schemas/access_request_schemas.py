"""Schémas Pydantic des endpoints `/access/*`.

⚠️ RGPD : `AccessRequestIn` et `VehicleKnownIn` reçoivent la plaque lue par
la borne, transmise telle quelle à Vehicles. Aucun schéma de réponse ne
l'expose : seul `vehicleId` (pseudonymisé, le `pseudoId` de Vehicles)
circule au-delà de la requête entrante.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    RequestStatus,
    RequestType,
)

# Plaque française (SIV). Acceptée en minuscules, avec espaces ou sans
# séparateur, puis normalisée en `AB-123-CD` : Vehicles reçoit toujours la
# même forme pour un même véhicule.
_PLATE_INPUT = re.compile(r"^([A-Z]{2})[\s-]?(\d{3})[\s-]?([A-Z]{2})$")
PLATE_FORMAT_ERROR = "Plaque attendue au format AB-123-CD"


def normalize_plate(value: str) -> str:
    """`ab 123 cd` → `AB-123-CD`. Le message d'erreur ne reprend jamais la
    valeur reçue."""

    match = _PLATE_INPUT.match(value.strip().upper())
    if match is None:
        raise ValueError(PLATE_FORMAT_ERROR)
    return "-".join(match.groups())


# Taille max d'une photo encodée en base64 (~3 Mo de photo une fois décodée).
MAX_PHOTO_BASE64_LENGTH = 4_000_000


class AccessRequestIn(BaseModel):
    """Requête entrante. La plaque n'existe que le temps de cette requête :
    elle n'est jamais persistée, publiée, loggée ni renvoyée."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "licensePlate": "AB-123-CD",
                    "type": 1,
                    "date": "2026-09-02T10:15:00Z",
                    "source": 3,
                    "photoBase64": None,
                }
            ]
        },
    )

    license_plate: str = Field(
        alias="licensePlate",
        max_length=20,
        description="Plaque lue par la borne, format AB-123-CD (transmise à Vehicles uniquement)",
    )
    type: RequestType = Field(description="1=ENTRY, 2=EXIT")
    date: datetime
    source: DetectionSource = Field(description="1=CAMERA, 2=TERMINAL, 3=LPR, 4=MOBILE_APP")
    photo_base64: str | None = Field(
        default=None, alias="photoBase64", max_length=MAX_PHOTO_BASE64_LENGTH
    )

    @field_validator("license_plate")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_plate(value)

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


class PlaceTypeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: int = Field(description="1=TWO_WHEELER, 2=FOUR_WHEELER")
    is_xl: bool = Field(alias="isXl")
    is_electric: bool = Field(alias="isElectric")
    is_handicap: bool = Field(alias="isHandicap")


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
    # Champs ajoutés en 4.1.0 (borne client), renseignés seulement quand le
    # passage est autorisé ; absents (null) sinon. Aucun champ existant modifié.
    place_type: PlaceTypeOut | None = Field(
        default=None, alias="placeType", description="Entrée : type de la place attribuée"
    )
    reservation: bool | None = Field(
        default=None, description="Entrée : une réservation a été reconnue"
    )
    entered_at: datetime | None = Field(
        default=None, alias="enteredAt", description="Sortie : heure d'entrée (UTC)"
    )
    duration_minutes: int | None = Field(
        default=None,
        alias="durationMinutes",
        description="Sortie : durée de stationnement (minutes entamées)",
    )


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


class PresentVehicleOut(BaseModel):
    """Un véhicule actuellement présent (`GET /access/presences`)."""

    model_config = ConfigDict(populate_by_name=True)

    vehicle_id: str = Field(alias="vehicleId")
    entry_request_id: str | None = Field(default=None, alias="entryRequestId")
    entered_at: datetime | None = Field(default=None, alias="enteredAt")
    place_id: str | None = Field(default=None, alias="placeId")
    place_type: PlaceTypeOut | None = Field(default=None, alias="placeType")
    reservation: bool


class VehicleKnownIn(BaseModel):
    """Corps de `POST /access/vehicles/known` : la plaque voyage dans le corps
    et non dans l'URL, qui finit dans les journaux des proxys et de Render."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"licensePlate": "AB-123-CD"}]},
    )

    license_plate: str = Field(alias="licensePlate", max_length=20)

    @field_validator("license_plate")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_plate(value)


class VehicleKnownOut(BaseModel):
    """Réponse de `POST /access/vehicles/known` — ne renvoie jamais la plaque."""

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
    database_engine: str = Field(
        alias="databaseEngine",
        examples=["postgresql"],
        description="Moteur de base utilisé (sqlite ou postgresql) — jamais l'URL",
    )
    uptime_seconds: int = Field(alias="uptimeSeconds", examples=[1234])
    version: str = Field(examples=["4.1.0"])
    commit: str = Field(examples=["b742756d0c1e9f4a8b3c2d1e0f9a8b7c6d5e4f3a"])

    model_config = ConfigDict(populate_by_name=True)
