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
        ("GET", "/api/v1/access/parking"),
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
    assert body["placeLabel"] == "Place de test"
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


def test_borne_servie_directement_sur_borne(client):
    """L'adresse reste `/borne` (pas de `.html`), mode compris."""

    for url in ("/borne", "/borne?mode=sortie"):
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert 'id="screen-plate"' in response.text


def test_ancienne_adresse_redirigee_vers_borne_en_gardant_le_mode(client):
    response = client.get("/static/borne.html?mode=entree", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/borne?mode=entree"
    assert client.get("/static/borne.html", follow_redirects=False).headers["location"] == "/borne"


def test_les_autres_fichiers_statiques_restent_servis(client):
    assert client.get("/static/dashboard.html").status_code == 200
    assert client.get("/static/fonts/MesloLGS-NF-Bold.woff2").status_code == 200


def test_page_borne_autonome_et_sans_donnees_d_exploitation(client):
    response = client.get("/borne")
    assert response.status_code == 200
    html = response.text
    for screen in (
        "screen-home",
        "screen-type",
        "screen-plate",
        "screen-wait",
        "screen-result",
        "screen-config",
    ):
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


# --- Mise en service depuis le dashboard ---------------------------------------

KEY_URL = "/api/v1/access/borne/key"


def test_dashboard_recupere_la_cle_borne_avec_la_cle_d_exploitation(client):
    response = client.get(KEY_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"borneKey": "test-borne-key-0001"}
    assert response.headers["cache-control"] == "no-store"


def test_cle_borne_jamais_remise_sans_cle_d_exploitation(client):
    assert client.get(KEY_URL).status_code == 401
    # La clé borne ne permet pas de se la faire redonner (ni d'en savoir plus).
    assert client.get(KEY_URL, headers=BORNE_HEADERS).status_code == 401


def test_cle_borne_non_definie(client, monkeypatch):
    from dataclasses import replace

    from src.interfaces.api.routers import access_router

    settings = access_router.get_settings()
    monkeypatch.setattr(access_router, "get_settings", lambda: replace(settings, borne_api_key=""))
    response = client.get(KEY_URL, headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert "BORNE_API_KEY" in response.json()["detail"]


def test_cle_borne_absente_des_logs(client, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        client.get(KEY_URL, headers=AUTH_HEADERS)
    assert all("test-borne-key-0001" not in r.getMessage() for r in caplog.records)


def test_bouton_de_mise_en_service_dans_le_dashboard(client):
    html = client.get("/static/dashboard.html").text
    assert 'id="borneLaunch" hidden' in html  # caché tant que la clé n'est pas validée
    assert "/api/v1/access/borne/key" in html
    assert "access.borne.key" in html  # même emplacement que celui lu par la borne


def test_ecran_type_de_vehicule_en_francais(client):
    html = client.get("/borne").text
    for code, label in [
        ("STANDARD", "Voiture"),
        ("ELECTRIC", "Électrique"),
        ("XL", "Grand gabarit"),
        ("HANDICAPPED", "Mobilité réduite"),
        ("TWO_WHEELS", "Deux-roues"),
    ]:
        assert f'code: "{code}", name: "{label}"' in html
    # Jamais de libellé technique de Parking à l'écran.
    assert "data.placeLabel ||" not in html
