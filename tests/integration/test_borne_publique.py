"""Tests d'intégration — borne publique (`/borne/status`, `/borne/passages`).

Le lien `/borne` doit marcher pour tout le monde, sans clé : la route
publique ne fait que le passage d'un véhicule, avec une date imposée par le
serveur, une réponse sans identifiant et un débit limité par adresse.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.interfaces.api.rate_limit import client_ip
from tests.integration.conftest import AUTH_HEADERS

URL = "/api/v1/borne/passages"


def _passage(plate: str, type_: int, **extra) -> dict:
    return {"licensePlate": plate, "type": type_, **extra}


def test_statut_public_sans_cle(client):
    response = client.get("/api/v1/borne/status")
    assert response.status_code == 200
    assert response.json() == {"publicAccess": True}


def test_entree_puis_sortie_sans_aucune_cle(client):
    entry = client.post(URL, json=_passage("AA-111-AA", 1))
    assert entry.status_code == 200
    body = entry.json()
    assert body["result"] == 1 and body["vehicleIdentified"] is True
    assert body["placeLabel"] == "Place de test"

    exit_ = client.post(URL, json=_passage("aa 111 aa", 2))
    assert exit_.status_code == 200
    assert exit_.json()["result"] == 1
    assert exit_.json()["durationMinutes"] in (0, 1)  # entrée et sortie à l'instant


def test_reponse_sans_identifiant_de_demande_ni_de_vehicule(client):
    body = client.post(URL, json=_passage("AA-111-AA", 1)).json()
    assert "requestId" not in body and "vehicleId" not in body
    assert "AA-111-AA" not in str(body)


def test_date_imposee_par_le_serveur(client):
    """Une date envoyée par le client (ici antidatée) est ignorée."""

    before = datetime.now(UTC) - timedelta(seconds=5)
    client.post(URL, json=_passage("AA-111-AA", 1, date="2020-01-01T00:00:00Z", source=4))
    request = client.get("/api/v1/access/requests", headers=AUTH_HEADERS).json()[0]
    detail = client.get(
        f"/api/v1/access/requests/{request['requestId']}", headers=AUTH_HEADERS
    ).json()
    assert datetime.fromisoformat(detail["date"].replace("Z", "+00:00")) >= before
    assert detail["source"] == 2  # TERMINAL


def test_plaque_invalide_refusee_sans_etre_renvoyee(client):
    response = client.post(URL, json=_passage("AB#123", 1))
    assert response.status_code == 422
    assert "AB#123" not in response.text


def test_type_invalide(client):
    assert client.post(URL, json=_passage("AA-111-AA", 3)).status_code == 422


def test_borne_publique_desactivee(client, monkeypatch):
    from src.interfaces.api.routers import borne_router

    settings = borne_router.get_settings()
    monkeypatch.setattr(borne_router, "get_settings", lambda: replace(settings, borne_public=False))
    assert client.get("/api/v1/borne/status").json() == {"publicAccess": False}
    response = client.post(URL, json=_passage("AA-111-AA", 1))
    assert response.status_code == 403
    # Rien n'a été enregistré.
    assert client.get("/api/v1/access/requests", headers=AUTH_HEADERS).json() == []


def test_debit_limite_par_adresse(client):
    # 10 passages par minute (le 1er entre, les suivants sont refusés « déjà présent »).
    codes = [client.post(URL, json=_passage("AA-111-AA", 1)).status_code for _ in range(10)]
    assert set(codes) == {200}
    assert client.post(URL, json=_passage("AA-111-AA", 1)).status_code == 429
    # Une autre adresse (vue par le proxy de Render) a sa propre limite.
    other = client.post(
        URL, json=_passage("AA-111-AA", 1), headers={"X-Forwarded-For": "203.0.113.7"}
    )
    assert other.status_code == 200


def test_route_publique_n_ouvre_rien_d_autre(client):
    for method, path in [
        ("GET", "/api/v1/access/requests"),
        ("GET", "/api/v1/access/presences"),
        ("GET", "/api/v1/access/borne/key"),
        ("POST", "/api/v1/access/requests"),
    ]:
        assert client.request(method, path, json={}).status_code == 401


class _Req:
    def __init__(self, headers, host="10.0.0.1"):
        self.headers = headers
        self.client = type("C", (), {"host": host})()
        self.scope = {"client": (host, 0)}


def test_adresse_client_derriere_le_proxy():
    # Dernière adresse = celle ajoutée par le proxy de Render ; les autres
    # peuvent être inventées par le client.
    assert client_ip(_Req({"x-forwarded-for": "1.2.3.4, 203.0.113.7"})) == "203.0.113.7"
    assert client_ip(_Req({"x-forwarded-for": "203.0.113.7"})) == "203.0.113.7"


def test_type_de_vehicule_a_l_entree(client):
    body = client.post(URL, json=_passage("ZZ-999-ZZ", 1, vehicleType="ELECTRIC")).json()
    assert body["result"] == 1
    assert body["placeType"]["isElectric"] is True


def test_pmr_declare_demande_un_agent(client):
    body = client.post(URL, json=_passage("ZZ-998-ZZ", 1, vehicleType="HANDICAPPED")).json()
    assert body["result"] == 3 and body["vehicleIdentified"] is True


def test_type_de_vehicule_invalide(client):
    response = client.post(URL, json=_passage("AA-111-AA", 1, vehicleType="TANK"))
    assert response.status_code == 422


def test_type_ignore_a_la_sortie(client):
    client.post(URL, json=_passage("AA-111-AA", 1))
    exit_ = client.post(URL, json=_passage("AA-111-AA", 2, vehicleType="XL"))
    assert exit_.json()["result"] == 1


# --- Pays de la plaque (4.8.0) -----------------------------------------------------


def test_plaque_italienne_et_francaise_identiques_sont_deux_vehicules(client):
    fr = client.post(URL, json=_passage("ZZ-931-ZZ", 1, country="FR")).json()
    it = client.post(URL, json=_passage("ZZ 931 ZZ", 1, country="IT")).json()
    assert fr["result"] == 1
    assert it["result"] == 1  # pas « déjà présent » : c'est un autre véhicule
    assert client.vehicles.created == ["ZZ-931-ZZ", "IT:ZZ931ZZ"]
    # Chacun sort avec son pays.
    assert client.post(URL, json=_passage("ZZ931ZZ", 2, country="IT")).json()["result"] == 1
    assert client.post(URL, json=_passage("ZZ-931-ZZ", 2, country="FR")).json()["result"] == 1


def test_format_incoherent_avec_le_pays(client):
    response = client.post(URL, json=_passage("B-MW 1234", 1, country="FR"))
    assert response.status_code == 422
    assert "BMW1234" not in response.text and "B-MW 1234" not in response.text


def test_pays_inconnu(client):
    assert client.post(URL, json=_passage("AB-123-CD", 1, country="US")).status_code == 422
