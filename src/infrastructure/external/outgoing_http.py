"""Client HTTP commun à tous les appels sortants d'Access.

Jalons 12 et 13 : chaque appel vers Vehicles, Booking, Parking, Pricing,
Payment (et les webhooks d'événements) passe par `outgoing_client(...)`,
qui :

1. **propage le correlation ID** de la requête en cours dans l'en-tête
   `X-Correlation-ID` — le service appelé peut le reprendre dans ses propres
   logs et le transmettre à son tour ;
2. **mesure l'appel** (métriques `access_outgoing_requests_total` et
   `access_outgoing_request_duration_seconds`, par service), y compris quand
   il échoue avant toute réponse (timeout, connexion refusée).

Les clients gardent leur propre gestion d'erreur (refus propre, jamais de
500) : ce module ne change que l'instrumentation, jamais le comportement.
"""

from __future__ import annotations

import time

import httpx

from src.infrastructure.logging_config import get_correlation_id
from src.infrastructure.metrics import OUTGOING_DURATION, OUTGOING_REQUESTS, status_outcome

CORRELATION_HEADER = "X-Correlation-ID"


class _TracedTransport(httpx.BaseTransport):
    """Enveloppe un transport httpx : ajoute le correlation ID et mesure."""

    def __init__(self, inner: httpx.BaseTransport, service: str) -> None:
        self._inner = inner
        self._service = service

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        correlation_id = get_correlation_id()
        if correlation_id and correlation_id != "-":
            request.headers[CORRELATION_HEADER] = correlation_id
        started = time.perf_counter()
        try:
            response = self._inner.handle_request(request)
        except Exception:
            OUTGOING_REQUESTS.labels(service=self._service, outcome="error").inc()
            raise
        finally:
            OUTGOING_DURATION.labels(service=self._service).observe(time.perf_counter() - started)
        OUTGOING_REQUESTS.labels(
            service=self._service, outcome=status_outcome(response.status_code)
        ).inc()
        return response

    def close(self) -> None:
        self._inner.close()


# Délai d'attente des cinq services de l'équipe. Ils sont sur l'offre gratuite
# de Render : endormis après 15 min sans trafic, 30 à 60 s pour se réveiller.
# Avec 20 s, le premier passage après une pause était refusé (« Service
# Parking indisponible », « Un agent arrive »…) alors que rien n'était en
# panne. Access les réveille aussi d'avance (voir `warm_up.py`).
COLD_START_TIMEOUT_S = 45.0


def outgoing_client(
    service: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """`httpx.Client` instrumenté pour appeler le service `service`.

    `transport` permet aux tests d'injecter un `httpx.MockTransport` : il est
    lui aussi enveloppé, donc la propagation du correlation ID est testable.
    """

    return httpx.Client(
        timeout=timeout,
        headers=headers,
        transport=_TracedTransport(transport or httpx.HTTPTransport(), service),
    )
