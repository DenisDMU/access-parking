"""Port de publication des Événements d'accès."""

from __future__ import annotations

from typing import Protocol

from src.domain.entities.evenement_acces import EvenementAcces


class EventPublisherPort(Protocol):
    def publish(self, evenement: EvenementAcces) -> None:
        """Journalise puis diffuse l'événement. `payload` utilise `vehiculeId`,
        jamais la plaque."""
        ...
