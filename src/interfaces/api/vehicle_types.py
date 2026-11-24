"""Type de véhicule déclaré à la borne : code d'API → `VehicleType` du domaine."""

from __future__ import annotations

from src.domain.value_objects.dto import VehicleType
from src.domain.value_objects.enums import VehicleCategory


def declared_vehicle_type(code: str | None) -> VehicleType | None:
    if code is None:
        return None
    return VehicleType(
        category=VehicleCategory.TWO_WHEELER
        if code == "TWO_WHEELS"
        else VehicleCategory.FOUR_WHEELER,
        is_xl=code == "XL",
        is_electric=code == "ELECTRIC",
        is_handicap=code == "HANDICAPPED",
    )
