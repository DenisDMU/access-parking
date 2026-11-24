"""Tests unitaires — `http_vehicles_client.py` contre un faux serveur Vehicles
(`httpx.MockTransport`), sans appel réseau au vrai service."""

import json
import logging

import httpx

from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_vehicles_client import HttpVehiclesClient

_BASE_URL = "https://vehicles.test"
_PSEUDO_ID = "301b7c98-3634-4842-8ff5-baf503c53302"
_PLATE = "AB-123-CD"


def _vehicle(**overrides) -> dict:
    body = {
        "pseudoId": _PSEUDO_ID,
        "electric": False,
        "disabled": False,
        "xl": False,
        "twoWheels": False,
    }
    body.update(overrides)
    return body


def _client(handler) -> HttpVehiclesClient:
    return HttpVehiclesClient(_BASE_URL, transport=httpx.MockTransport(handler))


class _FakeVehicles:
    """Faux Vehicles qui retient ce qu'on lui demande, avec un registre."""

    def __init__(self, known: bool = False, identify_status: int = 200) -> None:
        self.known = known
        self.identify_status = identify_status
        self.requests: list[tuple[str, str]] = []
        self.created: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.method == "POST":
            if self.identify_status != 200:
                return httpx.Response(self.identify_status)
            self.created.append(json.loads(request.content))
            self.known = True
            return httpx.Response(200, json=_PSEUDO_ID)
        return httpx.Response(200, json=_vehicle()) if self.known else httpx.Response(404)


# --- Consultation (get_vehicle_info) -----------------------------------------


def test_calls_vehicles_by_plate():
    vehicles = _FakeVehicles(known=True)
    _client(vehicles).get_vehicle_info(_PLATE)
    assert vehicles.requests == [("GET", f"/api/getvehicles/{_PLATE}")]


def test_maps_response_to_pseudonymized_vehicle_info():
    info = _client(lambda _r: httpx.Response(200, json=_vehicle())).get_vehicle_info(_PLATE)

    assert info is not None
    assert info.vehicle_id == _PSEUDO_ID
    assert info.vehicle_type.category is VehicleCategory.FOUR_WHEELER
    assert not info.vehicle_type.is_xl
    assert not info.vehicle_type.is_electric
    assert not info.vehicle_type.is_handicap
    assert info.disability_permit is False


def test_maps_vehicle_characteristics():
    body = _vehicle(twoWheels=True, xl=True, electric=True, disabled=True)
    info = _client(lambda _r: httpx.Response(200, json=body)).get_vehicle_info(_PLATE)

    assert info is not None
    assert info.vehicle_type.category is VehicleCategory.TWO_WHEELER
    assert info.vehicle_type.is_xl
    assert info.vehicle_type.is_electric
    # Pas de justificatif distinct côté Vehicles : `disabled` vaut les deux.
    assert info.vehicle_type.is_handicap
    assert info.disability_permit is True


def test_unknown_plate_returns_none_without_creating_it():
    vehicles = _FakeVehicles(known=False)
    assert _client(vehicles).get_vehicle_info(_PLATE) is None
    assert vehicles.created == []


def test_server_error_returns_none():
    assert _client(lambda _r: httpx.Response(500)).get_vehicle_info(_PLATE) is None


def test_network_error_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    assert _client(handler).get_vehicle_info(_PLATE) is None


def test_unexpected_payload_returns_none():
    client = _client(lambda _r: httpx.Response(200, json={"code": 1}))
    assert client.get_vehicle_info(_PLATE) is None


def test_non_object_payload_returns_none():
    client = _client(lambda _r: httpx.Response(200, json=["inattendu"]))
    assert client.get_vehicle_info(_PLATE) is None


# --- Identification à l'entrée (identify_vehicle) ----------------------------


def test_identify_known_vehicle_does_not_call_identify():
    vehicles = _FakeVehicles(known=True)
    info = _client(vehicles).identify_vehicle(_PLATE)

    assert info is not None and info.vehicle_id == _PSEUDO_ID
    assert vehicles.requests == [("GET", f"/api/getvehicles/{_PLATE}")]


def test_identify_unknown_vehicle_creates_it_then_reads_it():
    vehicles = _FakeVehicles(known=False)
    info = _client(vehicles).identify_vehicle(_PLATE)

    assert info is not None and info.vehicle_id == _PSEUDO_ID
    assert vehicles.requests == [
        ("GET", f"/api/getvehicles/{_PLATE}"),
        ("POST", "/api/identify"),
        ("GET", f"/api/getvehicles/{_PLATE}"),
    ]
    assert vehicles.created == [
        {
            "licensePlate": _PLATE,
            "isElectric": False,
            "isDisabled": False,
            "isXl": False,
            "isTwoWheels": False,
        }
    ]


def test_identify_never_creates_when_vehicles_is_down():
    """Une panne (500) n'est pas un « inconnu » : aucune création."""

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(500)

    assert _client(handler).identify_vehicle(_PLATE) is None
    assert seen == ["GET"]


def test_identify_returns_none_when_creation_fails():
    vehicles = _FakeVehicles(known=False, identify_status=500)
    assert _client(vehicles).identify_vehicle(_PLATE) is None


def test_identify_returns_none_on_network_error_during_creation():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            raise httpx.ConnectError("connexion refusée", request=request)
        return httpx.Response(404)

    assert _client(handler).identify_vehicle(_PLATE) is None


# --- RGPD ----------------------------------------------------------------------


def test_plate_never_appears_in_logs(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"échec vers {request.url}", request=request)

    with caplog.at_level(logging.DEBUG):
        _client(handler).identify_vehicle(_PLATE)
        _client(lambda _r: httpx.Response(500)).get_vehicle_info(_PLATE)
        _client(_FakeVehicles(known=False)).identify_vehicle(_PLATE)

    assert caplog.records
    assert all(_PLATE not in record.getMessage() for record in caplog.records)


def test_routes_reglables_si_vehicles_les_renomme():
    vehicles = _FakeVehicles(known=False)
    client = HttpVehiclesClient(
        _BASE_URL,
        transport=httpx.MockTransport(vehicles),
        lookup_path="/v2/cars/{plate}",
        identify_path="/v2/cars",
    )
    client.identify_vehicle(_PLATE)
    assert vehicles.requests == [
        ("GET", f"/v2/cars/{_PLATE}"),
        ("POST", "/v2/cars"),
        ("GET", f"/v2/cars/{_PLATE}"),
    ]


def test_identify_404_signale_une_route_changee_en_erreur(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)  # GET (inconnue) puis POST (route disparue)

    with caplog.at_level(logging.ERROR):
        assert _client(handler).identify_vehicle(_PLATE) is None
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "/api/identify" in errors[0]
    assert _PLATE not in errors[0]
