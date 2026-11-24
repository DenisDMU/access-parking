"""Tests unitaires — `http_vehicles_client.py` contre un faux serveur Vehicles
(`httpx.MockTransport`), sans appel réseau au vrai service.

Deux contrats : celui en vigueur (plaque → `POST /api/identify` → pseudoId →
`GET /api/getvehicles/{vehicleId}`) et l'ancien (consultation par plaque),
encore sélectionnable par `VEHICLES_LOOKUP_PATH` si Vehicles y revenait.
"""

import json
import logging

import httpx

from src.domain.value_objects.dto import VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_vehicles_client import HttpVehiclesClient

_BASE_URL = "https://vehicles.test"
_PSEUDO_ID = "301b7c98-3634-4842-8ff5-baf503c53302"
_PLATE = "AB-123-CD"
_PLATE_PATH = "/api/getvehicles/{plate}"


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


class _FakeVehicles:
    """Faux Vehicles (contrat en vigueur) : `identify` retrouve ou crée."""

    def __init__(self, known: bool = False, identify_status: int = 200, **vehicle) -> None:
        self.known = known
        self.identify_status = identify_status
        self.vehicle = _vehicle(**vehicle)
        self.requests: list[tuple[str, str]] = []
        self.identified: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.method == "POST":
            if self.identify_status != 200:
                return httpx.Response(self.identify_status)
            self.identified.append(json.loads(request.content))
            self.known = True
            return httpx.Response(200, json=_PSEUDO_ID)
        if request.url.path == f"/api/getvehicles/{_PSEUDO_ID}" and self.known:
            return httpx.Response(200, json=self.vehicle)
        return httpx.Response(404)


def _client(handler, **kwargs) -> HttpVehiclesClient:
    return HttpVehiclesClient(_BASE_URL, transport=httpx.MockTransport(handler), **kwargs)


# --- Contrat en vigueur : identify puis consultation par identifiant -----------


def test_identify_puis_consultation_par_identifiant():
    vehicles = _FakeVehicles(known=True)
    info = _client(vehicles).identify_vehicle(_PLATE)
    assert info is not None and info.vehicle_id == _PSEUDO_ID
    assert vehicles.requests == [
        ("POST", "/api/identify"),
        ("GET", f"/api/getvehicles/{_PSEUDO_ID}"),
    ]
    # Seule la plaque est envoyée : un véhicule connu n'est jamais réécrit.
    assert vehicles.identified == [{"licensePlate": _PLATE}]


def test_plaque_inconnue_creee_par_identify():
    vehicles = _FakeVehicles(known=False)
    assert _client(vehicles).identify_vehicle(_PLATE).vehicle_id == _PSEUDO_ID


def test_consultation_passe_aussi_par_identify():
    """Vehicles n'offre plus de consultation par plaque sans création."""

    vehicles = _FakeVehicles(known=True)
    assert _client(vehicles).get_vehicle_info(_PLATE).vehicle_id == _PSEUDO_ID
    assert vehicles.requests[0] == ("POST", "/api/identify")


def test_caracteristiques_traduites():
    vehicles = _FakeVehicles(known=True, twoWheels=True, xl=True, electric=True, disabled=True)
    info = _client(vehicles).identify_vehicle(_PLATE)
    assert info.vehicle_type.category is VehicleCategory.TWO_WHEELER
    assert info.vehicle_type.is_xl and info.vehicle_type.is_electric
    # Pas de justificatif distinct côté Vehicles : `disabled` vaut les deux.
    assert info.vehicle_type.is_handicap and info.disability_permit is True


def test_caracteristiques_par_defaut():
    info = _client(_FakeVehicles(known=True)).identify_vehicle(_PLATE)
    assert info.vehicle_type.category is VehicleCategory.FOUR_WHEELER
    assert not (info.vehicle_type.is_xl or info.vehicle_type.is_electric)
    assert info.disability_permit is False


def test_identify_404_signale_une_route_changee_en_erreur(caplog):
    with caplog.at_level(logging.ERROR):
        assert _client(_FakeVehicles(identify_status=404)).identify_vehicle(_PLATE) is None
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "/api/identify" in errors[0]
    assert _PLATE not in errors[0]


def test_identify_en_panne():
    assert _client(_FakeVehicles(identify_status=500)).identify_vehicle(_PLATE) is None


def test_identifiant_inattendu():
    for body in ({"pseudoId": _PSEUDO_ID}, "", None):
        client = _client(lambda r, b=body: httpx.Response(200, json=b))
        assert client.identify_vehicle(_PLATE) is None


def test_vehicule_introuvable_juste_apres_identify():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_PSEUDO_ID)
        return httpx.Response(404)

    assert _client(handler).identify_vehicle(_PLATE) is None


def test_reponse_de_consultation_inattendue():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_PSEUDO_ID if request.method == "POST" else ["?"])

    assert _client(handler).identify_vehicle(_PLATE) is None


def test_erreur_reseau():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    assert _client(handler).identify_vehicle(_PLATE) is None
    assert _client(handler).get_vehicle_info(_PLATE) is None


def test_routes_reglables_si_vehicles_les_renomme():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json=_PSEUDO_ID)
        return httpx.Response(200, json=_vehicle())

    client = _client(handler, lookup_path="/v2/cars/{vehicleId}", identify_path="/v2/identify")
    assert client.identify_vehicle(_PLATE) is not None
    assert seen == [("POST", "/v2/identify"), ("GET", f"/v2/cars/{_PSEUDO_ID}")]


# --- Ancien contrat : consultation par plaque ({plate} dans la route) ---------


class _FakeVehiclesParPlaque(_FakeVehicles):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.requests.append(("GET", request.url.path))
            return httpx.Response(200, json=self.vehicle) if self.known else httpx.Response(404)
        return super().__call__(request)


def test_ancien_contrat_consultation_sans_creation():
    vehicles = _FakeVehiclesParPlaque(known=False)
    assert _client(vehicles, lookup_path=_PLATE_PATH).get_vehicle_info(_PLATE) is None
    assert vehicles.requests == [("GET", f"/api/getvehicles/{_PLATE}")]


def test_ancien_contrat_entree_cree_sur_404_seulement():
    vehicles = _FakeVehiclesParPlaque(known=False)
    info = _client(vehicles, lookup_path=_PLATE_PATH).identify_vehicle(_PLATE)
    assert info is not None
    assert vehicles.requests == [
        ("GET", f"/api/getvehicles/{_PLATE}"),
        ("POST", "/api/identify"),
        ("GET", f"/api/getvehicles/{_PLATE}"),
    ]


def test_ancien_contrat_panne_ne_cree_jamais():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(500)

    assert _client(handler, lookup_path=_PLATE_PATH).identify_vehicle(_PLATE) is None
    assert seen == ["GET"]


# --- RGPD ----------------------------------------------------------------------


def test_plate_never_appears_in_logs(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"échec vers {request.url}", request=request)

    with caplog.at_level(logging.DEBUG):
        _client(handler).identify_vehicle(_PLATE)
        _client(handler, lookup_path=_PLATE_PATH).get_vehicle_info(_PLATE)
        _client(_FakeVehicles(identify_status=404)).identify_vehicle(_PLATE)
        _client(lambda _r: httpx.Response(500)).get_vehicle_info(_PLATE)

    assert caplog.records
    assert all(_PLATE not in record.getMessage() for record in caplog.records)


# --- Type déclaré à la borne -----------------------------------------------------


def test_type_declare_envoye_a_identify_sans_jamais_pmr():
    vehicles = _FakeVehicles(known=False)
    declared = VehicleType(
        category=VehicleCategory.FOUR_WHEELER, is_electric=True, is_handicap=True
    )
    _client(vehicles).identify_vehicle(_PLATE, declared=declared)
    assert vehicles.identified == [
        {"licensePlate": _PLATE, "isElectric": True, "isXl": False, "isTwoWheels": False}
    ]


def test_deux_roues_declare():
    vehicles = _FakeVehicles(known=False)
    _client(vehicles).identify_vehicle(
        _PLATE, declared=VehicleType(category=VehicleCategory.TWO_WHEELER)
    )
    assert vehicles.identified[0]["isTwoWheels"] is True


def test_sans_type_declare_seule_la_plaque_est_envoyee():
    vehicles = _FakeVehicles(known=False)
    _client(vehicles).identify_vehicle(_PLATE)
    assert vehicles.identified == [{"licensePlate": _PLATE}]
