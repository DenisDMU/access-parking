"""`GET /metrics` — exposition Prometheus, servie par `prometheus_client`.

**Lecture protégée** : la clé d'exploitation, ou le jeton de lecture
`METRICS_TOKEN` (dans `X-API-Key` ou `Authorization: Bearer …`), qui ne donne
accès qu'à cette route — c'est lui qu'on confie à un Prometheus. Sans l'un
des deux : 401. La route a été lisible sans clé de la 4.26.0 à la 4.27.1 ;
elle ne l'est plus : même sans plaque ni identifiant, elle montre l'activité
du parking (montant encaissé, refus par motif, véhicules présents), qui ne
regarde pas tout Internet.

La réponse ne contient que des agrégats — compteurs, jauges, histogrammes —
dont toutes les étiquettes ont un ensemble de valeurs borné : méthode, gabarit
de route (jamais le chemin reçu), classe de statut, opération, résultat, motif
constant, nom de service. Aucune plaque, aucun identifiant de véhicule ou de
demande, aucun correlation ID (vérifié par `tests/integration/test_metrics.py`).

La route est hors limitation de débit (Prometheus la lit toutes les 15 s),
hors du log d'accès courant quand elle répond 200 (`_QUIET_PREFIXES` ; un 401
est loggé en avertissement) et exclue de `http_requests_total` : ses propres
lectures ne se comptent pas.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from src.infrastructure.security.api_key_auth import verify_metrics_key
from src.interfaces.api.rate_limit import limiter

router = APIRouter(tags=["Monitoring"])


@router.get(
    "/metrics",
    summary="Métriques Prometheus du service (clé ou jeton de lecture)",
    description=(
        "Format d'exposition Prometheus. `http_requests_total{method,handler,status}` "
        "compte les requêtes par gabarit de route et classe de statut (`2xx`, `4xx`, "
        "`5xx`) ; `parking_operations_total{operation,result}` compte les entrées, "
        "sorties et sorties forcées, autorisées ou refusées. Uniquement des agrégats : "
        "aucune plaque ni identifiant. Exige la clé d'exploitation ou le jeton de "
        "lecture `METRICS_TOKEN`, dans `X-API-Key` ou `Authorization: Bearer`."
    ),
    response_class=Response,
    dependencies=[Depends(verify_metrics_key)],
    responses={
        200: {"content": {"text/plain": {}}, "description": "Métriques au format texte"},
        401: {"description": "Clé ou jeton manquant ou invalide"},
    },
)
@limiter.exempt
def metrics() -> Response:
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
        # Une valeur lue doit être celle de l'instant : jamais de cache en chemin.
        headers={"Cache-Control": "no-store"},
    )
