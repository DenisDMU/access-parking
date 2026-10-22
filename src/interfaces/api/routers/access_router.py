"""Endpoints `/access/requests` et `/access/plates/{plate}/known`.

⚠️ Discipline RGPD (section 6/11 de la spec) : la variable `plate`/`body`
n'est jamais passée à un logger, jamais incluse dans un schéma de réponse.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from src.application.use_cases.check_plate_known import CheckPlateKnown
from src.application.use_cases.get_access_request import GetAccessRequest
from src.application.use_cases.list_access_requests import ListAccessRequests
from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.value_objects.dto import AccessFilters
from src.domain.value_objects.enums import RequestType
from src.infrastructure.config import get_settings
from src.infrastructure.security.api_key_auth import verify_api_key
from src.interfaces.api import deps
from src.interfaces.api.rate_limit import limiter
from src.interfaces.api.schemas.access_request_schemas import (
    PLATE_PATTERN,
    AccessRequestDetailOut,
    AccessRequestIn,
    AccessRequestListItemOut,
    AccessRequestOut,
    AuthorizationOut,
    PlateKnownOut,
)
from src.interfaces.api.schemas.error_schemas import ErrorOut

router = APIRouter(
    prefix="/access",
    tags=["Access"],
    dependencies=[Depends(verify_api_key)],
)

_COMMON_ERROR_RESPONSES = {
    401: {"model": ErrorOut, "description": "Clé API manquante ou invalide"},
    422: {"model": ErrorOut, "description": "Erreur de validation"},
    500: {"model": ErrorOut, "description": "Erreur interne"},
}


@router.post(
    "/requests",
    response_model=AccessRequestOut,
    status_code=status.HTTP_200_OK,
    summary="Crée et traite une demande d'accès (entrée ou sortie)",
    description=(
        "Orchestre le workflow d'entrée (résolution Vehicles, réservation "
        "Booking ou attribution Parking, compatibilité véhicule/place, "
        "accessibilité PMR) ou de sortie (Pricing puis Payment) et retourne "
        "la décision. La plaque transmise n'est jamais persistée ni renvoyée."
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
            plate=body.plate, date=body.date, source=body.source, photo=photo
        )
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
        )

    decision = exit_use_case.execute(plate=body.plate, date=body.date, source=body.source)
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
    request_id: str,
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
    summary="Liste/filtre des demandes d'accès (audit)",
    description="Filtre exclusivement sur vehicleId (pseudonymisé), jamais sur la plaque.",
    responses=_COMMON_ERROR_RESPONSES,
)
def list_access_requests(
    vehicleId: str | None = Query(default=None),
    type_: RequestType | None = Query(default=None, alias="type"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    use_case: ListAccessRequests = Depends(deps.get_list_access_requests_use_case),
) -> list[AccessRequestListItemOut]:
    filters = AccessFilters(vehicle_id=vehicleId, type=type_, date_from=date_from, date_to=date_to)
    requests = use_case.execute(filters)
    return [
        AccessRequestListItemOut(
            requestId=r.id,
            vehicleId=r.vehicle_id,
            type=r.type,
            date=r.date,
            source=r.source,
            status=r.status,
        )
        for r in requests
    ]


@router.get(
    "/plates/{plate}/known",
    response_model=PlateKnownOut,
    summary="Vérifie si une plaque est connue par Vehicles",
    description=(
        "Résolution à la volée auprès de Vehicles, sans lancer le workflow "
        "complet et sans rien persister. Ne renvoie jamais la plaque."
    ),
    responses=_COMMON_ERROR_RESPONSES,
)
def check_plate_known(
    plate: str = Path(..., pattern=PLATE_PATTERN),
    use_case: CheckPlateKnown = Depends(deps.get_check_plate_known_use_case),
) -> PlateKnownOut:
    result = use_case.execute(plate)
    return PlateKnownOut(known=result.known, vehicleId=result.vehicle_id)
