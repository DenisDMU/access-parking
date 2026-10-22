"""Endpoint `/health` — sans authentification (section 9/11 de la spec)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from src import __version__
from src.infrastructure.config import get_settings
from src.infrastructure.db.session import check_connection
from src.interfaces.api import deps
from src.interfaces.api.schemas.access_request_schemas import HealthOut

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Vérifie l'état du service et de la base de données",
    description="Endpoint de healthcheck, non authentifié, à appeler par les outils de supervision.",
    responses={
        200: {"description": "Service opérationnel (ou dégradé si la base est injoignable)"}
    },
)
def health(request: Request, engine=Depends(deps.get_engine)) -> HealthOut:
    db_ok = check_connection(engine)
    start_time = getattr(request.app.state, "start_time", time.time())
    return HealthOut(
        status="ok" if db_ok else "degraded",
        database="connected" if db_ok else "unavailable",
        uptime_seconds=int(time.time() - start_time),
        version=__version__,
        commit=get_settings().git_commit,
    )
