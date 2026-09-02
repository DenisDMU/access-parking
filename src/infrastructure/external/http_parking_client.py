"""Client HTTP réel vers le service **Parking** — SQUELETTE À FINALISER.

Implémente `ParkingServicePort`. Voir `http_vehicles_client.py` pour le
principe général d'activation (`USE_MOCKS=false` + `PARKING_SERVICE_URL`).

──────────────────────────────────────────────────────────────────────────
TODO avant mise en service — À valider avec l'équipe Parking :
  [ ] TODO[PARKING-1] Route + méthode de `request_place`.
      Hypothèse actuelle : POST {base_url}/places/allocate
      { "vehicleType": {category, isXl, isElectric, isHandicap} }
  [ ] TODO[PARKING-2] Code retourné si aucune place disponible.
      Hypothèse actuelle : 404 (ou 409 ?) — à confirmer.
  [ ] TODO[PARKING-3] Route + méthode de `mark_place_occupied` /
      `mark_place_free`. Hypothèses actuelles :
        POST {base_url}/places/{place_id}/occupy   { "vehicleId": ... }
        POST {base_url}/places/{place_id}/free
      et code de succès attendu (200 ? 204 ?).
  [ ] TODO[PARKING-4] Rappel section 1 du cadrage : "Les places sont gérées
      par nombre disponible par catégorie, pas d'affectation nominale" —
      vérifier si Parking renvoie bien un `placeId` réutilisable pour
      `mark_place_occupied`/`mark_place_free`, ou seulement une confirmation
      de type de place (auquel cas adapter le port + les use cases).
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import httpx

from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.value_objects.dto import PlaceAssignment, PlaceType, VehicleType
from src.domain.value_objects.enums import VehicleCategory


class HttpParkingClient:
    """Implémente `ParkingServicePort` via un vrai appel HTTP à Parking."""

    def __init__(self, base_url: str, timeout_s: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def request_place(self, vehicle_type: VehicleType) -> PlaceAssignment | None:
        # TODO[PARKING-1] confirmer route/méthode/forme du payload.
        payload = {
            "vehicleType": {
                "category": int(vehicle_type.category),
                "isXl": vehicle_type.is_xl,
                "isElectric": vehicle_type.is_electric,
                "isHandicap": vehicle_type.is_handicap,
            }
        }
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(f"{self._base_url}/places/allocate", json=payload)

        # TODO[PARKING-2] confirmer le code "aucune place disponible".
        if response.status_code in (404, 409):
            return None
        response.raise_for_status()

        data = response.json()
        place_type_data = data.get("placeType", {})
        return PlaceAssignment(
            place_id=data["placeId"],
            place_type=PlaceType(
                category=VehicleCategory(place_type_data.get("category", VehicleCategory.FOUR_WHEELER)),
                is_xl=place_type_data.get("isXl", False),
                is_electric=place_type_data.get("isElectric", False),
                is_handicap=place_type_data.get("isHandicap", False),
            ),
        )

    def mark_place_occupied(self, place_id: str, vehicle_id: str) -> bool:
        # TODO[PARKING-3] confirmer route/méthode/code de succès.
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(
                f"{self._base_url}/places/{place_id}/occupy", json={"vehicleId": vehicle_id}
            )
        return response.status_code < 300

    def mark_place_free(self, place_id: str) -> bool:
        # TODO[PARKING-3] confirmer route/méthode/code de succès.
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(f"{self._base_url}/places/{place_id}/free")
        return response.status_code < 300
