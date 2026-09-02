"""Tests unitaires — matrice complète de compatibilité véhicule/place."""

import pytest

from src.domain.rules.vehicle_place_compatibility_rule import is_compatible
from src.domain.value_objects.dto import PlaceType, VehicleType
from src.domain.value_objects.enums import VehicleCategory

TWO = VehicleCategory.TWO_WHEELER
FOUR = VehicleCategory.FOUR_WHEELER


def veh(category=FOUR, xl=False, electric=False, handicap=False) -> VehicleType:
    return VehicleType(category=category, is_xl=xl, is_electric=electric, is_handicap=handicap)


def place(category=FOUR, xl=False, electric=False, handicap=False) -> PlaceType:
    return PlaceType(category=category, is_xl=xl, is_electric=electric, is_handicap=handicap)


def test_two_wheeler_can_use_four_wheeler_place():
    assert is_compatible(veh(category=TWO), place(category=FOUR)) is True


def test_two_wheeler_can_use_two_wheeler_place():
    assert is_compatible(veh(category=TWO), place(category=TWO)) is True


def test_four_wheeler_cannot_use_two_wheeler_place():
    assert is_compatible(veh(category=FOUR), place(category=TWO)) is False


def test_four_wheeler_can_use_four_wheeler_place():
    assert is_compatible(veh(category=FOUR), place(category=FOUR)) is True


def test_electric_vehicle_can_use_non_electric_place():
    assert is_compatible(veh(electric=True), place(electric=False)) is True


def test_electric_vehicle_can_use_electric_place():
    assert is_compatible(veh(electric=True), place(electric=True)) is True


def test_non_electric_vehicle_cannot_use_electric_place():
    assert is_compatible(veh(electric=False), place(electric=True)) is False


def test_xl_vehicle_can_only_use_xl_place():
    assert is_compatible(veh(xl=True), place(xl=False)) is False
    assert is_compatible(veh(xl=True), place(xl=True)) is True


def test_non_xl_vehicle_can_use_xl_place():
    assert is_compatible(veh(xl=False), place(xl=True)) is True


def test_disabled_vehicle_can_use_disabled_place():
    assert is_compatible(veh(handicap=True), place(handicap=True)) is True


def test_disabled_vehicle_can_use_xl_place():
    assert is_compatible(veh(handicap=True), place(xl=True)) is True


def test_disabled_vehicle_cannot_use_standard_place():
    assert is_compatible(veh(handicap=True), place()) is False


def test_only_disabled_vehicle_can_use_disabled_place():
    assert is_compatible(veh(handicap=False), place(handicap=True)) is False


@pytest.mark.parametrize("xl", [False, True])
@pytest.mark.parametrize("electric", [False, True])
@pytest.mark.parametrize("handicap", [False, True])
@pytest.mark.parametrize("category", [TWO, FOUR])
def test_full_matrix_never_raises(category, handicap, electric, xl):
    """Vérifie que la fonction reste pure et totale sur toute la matrice
    (aucune combinaison ne doit lever d'exception)."""

    for place_category in (TWO, FOUR):
        for place_xl in (False, True):
            for place_electric in (False, True):
                for place_handicap in (False, True):
                    result = is_compatible(
                        veh(category, xl, electric, handicap),
                        place(place_category, place_xl, place_electric, place_handicap),
                    )
                    assert isinstance(result, bool)
