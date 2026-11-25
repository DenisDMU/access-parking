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
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src import __version__
from src.infrastructure.config import check_secrets, get_settings, is_production
from src.infrastructure.db.session import init_db
from src.infrastructure.logging_config import configure_logging, get_correlation_id
from src.infrastructure.metrics import register_presence_collector
from src.infrastructure.security.api_key_auth import verify_api_key
from src.interfaces.api import deps
from src.interfaces.api.middleware import (
    CORRELATION_HEADER,
    correlation_id_middleware,
    security_headers_middleware,
)
from src.interfaces.api.rate_limit import limiter
from src.interfaces.api.routers import (
    access_router,
    borne_router,
    events_router,
    health_router,
    promenade_router,
)

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.start_time = time.time()
    for problem in check_secrets(settings, production=is_production()):
        logger.warning("Configuration non sécurisée (acceptée hors production) : %s", problem)
    init_db(deps.get_engine())
    register_presence_collector(deps.count_present_vehicles)
    logger.info(
        "Access %s (commit %s) démarré — base %s, Booking %s",
        __version__,
        settings.git_commit,
        deps.get_engine().dialect.name,
        "simulé" if settings.booking_use_mock else "réel",
    )
    # Access vient d'être réveillé par un visiteur : les autres services
    # dorment sans doute aussi (offre gratuite de Render). On les réveille.
    deps.wake_services()
    yield


app = FastAPI(
    title="Access — Microservice Parking",
    description=(
        "Access décide si un véhicule peut entrer ou sortir du parking et "
        "coordonne les échanges nécessaires avec Vehicles, Booking, Parking, "
        "Pricing et Payment. Il ne possède pas les données métier de ces "
        "services et ne reçoit jamais la plaque d'un véhicule : uniquement son "
        "code Vehicles, résolu en identifiant pseudonymisé (`vehicleId`)."
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
    allow_headers=["Content-Type", "X-API-Key", CORRELATION_HEADER],
    expose_headers=[CORRELATION_HEADER],
)

# Correlation ID + log d'accès (voir middleware.py). Ajouté en dernier =
# middleware le plus externe : même une réponse CORS ou 429 porte le cid.
app.middleware("http")(security_headers_middleware)
app.middleware("http")(correlation_id_middleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # jsonable_encoder : certaines erreurs Pydantic embarquent un objet
    # exception dans `ctx`, non sérialisable tel quel (sinon 500 au lieu de 422).
    logger.info(
        "Requête invalide sur %s : %d erreur(s) de validation", request.url.path, len(exc.errors())
    )
    # RGPD : Pydantic recopie la valeur reçue (`input`) dans chaque erreur ;
    # elle est retirée pour ne jamais renvoyer une plaque, même invalide.
    errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(errors)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Aucune stack trace n'est jamais renvoyée au client (section 11).
    # Le correlation ID est renvoyé au client : il permet de retrouver la
    # ligne de log détaillée sans rien exposer de l'erreur elle-même.
    logger.exception("Erreur interne non gérée sur %s %s", request.method, request.url.path)
    correlation_id = get_correlation_id()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erreur interne du serveur", "correlationId": correlation_id},
        headers={CORRELATION_HEADER: correlation_id},
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
app.include_router(access_router.passage_router, prefix="/api/v1")
app.include_router(access_router.router, prefix="/api/v1")
app.include_router(events_router.router, prefix="/api/v1")
app.include_router(borne_router.router, prefix="/api/v1")
app.include_router(promenade_router.router, prefix="/api/v1")

# Journal de bord (dashboard) — servi par Access lui-même, sans port
# supplémentaire : simple page statique appelant GET /api/v1/access/events
# en same-origin (pas de souci CORS). Clé API saisie côté navigateur.
_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/borne", include_in_schema=False)
async def borne() -> FileResponse:
    """Borne client (écran public), servie directement sur `/borne` : l'adresse
    affichée reste courte. `?mode=entree|sortie` fixe son emplacement."""

    return FileResponse(_STATIC_DIR / "borne.html", media_type="text/html")


@app.get("/static/borne.html", include_in_schema=False)
async def borne_old_url(request: Request) -> RedirectResponse:
    """Ancienne adresse (4.1.0 à 4.4.0) : redirigée vers `/borne`, paramètres
    conservés, pour les bornes déjà ouvertes avec ce lien. Déclarée avant le
    montage de `/static` pour passer en premier."""

    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"/borne{query}", status_code=301)


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/static/dashboard.html")
