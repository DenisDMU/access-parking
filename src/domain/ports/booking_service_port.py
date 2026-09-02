"""Port vers le service Booking."""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import Reservation


class BookingServicePort(Protocol):
    def get_reservation(self, vehicule_id: str) -> Reservation | None:
        """Réservation active pour ce véhicule pseudonymisé, si elle existe."""
        ...
