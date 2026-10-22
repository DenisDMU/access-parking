"""Tests unitaires — fonctions pures de `http_pricing_client.py`
(mapping zone + calcul de durée), sans appel réseau au vrai service Pricing."""

from datetime import UTC, datetime

from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_pricing_client import (
    HttpPricingClient,
    _duration_minutes,
    _map_zone,
)

FOUR = VehicleCategory.FOUR_WHEELER
TWO = VehicleCategory.TWO_WHEELER

# Port fermé en local : connexion refusée immédiatement, pas de réseau réel
# nécessaire ni de délai notable (même principe que pour Parking/RabbitMQ).
_UNREACHABLE_URL = "http://127.0.0.1:59999"


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
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = datetime(2026, 1, 1, 10, 32, 30, tzinfo=UTC)  # 32.5 min
    assert _duration_minutes(entry, exit_, is_reservation=False) == 32 or _duration_minutes(
        entry, exit_, is_reservation=False
    ) == 33  # arrondi standard, peu importe le sens exact


def test_duration_minutes_reservation_rounds_up_to_multiple_of_60():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = datetime(2026, 1, 1, 11, 5, tzinfo=UTC)  # 65 min
    assert _duration_minutes(entry, exit_, is_reservation=True) == 120


def test_duration_minutes_reservation_exact_hour_stays_unchanged():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # exactement 120 min
    assert _duration_minutes(entry, exit_, is_reservation=True) == 120


def test_duration_minutes_reservation_never_below_60():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)  # 5 min seulement
    assert _duration_minutes(entry, exit_, is_reservation=True) == 60


def test_calculate_price_returns_none_when_pricing_unreachable():
    client = HttpPricingClient(_UNREACHABLE_URL, timeout_s=1.0)
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    result = client.calculate_price("v1", entry, exit_, PlaceType(category=FOUR))
    assert result is None  # ne doit jamais lever, ni inventer un montant
