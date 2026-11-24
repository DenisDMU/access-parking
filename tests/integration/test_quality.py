"""Tests d'intégration — qualité et fiabilité (jalon 9).

Entrées invalides, cas limites, logs exploitables (correlation ID) et
liste d'audit avec décision.
"""

import logging

import pytest

from tests.integration.conftest import AUTH_HEADERS

URL = "/api/v1/access/requests"


def _payload(plate: str, type_: int, date: str, source: int = 3) -> dict:
    return {"licensePlate": plate, "type": type_, "date": date, "source": source}


# --- Entrées invalides --------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},  # tout manque
        _payload("ZZ-0-ZZZ", 1, "2026-09-02T10:00:00Z"),  # plaque mal formée
        _payload("A" * 21, 1, "2026-09-02T10:00:00Z"),  # plaque trop longue
        _payload("", 1, "2026-09-02T10:00:00Z"),  # plaque vide
        _payload("AA-111-AA", 3, "2026-09-02T10:00:00Z"),  # type inconnu
        _payload("AA-111-AA", 1, "2026-09-02T10:00:00Z", source=9),  # source inconnue
        _payload("AA-111-AA", 1, "pas-une-date"),  # date illisible
        {**_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"), "licensePlate": 123},  # non texte
    ],
)
def test_corps_invalide_renvoie_422_sans_rien_persister(client, body):
    response = client.post(URL, json=body, headers=AUTH_HEADERS)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert client.get(URL, headers=AUTH_HEADERS).json() == []


def test_json_mal_forme_renvoie_422(client):
    response = client.post(
        URL,
        content=b"{pas du json",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_photo_base64_invalide_renvoie_400(client):
    body = {**_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"), "photoBase64": "%%%"}
    response = client.post(URL, json=body, headers=AUTH_HEADERS)
    assert response.status_code == 400
    assert response.json() == {"detail": "photoBase64 invalide"}


def test_plaque_invalide_sur_known(client):
    response = client.post(
        "/api/v1/access/vehicles/known", json={"licensePlate": "ZZ-0-ZZZ"}, headers=AUTH_HEADERS
    )
    assert response.status_code == 422
    assert "ZZ-0-ZZZ" not in response.text


def test_filtre_periode_inversee_renvoie_422(client):
    response = client.get(
        URL,
        params={"from": "2026-09-03T00:00:00Z", "to": "2026-09-02T00:00:00Z"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422
    assert "from" in response.json()["detail"]


@pytest.mark.parametrize("limit", [0, 501])
def test_limit_hors_bornes_renvoie_422(client, limit):
    response = client.get(URL, params={"limit": limit}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_cle_api_invalide_renvoie_401_sans_detail_technique(client):
    response = client.get(URL, headers={"X-API-Key": "mauvaise-cle"})
    assert response.status_code == 401
    assert set(response.json()) == {"detail"}


# --- Cas limites métier ------------------------------------------------------------


def test_sortie_datee_avant_lentree_est_refusee(client):
    client.post(URL, json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"), headers=AUTH_HEADERS)

    body = client.post(
        URL, json=_payload("AA-111-AA", 2, "2026-09-02T09:00:00Z", source=2), headers=AUTH_HEADERS
    ).json()

    assert body["authorization"]["result"] == 2
    assert body["authorization"]["reason"] == "Date de sortie antérieure à la date d'entrée"
    # Toujours présent : une sortie valide reste possible ensuite
    assert len(client.get("/api/v1/access/presences", headers=AUTH_HEADERS).json()) == 1


def test_date_sans_fuseau_consideree_comme_utc(client):
    client.post(URL, json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00"), headers=AUTH_HEADERS)
    body = client.post(
        URL, json=_payload("AA-111-AA", 2, "2026-09-02T12:00:00Z", source=2), headers=AUTH_HEADERS
    ).json()
    assert body["authorization"]["result"] == 1


def test_liste_daudit_inclut_la_decision_plus_recente_dabord(client):
    client.post(URL, json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"), headers=AUTH_HEADERS)
    client.post(URL, json=_payload("AA-111-AA", 1, "2026-09-02T10:05:00Z"), headers=AUTH_HEADERS)

    items = client.get(URL, headers=AUTH_HEADERS).json()

    assert [i["result"] for i in items] == [2, 1]
    assert items[0]["reason"] == "Véhicule déjà présent dans le parking"
    assert client.get(URL, params={"limit": 1}, headers=AUTH_HEADERS).json() == items[:1]


# --- Logs exploitables / correlation ID ---------------------------------------------


def test_correlation_id_genere_et_renvoye(client):
    response = client.get("/health")
    assert len(response.headers["X-Correlation-ID"]) == 36  # UUID4


def test_correlation_id_fourni_est_reutilise(client):
    response = client.get("/health", headers={"X-Correlation-ID": "borne-42_abc"})
    assert response.headers["X-Correlation-ID"] == "borne-42_abc"


@pytest.mark.parametrize("bad", ["x" * 65, "a b", "cid] ERROR faux log", "<script>"])
def test_correlation_id_mal_forme_est_remplace(client, bad):
    # Trop long ou caractères hors [A-Za-z0-9._-] : ignoré (anti-injection
    # dans les logs), Access en génère un nouveau.
    response = client.get("/health", headers={"X-Correlation-ID": bad})
    assert response.headers["X-Correlation-ID"] != bad
    assert len(response.headers["X-Correlation-ID"]) == 36


def test_decision_loggee_avec_le_correlation_id(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.post(
        URL,
        json=_payload("AA-111-AA", 1, "2026-09-02T10:00:00Z"),
        headers={**AUTH_HEADERS, "X-Correlation-ID": "test-cid-1"},
    )
    request_id = response.json()["requestId"]

    decision = [r for r in caplog.records if "Entrée autorisée" in r.getMessage()]
    assert len(decision) == 1
    assert request_id in decision[0].getMessage()
    assert decision[0].correlation_id == "test-cid-1"

    access_log = [r for r in caplog.records if r.name == "access.http"]
    assert any("POST /api/v1/access/requests -> 200" in r.getMessage() for r in access_log)


def test_erreurs_loggees_en_warning_et_lectures_en_debug(client, caplog):
    caplog.set_level(logging.DEBUG, logger="access.http")
    client.get(URL, headers={"X-API-Key": "mauvaise-cle"})
    client.get(URL, headers=AUTH_HEADERS)

    levels = {
        r.getMessage().split(" -> ")[1][:3]: r.levelno
        for r in caplog.records
        if r.name == "access.http"
    }
    assert levels["401"] == logging.WARNING
    assert levels["200"] == logging.DEBUG


def test_erreur_interne_generique_avec_correlation_id(client):
    """Une panne imprévue renvoie un 500 sans détail technique, mais avec le
    correlation ID pour retrouver la stack trace dans les logs."""

    from fastapi.testclient import TestClient

    from src.interfaces.api import deps
    from src.interfaces.api.main import app

    def _boom():
        raise RuntimeError("secret technique à ne pas exposer")

    app.dependency_overrides[deps.get_list_access_requests_use_case] = _boom
    with TestClient(app, raise_server_exceptions=False) as raw_client:
        response = raw_client.get(URL, headers={**AUTH_HEADERS, "X-Correlation-ID": "cid-500"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Erreur interne du serveur", "correlationId": "cid-500"}
    assert response.headers["X-Correlation-ID"] == "cid-500"
