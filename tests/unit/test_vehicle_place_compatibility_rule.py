"""Tests unitaires — matrice complète de compatibilité véhicule/place."""

import pytest

from src.domain.rules.vehicle_place_compatibility_rule import is_compatible
from src.domain.value_objects.dto import PlaceType, VehicleType
from src.domain.value_objects.enums import VehicleCategory

DEUX = VehicleCategory.DEUX_ROUES
QUATRE = VehicleCategory.QUATRE_ROUES


def veh(category=QUATRE, xl=False, electric=False, handicap=False) -> VehicleType:
    return VehicleType(category=category, is_xl=xl, is_electric=electric, is_handicap=handicap)


def place(category=QUATRE, xl=False, electric=False, handicap=False) -> PlaceType:
    return PlaceType(category=category, is_xl=xl, is_electric=electric, is_handicap=handicap)


def test_deux_roues_peut_occuper_place_quatre_roues():
    assert is_compatible(veh(category=DEUX), place(category=QUATRE)) is True


def test_deux_roues_peut_occuper_place_deux_roues():
    assert is_compatible(veh(category=DEUX), place(category=DEUX)) is True


def test_quatre_roues_ne_peut_pas_occuper_place_deux_roues():
    assert is_compatible(veh(category=QUATRE), place(category=DEUX)) is False


def test_quatre_roues_peut_occuper_place_quatre_roues():
    assert is_compatible(veh(category=QUATRE), place(category=QUATRE)) is True


def test_vehicule_electrique_peut_occuper_place_non_electrique():
    assert is_compatible(veh(electric=True), place(electric=False)) is True


def test_vehicule_electrique_peut_occuper_place_electrique():
    assert is_compatible(veh(electric=True), place(electric=True)) is True


def test_vehicule_non_electrique_ne_peut_pas_occuper_place_electrique():
    assert is_compatible(veh(electric=False), place(electric=True)) is False


def test_vehicule_xl_ne_peut_occuper_que_place_xl():
    assert is_compatible(veh(xl=True), place(xl=False)) is False
    assert is_compatible(veh(xl=True), place(xl=True)) is True


def test_vehicule_non_xl_peut_occuper_place_xl():
    assert is_compatible(veh(xl=False), place(xl=True)) is True


def test_vehicule_handicap_peut_occuper_place_handicap():
    assert is_compatible(veh(handicap=True), place(handicap=True)) is True


def test_vehicule_handicap_peut_occuper_place_xl():
    assert is_compatible(veh(handicap=True), place(xl=True)) is True


def test_vehicule_handicap_ne_peut_pas_occuper_place_normale():
    assert is_compatible(veh(handicap=True), place()) is False


def test_seul_vehicule_handicap_peut_occuper_place_handicap():
    assert is_compatible(veh(handicap=False), place(handicap=True)) is False


@pytest.mark.parametrize("xl", [False, True])
@pytest.mark.parametrize("electric", [False, True])
@pytest.mark.parametrize("handicap", [False, True])
@pytest.mark.parametrize("category", [DEUX, QUATRE])
def test_matrice_complete_ne_leve_jamais_exception(category, handicap, electric, xl):
    """Vérifie que la fonction reste pure et totale sur toute la matrice
    (aucune combinaison ne doit lever d'exception)."""

    for place_category in (DEUX, QUATRE):
        for place_xl in (False, True):
            for place_electric in (False, True):
                for place_handicap in (False, True):
                    result = is_compatible(
                        veh(category, xl, electric, handicap),
                        place(place_category, place_xl, place_electric, place_handicap),
                    )
                    assert isinstance(result, bool)
