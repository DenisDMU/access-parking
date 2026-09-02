"""Schémas Pydantic des endpoints `/access/*`.

⚠️ Règle stricte (section 6/11 de la spec) : `AccessRequestIn` contient un
champ `plaque`, mais aucun schéma de réponse ne doit jamais exposer la
plaque — seul `vehicule_id` (pseudonymisé) circule au-delà de la requête
entrante.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.value_objects.enums import (
    ResultatAutorisation,
    SourceDetection,
    StatutDemande,
    TypeDemande,
)

PLAQUE_PATTERN = r"^[A-Z]{2}-\d{3}-[A-Z]{2}$"


class AccessRequestIn(BaseModel):
    """Requête entrante. La plaque n'existe que le temps de cette requête —
    elle n'est jamais persistée ni renvoyée telle quelle."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "plaque": "AA-111-AA",
                    "type": 1,
                    "date": "2026-09-02T10:15:00Z",
                    "source": 3,
                    "photoBase64": None,
                }
            ]
        },
    )

    plaque: str = Field(pattern=PLAQUE_PATTERN, description="Plaque française, format AB-123-CD")
    type: TypeDemande = Field(description="1=ENTREE, 2=SORTIE")
    date: datetime
    source: SourceDetection = Field(description="1=CAMERA, 2=BORNE, 3=LPR, 4=APP_MOBILE")
    photo_base64: str | None = Field(default=None, alias="photoBase64")

    @field_validator("date")
    @classmethod
    def _normalize_to_utc(cls, value: datetime) -> datetime:
        """Toute date sans fuseau est considérée comme UTC — évite les
        comparaisons naive/aware plus loin dans le traitement (Pricing)."""

        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class AutorisationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resultat: ResultatAutorisation = Field(description="1=AUTORISE, 2=REFUSE, 3=CONFIRMATION_REQUISE")
    motif: str | None = None
    controle_type_vehicule_ok: bool | None = Field(default=None, alias="controleTypeVehiculeOk")
    controle_pmr_ok: bool | None = Field(default=None, alias="controlePmrOk")
    montant_paiement: float | None = Field(default=None, alias="montantPaiement")


class AccessRequestOut(BaseModel):
    """Réponse de `POST /access/requests` — ne contient jamais la plaque."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "demandeId": "b3a1f7b0-0000-4000-8000-000000000000",
                    "vehiculeId": "v_normal_4roues",
                    "type": 1,
                    "statut": 2,
                    "autorisation": {
                        "resultat": 1,
                        "motif": "Accès autorisé",
                        "controleTypeVehiculeOk": True,
                        "controlePmrOk": None,
                    },
                }
            ]
        },
    )

    demande_id: str = Field(alias="demandeId")
    vehicule_id: str | None = Field(alias="vehiculeId")
    type: TypeDemande
    statut: StatutDemande = Field(description="1=EN_COURS, 2=TRAITEE, 3=REJETEE")
    autorisation: AutorisationOut | None = None


class AccessRequestDetailOut(AccessRequestOut):
    """Réponse de `GET /access/requests/{id}` — ajoute date/source/ai_check."""

    date: datetime
    source: SourceDetection
    ai_check: dict | None = Field(default=None, alias="aiCheck")


class AccessRequestListItemOut(BaseModel):
    """Un élément de `GET /access/requests` (audit)."""

    model_config = ConfigDict(populate_by_name=True)

    demande_id: str = Field(alias="demandeId")
    vehicule_id: str | None = Field(alias="vehiculeId")
    type: TypeDemande
    date: datetime
    source: SourceDetection
    statut: StatutDemande


class PlateKnownOut(BaseModel):
    """Réponse de `GET /access/plates/{plaque}/known`.

    Ne renvoie **jamais** la plaque (section 15, Definition of Done) : elle
    est déjà dans l'URL demandée par le client, l'API n'a pas besoin de
    l'échoïser.
    """

    model_config = ConfigDict(populate_by_name=True)

    known: bool
    vehicule_id: str | None = Field(default=None, alias="vehiculeId")


class EventOut(BaseModel):
    """Un événement publié, tel que renvoyé par `GET /access/events`."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: int = Field(description="1=VEHICULE_ENTRE, 2=VEHICULE_SORTI, 3=ACCES_REFUSE, 4=AUTRE")
    demande_id: str = Field(alias="demandeId")
    payload: dict
    created_at: datetime = Field(alias="createdAt")


class HealthOut(BaseModel):
    status: str = Field(examples=["ok"])
    database: str = Field(examples=["connected"])
    uptime_seconds: int = Field(alias="uptimeSeconds", examples=[1234])

    model_config = ConfigDict(populate_by_name=True)
