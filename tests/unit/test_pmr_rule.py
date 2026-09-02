"""Tests unitaires — règle PMR."""

from src.domain.rules.pmr_rule import requires_pmr_confirmation
from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory


def test_place_handicap_sans_justificatif_requiert_confirmation():
    place = PlaceType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True)
    assert requires_pmr_confirmation(place, justificatif_pmr=False) is True


def test_place_handicap_avec_justificatif_ne_requiert_pas_confirmation():
    place = PlaceType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True)
    assert requires_pmr_confirmation(place, justificatif_pmr=True) is False


def test_place_non_handicap_ne_requiert_jamais_confirmation():
    place = PlaceType(category=VehicleCategory.QUATRE_ROUES, is_handicap=False)
    assert requires_pmr_confirmation(place, justificatif_pmr=False) is False
    assert requires_pmr_confirmation(place, justificatif_pmr=True) is False
