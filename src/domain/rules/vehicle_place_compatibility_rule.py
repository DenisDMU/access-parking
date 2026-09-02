"""Règle de compatibilité véhicule / place (règle du projet fil rouge).

Fonction pure, sans aucune dépendance — testée unitairement sur toute la
matrice (section 5 et 13 de la spec) :

- Un 2 roues peut occuper une place 4 roues.
- Un 4 roues ne peut occuper une place 2 roues.
- Un véhicule électrique peut occuper une place non-électrique.
- Un véhicule non-électrique ne peut occuper une place électrique.
- Un véhicule XL ne peut occuper qu'une place XL.
- Un véhicule handicapé peut occuper une place handicapé ou XL.
- Seul un véhicule handicapé peut occuper une place handicapé.
"""

from __future__ import annotations

from src.domain.value_objects.dto import PlaceType, VehicleType
from src.domain.value_objects.enums import VehicleCategory


def is_compatible(vehicle_type: VehicleType, place_type: PlaceType) -> bool:
    """Retourne `True` si `vehicle_type` peut occuper `place_type`."""

    # Un 4 roues ne peut pas occuper une place 2 roues (l'inverse est permis).
    if (
        vehicle_type.category is VehicleCategory.QUATRE_ROUES
        and place_type.category is VehicleCategory.DEUX_ROUES
    ):
        return False

    # Un véhicule non-électrique ne peut pas occuper une place électrique.
    if place_type.is_electric and not vehicle_type.is_electric:
        return False

    # Un véhicule XL ne peut occuper qu'une place XL.
    if vehicle_type.is_xl and not place_type.is_xl:
        return False

    # Seul un véhicule handicapé peut occuper une place handicapé.
    if place_type.is_handicap and not vehicle_type.is_handicap:
        return False

    # Un véhicule handicapé ne peut occuper qu'une place handicapé ou XL.
    if vehicle_type.is_handicap and not (place_type.is_handicap or place_type.is_xl):
        return False

    return True
