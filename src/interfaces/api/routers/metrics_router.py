"""`GET /metrics` — exposition Prometheus, servie par `prometheus_client`.

**Lecture sans clé**, par décision : le Prometheus de chaque équipe du projet
doit pouvoir superviser Access (TP « Observabilité avec Prometheus »), comme
il lit `/health`. Ce choix tient parce que la réponse ne contient que des
agrégats — compteurs, jauges, histogrammes — dont toutes les étiquettes ont un
ensemble de valeurs borné : méthode, gabarit de route (jamais le chemin reçu),
classe de statut, opération, résultat, motif constant, nom de service. Aucune
plaque, aucun identifiant de véhicule ou de demande, aucun correlation ID
(vérifié par `tests/integration/test_metrics.py`).

La route est hors limitation de débit (plusieurs Prometheus la lisent toutes
les 15 s), hors du log d'accès courant (`_QUIET_PREFIXES`) et exclue de
`http_requests_total` : ses propres lectures ne se comptent pas.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from src.interfaces.api.rate_limit import limiter

router = APIRouter(tags=["Monitoring"])


@router.get(
    "/metrics",
    summary="Métriques Prometheus du service (sans clé)",
    description=(
        "Format d'exposition Prometheus. `http_requests_total{method,handler,status}` "
        "compte les requêtes par gabarit de route et classe de statut (`2xx`, `4xx`, "
        "`5xx`) ; `parking_operations_total{operation,result}` compte les entrées, "
        "sorties et sorties forcées, autorisées ou refusées. Uniquement des agrégats : "
        "aucune plaque ni identifiant."
    ),
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}, "description": "Métriques au format texte"}},
)
@limiter.exempt
def metrics() -> Response:
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
        # Une valeur lue doit être celle de l'instant : jamais de cache en chemin.
        headers={"Cache-Control": "no-store"},
    )
