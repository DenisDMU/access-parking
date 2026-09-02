"""Mock du service Booking.

Un seul véhicule du registre `mock_vehicles_client` (`v_with_reservation`,
plaque de démo `GG-777-GG`) a une réservation active, utile pour exercer le
workflow "Réservation" du cadrage.

`place_id=None` (aucune place déjà assignée) : c'est le cas normal depuis
l'intégration du vrai service Parking, qui ne gère aucun identifiant de
place individuel (juste des compteurs par catégorie, cf.
`http_parking_client.py`) — le use case retombe donc systématiquement sur
`ParkingServicePort.request_place(..., is_reservation=True)`, qui appelle
réellement Parking avec `commercial_type="booking"`. Un `place_id` fixe
type "P-RES-01" (comme avant l'intégration réelle) casserait
`HttpParkingClient.mark_place_occupied`/`mark_place_free`, qui attendent le
format `"{category_name}:{commercial_type}"`.
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
        place_id=None,
    )
}


class MockBookingClient:
    """Implémente `BookingServicePort`."""

    def get_reservation(self, vehicle_id: str) -> Reservation | None:
        return _RESERVATIONS.get(vehicle_id)
