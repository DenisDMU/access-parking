"""Tests d'intégration — borne client (`/borne`) et clé des bornes.

La clé borne (`BORNE_API_KEY`) ne sert qu'à faire passer un véhicule : une
borne publique inspectée ou volée ne donne accès à aucune donnée
d'exploitation.
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import AUTH_HEADERS, BORNE_HEADERS

URL = "/api/v1/access/requests"


def _passage(plate: str, type_: int, date: str) -> dict:
    return {"licensePlate": plate, "type": type_, "date": date, "source": 2}


# --- Périmètre de la clé borne ------------------------------------------------


def test_cle_borne_fait_entrer_et_sortir_un_vehicule(client):
    entry = client.post(
        URL, json=_passage("AA-111-AA", 1, "2026-09-02T10:00:00Z"), headers=BORNE_HEADERS
    )
    assert entry.status_code == 200
    assert entry.json()["authorization"]["result"] == 1

    exit_ = client.post(
        URL, json=_passage("AA-111-AA", 2, "2026-09-02T12:30:00Z"), headers=BORNE_HEADERS
    )
    assert exit_.status_code == 200
    assert exit_.json()["authorization"]["result"] == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/access/requests"),
        ("GET", "/api/v1/access/requests/inexistante"),
        ("GET", "/api/v1/access/presences"),
        ("GET", "/api/v1/access/events"),
        ("POST", "/api/v1/access/vehicles/known"),
        ("GET", "/metrics"),
    ],
)
def test_cle_borne_refusee_partout_ailleurs(client, method, path):
    body = {"licensePlate": "AA-111-AA"} if method == "POST" else None
    response = client.request(method, path, json=body, headers=BORNE_HEADERS)
    assert response.status_code == 401


def test_cle_admin_toujours_acceptee_pour_un_passage(client):
    response = client.post(
        URL, json=_passage("AA-111-AA", 1, "2026-09-02T10:00:00Z"), headers=AUTH_HEADERS
    )
    assert response.status_code == 200


def test_mauvaise_cle_refusee(client):
    response = client.post(
        URL, json=_passage("AA-111-AA", 1, "2026-09-02T10:00:00Z"), headers={"X-API-Key": "faux"}
    )
    assert response.status_code == 401


def test_verification_de_cle_sans_effet_de_bord(client):
    """La borne teste sa clé avec un corps vide : 422 si la clé est bonne,
    401 sinon, et rien n'est enregistré."""

    assert client.post(URL, json={}, headers=BORNE_HEADERS).status_code == 422
    assert client.post(URL, json={}, headers={"X-API-Key": "faux"}).status_code == 401
    assert client.get(URL, headers=AUTH_HEADERS).json() == []


# --- Informations du ticket (champs ajoutés, non cassants) --------------------


def test_entree_indique_le_type_de_place(client):
    body = client.post(
        URL, json=_passage("DD-444-DD", 1, "2026-09-02T10:00:00Z"), headers=BORNE_HEADERS
    ).json()
    assert body["reservation"] is False
    assert body["placeType"] == {
        "category": 2,
        "isXl": False,
        "isElectric": True,
        "isHandicap": False,
    }
    assert body["enteredAt"] is None and body["durationMinutes"] is None


def test_sortie_indique_heure_entree_et_duree(client):
    client.post(URL, json=_passage("AA-111-AA", 1, "2026-09-02T10:00:00Z"), headers=BORNE_HEADERS)
    body = client.post(
        URL, json=_passage("AA-111-AA", 2, "2026-09-02T12:30:10Z"), headers=BORNE_HEADERS
    ).json()
    assert body["enteredAt"].startswith("2026-09-02T10:00:00")
    assert body["durationMinutes"] == 151  # minute entamée
    assert body["authorization"]["paymentAmount"] == 9.99
    assert body["placeType"] is None


def test_refus_sans_informations_de_ticket(client):
    client.post(URL, json=_passage("BB-222-BB", 1, "2026-09-02T10:00:00Z"), headers=BORNE_HEADERS)
    body = client.post(
        URL, json=_passage("BB-222-BB", 1, "2026-09-02T10:05:00Z"), headers=BORNE_HEADERS
    ).json()
    assert body["authorization"]["result"] == 2
    assert body["placeType"] is None and body["reservation"] is None


# --- Page ----------------------------------------------------------------------


def test_borne_redirige_vers_la_page_en_gardant_le_mode(client):
    response = client.get("/borne?mode=sortie", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/static/borne.html?mode=sortie"
    assert client.get("/borne", follow_redirects=False).headers["location"] == "/static/borne.html"


def test_page_borne_autonome_et_sans_donnees_d_exploitation(client):
    response = client.get("/static/borne.html")
    assert response.status_code == 200
    html = response.text
    for screen in ("screen-home", "screen-plate", "screen-wait", "screen-result", "screen-config"):
        assert f'id="{screen}"' in html
    # Aucune ressource externe.
    assert "https://" not in html.replace("http://www.w3.org/2000/svg", "")
    # La borne n'appelle que la route de passage, jamais les routes d'exploitation.
    for admin_route in (
        "/access/presences",
        "/access/events",
        "/access/vehicles/known",
        "/metrics",
    ):
        assert admin_route not in html
    # La plaque n'est jamais mémorisée dans le navigateur.
    assert "access.borne.plate" not in html
    assert html.count("localStorage.setItem") == 1
