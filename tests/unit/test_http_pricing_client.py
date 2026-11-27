"""Tests unitaires — fonctions pures de `http_pricing_client.py`
(mapping zone + calcul de durée), sans appel réseau au vrai service Pricing."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_pricing_client import (
    MAX_STAY_MINUTES,
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


def test_map_zone_handicapped():
    # Grille Pricing v2 (24/11) : la zone PMR s'appelle `handicapped`.
    assert _map_zone(PlaceType(category=FOUR, is_handicap=True)) == "handicapped"


def test_map_zone_two_wheels():
    assert _map_zone(PlaceType(category=TWO)) == "two_wheels"


def test_map_zone_priority_handicapped_over_everything_else():
    # Un cumul d'attributs ne doit jamais produire une zone invalide : la
    # priorité PMR documentée dans http_pricing_client.py l'emporte.
    place = PlaceType(category=FOUR, is_xl=True, is_electric=True, is_handicap=True)
    assert _map_zone(place) == "handicapped"


def test_duration_minutes_walk_in_arrondie_a_la_minute_superieure():
    """« Tout quart d'heure entamé est dû » : on ne perd jamais de secondes."""

    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = datetime(2026, 1, 1, 10, 32, 1, tzinfo=UTC)  # 32 min 1 s
    assert _duration_minutes(entry, exit_, is_reservation=False) == 33


def test_sortie_immediate_donne_au_moins_une_minute():
    """Bug corrigé : 0 minute était refusé par Pricing (422) et bloquait la sortie."""

    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert _duration_minutes(entry, entry, is_reservation=False) == 1
    assert _duration_minutes(entry, entry + timedelta(seconds=20), is_reservation=False) == 1


def test_duree_plafonnee_a_sept_jours():
    """Règle 2.4 : plafond de 7 jours (Pricing refuse au-delà de 10 080 min)."""

    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = entry + timedelta(days=12)
    assert _duration_minutes(entry, exit_, is_reservation=False) == MAX_STAY_MINUTES == 10080
    assert _duration_minutes(entry, exit_, is_reservation=True) == 10080


def test_sept_jours_pile_non_modifies():
    entry = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    exit_ = entry + timedelta(days=7)
    assert _duration_minutes(entry, exit_, is_reservation=False) == 10080


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


# --- Zones (faux Pricing, httpx.MockTransport) ------------------------------------

_ENTRY = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
_EXIT = _ENTRY + timedelta(minutes=90)
_PMR = PlaceType(category=FOUR, is_handicap=True)


class _FakePricing:
    def __init__(self, zones: set[str]) -> None:
        self.zones = zones
        self.sent: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        zone = json.loads(request.content)["zone"]
        self.sent.append(zone)
        if zone not in self.zones:
            return httpx.Response(404, json={"code": "ZONE_NOT_FOUND", "message": zone})
        return httpx.Response(201, json={"amount_eur": "0.75", "currency": "EUR"})


def _pricing(handler) -> HttpPricingClient:
    return HttpPricingClient("https://pricing.test", transport=httpx.MockTransport(handler))


def test_sortie_pmr_tarifee_avec_la_zone_handicapped():
    pricing = _FakePricing({"standard", "handicapped"})
    assert _pricing(pricing).calculate_price("v1", _ENTRY, _EXIT, _PMR) == Decimal("0.75")
    assert pricing.sent == ["handicapped"]


def test_ancien_nom_de_zone_essaye_si_pricing_revient_en_arriere():
    pricing = _FakePricing({"standard", "disabled"})
    assert _pricing(pricing).calculate_price("v1", _ENTRY, _EXIT, _PMR) == Decimal("0.75")
    assert pricing.sent == ["handicapped", "disabled"]


def test_zone_inconnue_sous_tous_ses_noms():
    pricing = _FakePricing({"standard"})
    assert _pricing(pricing).calculate_price("v1", _ENTRY, _EXIT, _PMR) is None
    assert pricing.sent == ["handicapped", "disabled"]


def test_zone_sans_alias_un_seul_appel():
    pricing = _FakePricing({"handicapped"})
    assert _pricing(pricing).calculate_price("v1", _ENTRY, _EXIT, PlaceType(category=FOUR)) is None
    assert pricing.sent == ["standard"]


def test_autre_404_pas_de_nouvel_essai():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(404, text="Not Found")

    assert _pricing(handler).calculate_price("v1", _ENTRY, _EXIT, _PMR) is None
    assert len(sent) == 1


def test_reponse_sans_montant():
    client = _pricing(lambda r: httpx.Response(201, json={"currency": "EUR"}))
    assert client.calculate_price("v1", _ENTRY, _EXIT, _PMR) is None


# --- Clé d'API ---------------------------------------------------------------


def test_cle_envoyee_a_pricing_seulement_si_elle_est_renseignee():
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-API-Key"))
        return httpx.Response(201, json={"amount_eur": "0.75"})

    with_key = HttpPricingClient(
        "https://pricing.test",
        api_key="cle-de-test-pricing",
        transport=httpx.MockTransport(handler),
    )
    assert with_key.calculate_price("v1", _ENTRY, _EXIT, PlaceType(category=FOUR)) == Decimal(
        "0.75"
    )
    _pricing(handler).calculate_price("v1", _ENTRY, _EXIT, PlaceType(category=FOUR))
    assert seen == ["cle-de-test-pricing", None]


def test_cle_refusee_par_pricing_sortie_refusee_et_erreur_loggee(caplog):
    for status in (401, 403):
        caplog.clear()
        client = HttpPricingClient(
            "https://pricing.test",
            api_key="cle-de-test-pricing",
            transport=httpx.MockTransport(
                lambda _r, s=status: httpx.Response(s, json={"detail": "clé invalide"})
            ),
        )
        with caplog.at_level("ERROR"):
            assert client.calculate_price("v1", _ENTRY, _EXIT, PlaceType(category=FOUR)) is None
        assert "PRICING_API_KEY" in caplog.text
        assert "cle-de-test-pricing" not in caplog.text
