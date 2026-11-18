"""Client HTTP réel vers le service **Booking** — SQUELETTE À FINALISER.

Implémente `BookingServicePort`. Voir `http_vehicles_client.py` pour le
principe général d'activation (`USE_MOCKS=false` + `BOOKING_SERVICE_URL`).

──────────────────────────────────────────────────────────────────────────
TODO avant mise en service — À valider avec l'équipe Booking :
  [ ] TODO[BOOKING-1] Route + méthode HTTP exactes.
      Hypothèse actuelle : GET {base_url}/bookings/active?vehicleId=...
  [ ] TODO[BOOKING-2] Code retourné si pas de réservation active.
      Hypothèse actuelle : 404. Adapter si 200 + liste vide, etc.
  [ ] TODO[BOOKING-3] Noms exacts des champs (id, vehicleId, reservedPlaceType,
      startDate/endDate, placeId — cf. note dans `Reservation.place_id`,
      README section 12 "Écarts assumés" : notre modèle suppose que Booking
      peut déjà indiquer une place précise si la réservation en a une ;
      sinon laisser `placeId: null` et Access retombera sur Parking).
  [ ] TODO[BOOKING-4] Format des dates (ISO 8601 attendu par
      `datetime.fromisoformat`, avec fuseau explicite de préférence).
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from src.domain.value_objects.dto import PlaceType, Reservation
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.outgoing_http import outgoing_client

logger = logging.getLogger(__name__)


class HttpBookingClient:
    """Implémente `BookingServicePort` via un vrai appel HTTP à Booking."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport  # injecté par les tests (httpx.MockTransport)

    def get_reservation(self, vehicle_id: str) -> Reservation | None:
        # TODO[BOOKING-1] confirmer route/méthode avec l'équipe Booking.
        try:
            with outgoing_client(
                "booking", timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = client.get(
                    f"{self._base_url}/bookings/active", params={"vehicleId": vehicle_id}
                )

            # TODO[BOOKING-2] confirmer le code "pas de réservation" (404 supposé).
            if response.status_code == 404:
                return None
            response.raise_for_status()

            # TODO[BOOKING-3] adapter le mapping de champs à la réponse réelle.
            data = response.json()
            return self._to_reservation(vehicle_id, data)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # Booking indisponible ou réponse inattendue : on poursuit comme
            # une entrée sans réservation (Parking attribue une place) plutôt
            # que de renvoyer une 500 — même principe que les autres clients.
            logger.warning("Booking indisponible, entrée traitée sans réservation : %r", exc)
            return None

    @staticmethod
    def _to_reservation(vehicle_id: str, data: dict) -> Reservation:
        place_type_data = data.get("reservedPlaceType", {})
        return Reservation(
            id=data["id"],
            vehicle_id=vehicle_id,
            reserved_place_type=PlaceType(
                category=VehicleCategory(
                    place_type_data.get("category", VehicleCategory.FOUR_WHEELER)
                ),
                is_xl=place_type_data.get("isXl", False),
                is_electric=place_type_data.get("isElectric", False),
                is_handicap=place_type_data.get("isHandicap", False),
            ),
            # TODO[BOOKING-4] confirmer le format de date exact renvoyé.
            start_date=datetime.fromisoformat(data["startDate"]),
            end_date=datetime.fromisoformat(data["endDate"]),
            place_id=data.get("placeId"),
        )
