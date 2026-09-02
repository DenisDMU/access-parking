"""Mock du service Booking.

Un seul véhicule du registre `mock_vehicles_client` (`v_with_reservation`,
plaque de démo `GG-777-GG`) a une réservation active, avec une place déjà
assignée — utile pour exercer le workflow "Réservation" du cadrage sans
repasser par Parking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.domain.value_objects.dto import PlaceType, Reservation
from src.domain.value_objects.enums import VehicleCategory

_RESERVATIONS: dict[str, Reservation] = {
    "v_with_reservation": Reservation(
        id="res-demo-1",
        vehicle_id="v_with_reservation",
        reserved_place_type=PlaceType(category=VehicleCategory.FOUR_WHEELER),
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(hours=2),
        place_id="P-RES-01",
    )
}


class MockBookingClient:
    """Implémente `BookingServicePort`."""

    def get_reservation(self, vehicle_id: str) -> Reservation | None:
        return _RESERVATIONS.get(vehicle_id)
