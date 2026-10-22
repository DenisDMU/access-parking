"""Point d'entrée FastAPI — instancie l'app, la documentation, la sécurité
transverse (CORS, rate limiting, gestion d'erreurs centralisée) et monte les
routers. Lancer avec :

    uvicorn src.interfaces.api.main:app --reload
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src import __version__
from src.infrastructure.config import get_settings
from src.infrastructure.db.session import init_db
from src.infrastructure.logging_config import configure_logging
from src.infrastructure.security.api_key_auth import verify_api_key
from src.interfaces.api import deps
from src.interfaces.api.rate_limit import limiter
from src.interfaces.api.routers import access_router, events_router, health_router

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.start_time = time.time()
    init_db(deps.get_engine())
    logger.info(
        "Access %s (commit %s) démarré — SQLite initialisée, USE_MOCKS=%s",
        __version__,
        settings.git_commit,
        settings.use_mocks,
    )
    yield


app = FastAPI(
    title="Access — Microservice Parking",
    description=(
        "Access décide si un véhicule peut entrer ou sortir du parking et "
        "coordonne les échanges nécessaires avec Vehicles, Booking, Parking, "
        "Pricing et Payment. Il ne possède pas les données métier de ces "
        "services et ne stocke/publie/renvoie jamais la plaque brute d'un "
        "véhicule — uniquement un identifiant pseudonymisé (`vehiculeId`)."
    ),
    version=__version__,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Access", "description": "Traitement des demandes d'entrée/sortie"},
        {"name": "Events", "description": "Lecture de l'outbox d'événements publiés"},
        {"name": "Health", "description": "Healthcheck non authentifié"},
        {"name": "Monitoring", "description": "Métriques Prometheus (clé API requise)"},
    ],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS volontairement restreint : le dashboard est servi par Access lui-même
# (same-origin, pas concerné par CORS). Seules les origines listées dans
# CORS_ALLOWED_ORIGINS peuvent appeler l'API depuis un navigateur. Pas de
# credentials (cookies) : l'authentification passe par l'en-tête X-API-Key.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Aucune stack trace n'est jamais renvoyée au client (section 11).
    logger.exception("Erreur interne non gérée")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erreur interne du serveur"},
    )


app.include_router(health_router.router)

# Métriques Prometheus (nombre de requêtes, latences, codes HTTP par route).
# Informations d'exploitation : protégées par la clé API, comme le reste.
Instrumentator(excluded_handlers=["/health", "/metrics", "/static.*"]).instrument(app).expose(
    app,
    endpoint="/metrics",
    tags=["Monitoring"],
    summary="Métriques Prometheus du service",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(access_router.router, prefix="/api/v1")
app.include_router(events_router.router, prefix="/api/v1")

# Journal de bord (dashboard) — servi par Access lui-même, sans port
# supplémentaire : simple page statique appelant GET /api/v1/access/events
# en same-origin (pas de souci CORS). Clé API saisie côté navigateur.
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/static/dashboard.html")
