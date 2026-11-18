"""Implémentation `EventPublisherPort` — outbox + fan-out HTTP best-effort.

Cf. section 3 point 3 de la spec : à chaque événement, ce publisher
1. persiste l'événement dans `access_events` (via `AccessRepositoryPort`)
   et dans `outbox_events` (traçabilité) ;
2. diffuse l'événement en HTTP POST vers chaque URL de
   `EVENT_SUBSCRIBERS_URLS`, en best-effort : un abonné indisponible est
   loggé mais ne bloque jamais le use case principal (pas de broker, pas de
   garantie de livraison — acceptable pour le MVP, cf. hors périmètre).

Ce mécanisme reste isolé ici et pourra être remplacé par un vrai broker
(Kafka/RabbitMQ/Redis, voir `rabbitmq_event_publisher.py`) sans toucher au
domaine ni aux use cases — seul ce fichier serait ré-implémenté.
"""

from __future__ import annotations

import logging

import httpx

from src.domain.entities.access_event import AccessEvent
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.infrastructure.db.repositories.sqlite_outbox_repository import (
    SqliteOutboxRepository,
)
from src.infrastructure.external.outgoing_http import outgoing_client
from src.infrastructure.logging_config import get_correlation_id
from src.infrastructure.metrics import EVENT_TYPE_LABEL, EVENTS_PUBLISHED

logger = logging.getLogger(__name__)


def _serialize(event: AccessEvent) -> dict:
    return {
        "id": event.id,
        "type": int(event.type),
        "requestId": event.request_id,
        "payload": event.payload,
        "createdAt": event.created_at.isoformat(),
        # Correlation ID de la requête qui a produit l'événement (jalon 12).
        "correlationId": get_correlation_id(),
    }


class OutboxEventPublisher:
    def __init__(
        self,
        access_repo: AccessRepositoryPort,
        outbox_repo: SqliteOutboxRepository,
        subscriber_urls: list[str],
        timeout_ms: int,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._access_repo = access_repo
        self._outbox_repo = outbox_repo
        self._subscriber_urls = subscriber_urls
        self._timeout_s = max(timeout_ms, 1) / 1000
        self._http_client = http_client or outgoing_client("webhook", timeout=self._timeout_s)

    def publish(self, event: AccessEvent) -> None:
        self._access_repo.save_event(event)
        self._outbox_repo.record_publication(event.id)

        if not self._subscriber_urls:
            return

        body = _serialize(event)
        event_type = EVENT_TYPE_LABEL.get(int(event.type), "other")
        for url in self._subscriber_urls:
            try:
                response = self._http_client.post(url, json=body, timeout=self._timeout_s)
                response.raise_for_status()
                EVENTS_PUBLISHED.labels(
                    channel="webhook", event_type=event_type, outcome="ok"
                ).inc()
            except httpx.HTTPError as exc:
                # Best-effort : un abonné indisponible n'empêche jamais la
                # décision d'accès de repartir vers l'appelant.
                EVENTS_PUBLISHED.labels(
                    channel="webhook", event_type=event_type, outcome="error"
                ).inc()
                logger.warning("Échec de diffusion de l'événement vers %s: %s", url, exc)
