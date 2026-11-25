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
- `POST /borne/pmr-validation` : un agent valide sur la borne un conducteur
  PMR que Vehicles ne connaissait pas comme tel (carte vérifiée, code agent
  `AGENT_CODE`). Le justificatif est enregistré chez Vehicles, puis l'entrée
  est rejouée normalement. Même débit limité par adresse.
- `GET /borne/parking` : occupation par catégorie pour le plan 3D affiché
  sur la borne. Des compteurs seulement (capacité, places prises, mises de
  côté) : aucun véhicule, aucun identifiant. Réponse de Parking gardée
  quelques secondes (`BORNE_PARKING_CACHE_S`) : le nombre de visiteurs ne
  change pas le nombre d'appels à Parking.

⚠️ La plaque reçue n'est ni loggée ni renvoyée (même discipline RGPD que
`access_router`).
"""

from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.application.use_cases.confirm_disability_by_agent import (
    ConfirmDisabilityByAgent,
    NoPendingDisabilityCheckError,
)
from src.application.use_cases.get_parking_overview import GetParkingOverview
from src.application.use_cases.list_present_vehicles import ListPresentVehicles
from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.ports.booking_service_port import BookingServicePort
from src.domain.value_objects.enums import DetectionSource, RequestType
from src.infrastructure.config import get_settings
from src.infrastructure.external.place_categories import code_of_place
from src.infrastructure.metrics import record_decision
from src.interfaces.api import deps
from src.interfaces.api.rate_limit import client_ip, limiter
from src.interfaces.api.routers.access_router import _place_type_out
from src.interfaces.api.schemas.access_request_schemas import (
    BorneParkingCategoryOut,
    BorneParkingOut,
    BornePassageIn,
    BornePassageOut,
    BornePmrValidationIn,
    BorneStatusOut,
)
from src.interfaces.api.schemas.error_schemas import ErrorOut
from src.interfaces.api.vehicle_types import declared_vehicle_type

router = APIRouter(prefix="/borne", tags=["Borne publique"])

BORNE_OFF = "Borne publique désactivée : configurez la borne avec sa clé"
BORNE_BUSY = "Borne très sollicitée, réessayez dans un instant"
NO_PENDING_PMR = (
    "Aucune entrée en attente de vérification PMR pour ce véhicule : "
    "refaites l'entrée à la borne en choisissant « Mobilité réduite »"
)

# Passages traités en même temps par la borne publique (`BORNE_MAX_CONCURRENT`).
_slots = threading.BoundedSemaphore(max(1, get_settings().borne_max_concurrent))


@contextmanager
def _borne_slot() -> Iterator[None]:
    """Une place parmi les passages simultanés, sans attendre ; 503 sinon."""

    if not _slots.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=BORNE_BUSY)
    try:
        yield
    finally:
        _slots.release()


WRONG_AGENT_CODE = "Code agent incorrect"


def _require_public_borne() -> None:
    if not get_settings().borne_public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=BORNE_OFF)


def _entry_out(decision) -> BornePassageOut:
    record_decision(decision.type, decision.result, decision.reason)
    return BornePassageOut(
        result=decision.result,
        reason=decision.reason,
        vehicleIdentified=decision.vehicle_id is not None,
        placeType=_place_type_out(decision.place_type),
        placeLabel=decision.place_label,
        reservation=decision.reservation,
    )


@router.get(
    "/status",
    response_model=BorneStatusOut,
    summary="La borne publique est-elle ouverte ?",
    description="Lu par la page `/borne` au démarrage. Sans clé.",
)
def borne_status() -> BorneStatusOut:
    # La borne vient de s'ouvrir : un passage va suivre, on réveille les services.
    deps.wake_services()
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
    _require_public_borne()
    with _borne_slot():
        return _passage(body, entry_use_case, exit_use_case)


def _passage(body, entry_use_case, exit_use_case) -> BornePassageOut:
    now = datetime.now(UTC)
    if body.type == RequestType.ENTRY:
        decision = entry_use_case.execute(
            plate=body.license_plate,
            date=now,
            source=DetectionSource.TERMINAL,
            declared_type=declared_vehicle_type(body.vehicle_type),
        )
        return _entry_out(decision)

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


@router.post(
    "/pmr-validation",
    response_model=BornePassageOut,
    summary="Validation PMR par un agent, à la borne (code agent)",
    description=(
        "Après une entrée « confirmation requise » (PMR déclaré, justificatif "
        "inconnu de Vehicles), l'agent vérifie la carte mobilité inclusion et "
        "saisit son code. Access enregistre le justificatif chez Vehicles "
        "(le véhicule n'aura plus besoin d'agent), puis rejoue l'entrée : "
        "réponse identique à `POST /borne/passages`. Si Vehicles refuse "
        "d'enregistrer le justificatif, l'entrée PMR est quand même autorisée "
        "pour ce passage (carte vérifiée par l'agent). 403 si le code est faux "
        "ou la borne publique désactivée ; 409 si ce véhicule n'a pas été mis "
        "en attente de vérification PMR à l'entrée dans les 5 dernières minutes."
    ),
    responses={
        403: {"model": ErrorOut, "description": "Code agent incorrect, ou borne désactivée"},
        409: {
            "model": ErrorOut,
            "description": "Aucune entrée de ce véhicule en attente de vérification PMR (5 min)",
        },
        503: {"model": ErrorOut, "description": "Borne très sollicitée, réessayez"},
        422: {"model": ErrorOut, "description": "Plaque invalide"},
        429: {"description": "Trop de tentatives depuis cette adresse"},
    },
)
@limiter.limit(lambda: get_settings().rate_limit_borne, key_func=client_ip)
def borne_pmr_validation(
    request: Request,
    body: BornePmrValidationIn,
    use_case: ConfirmDisabilityByAgent = Depends(deps.get_confirm_disability_use_case),
) -> BornePassageOut:
    _require_public_borne()
    expected = get_settings().agent_code
    if not expected or not hmac.compare_digest(body.agent_code.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=WRONG_AGENT_CODE)
    with _borne_slot():
        try:
            decision = use_case.execute(
                plate=body.license_plate, date=datetime.now(UTC), source=DetectionSource.TERMINAL
            )
        except NoPendingDisabilityCheckError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=NO_PENDING_PMR
            ) from None
    return _entry_out(decision)


# Places réservables lues chez Booking (borne de réservation du plan 3D),
# resservies une minute : Booking raisonne à l'heure, et n'est jamais sollicité
# par visiteur.
RESERVABLE_CACHE_S = 60.0
_reservable_cache: dict = {"at": None, "value": {}}


def _reservable(names: list[str], booking: BookingServicePort) -> dict[str, int]:
    now = time.monotonic()
    if _reservable_cache["at"] is not None and now - _reservable_cache["at"] < RESERVABLE_CACHE_S:
        return _reservable_cache["value"]
    value: dict[str, int] = {}
    for name in names:
        free = booking.free_capacity(name)
        if free is None:
            break  # Booking ne répond pas : on n'insiste pas pour les autres types
        value[name] = free
    _reservable_cache.update(at=now, value=value)
    return value


# Dernière occupation lue chez Parking, resservie pendant quelques secondes.
_parking_cache: dict = {"at": 0.0, "value": None}


def reset_parking_cache() -> None:
    """Oublie l'occupation gardée en mémoire (tests)."""

    _parking_cache.update(at=0.0, value=None)
    _reservable_cache.update(at=None, value={})


@router.get(
    "/parking",
    response_model=BorneParkingOut,
    summary="Occupation du parking pour le plan 3D de la borne (sans clé)",
    description=(
        "Compteurs par catégorie (capacité, places prises, places mises de "
        "côté, véhicules entrés avec une réservation), pour le plan 3D affiché "
        "sur la borne publique. Aucun "
        "véhicule, aucun identifiant, aucune demande. Réponse de Parking "
        "gardée quelques secondes. `available: false` si Parking ne répond "
        "pas. 403 si la borne publique est désactivée."
    ),
    responses={
        403: {"model": ErrorOut, "description": "Borne publique désactivée"},
        429: {"description": "Trop de demandes depuis cette adresse"},
    },
)
@limiter.limit(lambda: get_settings().rate_limit_borne_parking, key_func=client_ip)
def borne_parking(
    request: Request,
    use_case: GetParkingOverview = Depends(deps.get_parking_overview_use_case),
    presences: ListPresentVehicles = Depends(deps.get_list_present_vehicles_use_case),
    booking: BookingServicePort = Depends(deps.get_booking_port),
) -> BorneParkingOut:
    _require_public_borne()
    now = time.monotonic()
    cached = _parking_cache["value"]
    if cached is not None and now - _parking_cache["at"] < get_settings().borne_parking_cache_s:
        return cached
    overview = use_case.execute()
    # Véhicules entrés avec une réservation, par catégorie : un compte, rien d'autre.
    reserved: dict[str, int] = {}
    for vehicle in presences.execute():
        name = code_of_place(vehicle.place_id, vehicle.place_type)
        if vehicle.is_reservation and name:
            reserved[name] = reserved.get(name, 0) + 1
    reservable = _reservable([c.name for c in overview.categories if c.total_capacity], booking)
    result = BorneParkingOut(
        available=overview.available,
        categories=[
            BorneParkingCategoryOut(
                name=c.name,
                label=c.label,
                totalCapacity=c.total_capacity,
                spotTaken=c.spot_taken or 0,
                spotHeld=c.spot_held or 0,
                reserved=reserved.get(c.name, 0),
                reservable=reservable.get(c.name),
            )
            for c in overview.categories
            if c.total_capacity
        ],
    )
    _parking_cache.update(at=now, value=result)
    return result
