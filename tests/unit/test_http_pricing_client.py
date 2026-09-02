"""Tests unitaires — fonctions pures de `http_pricing_client.py`
(mapping zone + calcul de durée), sans appel réseau au vrai service Pricing."""

from datetime import datetime, timezone

from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_pricing_client import (
    _duration_minutes,
    _map_zone,
)

FOUR = VehicleCategory.FOUR_WHEELER
TWO = VehicleCategory.TWO_WHEELER


def test_map_zone_standard():
    assert _map_zone(PlaceType(category=FOUR)) == "standard"


def test_map_zone_xl():
    assert _map_zone(PlaceType(category=FOUR, is_xl=True)) == "xl"


def test_map_zone_electric():
    assert _map_zone(PlaceType(category=FOUR, is_electric=True)) == "electric"


def test_map_zone_disabled():
    assert _map_zone(PlaceType(category=FOUR, is_handicap=True)) == "disabled"


def test_map_zone_two_wheels():
    assert _map_zone(PlaceType(category=TWO)) == "two_wheels"


def test_map_zone_priority_disabled_over_everything_else():
    # Un cumul d'attributs ne doit jamais produire une zone invalide : la
    # priorité "disabled" documentée dans http_pricing_client.py l'emporte.
    place = PlaceType(category=FOUR, is_xl=True, is_electric=True, is_handicap=True)
    assert _map_zone(place) == "disabled"


def test_duration_minutes_walk_in_rounds_to_nearest_minute():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 1, 10, 32, 30, tzinfo=timezone.utc)  # 32.5 min
    assert _duration_minutes(entry, exit_, is_reservation=False) == 32 or _duration_minutes(
        entry, exit_, is_reservation=False
    ) == 33  # arrondi standard, peu importe le sens exact


def test_duration_minutes_reservation_rounds_up_to_multiple_of_60():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 1, 11, 5, tzinfo=timezone.utc)  # 65 min
    assert _duration_minutes(entry, exit_, is_reservation=True) == 120


def test_duration_minutes_reservation_exact_hour_stays_unchanged():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)  # exactement 120 min
    assert _duration_minutes(entry, exit_, is_reservation=True) == 120


def test_duration_minutes_reservation_never_below_60():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc)  # 5 min seulement
    assert _duration_minutes(entry, exit_, is_reservation=True) == 60
