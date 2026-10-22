"""Implémentation alternative `EventPublisherPort` — RabbitMQ.

Compatible avec un broker RabbitMQ auto-hébergé (`amqp://...`) OU un broker
hébergé type **CloudAMQP** (`amqps://...`, TLS) — c'est ce dernier qui est
utilisé pour connecter Access au bus d'événements partagé de l'équipe
("microservice-event-bus"), chaque microservice publiant sous sa propre
routing key (`access.*` pour Access, `vehicles.*` pour Vehicles, etc.) sur
le même exchange, afin que n'importe quel service intéressé puisse y
brancher sa propre queue (ex. bind sur `access.#` pour tout recevoir).

Activation : dans `.env` (local) ou dans les variables d'environnement
Render (production), `EVENT_PUBLISHER=rabbitmq` + `RABBITMQ_URL` pointant
vers le broker (`amqps://user:pass@host/vhost` pour CloudAMQP). Le point de
bascule est dans `deps.py::get_event_publisher()`.

Comme `OutboxEventPublisher`, cette implémentation persiste TOUJOURS
l'événement (source de vérité, `access_events` + `outbox_events`) avant de
tenter la diffusion : un souci RabbitMQ est loggé mais ne bloque jamais la
décision d'accès (cf. section 3 point 3 de la spec — "pas de garantie de
livraison, acceptable pour le MVP", pas de reprise après incident).

⚠️ `exchange_declare(..., passive=True)` — l'exchange partagé
("microservice-event-bus") est créé et administré ailleurs (par l'équipe /
un autre service), Access ne doit jamais essayer de le (re)créer avec ses
propres paramètres : ça déclenche une erreur `406 PRECONDITION_FAILED` si
les paramètres ne correspondent pas exactement à ceux déjà en place.
`passive=True` se contente de vérifier que l'exchange existe.

⚠️ TLS : pour un `amqps://` (CloudAMQP), on fournit explicitement le magasin
de certificats `certifi` plutôt que de compter sur le magasin système —
certains environnements (ex. certains interpréteurs Python sur macOS) n'ont
pas de certificats CA configurés par défaut et échouent sinon avec
`CERTIFICATE_VERIFY_FAILED`. Comportement inchangé pour un `amqp://` non
chiffré (ex. RabbitMQ local en Docker).
"""

from __future__ import annotations

import json
import logging
import ssl

import certifi
import pika
from pika.exceptions import AMQPError

from src.domain.entities.access_event import AccessEvent
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.value_objects.enums import EventType
from src.infrastructure.db.repositories.sqlite_outbox_repository import (
    SqliteOutboxRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_EXCHANGE_NAME = "microservice-event-bus"
DEFAULT_ROUTING_PREFIX = "access"


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
        exchange_name: str = DEFAULT_EXCHANGE_NAME,
        routing_prefix: str = DEFAULT_ROUTING_PREFIX,
    ) -> None:
        self._access_repo = access_repo
        self._outbox_repo = outbox_repo
        self._amqp_url = amqp_url
        self._exchange_name = exchange_name
        self._routing_keys: dict[EventType, str] = {
            EventType.VEHICLE_ENTERED: f"{routing_prefix}.entry",
            EventType.VEHICLE_EXITED: f"{routing_prefix}.exit",
            EventType.ACCESS_REFUSED: f"{routing_prefix}.refused",
            EventType.OTHER: f"{routing_prefix}.other",
        }

    def publish(self, event: AccessEvent) -> None:
        self._access_repo.save_event(event)
        self._outbox_repo.record_publication(event.id)

        try:
            self._send_to_rabbitmq(event)
        except AMQPError as exc:
            # Best-effort : un souci RabbitMQ ne bloque jamais la décision d'accès.
            logger.warning("Échec de publication RabbitMQ pour l'événement %s: %s", event.id, exc)

    def _connection_params(self) -> pika.URLParameters:
        params = pika.URLParameters(self._amqp_url)
        if self._amqp_url.startswith("amqps://"):
            context = ssl.create_default_context(cafile=certifi.where())
            params.ssl_options = pika.SSLOptions(context)
        return params

    def _send_to_rabbitmq(self, event: AccessEvent) -> None:
        connection = pika.BlockingConnection(self._connection_params())
        try:
            channel = connection.channel()
            # Ne JAMAIS déclarer activement : l'exchange partagé existe déjà,
            # créé/administré ailleurs (cf. docstring du module).
            channel.exchange_declare(exchange=self._exchange_name, passive=True)
            routing_key = self._routing_keys.get(event.type, f"{DEFAULT_ROUTING_PREFIX}.other")
            channel.basic_publish(
                exchange=self._exchange_name,
                routing_key=routing_key,
                body=json.dumps(_serialize(event)).encode("utf-8"),
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            )
        finally:
            connection.close()
