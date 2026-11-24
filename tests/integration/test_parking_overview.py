"""Test d'intégration — `GET /access/parking` (état vu par Parking)."""

from src.interfaces.api import deps
from src.interfaces.api.main import app
from tests.integration.conftest import AUTH_HEADERS, BORNE_HEADERS
from tests.unit.fakes import FakeParkingPort

URL = "/api/v1/access/parking"


def test_vue_parking(client):
    response = client.get(URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True and body["missingCategories"] == []
    assert body["categories"][0] == {
        "name": "STANDARD",
        "label": "Standard",
        "usedByAccess": True,
        "spotTaken": 3,
        "spotHeld": 1,
        "totalCapacity": 10,
        "occupationRate": 0.3,
    }


def test_parking_injoignable_sans_erreur_500(client):
    app.dependency_overrides[deps.get_parking_port] = lambda: FakeParkingPort(unavailable=True)
    response = client.get(URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"available": False, "categories": [], "missingCategories": []}


def test_reserve_a_l_exploitation(client):
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=BORNE_HEADERS).status_code == 401
