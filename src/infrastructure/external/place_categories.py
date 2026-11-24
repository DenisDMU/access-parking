"""Codes de type de place partagés par Parking et Booking.

Les deux services de l'équipe utilisent les mêmes codes (`STANDARD`, `XL`,
`ELECTRIC`, `HANDICAPPED`, `TWO_WHEELS`) : un seul endroit pour les
traduire dans le modèle d'Access (`PlaceType`).
"""

from __future__ import annotations

from src.domain.value_objects.dto import PlaceType, VehicleType
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


def code_from_place_type(place_type: PlaceType | VehicleType) -> str:
    """Inverse de `place_type_from_code` : une place → un des 5 codes, dans
    l'ordre de priorité de Parking et Pricing (PMR, deux-roues, électrique,
    XL, standard)."""

    if place_type.is_handicap:
        return "HANDICAPPED"
    if place_type.category is VehicleCategory.TWO_WHEELER:
        return "TWO_WHEELS"
    if place_type.is_electric:
        return "ELECTRIC"
    if place_type.is_xl:
        return "XL"
    return "STANDARD"


def code_of_place(place_id: str | None, place_type: PlaceType | None) -> str | None:
    """Catégorie d'une place attribuée : préfixe de `place_id`
    (`"XL:booking"`), sinon déduite de son type ; `None` si rien n'est connu."""

    if place_id and ":" in place_id:
        return place_id.split(":", 1)[0].upper()
    return code_from_place_type(place_type) if place_type is not None else None
