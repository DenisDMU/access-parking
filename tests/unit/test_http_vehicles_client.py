"""Tests unitaires — `http_vehicles_client.py` contre un faux serveur Vehicles
(`httpx.MockTransport`), sans appel réseau au vrai service.

Deux contrats : celui en vigueur (plaque → `POST /api/vehicle/create` →
pseudoId → `GET /api/vehicle/{vehicleId}`) et l'ancien (consultation par plaque),
encore sélectionnable par `VEHICLES_LOOKUP_PATH` si Vehicles y revenait. Plus
la découverte automatique des routes dans le Swagger de Vehicles quand une
route répond 404 (Vehicles a renommé ses routes cinq fois le 24/11).
"""

import json
import logging

import httpx
import pytest

from src.domain.value_objects.dto import VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external import http_vehicles_client as module
from src.infrastructure.external.http_vehicles_client import (
    HttpVehiclesClient,
    discover_routes,
    reset_discovered_routes,
)

_BASE_URL = "https://vehicles.test"
_PSEUDO_ID = "301b7c98-3634-4842-8ff5-baf503c53302"
_PLATE = "AB-123-CD"
_PLATE_PATH = "/api/getvehicles/{plate}"


@pytest.fixture(autouse=True)
def _routes_oubliees():
    """Les routes découvertes sont partagées : chaque test repart de zéro."""

    reset_discovered_routes()
    yield
    reset_discovered_routes()


def _vehicle(**overrides) -> dict:
    body = {
        "pseudoId": _PSEUDO_ID,
        "isElectric": False,
        "isHandicaped": False,
        "isXl": False,
        "isTwoWheels": False,
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
        if request.url.path == f"/api/vehicle/{_PSEUDO_ID}" and self.known:
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
        ("POST", "/api/vehicle/create"),
        ("GET", f"/api/vehicle/{_PSEUDO_ID}"),
    ]
    # Seule la plaque est envoyée : un véhicule connu n'est jamais réécrit.
    assert vehicles.identified == [{"licensePlate": _PLATE}]


def test_creation_en_201_acceptee():
    """Vehicles a annoncé « 201 Created » à la création : même traitement que 200."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=_PSEUDO_ID)
        return httpx.Response(200, json=_vehicle(isElectric=True))

    info = _client(handler).identify_vehicle(_PLATE)
    assert info is not None and info.vehicle_id == _PSEUDO_ID and info.vehicle_type.is_electric


def test_enregistrement_pmr_en_204_accepte():
    assert _client(lambda r: httpx.Response(204)).confirm_disability(_PSEUDO_ID) is True


def test_plaque_inconnue_creee_par_identify():
    vehicles = _FakeVehicles(known=False)
    assert _client(vehicles).identify_vehicle(_PLATE).vehicle_id == _PSEUDO_ID


def test_consultation_passe_aussi_par_identify():
    """Vehicles n'offre plus de consultation par plaque sans création."""

    vehicles = _FakeVehicles(known=True)
    assert _client(vehicles).get_vehicle_info(_PLATE).vehicle_id == _PSEUDO_ID
    assert vehicles.requests[0] == ("POST", "/api/vehicle/create")


def test_caracteristiques_traduites():
    vehicles = _FakeVehicles(
        known=True, isTwoWheels=True, isXl=True, isElectric=True, isHandicaped=True
    )
    info = _client(vehicles).identify_vehicle(_PLATE)
    assert info.vehicle_type.category is VehicleCategory.TWO_WHEELER
    assert info.vehicle_type.is_xl and info.vehicle_type.is_electric
    # Pas de justificatif distinct côté Vehicles : `isHandicaped` vaut les deux.
    assert info.vehicle_type.is_handicap and info.disability_permit is True


def test_noms_du_contrat_5_encore_lus():
    """`electric`, `xl`, `twoWheels`, `handicaped` (avant le 24/11, 14 h)."""

    vehicles = _FakeVehicles(known=True)
    vehicles.vehicle = {
        "pseudoId": _PSEUDO_ID,
        "electric": True,
        "xl": True,
        "twoWheels": False,
        "handicaped": True,
    }
    info = _client(vehicles).identify_vehicle(_PLATE)
    assert info.vehicle_type.is_electric and info.vehicle_type.is_xl
    assert info.vehicle_type.is_handicap and info.disability_permit is True


def test_ancien_nom_du_champ_pmr_encore_lu():
    """`disabled` (contrats 1 à 3) reste compris si Vehicles y revenait."""

    vehicles = _FakeVehicles(known=True)
    vehicles.vehicle = {"pseudoId": _PSEUDO_ID, "disabled": True}
    info = _client(vehicles).identify_vehicle(_PLATE)
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
    assert len(errors) == 1 and "/api/vehicle/create" in errors[0]
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
        ("POST", "/api/vehicle/create"),
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


# --- Découverte automatique des routes (Swagger de Vehicles) ---------------------


def _openapi(create: str, lookup: str, param: str = "vehicleId") -> dict:
    """Swagger minimal, au format de celui de Vehicles (springdoc)."""

    lookup_path = lookup.replace("{vehicleId}", "{" + param + "}")
    ref = {"$ref": "#/components/schemas/VehicleResponse"}
    return {
        "paths": {
            create: {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/VehicleCreateRequest"}
                            }
                        }
                    },
                    "responses": {"200": {"content": {"*/*": {"schema": {"type": "string"}}}}},
                }
            },
            lookup_path: {
                "get": {"responses": {"200": {"content": {"*/*": {"schema": ref}}}}},
                "delete": {"responses": {"200": {}}},
            },
            lookup_path + "/plate": {
                "get": {"responses": {"200": {"content": {"*/*": {"schema": {"type": "string"}}}}}}
            },
            "/health": {"get": {"responses": {"200": {}}}},
        },
        "components": {
            "schemas": {
                "VehicleCreateRequest": {
                    "properties": {"licensePlate": {"type": "string"}, "isXl": {}}
                },
                "VehicleResponse": {"properties": {"pseudoId": {}, "xl": {}, "handicaped": {}}},
            }
        },
    }


class _VehiclesRenomme:
    """Faux Vehicles dont les routes ont changé ; il publie son Swagger."""

    def __init__(self, create="/api/v9/cars/new", lookup="/api/v9/cars/{vehicleId}") -> None:
        self.create = create
        self.lookup = lookup
        self.openapi = _openapi(create, lookup)
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and path == "/v3/api-docs":
            return httpx.Response(200, json=self.openapi)
        if request.method == "POST" and path == self.create:
            return httpx.Response(200, json=_PSEUDO_ID)
        if request.method == "GET" and path == self.lookup.replace("{vehicleId}", _PSEUDO_ID):
            return httpx.Response(200, json=_vehicle(isXl=True))
        return httpx.Response(404)


def test_discover_routes_sur_le_swagger_reel_de_vehicles():
    routes = discover_routes(_openapi("/api/vehicle/create", "/api/vehicle/{vehicleId}"))
    # La route `/plate` (qui renvoie la plaque) n'est jamais choisie.
    assert routes == ("/api/vehicle/create", "/api/vehicle/{vehicleId}")


def test_discover_routes_renomme_le_parametre():
    routes = discover_routes(_openapi("/c", "/v/{id}", param="id"))
    assert routes == ("/c", "/v/{vehicleId}")


def test_discover_routes_sans_route_utilisable():
    assert discover_routes({"paths": {"/health": {"get": {}}}}) is None
    assert discover_routes({}) is None


def test_route_renommee_retrouvee_dans_le_swagger(caplog):
    vehicles = _VehiclesRenomme()
    with caplog.at_level(logging.WARNING):
        info = _client(vehicles).identify_vehicle(_PLATE)
    assert info is not None and info.vehicle_id == _PSEUDO_ID and info.vehicle_type.is_xl
    assert vehicles.requests == [
        ("POST", "/api/vehicle/create"),
        ("GET", "/v3/api-docs"),
        ("POST", "/api/v9/cars/new"),
        ("GET", f"/api/v9/cars/{_PSEUDO_ID}"),
    ]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("/api/v9/cars/new" in w for w in warnings)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert all(_PLATE not in r.getMessage() for r in caplog.records)


def test_routes_decouvertes_reutilisees_par_les_requetes_suivantes():
    vehicles = _VehiclesRenomme()
    _client(vehicles).identify_vehicle(_PLATE)
    vehicles.requests.clear()
    # Nouvelle instance (une par requête d'Access) : plus de 404, plus de Swagger.
    assert _client(vehicles).identify_vehicle(_PLATE) is not None
    assert vehicles.requests == [
        ("POST", "/api/v9/cars/new"),
        ("GET", f"/api/v9/cars/{_PSEUDO_ID}"),
    ]


def test_seule_la_consultation_renommee():
    vehicles = _VehiclesRenomme(create="/api/vehicle/create")
    info = _client(vehicles).identify_vehicle(_PLATE)
    assert info is not None
    assert vehicles.requests == [
        ("POST", "/api/vehicle/create"),
        ("GET", f"/api/vehicle/{_PSEUDO_ID}"),
        ("GET", "/v3/api-docs"),
        ("GET", f"/api/v9/cars/{_PSEUDO_ID}"),
    ]


def test_swagger_lu_au_plus_une_fois_par_minute(monkeypatch):
    vehicles = _VehiclesRenomme()
    vehicles.openapi = {}  # rien d'exploitable
    assert _client(vehicles).identify_vehicle(_PLATE) is None
    assert _client(vehicles).identify_vehicle(_PLATE) is None
    assert vehicles.requests.count(("GET", "/v3/api-docs")) == 1
    # Une minute plus tard, nouvelle tentative.
    clock = module.time.monotonic() + module.DISCOVERY_MIN_INTERVAL_S + 1
    monkeypatch.setattr(module.time, "monotonic", lambda: clock)
    _client(vehicles).identify_vehicle(_PLATE)
    assert vehicles.requests.count(("GET", "/v3/api-docs")) == 2


def test_swagger_injoignable_reste_un_vehicule_non_identifie():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/api-docs":
            raise httpx.ConnectError("refusé", request=request)
        return httpx.Response(404)

    assert _client(handler).identify_vehicle(_PLATE) is None


# --- Justificatif PMR validé par un agent ----------------------------------------


def test_confirm_disability_met_seulement_le_champ_pmr():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=_vehicle(isHandicaped=True))

    assert _client(handler).confirm_disability(_PSEUDO_ID) is True
    assert seen == [("PUT", f"/api/vehicle/{_PSEUDO_ID}", {"isHandicaped": True})]


def test_confirm_disability_suit_les_routes_decouvertes():
    vehicles = _VehiclesRenomme()
    _client(vehicles).identify_vehicle(_PLATE)  # découvre /api/v9/cars/...
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200)

    assert _client(handler).confirm_disability(_PSEUDO_ID) is True
    assert seen == [f"/api/v9/cars/{_PSEUDO_ID}"]


def test_confirm_disability_echec():
    assert _client(lambda r: httpx.Response(404)).confirm_disability(_PSEUDO_ID) is False

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    assert _client(down).confirm_disability(_PSEUDO_ID) is False


def test_confirm_disability_impossible_en_mode_par_plaque():
    seen = []
    client = _client(lambda r: seen.append(r) or httpx.Response(200), lookup_path=_PLATE_PATH)
    assert client.confirm_disability(_PSEUDO_ID) is False and seen == []


def test_discover_routes_ignore_les_routes_vers_un_autre_hote():
    """Un Swagger modifié ne doit jamais faire partir la plaque ailleurs."""

    for bad in ("@exemple.invalid/c", "//exemple.invalid/c", "/a/../../c", "/c?x=1", "https://x/c"):
        assert discover_routes(_openapi(bad, "/api/vehicle/{vehicleId}")) is None
    # La route sûre est toujours trouvée à côté d'une route piégée.
    openapi = _openapi("/api/vehicle/create", "/api/vehicle/{vehicleId}")
    openapi["paths"]["@exemple.invalid/x"] = openapi["paths"]["/api/vehicle/create"]
    assert discover_routes(openapi) == ("/api/vehicle/create", "/api/vehicle/{vehicleId}")
