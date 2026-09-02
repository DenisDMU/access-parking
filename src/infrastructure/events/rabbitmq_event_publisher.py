"""Implémentation alternative `EventPublisherPort` — RabbitMQ.

Prête à l'usage dès qu'un broker RabbitMQ tourne, par exemple en local :

    docker run -d --name access-rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management

Interface de gestion sur http://localhost:15672 (guest/guest).

Activation : dans `.env`, `EVENT_PUBLISHER=rabbitmq` (au lieu de `webhook`,
la valeur par défaut) + `RABBITMQ_URL` pointant vers le broker. Le point de
bascule est dans `deps.py::get_event_publisher()`.

Comme `OutboxEventPublisher`, cette implémentation persiste TOUJOURS
l'événement (source de vérité, `access_events` + `outbox_events`) avant de
tenter la diffusion : un souci RabbitMQ est loggé mais ne bloque jamais la
décision d'accès (cf. section 3 point 3 de la spec — "pas de garantie de
livraison, acceptable pour le MVP", pas de reprise après incident).

Topologie :
    Exchange "access.events" (topic, durable)
    Routing key "access.<event_type>" (ex. "access.vehicle_entered")
    -> chaque service intéressé déclare sa propre queue et la bind sur les
       routing keys qui l'intéressent (ex. "access.#" pour tout recevoir,
       ou juste "access.vehicle_exited" pour Messages/facturation).

Limite connue (MVP) : une connexion AMQP est ouverte/fermée à chaque
publication plutôt qu'une connexion persistante réutilisée — plus simple et
plus robuste (pas d'état de connexion à surveiller) mais moins performant à
haut volume. À optimiser (pool de connexions, connexion persistante avec
reconnexion automatique) si le débit d'événements le justifie.
"""

from __future__ import annotations

import json
import logging

import pika
from pika.exceptions import AMQPError

from src.domain.entities.access_event import AccessEvent
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.value_objects.enums import EventType
from src.infrastructure.db.repositories.sqlite_outbox_repository import (
    SqliteOutboxRepository,
)

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "access.events"

_ROUTING_KEYS: dict[EventType, str] = {
    EventType.VEHICLE_ENTERED: "access.vehicle_entered",
    EventType.VEHICLE_EXITED: "access.vehicle_exited",
    EventType.ACCESS_REFUSED: "access.access_refused",
    EventType.OTHER: "access.other",
}


def _serialize(event: AccessEvent) -> dict:
    return {
        "id": event.id,
        "type": int(event.type),
        "requestId": event.request_id,
        "payload": event.payload,
        "createdAt": event.created_at.isoformat(),
    }


class RabbitMQEventPublisher:
    def __init__(
        self,
        access_repo: AccessRepositoryPort,
        outbox_repo: SqliteOutboxRepository,
        amqp_url: str,
    ) -> None:
        self._access_repo = access_repo
        self._outbox_repo = outbox_repo
        self._amqp_url = amqp_url

    def publish(self, event: AccessEvent) -> None:
        self._access_repo.save_event(event)
        self._outbox_repo.record_publication(event.id)

        try:
            self._send_to_rabbitmq(event)
        except AMQPError as exc:
            # Best-effort : un souci RabbitMQ ne bloque jamais la décision d'accès.
            logger.warning(
                "Échec de publication RabbitMQ pour l'événement %s: %s", event.id, exc
            )

    def _send_to_rabbitmq(self, event: AccessEvent) -> None:
        params = pika.URLParameters(self._amqp_url)
        connection = pika.BlockingConnection(params)
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=EXCHANGE_NAME, exchange_type="topic", durable=True
            )
            routing_key = _ROUTING_KEYS.get(event.type, "access.other")
            channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=routing_key,
                body=json.dumps(_serialize(event)).encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json", delivery_mode=2
                ),
            )
        finally:
            connection.close()
