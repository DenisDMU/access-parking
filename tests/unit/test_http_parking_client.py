"""Tests unitaires — fonctions pures de `http_parking_client.py`
(mapping catégorie), sans appel réseau au vrai service Parking."""

from src.domain.value_objects.dto import VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_parking_client import (
    _map_category,
    _place_type_from_category,
)

FOUR = VehicleCategory.FOUR_WHEELER
TWO = VehicleCategory.TWO_WHEELER


def test_map_category_standard():
    assert _map_category(VehicleType(category=FOUR)) == "STANDARD"


def test_map_category_xl():
    assert _map_category(VehicleType(category=FOUR, is_xl=True)) == "XL"


def test_map_category_electric():
    assert _map_category(VehicleType(category=FOUR, is_electric=True)) == "ELECTRIC"


def test_map_category_handicapped():
    assert _map_category(VehicleType(category=FOUR, is_handicap=True)) == "HANDICAPPED"


def test_map_category_two_wheels():
    assert _map_category(VehicleType(category=TWO)) == "TWO_WHEELS"


def test_map_category_priority_handicapped_over_everything_else():
    vehicle = VehicleType(category=FOUR, is_xl=True, is_electric=True, is_handicap=True)
    assert _map_category(vehicle) == "HANDICAPPED"


def test_place_type_from_category_roundtrips_each_category():
    for category in ("STANDARD", "XL", "ELECTRIC", "HANDICAPPED", "TWO_WHEELS"):
        vehicle = VehicleType(
            category=TWO if category == "TWO_WHEELS" else FOUR,
            is_xl=category == "XL",
            is_electric=category == "ELECTRIC",
            is_handicap=category == "HANDICAPPED",
        )
        place = _place_type_from_category(category)
        assert _map_category(vehicle) == category
        assert place.is_xl == vehicle.is_xl
        assert place.is_electric == vehicle.is_electric
        assert place.is_handicap == vehicle.is_handicap
        assert place.category == vehicle.category
