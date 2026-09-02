"""Endpoint `/access/events` — lecture de l'outbox, démo/observabilité en
l'absence de vrai broker (section 9 et point tranché en section 17)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.infrastructure.security.api_key_auth import verify_api_key
from src.interfaces.api import deps
from src.interfaces.api.schemas.access_request_schemas import EventOut

router = APIRouter(
    prefix="/access",
    tags=["Events"],
    dependencies=[Depends(verify_api_key)],
)


@router.get(
    "/events",
    response_model=list[EventOut],
    summary="Liste les événements publiés (outbox)",
    description=(
        "Endpoint de démo/observabilité : les événements sont normalement "
        "diffusés en HTTP POST vers EVENT_SUBSCRIBERS_URLS, cet endpoint "
        "permet de les relire côté Access en local."
    ),
)
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    access_repo: AccessRepositoryPort = Depends(deps.get_access_repository),
) -> list[EventOut]:
    evenements = access_repo.list_evenements(limit=limit, offset=offset)
    return [
        EventOut(
            id=e.id,
            type=int(e.type),
            demande_id=e.demande_id,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in evenements
    ]
