"""Endpoints `/access/requests`, `/access/presences` et
`/access/vehicles/known`.

⚠️ Discipline RGPD : la plaque reçue (`body.license_plate`) n'est transmise
qu'aux use cases, qui la passent à Vehicles. Elle n'est jamais passée à un
logger ni incluse dans une réponse : seul l'identifiant pseudonymisé circule.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from src.application.use_cases.check_vehicle_known import CheckVehicleKnown
from src.application.use_cases.get_access_request import GetAccessRequest
from src.application.use_cases.get_parking_overview import GetParkingOverview
from src.application.use_cases.list_access_requests import ListAccessRequests
from src.application.use_cases.list_present_vehicles import ListPresentVehicles
from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.value_objects.dto import AccessFilters, PlaceType
from src.domain.value_objects.enums import RequestType
from src.infrastructure.config import get_settings
from src.infrastructure.metrics import record_decision
from src.infrastructure.security.api_key_auth import verify_api_key, verify_passage_key
from src.interfaces.api import deps
from src.interfaces.api.rate_limit import limiter
from src.interfaces.api.schemas.access_request_schemas import (
    AccessRequestDetailOut,
    AccessRequestIn,
    AccessRequestListItemOut,
    AccessRequestOut,
    AuthorizationOut,
    ParkingCategoryOut,
    ParkingOverviewOut,
    PlaceTypeOut,
    PresentVehicleOut,
    VehicleKnownIn,
    VehicleKnownOut,
)
from src.interfaces.api.schemas.error_schemas import ErrorOut

router = APIRouter(
    prefix="/access",
    tags=["Access"],
    dependencies=[Depends(verify_api_key)],
)
# Passage d'un véhicule : seule route ouverte aussi à la clé des bornes client
# (`BORNE_API_KEY`). Toutes les autres routes exigent la clé d'exploitation.
passage_router = APIRouter(
    prefix="/access",
    tags=["Access"],
    dependencies=[Depends(verify_passage_key)],
)


def _as_utc(value: datetime) -> datetime:
    """Date sans fuseau = UTC (même convention que `AccessRequestIn`)."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _place_type_out(place_type: PlaceType | None) -> PlaceTypeOut | None:
    if place_type is None:
        return None
    return PlaceTypeOut(
        category=int(place_type.category),
        isXl=place_type.is_xl,
        isElectric=place_type.is_electric,
        isHandicap=place_type.is_handicap,
    )


_COMMON_ERROR_RESPONSES = {
    401: {"model": ErrorOut, "description": "Clé API manquante ou invalide"},
    422: {"model": ErrorOut, "description": "Erreur de validation"},
    500: {"model": ErrorOut, "description": "Erreur interne"},
}


@passage_router.post(
    "/requests",
    response_model=AccessRequestOut,
    status_code=status.HTTP_200_OK,
    summary="Crée et traite une demande d'accès (entrée ou sortie)",
    description=(
        "Orchestre le workflow d'entrée (résolution Vehicles, réservation "
        "Booking ou attribution Parking, compatibilité véhicule/place, "
        "accessibilité PMR) ou de sortie (Pricing puis Payment) et retourne "
        "la décision. La plaque est transmise à Vehicles puis oubliée : elle "
        "n'est jamais persistée, publiée ni renvoyée. Accepte la clé "
        "d'exploitation ou la clé des bornes client (`BORNE_API_KEY`)."
    ),
    responses={
        200: {"description": "Décision rendue (autorisée, refusée, ou confirmation requise)"},
        **_COMMON_ERROR_RESPONSES,
        400: {"model": ErrorOut, "description": "Requête invalide (ex. photoBase64 mal formé)"},
    },
)
@limiter.limit(get_settings().rate_limit_access_requests)
def create_access_request(
    request: Request,
    body: AccessRequestIn,
    entry_use_case: ProcessEntryRequest = Depends(deps.get_process_entry_request_use_case),
    exit_use_case: ProcessExitRequest = Depends(deps.get_process_exit_request_use_case),
) -> AccessRequestOut:
    photo: bytes | None = None
    if body.photo_base64:
        try:
            photo = base64.b64decode(body.photo_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="photoBase64 invalide"
            ) from exc

    if body.type == RequestType.ENTRY:
        decision = entry_use_case.execute(
            plate=body.license_plate, date=body.date, source=body.source, photo=photo
        )
        record_decision(decision.type, decision.result, decision.reason)
        return AccessRequestOut(
            requestId=decision.request_id,
            vehicleId=decision.vehicle_id,
            type=decision.type,
            status=decision.status,
            authorization=AuthorizationOut(
                result=decision.result,
                reason=decision.reason,
                vehicleTypeCheckOk=decision.vehicle_type_check_ok,
                disabilityCheckOk=decision.disability_check_ok,
                paymentAmount=None,
            ),
            placeType=_place_type_out(decision.place_type),
            placeLabel=decision.place_label,
            reservation=decision.reservation,
        )

    decision = exit_use_case.execute(plate=body.license_plate, date=body.date, source=body.source)
    record_decision(decision.type, decision.result, decision.reason)
    amount = float(decision.payment_amount) if decision.payment_amount is not None else None
    return AccessRequestOut(
        requestId=decision.request_id,
        vehicleId=decision.vehicle_id,
        type=decision.type,
        status=decision.status,
        authorization=AuthorizationOut(
            result=decision.result,
            reason=decision.reason,
            vehicleTypeCheckOk=None,
            disabilityCheckOk=None,
            paymentAmount=amount,
        ),
        enteredAt=decision.entered_at,
        durationMinutes=decision.duration_minutes,
    )


@router.get(
    "/requests/{request_id}",
    response_model=AccessRequestDetailOut,
    summary="Détail d'une demande d'accès et de sa décision",
    responses={
        404: {"model": ErrorOut, "description": "Demande introuvable"},
        **_COMMON_ERROR_RESPONSES,
    },
)
def get_access_request(
    request_id: str = Path(..., min_length=1, max_length=64),
    use_case: GetAccessRequest = Depends(deps.get_get_access_request_use_case),
) -> AccessRequestDetailOut:
    result = use_case.execute(request_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable")

    access_request, authorization = result.request, result.authorization
    amount = (
        float(authorization.payment_amount)
        if authorization and authorization.payment_amount is not None
        else None
    )
    authorization_out = (
        AuthorizationOut(
            result=authorization.result,
            reason=authorization.reason,
            vehicleTypeCheckOk=authorization.vehicle_type_check_ok,
            disabilityCheckOk=authorization.disability_check_ok,
            paymentAmount=amount,
        )
        if authorization
        else None
    )
    return AccessRequestDetailOut(
        requestId=access_request.id,
        vehicleId=access_request.vehicle_id,
        type=access_request.type,
        status=access_request.status,
        authorization=authorization_out,
        date=access_request.date,
        source=access_request.source,
        aiCheck=access_request.ai_check,
    )


@router.get(
    "/requests",
    response_model=list[AccessRequestListItemOut],
    summary="Liste/filtre des demandes d'accès (audit), avec leur décision",
    description=(
        "Filtre exclusivement sur vehicleId (pseudonymisé), jamais sur la plaque. "
        "Les demandes les plus récentes d'abord, `limit` au plus (500 max)."
    ),
    responses={
        **_COMMON_ERROR_RESPONSES,
        422: {"model": ErrorOut, "description": "Filtre invalide (ex. `from` après `to`)"},
    },
)
def list_access_requests(
    vehicleId: str | None = Query(default=None, max_length=64),
    type_: RequestType | None = Query(default=None, alias="type"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    use_case: ListAccessRequests = Depends(deps.get_list_access_requests_use_case),
) -> list[AccessRequestListItemOut]:
    if date_from is not None and date_to is not None and _as_utc(date_from) > _as_utc(date_to):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Période invalide : `from` doit précéder `to`",
        )
    filters = AccessFilters(
        vehicle_id=vehicleId, type=type_, date_from=date_from, date_to=date_to, limit=limit
    )
    items = use_case.execute(filters)
    return [
        AccessRequestListItemOut(
            requestId=item.request.id,
            vehicleId=item.request.vehicle_id,
            type=item.request.type,
            date=item.request.date,
            source=item.request.source,
            status=item.request.status,
            result=item.authorization.result if item.authorization else None,
            reason=item.authorization.reason if item.authorization else None,
            paymentAmount=(
                float(item.authorization.payment_amount)
                if item.authorization and item.authorization.payment_amount is not None
                else None
            ),
        )
        for item in items
    ]


@router.get(
    "/presences",
    response_model=list[PresentVehicleOut],
    summary="Véhicules actuellement présents dans le parking",
    description=(
        "État courant vu par Access : véhicules entrés et pas encore sortis, "
        "avec l'heure d'entrée et la place attribuée. Reconstruit à partir des "
        "seules données d'Access (aucun appel aux autres services)."
    ),
    responses=_COMMON_ERROR_RESPONSES,
)
def list_present_vehicles(
    use_case: ListPresentVehicles = Depends(deps.get_list_present_vehicles_use_case),
) -> list[PresentVehicleOut]:
    return [
        PresentVehicleOut(
            vehicleId=v.vehicle_id,
            entryRequestId=v.entry_request_id,
            enteredAt=v.entered_at,
            placeId=v.place_id,
            placeType=_place_type_out(v.place_type),
            reservation=v.is_reservation,
        )
        for v in use_case.execute()
    ]


@router.post(
    "/vehicles/known",
    response_model=VehicleKnownOut,
    summary="Vérifie si une plaque est connue par Vehicles",
    description=(
        "Consultation à la volée auprès de Vehicles, sans lancer le workflow "
        "complet, sans créer le véhicule et sans rien persister. La plaque "
        "voyage dans le corps (jamais dans l'URL) et n'est jamais renvoyée."
    ),
    responses=_COMMON_ERROR_RESPONSES,
)
def check_vehicle_known(
    body: VehicleKnownIn,
    use_case: CheckVehicleKnown = Depends(deps.get_check_vehicle_known_use_case),
) -> VehicleKnownOut:
    result = use_case.execute(body.license_plate)
    return VehicleKnownOut(known=result.known, vehicleId=result.vehicle_id)


@router.get(
    "/parking",
    response_model=ParkingOverviewOut,
    summary="État du parking vu par le service Parking",
    description=(
        "Catégories déclarées par Parking (libellé, places prises, mises de "
        "côté, capacité) et catégories dont Access a besoin mais que Parking "
        "ne déclare pas. `available: false` si Parking ne répond pas (jamais "
        "d'erreur 500). Rien n'est persisté."
    ),
    responses=_COMMON_ERROR_RESPONSES,
)
def get_parking_overview(
    use_case: GetParkingOverview = Depends(deps.get_parking_overview_use_case),
) -> ParkingOverviewOut:
    overview = use_case.execute()
    return ParkingOverviewOut(
        available=overview.available,
        categories=[
            ParkingCategoryOut(
                name=c.name,
                label=c.label,
                usedByAccess=c.used_by_access,
                spotTaken=c.spot_taken,
                spotHeld=c.spot_held,
                totalCapacity=c.total_capacity,
                occupationRate=c.occupation_rate,
            )
            for c in overview.categories
        ],
        missingCategories=overview.missing_categories,
    )
