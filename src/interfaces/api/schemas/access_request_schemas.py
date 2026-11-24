"""Schémas Pydantic des endpoints `/access/*`.

⚠️ RGPD : `AccessRequestIn` et `VehicleKnownIn` reçoivent la plaque lue par
la borne, transmise telle quelle à Vehicles. Aucun schéma de réponse ne
l'expose : seul `vehicleId` (pseudonymisé, le `pseudoId` de Vehicles)
circule au-delà de la requête entrante.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    RequestStatus,
    RequestType,
)
from src.interfaces.api.plates import CountryCode, plate_identity

# Plaques de tous pays et de tous formats (SIV, ancien FNI, étrangères).
# Les séparateurs (espaces, tirets, points) sont retirés pour qu'une même
# plaque donne toujours la même forme chez Vehicles, quelle que soit la façon
# de la saisir. Seule exception : la plaque française SIV garde sa forme
# `AB-123-CD` (celle déjà enregistrée chez Vehicles depuis la 4.0.0).
_SEPARATORS = re.compile(r"[\s.\-]+")
_SIV = re.compile(r"^([A-Z]{2})(\d{3})([A-Z]{2})$")
_ANY_PLATE = re.compile(r"^[A-Z0-9]{2,10}$")
# Type de véhicule choisi par le conducteur à la borne (entrée) : mêmes
# codes que Parking et Booking. Sert à créer un véhicule inconnu avec les
# bonnes caractéristiques ; pour un véhicule connu, Vehicles fait foi.
VehicleTypeCode = Literal["STANDARD", "ELECTRIC", "XL", "HANDICAPPED", "TWO_WHEELS"]
VEHICLE_TYPE_DESCRIPTION = (
    "Entrée seulement, facultatif : type choisi à la borne (STANDARD, ELECTRIC, XL, "
    "HANDICAPPED, TWO_WHEELS). Crée un véhicule inconnu avec ces caractéristiques ; "
    "pour un véhicule connu, Vehicles fait foi. HANDICAPPED sur un véhicule que "
    "Vehicles ne connaît pas comme PMR : place PMR, justificatif vérifié par un agent."
)
COUNTRY_DESCRIPTION = (
    "Pays de la plaque, code ISO (FR, IT, ES, DE, BE, CH, GB, NL, LU, PT, XX = autre). "
    "Vérifie le format national et distingue des plaques identiques de pays "
    "différents (une plaque italienne n'est jamais confondue avec une française). "
    "Absent : comportement d'avant 4.8.0 (plaque traitée comme française)."
)
PLATE_FORMAT_ERROR = "Plaque attendue : 2 à 10 lettres (A-Z) ou chiffres, séparateurs acceptés"


def normalize_plate(value: str) -> str:
    """`ab 123 cd` → `AB-123-CD` ; `b-mw 1234` → `BMW1234` ; `123 abc 75` →
    `123ABC75`. Le message d'erreur ne reprend jamais la valeur reçue."""

    compact = _SEPARATORS.sub("", value.strip().upper())
    siv = _SIV.match(compact)
    if siv:
        return "-".join(siv.groups())
    if _ANY_PLATE.match(compact):
        return compact
    raise ValueError(PLATE_FORMAT_ERROR)


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
        description=(
            "Plaque lue par la borne, française ou étrangère : 2 à 10 lettres ou "
            "chiffres, séparateurs acceptés (transmise à Vehicles uniquement)"
        ),
    )
    type: RequestType = Field(description="1=ENTRY, 2=EXIT")
    date: datetime
    source: DetectionSource = Field(description="1=CAMERA, 2=TERMINAL, 3=LPR, 4=MOBILE_APP")
    vehicle_type: VehicleTypeCode | None = Field(
        default=None, alias="vehicleType", description=VEHICLE_TYPE_DESCRIPTION
    )
    photo_base64: str | None = Field(
        default=None, alias="photoBase64", max_length=MAX_PHOTO_BASE64_LENGTH
    )

    country: CountryCode | None = Field(default=None, description=COUNTRY_DESCRIPTION)

    @field_validator("license_plate")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_plate(value)

    @model_validator(mode="after")
    def _apply_country(self):
        self.license_plate = plate_identity(self.license_plate, self.country)
        return self

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
    place_label: str | None = Field(
        default=None,
        alias="placeLabel",
        description="Entrée : libellé de la catégorie fourni par Parking (4.2.0)",
    )
    reservation: bool | None = Field(
        default=None,
        description=(
            "Entrée : une réservation Booking a été reconnue. Sortie : le "
            "stationnement relevait d'une réservation (créneau déjà payé)"
        ),
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


class ParkingCategoryOut(BaseModel):
    """Une catégorie de places vue par Parking."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(description="Nom technique chez Parking (ex. ELECTRIC)")
    label: str = Field(description="Libellé fourni par Parking")
    used_by_access: bool = Field(alias="usedByAccess")
    spot_taken: int | None = Field(default=None, alias="spotTaken")
    spot_held: int | None = Field(
        default=None, alias="spotHeld", description="Places mises de côté (hold de 30 s)"
    )
    total_capacity: int | None = Field(default=None, alias="totalCapacity")
    occupation_rate: float | None = Field(default=None, alias="occupationRate")


class ParkingOverviewOut(BaseModel):
    """Réponse de `GET /access/parking`."""

    model_config = ConfigDict(populate_by_name=True)

    available: bool = Field(description="false si Parking n'a pas répondu")
    categories: list[ParkingCategoryOut]
    missing_categories: list[str] = Field(
        alias="missingCategories",
        description="Catégories dont Access a besoin mais que Parking ne déclare pas",
    )


class BorneKeyOut(BaseModel):
    """Réponse de `GET /access/borne/key` (exploitation uniquement)."""

    model_config = ConfigDict(populate_by_name=True)

    borne_key: str = Field(alias="borneKey", description="Valeur de BORNE_API_KEY")


class BornePassageIn(BaseModel):
    """Corps de `POST /borne/passages` : la plaque et le sens, rien d'autre
    (date et source sont imposées par le serveur)."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [{"licensePlate": "AB-123-CD", "type": 1, "vehicleType": "ELECTRIC"}]
        },
    )

    license_plate: str = Field(alias="licensePlate", max_length=20)
    type: RequestType = Field(description="1=ENTRY, 2=EXIT")
    vehicle_type: VehicleTypeCode | None = Field(
        default=None, alias="vehicleType", description=VEHICLE_TYPE_DESCRIPTION
    )

    country: CountryCode | None = Field(default=None, description=COUNTRY_DESCRIPTION)

    @field_validator("license_plate")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_plate(value)

    @model_validator(mode="after")
    def _apply_country(self):
        self.license_plate = plate_identity(self.license_plate, self.country)
        return self


class BornePmrValidationIn(BaseModel):
    """Corps de `POST /borne/pmr-validation` : la plaque (et son pays), et le
    code saisi par l'agent après vérification de la carte mobilité inclusion."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [{"licensePlate": "AB-123-CD", "country": "FR", "agentCode": "123"}]
        },
    )

    license_plate: str = Field(alias="licensePlate", max_length=20)
    country: CountryCode | None = Field(default=None, description=COUNTRY_DESCRIPTION)
    agent_code: str = Field(alias="agentCode", min_length=1, max_length=32)

    @field_validator("license_plate")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_plate(value)

    @model_validator(mode="after")
    def _apply_country(self):
        self.license_plate = plate_identity(self.license_plate, self.country)
        return self


class BornePassageOut(BaseModel):
    """Réponse de `POST /borne/passages` : ce qu'affiche la borne, sans
    identifiant de demande ni identifiant du véhicule."""

    model_config = ConfigDict(populate_by_name=True)

    result: AuthorizationResult = Field(
        description="1=AUTHORIZED, 2=REFUSED, 3=CONFIRMATION_REQUIRED"
    )
    reason: str | None = None
    vehicle_identified: bool = Field(alias="vehicleIdentified")
    place_type: PlaceTypeOut | None = Field(default=None, alias="placeType")
    place_label: str | None = Field(default=None, alias="placeLabel")
    reservation: bool | None = None
    payment_amount: float | None = Field(default=None, alias="paymentAmount")
    entered_at: datetime | None = Field(default=None, alias="enteredAt")
    duration_minutes: int | None = Field(default=None, alias="durationMinutes")


class BorneParkingCategoryOut(BaseModel):
    """Occupation d'une catégorie, telle que la montre le plan 3D de la borne."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(description="Nom technique chez Parking (ex. ELECTRIC)")
    label: str = Field(description="Libellé fourni par Parking")
    total_capacity: int = Field(alias="totalCapacity")
    spot_taken: int = Field(alias="spotTaken")
    spot_held: int = Field(alias="spotHeld", description="Places mises de côté (hold de 30 s)")


class BorneParkingOut(BaseModel):
    """Réponse de `GET /borne/parking` : des compteurs par catégorie, rien
    d'autre (aucun véhicule, aucun identifiant, aucune demande)."""

    model_config = ConfigDict(populate_by_name=True)

    available: bool = Field(description="false si Parking n'a pas répondu")
    categories: list[BorneParkingCategoryOut]


class BorneStatusOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    public_access: bool = Field(alias="publicAccess")


class VehicleKnownIn(BaseModel):
    """Corps de `POST /access/vehicles/known` : la plaque voyage dans le corps
    et non dans l'URL, qui finit dans les journaux des proxys et de Render."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"licensePlate": "AB-123-CD"}]},
    )

    license_plate: str = Field(alias="licensePlate", max_length=20)

    country: CountryCode | None = Field(default=None, description=COUNTRY_DESCRIPTION)

    @field_validator("license_plate")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_plate(value)

    @model_validator(mode="after")
    def _apply_country(self):
        self.license_plate = plate_identity(self.license_plate, self.country)
        return self


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
    version: str = Field(examples=["4.12.1"])
    commit: str = Field(examples=["b742756d0c1e9f4a8b3c2d1e0f9a8b7c6d5e4f3a"])
    booking: str = Field(
        examples=["réel"],
        description="Service Booking utilisé : « réel » ou « simulé » (jamais l'URL)",
    )

    model_config = ConfigDict(populate_by_name=True)
