"""Mock du service Vehicles.

Interface strictement identique à ce qu'aurait un vrai client HTTP
(`VehiclesServicePort`) — remplacer ce mock par un vrai appel ne touche que
ce fichier (cf. README, "Comment brancher un vrai microservice").

Registre fixe et déterministe de plaques "connues", pensé pour exercer
chaque branche des règles métier en test manuel (Swagger/Postman) comme en
test automatisé :

| Plaque       | vehicule_id            | Profil                                   |
|--------------|-------------------------|-------------------------------------------|
| AA-111-AA    | v_normal_4roues         | 4 roues standard                          |
| BB-222-BB    | v_2roues                | 2 roues                                   |
| CC-333-CC    | v_xl                    | 4 roues XL                                |
| DD-444-DD    | v_electric              | 4 roues électrique                        |
| EE-555-EE    | v_handicap_ok           | 4 roues handicapé, justificatif PMR OK    |
| FF-666-FF    | v_handicap_no_just      | 4 roues handicapé, SANS justificatif PMR  |
| GG-777-GG    | v_with_reservation      | 4 roues standard, a une réservation active|
| HH-888-HH    | v_payment_fail          | 4 roues standard, paiement toujours refusé|
| autre plaque | —                       | inconnue (None)                           |
"""

from __future__ import annotations

from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import VehicleCategory

_REGISTRY: dict[str, VehicleInfo] = {
    "AA-111-AA": VehicleInfo(
        vehicule_id="v_normal_4roues",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES),
        justificatif_pmr=False,
    ),
    "BB-222-BB": VehicleInfo(
        vehicule_id="v_2roues",
        type_vehicule=VehicleType(category=VehicleCategory.DEUX_ROUES),
        justificatif_pmr=False,
    ),
    "CC-333-CC": VehicleInfo(
        vehicule_id="v_xl",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES, is_xl=True),
        justificatif_pmr=False,
    ),
    "DD-444-DD": VehicleInfo(
        vehicule_id="v_electric",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES, is_electric=True),
        justificatif_pmr=False,
    ),
    "EE-555-EE": VehicleInfo(
        vehicule_id="v_handicap_ok",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True),
        justificatif_pmr=True,
    ),
    "FF-666-FF": VehicleInfo(
        vehicule_id="v_handicap_no_just",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True),
        justificatif_pmr=False,
    ),
    "GG-777-GG": VehicleInfo(
        vehicule_id="v_with_reservation",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES),
        justificatif_pmr=False,
    ),
    "HH-888-HH": VehicleInfo(
        vehicule_id="v_payment_fail",
        type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES),
        justificatif_pmr=False,
    ),
}


class MockVehiclesClient:
    """Implémente `VehiclesServicePort`."""

    def get_vehicle_info(self, plaque_brute: str) -> VehicleInfo | None:
        return _REGISTRY.get(plaque_brute)
