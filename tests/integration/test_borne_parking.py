"""Tests d'intégration — `GET /borne/parking` (occupation pour le plan 3D public).

La borne affiche le parking en 3D à tout le monde : la route ne rend que des
compteurs par catégorie, sans clé, et ne sollicite pas Parking à chaque
visiteur (réponse gardée quelques secondes).
"""

from __future__ import annotations

from dataclasses import replace

from src.interfaces.api import deps
from src.interfaces.api.main import app
from src.interfaces.api.routers import borne_router
from tests.unit.fakes import FakeParkingPort

URL = "/api/v1/borne/parking"


def test_occupation_publique_sans_cle(client):
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["categories"][0] == {
        "name": "STANDARD",
        "label": "Standard",
        "totalCapacity": 10,
        "spotTaken": 3,
        "spotHeld": 1,
    }


def test_des_compteurs_seulement(client):
    """Ni véhicule, ni identifiant, ni demande : rien qui désigne quelqu'un."""

    client.post("/api/v1/borne/passages", json={"licensePlate": "AA-111-AA", "type": 1})
    body = client.get(URL).json()
    assert set(body) == {"available", "categories"}
    for category in body["categories"]:
        assert set(category) == {"name", "label", "totalCapacity", "spotTaken", "spotHeld"}
    assert "vehicleId" not in client.get(URL).text and "AA-111-AA" not in client.get(URL).text


def test_parking_injoignable_sans_erreur_500(client):
    app.dependency_overrides[deps.get_parking_port] = lambda: FakeParkingPort(unavailable=True)
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == {"available": False, "categories": []}


def test_reponse_gardee_parking_appele_une_seule_fois(client):
    calls = []

    class Counting(FakeParkingPort):
        def list_categories(self):
            calls.append(1)
            return super().list_categories()

    app.dependency_overrides[deps.get_parking_port] = lambda: Counting()
    first = client.get(URL).json()
    for _ in range(5):
        assert client.get(URL).json() == first
    assert len(calls) == 1


def test_reponse_redemandee_apres_expiration(client, monkeypatch):
    calls = []

    class Counting(FakeParkingPort):
        def list_categories(self):
            calls.append(1)
            return super().list_categories()

    app.dependency_overrides[deps.get_parking_port] = lambda: Counting()
    settings = borne_router.get_settings()
    monkeypatch.setattr(
        borne_router, "get_settings", lambda: replace(settings, borne_parking_cache_s=0)
    )
    client.get(URL)
    client.get(URL)
    assert len(calls) == 2


def test_borne_publique_desactivee(client, monkeypatch):
    settings = borne_router.get_settings()
    monkeypatch.setattr(borne_router, "get_settings", lambda: replace(settings, borne_public=False))
    assert client.get(URL).status_code == 403


def test_debit_limite_par_adresse(client, monkeypatch):
    settings = borne_router.get_settings()
    monkeypatch.setattr(
        borne_router, "get_settings", lambda: replace(settings, rate_limit_borne_parking="3/minute")
    )
    codes = [client.get(URL).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
