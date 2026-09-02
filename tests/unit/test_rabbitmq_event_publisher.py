"""Tests unitaires — `RabbitMQEventPublisher`.

Aucun vrai broker n'est nécessaire pour ces tests : ils vérifient le
comportement "best-effort" (section 3 point 3 de la spec) — un broker
injoignable est loggé mais ne doit jamais empêcher la persistance de
l'événement ni lever d'exception vers l'appelant.
"""

from datetime import datetime, timezone

from src.domain.entities.access_event import AccessEvent
from src.domain.value_objects.enums import EventType
from src.infrastructure.events.rabbitmq_event_publisher import RabbitMQEventPublisher
from tests.unit.fakes import FakeAccessRepo

# Port fermé en local : la connexion échoue immédiatement (connexion refusée),
# pas de délai d'attente notable.
_UNREACHABLE_AMQP_URL = "amqp://guest:guest@127.0.0.1:59999/%2F?connection_attempts=1"


class _FakeOutboxRepo:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record_publication(self, event_id: str) -> None:
        self.recorded.append(event_id)


def _make_event() -> AccessEvent:
    return AccessEvent(
        id="evt-1",
        type=EventType.VEHICLE_ENTERED,
        request_id="request-1",
        payload={"vehicleId": "v1"},
        created_at=datetime.now(timezone.utc),
    )


def test_publish_persists_even_if_broker_unreachable():
    access_repo = FakeAccessRepo()
    outbox_repo = _FakeOutboxRepo()
    publisher = RabbitMQEventPublisher(
        access_repo=access_repo, outbox_repo=outbox_repo, amqp_url=_UNREACHABLE_AMQP_URL
    )
    event = _make_event()

    publisher.publish(event)  # ne doit jamais lever, même sans broker

    assert access_repo.events["request-1"] is event
    assert outbox_repo.recorded == ["evt-1"]


def test_publish_never_raises_for_any_event_type():
    access_repo = FakeAccessRepo()
    outbox_repo = _FakeOutboxRepo()
    publisher = RabbitMQEventPublisher(
        access_repo=access_repo, outbox_repo=outbox_repo, amqp_url=_UNREACHABLE_AMQP_URL
    )

    for event_type in EventType:
        event = AccessEvent(
            id=f"evt-{int(event_type)}",
            type=event_type,
            request_id=f"request-{int(event_type)}",
            payload={},
            created_at=datetime.now(timezone.utc),
        )
        publisher.publish(event)

    assert len(outbox_repo.recorded) == len(list(EventType))
