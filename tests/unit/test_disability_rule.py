"""Tests unitaires — règle d'accessibilité (PMR)."""

from src.domain.rules.disability_rule import requires_disability_confirmation
from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory


def test_disabled_place_without_permit_requires_confirmation():
    place = PlaceType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True)
    assert requires_disability_confirmation(place, disability_permit=False) is True


def test_disabled_place_with_permit_does_not_require_confirmation():
    place = PlaceType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True)
    assert requires_disability_confirmation(place, disability_permit=True) is False


def test_non_disabled_place_never_requires_confirmation():
    place = PlaceType(category=VehicleCategory.FOUR_WHEELER, is_handicap=False)
    assert requires_disability_confirmation(place, disability_permit=False) is False
    assert requires_disability_confirmation(place, disability_permit=True) is False
