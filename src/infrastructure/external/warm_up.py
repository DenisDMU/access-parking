"""Réveil des services de l'équipe (offre gratuite de Render).

Vehicles, Booking, Parking, Pricing et Payment sont hébergés sur l'offre
gratuite de Render : après 15 minutes sans trafic, le service s'endort, et sa
première réponse met ensuite 30 à 60 secondes. Un passage qui tombait sur un
service endormi était refusé (« Service Parking indisponible, réessayez plus
tard », « Un agent arrive »…) alors que le service n'était pas en panne.

Access les réveille donc **avant** d'en avoir besoin : un simple `GET /health`
envoyé à chacun, en parallèle et sans attendre la réponse,
- au démarrage d'Access (lui-même réveillé par un visiteur) ;
- quand la borne ou le dashboard s'ouvre (`/borne/status`, `/health`).
Le temps que le conducteur choisisse son véhicule et saisisse sa plaque, les
services sont prêts. Tant qu'une page d'Access reste ouverte, ils restent
éveillés ; quand plus personne ne l'utilise, Access s'endort à son tour et
n'envoie plus rien.

Au plus un réveil toutes les `MIN_INTERVAL_S` secondes ; aucune donnée
n'est envoyée ; un échec est sans conséquence (simple ligne de log).
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

logger = logging.getLogger(__name__)

MIN_INTERVAL_S = 240.0  # bien en dessous des 15 min de mise en veille
PING_TIMEOUT_S = 75.0  # un réveil complet peut dépasser la minute

_lock = threading.Lock()
_last = {"at": None}


def reset_warm_up() -> None:
    """Oublie le dernier réveil (tests)."""

    _last["at"] = None


def _ping(name: str, base_url: str, transport: httpx.BaseTransport | None) -> None:
    started = time.monotonic()
    try:
        with httpx.Client(timeout=PING_TIMEOUT_S, transport=transport) as client:
            status = client.get(f"{base_url.rstrip('/')}/health").status_code
    except httpx.HTTPError as exc:
        logger.info("Réveil de %s : pas de réponse (%s)", name, type(exc).__name__)
        return
    elapsed = time.monotonic() - started
    if elapsed > 5:
        logger.info("Réveil de %s : HTTP %s après %.0f s (il dormait)", name, status, elapsed)


def warm_up_services(
    services: dict[str, str],
    *,
    min_interval_s: float = MIN_INTERVAL_S,
    transport: httpx.BaseTransport | None = None,
    wait: bool = False,
) -> bool:
    """Envoie un `GET /health` à chaque service, en parallèle. `True` si les
    réveils sont partis, `False` s'ils l'ont déjà été il y a peu.

    `wait=True` attend les réponses (tests) ; sinon l'appel rend la main tout
    de suite : jamais une requête d'Access n'attend un réveil.
    """

    now = time.monotonic()
    with _lock:
        if _last["at"] is not None and now - _last["at"] < min_interval_s:
            return False
        _last["at"] = now
    threads = [
        threading.Thread(
            target=_ping, args=(name, url, transport), daemon=True, name=f"reveil-{name}"
        )
        for name, url in services.items()
        if url
    ]
    for thread in threads:
        thread.start()
    if wait:
        for thread in threads:
            thread.join()
    return True
