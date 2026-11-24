"""Port vers le service Booking."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.domain.value_objects.dto import Reservation


class BookingServicePort(Protocol):
    def get_reservation(self, vehicle_id: str, at: datetime | None = None) -> Reservation | None:
        """Réservation confirmée qui couvre l'instant `at` (le passage) pour ce
        véhicule pseudonymisé, ou `None`. `at=None` : maintenant.

        Ne lève jamais : Booking indisponible = pas de réservation (l'entrée
        se fait alors comme une entrée sans réservation).
        """
        ...
