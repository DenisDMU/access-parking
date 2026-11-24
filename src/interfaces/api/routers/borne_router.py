"""Borne publique — `/borne/status` et `/borne/passages`, sans clé.

Le lien de la borne client (`/borne`) doit marcher pour n'importe qui, sans
réglage. Une page web publique ne peut pas cacher de clé : cette route
publique est donc réduite au strict nécessaire, et tout le reste de l'API
garde sa clé.

- Une seule action : faire entrer ou sortir un véhicule (mêmes use cases,
  mêmes règles métier que `POST /access/requests`).
- Date imposée par le serveur (impossible d'antidater une entrée pour payer
  moins) et source forcée à TERMINAL ; pas de photo.
- Débit limité par adresse (`RATE_LIMIT_BORNE`, 10/minute par défaut).
- Réponse réduite à ce qu'affiche la borne : ni identifiant de demande, ni
  identifiant pseudonymisé du véhicule (pas de lien plaque → pseudoId).
- Interrupteur `BORNE_PUBLIC` (activé par défaut) : à `false`, 403 et la
  borne exige sa clé (`BORNE_API_KEY`).

⚠️ La plaque reçue n'est ni loggée ni renvoyée (même discipline RGPD que
`access_router`).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.value_objects.enums import DetectionSource, RequestType
from src.infrastructure.config import get_settings
from src.infrastructure.metrics import record_decision
from src.interfaces.api import deps
from src.interfaces.api.rate_limit import client_ip, limiter
from src.interfaces.api.routers.access_router import _place_type_out
from src.interfaces.api.schemas.access_request_schemas import (
    BornePassageIn,
    BornePassageOut,
    BorneStatusOut,
)
from src.interfaces.api.schemas.error_schemas import ErrorOut
from src.interfaces.api.vehicle_types import declared_vehicle_type

router = APIRouter(prefix="/borne", tags=["Borne publique"])


@router.get(
    "/status",
    response_model=BorneStatusOut,
    summary="La borne publique est-elle ouverte ?",
    description="Lu par la page `/borne` au démarrage. Sans clé.",
)
def borne_status() -> BorneStatusOut:
    return BorneStatusOut(publicAccess=get_settings().borne_public)


@router.post(
    "/passages",
    response_model=BornePassageOut,
    summary="Passage d'un véhicule à la borne publique (sans clé)",
    description=(
        "Entrée ou sortie d'un véhicule depuis la borne client, sans clé. "
        "Date imposée par le serveur, source TERMINAL, débit limité par "
        "adresse. Réponse réduite à ce qu'affiche la borne. 403 si la borne "
        "publique est désactivée (`BORNE_PUBLIC=false`)."
    ),
    responses={
        403: {"model": ErrorOut, "description": "Borne publique désactivée"},
        422: {"model": ErrorOut, "description": "Plaque ou type invalide"},
        429: {"description": "Trop de passages depuis cette adresse"},
    },
)
@limiter.limit(lambda: get_settings().rate_limit_borne, key_func=client_ip)
def borne_passage(
    request: Request,
    body: BornePassageIn,
    entry_use_case: ProcessEntryRequest = Depends(deps.get_process_entry_request_use_case),
    exit_use_case: ProcessExitRequest = Depends(deps.get_process_exit_request_use_case),
) -> BornePassageOut:
    if not get_settings().borne_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Borne publique désactivée : configurez la borne avec sa clé",
        )
    now = datetime.now(UTC)
    if body.type == RequestType.ENTRY:
        decision = entry_use_case.execute(
            plate=body.license_plate,
            date=now,
            source=DetectionSource.TERMINAL,
            declared_type=declared_vehicle_type(body.vehicle_type),
        )
        record_decision(decision.type, decision.result, decision.reason)
        return BornePassageOut(
            result=decision.result,
            reason=decision.reason,
            vehicleIdentified=decision.vehicle_id is not None,
            placeType=_place_type_out(decision.place_type),
            placeLabel=decision.place_label,
            reservation=decision.reservation,
        )

    decision = exit_use_case.execute(
        plate=body.license_plate, date=now, source=DetectionSource.TERMINAL
    )
    record_decision(decision.type, decision.result, decision.reason)
    return BornePassageOut(
        result=decision.result,
        reason=decision.reason,
        vehicleIdentified=decision.vehicle_id is not None,
        paymentAmount=(
            float(decision.payment_amount) if decision.payment_amount is not None else None
        ),
        enteredAt=decision.entered_at,
        durationMinutes=decision.duration_minutes,
        reservation=decision.reservation,
    )
