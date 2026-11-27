"""Tests unitaires — `http_booking_client.py` contre un faux Booking 2.5.0
(`httpx.MockTransport`), sans appel réseau."""

from datetime import UTC, datetime, timedelta, timezone

import httpx

from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_booking_client import HttpBookingClient

_BASE = "https://booking.test"
_AT = datetime(2026, 11, 24, 14, 30, tzinfo=UTC)


def _active(valid=True, place_type="ELECTRIC"):
    return {
        "vehicle_id": "v1",
        "at": "2026-11-24T14:30:00Z",
        "valid": valid,
        "reservations": (
            [
                {
                    "id": "482913",
                    "place_type": place_type,
                    "start_at": "2026-11-24T14:00:00Z",
                    "end_at": "2026-11-24T16:00:00+00:00",
                }
            ]
            if valid
            else []
        ),
    }


def _client(handler) -> HttpBookingClient:
    return HttpBookingClient(_BASE, transport=httpx.MockTransport(handler))


def test_appelle_reservations_valid_avec_le_vehicule_et_l_instant():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_active())

    paris = timezone(timedelta(hours=1))
    _client(handler).get_reservation("v1", at=datetime(2026, 11, 24, 15, 30, tzinfo=paris))
    assert seen["path"] == "/v2/booking/reservations/valid"
    assert seen["params"] == {"vehicle_id": "v1", "at": "2026-11-24T14:30:00+00:00"}


def test_reservation_valable_traduite():
    reservation = _client(lambda _r: httpx.Response(200, json=_active())).get_reservation(
        "v1", at=_AT
    )
    assert reservation is not None
    assert reservation.id == "482913"
    assert reservation.vehicle_id == "v1"
    assert reservation.reserved_place_type.is_electric
    assert reservation.reserved_place_type.category is VehicleCategory.FOUR_WHEELER
    assert reservation.start_date == datetime(2026, 11, 24, 14, 0, tzinfo=UTC)
    assert reservation.end_date == datetime(2026, 11, 24, 16, 0, tzinfo=UTC)
    assert reservation.place_id is None  # Booking ne gère pas de place nominative


def test_deux_roues():
    body = _active(place_type="TWO_WHEELS")
    reservation = _client(lambda _r: httpx.Response(200, json=body)).get_reservation("v1", at=_AT)
    assert reservation.reserved_place_type.category is VehicleCategory.TWO_WHEELER


def test_envoie_la_cle_de_booking_quand_elle_est_renseignee():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-API-Key"))
        if request.url.path.endswith("/availability"):
            return httpx.Response(200, json={"available": True, "min_free_capacity": 3})
        return httpx.Response(200, json=_active(valid=False))

    with_key = HttpBookingClient(
        _BASE, transport=httpx.MockTransport(handler), api_key="cle-de-test-booking"
    )
    with_key.get_reservation("v1", at=_AT)
    with_key.free_capacity("XL", _AT)
    _client(handler).get_reservation("v1", at=_AT)
    assert seen == ["cle-de-test-booking", "cle-de-test-booking", None]


def test_cle_refusee_par_booking_entree_sans_reservation_et_erreur_loggee(caplog):
    for status in (401, 403):
        caplog.clear()
        client = _client(lambda _r, s=status: httpx.Response(s, json={"detail": "clé invalide"}))
        with caplog.at_level("ERROR"):
            assert client.get_reservation("v1", at=_AT) is None
        assert "BOOKING_API_KEY" in caplog.text
        assert client.free_capacity("XL", _AT) is None


def test_pas_de_reservation_valable():
    client = _client(lambda _r: httpx.Response(200, json=_active(valid=False)))
    assert client.get_reservation("v1", at=_AT) is None


def test_booking_en_panne_ou_injoignable_entree_sans_reservation():
    assert _client(lambda _r: httpx.Response(503)).get_reservation("v1", at=_AT) is None

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    assert _client(down).get_reservation("v1", at=_AT) is None


def test_reponse_inattendue():
    for body in ({"valid": True, "reservations": [{"id": "1"}]}, ["?"], {"valid": True}):
        assert (
            _client(lambda _r, b=body: httpx.Response(200, json=b)).get_reservation("v1", at=_AT)
            is None
        )


def test_sans_instant_utilise_maintenant():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["at"] = request.url.params["at"]
        return httpx.Response(200, json=_active(valid=False))

    before = datetime.now(UTC)
    _client(handler).get_reservation("v1")
    assert datetime.fromisoformat(seen["at"]) >= before - timedelta(seconds=1)


# --- Places réservables (borne de réservation du plan 3D) ------------------------


def test_free_capacity_interroge_l_heure_pleine_en_cours():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"available": True, "min_free_capacity": 7})

    at = datetime(2026, 11, 25, 9, 42, 13, tzinfo=UTC)
    assert _client(handler).free_capacity("XL", at) == 7
    assert seen["path"] == "/v2/booking/availability"
    assert seen["params"]["place_type"] == "XL"
    assert seen["params"]["start_at"].startswith("2026-11-25T09:00:00")
    assert seen["params"]["end_at"].startswith("2026-11-25T10:00:00")


def test_free_capacity_none_si_booking_ne_repond_pas():
    assert _client(lambda r: httpx.Response(500)).free_capacity("XL") is None
    assert (
        _client(lambda r: httpx.Response(200, json={"available": True})).free_capacity("XL") is None
    )

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("trop long", request=request)

    assert _client(down).free_capacity("XL") is None
