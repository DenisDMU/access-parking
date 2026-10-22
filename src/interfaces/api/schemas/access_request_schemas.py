"""Schémas Pydantic des endpoints `/access/*`.

⚠️ Règle stricte (section 6/11 de la spec) : `AccessRequestIn` contient un
champ `plate`, mais aucun schéma de réponse ne doit jamais exposer la
plaque — seul `vehicleId` (pseudonymisé) circule au-delà de la requête
entrante.
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

PLATE_PATTERN = r"^[A-Z]{2}-\d{3}-[A-Z]{2}$"


class AccessRequestIn(BaseModel):
    """Requête entrante. La plaque n'existe que le temps de cette requête —
    elle n'est jamais persistée ni renvoyée telle quelle."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "plate": "AA-111-AA",
                    "type": 1,
                    "date": "2026-09-02T10:15:00Z",
                    "source": 3,
                    "photoBase64": None,
                }
            ]
        },
    )

    plate: str = Field(pattern=PLATE_PATTERN, description="Plaque française, format AB-123-CD")
    type: RequestType = Field(description="1=ENTRY, 2=EXIT")
    date: datetime
    source: DetectionSource = Field(description="1=CAMERA, 2=TERMINAL, 3=LPR, 4=MOBILE_APP")
    photo_base64: str | None = Field(default=None, alias="photoBase64")

    @field_validator("date")
    @classmethod
    def _normalize_to_utc(cls, value: datetime) -> datetime:
        """Toute date sans fuseau est considérée comme UTC — évite les
        comparaisons naive/aware plus loin dans le traitement (Pricing)."""

        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AuthorizationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    result: AuthorizationResult = Field(description="1=AUTHORIZED, 2=REFUSED, 3=CONFIRMATION_REQUIRED")
    reason: str | None = None
    vehicle_type_check_ok: bool | None = Field(default=None, alias="vehicleTypeCheckOk")
    disability_check_ok: bool | None = Field(default=None, alias="disabilityCheckOk")
    payment_amount: float | None = Field(default=None, alias="paymentAmount")


class AccessRequestOut(BaseModel):
    """Réponse de `POST /access/requests` — ne contient jamais la plaque."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "requestId": "b3a1f7b0-0000-4000-8000-000000000000",
                    "vehicleId": "v_standard_4wheeler",
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
    """Un élément de `GET /access/requests` (audit)."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    vehicle_id: str | None = Field(alias="vehicleId")
    type: RequestType
    date: datetime
    source: DetectionSource
    status: RequestStatus


class PlateKnownOut(BaseModel):
    """Réponse de `GET /access/plates/{plate}/known`.

    Ne renvoie **jamais** la plaque (section 15, Definition of Done) : elle
    est déjà dans l'URL demandée par le client, l'API n'a pas besoin de
    l'échoïser.
    """

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

    model_config = ConfigDict(populate_by_name=True)
