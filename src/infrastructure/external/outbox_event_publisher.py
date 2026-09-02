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

logger = logging.getLogger(__name__)


def _serialize(event: AccessEvent) -> dict:
    return {
        "id": event.id,
        "type": int(event.type),
        "requestId": event.request_id,
        "payload": event.payload,
        "createdAt": event.created_at.isoformat(),
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
        self._http_client = http_client or httpx.Client()

    def publish(self, event: AccessEvent) -> None:
        self._access_repo.save_event(event)
        self._outbox_repo.record_publication(event.id)

        if not self._subscriber_urls:
            return

        body = _serialize(event)
        for url in self._subscriber_urls:
            try:
                self._http_client.post(url, json=body, timeout=self._timeout_s)
            except httpx.HTTPError as exc:
                # Best-effort : un abonné indisponible n'empêche jamais la
                # décision d'accès de repartir vers l'appelant.
                logger.warning("Échec de diffusion de l'événement vers %s: %s", url, exc)
