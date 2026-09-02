"""Mock du service Parking.

`request_place` attribue une place dont le type correspond exactement aux
attributs du véhicule demandé (comportement "idéal", suffisant pour un
mock) : une place normale pour un véhicule normal, une place XL pour un
véhicule XL, une place handicapé pour un véhicule handicapé (que le
justificatif PMR soit fourni ou non — ce contrôle relève d'Access, pas de
Parking), etc. Les scénarios d'incompatibilité volontaire sont exercés dans
les tests via une implémentation de test dédiée (double), pas via ce mock.

L'occupation des places est suivie en mémoire (process-local) uniquement
pour donner un comportement cohérent en session de test manuelle — la
détection physique réelle de l'occupation est hors périmètre (section 1/16
de la spec).
"""

from __future__ import annotations

from itertools import count

from src.domain.value_objects.dto import PlaceAssignment, PlaceType, VehicleType

_place_id_counter = count(1)
_occupied_places: dict[str, str] = {}  # place_id -> vehicule_id


class MockParkingClient:
    """Implémente `ParkingServicePort`."""

    def request_place(self, type_vehicule: VehicleType) -> PlaceAssignment | None:
        place_id = f"P-{next(_place_id_counter):04d}"
        place_type = PlaceType(
            category=type_vehicule.category,
            is_xl=type_vehicule.is_xl,
            is_electric=type_vehicule.is_electric,
            is_handicap=type_vehicule.is_handicap,
        )
        return PlaceAssignment(place_id=place_id, place_type=place_type)

    def mark_place_occupied(self, place_id: str, vehicule_id: str) -> bool:
        _occupied_places[place_id] = vehicule_id
        return True

    def mark_place_free(self, place_id: str) -> bool:
        _occupied_places.pop(place_id, None)
        return True
