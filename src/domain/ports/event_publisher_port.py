"""Port de publication des Événements d'accès."""

from __future__ import annotations

from typing import Protocol

from src.domain.entities.access_event import AccessEvent


class EventPublisherPort(Protocol):
    def publish(self, event: AccessEvent) -> None:
        """Journalise puis diffuse l'événement. `payload` utilise `vehicleId`,
        jamais la plaque."""
        ...
