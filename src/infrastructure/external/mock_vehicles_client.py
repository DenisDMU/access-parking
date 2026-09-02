"""Mock du service Vehicles.

Interface strictement identique à ce qu'aurait un vrai client HTTP
(`VehiclesServicePort`) — remplacer ce mock par un vrai appel ne touche
aucune autre couche (domain/application/interfaces), conformément à
l'architecture hexagonale — voir README section 5.

Registre fixe et déterministe de plaques "connues", pensé pour exercer
chaque branche des règles métier en test manuel (Swagger/Postman) comme en
test automatisé :

| Plaque       | vehicle_id              | Profil                                   |
|--------------|--------------------------|-------------------------------------------|
| AA-111-AA    | v_standard_4wheeler      | 4 roues standard                          |
| BB-222-BB    | v_2wheeler               | 2 roues                                   |
| CC-333-CC    | v_xl                     | 4 roues XL                                |
| DD-444-DD    | v_electric               | 4 roues électrique                        |
| EE-555-EE    | v_disabled_ok            | 4 roues handicapé, justificatif OK        |
| FF-666-FF    | v_disabled_no_permit     | 4 roues handicapé, SANS justificatif      |
| GG-777-GG    | v_with_reservation       | 4 roues standard, a une réservation active|
| HH-888-HH    | v_payment_fail           | 4 roues standard, paiement toujours refusé|
| autre plaque | —                        | inconnue (None)                           |
"""

from __future__ import annotations

from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import VehicleCategory

_REGISTRY: dict[str, VehicleInfo] = {
    "AA-111-AA": VehicleInfo(
        vehicle_id="v_standard_4wheeler",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
        disability_permit=False,
    ),
    "BB-222-BB": VehicleInfo(
        vehicle_id="v_2wheeler",
        vehicle_type=VehicleType(category=VehicleCategory.TWO_WHEELER),
        disability_permit=False,
    ),
    "CC-333-CC": VehicleInfo(
        vehicle_id="v_xl",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_xl=True),
        disability_permit=False,
    ),
    "DD-444-DD": VehicleInfo(
        vehicle_id="v_electric",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_electric=True),
        disability_permit=False,
    ),
    "EE-555-EE": VehicleInfo(
        vehicle_id="v_disabled_ok",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
        disability_permit=True,
    ),
    "FF-666-FF": VehicleInfo(
        vehicle_id="v_disabled_no_permit",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
        disability_permit=False,
    ),
    "GG-777-GG": VehicleInfo(
        vehicle_id="v_with_reservation",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
        disability_permit=False,
    ),
    "HH-888-HH": VehicleInfo(
        vehicle_id="v_payment_fail",
        vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
        disability_permit=False,
    ),
}


class MockVehiclesClient:
    """Implémente `VehiclesServicePort`."""

    def get_vehicle_info(self, raw_plate: str) -> VehicleInfo | None:
        return _REGISTRY.get(raw_plate)
