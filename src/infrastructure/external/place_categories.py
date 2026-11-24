"""Codes de type de place partagés par Parking et Booking.

Les deux services de l'équipe utilisent les mêmes codes (`STANDARD`, `XL`,
`ELECTRIC`, `HANDICAPPED`, `TWO_WHEELS`) : un seul endroit pour les
traduire dans le modèle d'Access (`PlaceType`).
"""

from __future__ import annotations

from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory


def place_type_from_code(code: str) -> PlaceType:
    """`ELECTRIC` → place 4 roues électrique ; code inconnu → place standard."""

    code = code.upper()
    return PlaceType(
        category=VehicleCategory.TWO_WHEELER
        if code == "TWO_WHEELS"
        else VehicleCategory.FOUR_WHEELER,
        is_xl=code == "XL",
        is_electric=code == "ELECTRIC",
        is_handicap=code == "HANDICAPPED",
    )
