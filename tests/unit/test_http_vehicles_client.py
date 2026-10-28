"""Tests unitaires — `http_vehicles_client.py` contre un faux serveur Vehicles
(`httpx.MockTransport`), sans appel réseau au vrai service."""

import httpx

from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_vehicles_client import HttpVehiclesClient

_BASE_URL = "https://vehicles.test"
_PSEUDO_ID = "301b7c98-3634-4842-8ff5-baf503c53302"


def _vehicle(**overrides) -> dict:
    body = {
        "pseudoId": _PSEUDO_ID,
        "code": 1,
        "electric": False,
        "disabled": False,
        "xl": False,
        "twoWheels": False,
    }
    body.update(overrides)
    return body


def _client(handler) -> HttpVehiclesClient:
    return HttpVehiclesClient(_BASE_URL, transport=httpx.MockTransport(handler))


def test_calls_vehicles_by_code():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_vehicle())

    _client(handler).get_vehicle_info(1)

    assert seen == {"method": "GET", "url": f"{_BASE_URL}/api/vehicles/1"}


def test_maps_response_to_pseudonymized_vehicle_info():
    info = _client(lambda _r: httpx.Response(200, json=_vehicle())).get_vehicle_info(1)

    assert info is not None
    assert info.vehicle_id == _PSEUDO_ID
    assert info.vehicle_type.category is VehicleCategory.FOUR_WHEELER
    assert not info.vehicle_type.is_xl
    assert not info.vehicle_type.is_electric
    assert not info.vehicle_type.is_handicap
    assert info.disability_permit is False


def test_maps_vehicle_characteristics():
    body = _vehicle(twoWheels=True, xl=True, electric=True, disabled=True)
    info = _client(lambda _r: httpx.Response(200, json=body)).get_vehicle_info(1)

    assert info is not None
    assert info.vehicle_type.category is VehicleCategory.TWO_WHEELER
    assert info.vehicle_type.is_xl
    assert info.vehicle_type.is_electric
    # Pas de justificatif distinct côté Vehicles : `disabled` vaut les deux.
    assert info.vehicle_type.is_handicap
    assert info.disability_permit is True


def test_unknown_code_returns_none():
    # Constaté en réel : Vehicles renvoie 500 (et non 404) pour un code inconnu.
    error = {"status": 500, "error": "Internal Server Error"}
    client = _client(lambda _r: httpx.Response(500, json=error))
    assert client.get_vehicle_info(999) is None


def test_not_found_returns_none():
    assert _client(lambda _r: httpx.Response(404)).get_vehicle_info(999) is None


def test_network_error_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    assert _client(handler).get_vehicle_info(1) is None


def test_unexpected_payload_returns_none():
    client = _client(lambda _r: httpx.Response(200, json={"code": 1}))
    assert client.get_vehicle_info(1) is None
