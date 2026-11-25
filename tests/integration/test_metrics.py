"""Tests d'intégration — `GET /metrics` (TP « Observabilité avec Prometheus »).

La route exige la clé d'exploitation ou le jeton de lecture `METRICS_TOKEN` :
ces tests vérifient cette protection, le format, que les compteurs suivent
l'usage de l'API et les opérations métier, et qu'aucune étiquette ne peut
porter une plaque, un identifiant ou un chemin brut.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus_client import REGISTRY
from prometheus_client.parser import text_string_to_metric_families

from src.infrastructure.config import get_settings
from src.infrastructure.security import api_key_auth
from tests.integration.conftest import AUTH_HEADERS, BORNE_HEADERS

REQUESTS = "/api/v1/access/requests"
PLATE = "AA-111-AA"

OPERATIONS = {"entry", "exit", "forced_exit"}
RESULTS = {"authorized", "refused", "confirmation_required"}
STATUS_CLASSES = {"1xx", "2xx", "3xx", "4xx", "5xx"}


def _sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _http(handler: str, method: str, status: str) -> float:
    return _sample("http_requests_total", handler=handler, method=method, status=status)


def _operation(operation: str, result: str) -> float:
    return _sample("parking_operations_total", operation=operation, result=result)


def _passage(client, plate: str, type_: int, date: str) -> dict:
    response = client.post(
        REQUESTS,
        json={"licensePlate": plate, "type": type_, "date": date, "source": 3},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    return response.json()


def _families(client) -> dict:
    return {
        f.name: f
        for f in text_string_to_metric_families(client.get("/metrics", headers=AUTH_HEADERS).text)
    }


def test_metrics_refuse_sans_cle_ni_jeton(client):
    wrong = "x" * 12
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-API-Key": wrong}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Bearer {wrong}"}).status_code == 401
    # Un refus ne montre rien : ni compteur, ni nom de métrique.
    refused = client.get("/metrics")
    assert refused.json() == {"detail": "Clé API manquante ou invalide"}
    assert "http_requests_total" not in refused.text


def test_jeton_de_lecture_reserve_aux_metriques(client, monkeypatch):
    """`METRICS_TOKEN` lit `/metrics` (en-tête `X-API-Key` ou `Authorization:
    Bearer`) et rien d'autre ; la clé borne, elle, ne lit pas les métriques."""

    reader, admin = "r" * 24, AUTH_HEADERS["X-API-Key"]
    settings = replace(get_settings(), metrics_token=reader)
    monkeypatch.setattr(api_key_auth, "get_settings", lambda: settings)

    assert client.get("/metrics", headers={"X-API-Key": reader}).status_code == 200
    assert client.get("/metrics", headers={"Authorization": f"Bearer {reader}"}).status_code == 200
    assert client.get("/metrics", headers={"Authorization": f"Bearer {admin}"}).status_code == 200
    assert settings.borne_api_key == BORNE_HEADERS["X-API-Key"]
    assert client.get("/metrics", headers=BORNE_HEADERS).status_code == 401
    for path in ("/api/v1/access/requests", "/api/v1/access/presences", "/api/v1/access/events"):
        assert client.get(path, headers={"X-API-Key": reader}).status_code == 401


def test_sans_jeton_configure_un_jeton_vide_ne_passe_pas(client):
    assert get_settings().metrics_token == ""
    assert client.get("/metrics", headers={"X-API-Key": ""}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer "}).status_code == 401


def test_metrics_au_format_prometheus(client):
    response = client.get("/metrics", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")
    assert response.headers["Cache-Control"] == "no-store"
    assert "# TYPE http_requests_total counter" in response.text
    assert "# TYPE parking_operations_total counter" in response.text
    # Le texte entier se relit comme une exposition Prometheus valide.
    families = _families(client)
    assert families["http_requests"].type == "counter"
    assert families["parking_operations"].type == "counter"


def test_operations_visibles_a_zero_avant_le_premier_passage(client):
    """Séries créées dès le démarrage : sans cela, `rate()` ne voit pas le
    premier incrément et le graphique reste vide tant que rien ne s'est passé."""

    samples = [
        s
        for s in _families(client)["parking_operations"].samples
        if s.name == "parking_operations_total"
    ]
    seen = {(s.labels["operation"], s.labels["result"]) for s in samples}
    assert ("entry", "authorized") in seen
    assert ("exit", "refused") in seen
    assert ("forced_exit", "authorized") in seen


def test_http_requests_total_suit_les_appels_et_separe_succes_et_erreurs(client):
    ok_before = _http("/api/v1/access/events", "GET", "2xx")
    refused_before = _http("/api/v1/access/events", "GET", "4xx")

    assert client.get("/api/v1/access/events", headers=AUTH_HEADERS).status_code == 200
    assert client.get("/api/v1/access/events", headers=AUTH_HEADERS).status_code == 200
    assert client.get("/api/v1/access/events").status_code == 401  # sans clé

    assert _http("/api/v1/access/events", "GET", "2xx") == ok_before + 2
    assert _http("/api/v1/access/events", "GET", "4xx") == refused_before + 1
    body = client.get("/metrics", headers=AUTH_HEADERS).text
    assert 'handler="/api/v1/access/events",method="GET",status="2xx"' in body


def test_route_comptee_par_gabarit_jamais_par_chemin_brut(client):
    entry = _passage(client, PLATE, 1, "2026-09-02T10:00:00Z")
    request_id, vehicle_id = entry["requestId"], entry["vehicleId"]
    template = "/api/v1/access/requests/{request_id}"
    before = _http(template, "GET", "2xx")
    unknown_before = _http("none", "GET", "4xx")

    assert client.get(f"{REQUESTS}/{request_id}", headers=AUTH_HEADERS).status_code == 200
    # Une adresse inconnue qui contient une plaque : regroupée sous `none`.
    assert client.get(f"/nimporte/{PLATE}").status_code == 404
    assert client.get(f"/api/v1/inconnu/{vehicle_id}").status_code == 404

    assert _http(template, "GET", "2xx") == before + 1
    assert _http("none", "GET", "4xx") == unknown_before + 2
    body = client.get("/metrics", headers=AUTH_HEADERS).text
    assert request_id not in body
    assert vehicle_id not in body
    assert PLATE not in body


def test_metrics_ne_compte_ni_ses_lectures_ni_la_sonde_de_sante(client):
    """Prometheus lit `/metrics` toutes les 15 s et Render sonde `/health` :
    comptées, ces lectures feraient croire à une activité qui n'existe pas."""

    for _ in range(5):
        client.get("/metrics", headers=AUTH_HEADERS)
        client.get("/health")

    body = client.get("/metrics", headers=AUTH_HEADERS).text
    assert 'handler="/metrics"' not in body
    assert 'handler="/health"' not in body


def test_metrics_hors_limitation_de_debit(client):
    # Bien au-delà de toutes les limites par adresse définies dans l'API.
    assert {client.get("/metrics", headers=AUTH_HEADERS).status_code for _ in range(80)} == {200}


def test_parking_operations_total_suit_les_entrees_et_sorties(client):
    entry_ok = _operation("entry", "authorized")
    entry_refused = _operation("entry", "refused")
    exit_ok = _operation("exit", "authorized")
    exit_refused = _operation("exit", "refused")

    _passage(client, PLATE, 1, "2026-09-02T10:00:00Z")  # entrée autorisée
    _passage(client, PLATE, 1, "2026-09-02T10:05:00Z")  # déjà présent → refus
    _passage(client, PLATE, 2, "2026-09-02T12:00:00Z")  # sortie autorisée
    _passage(client, PLATE, 2, "2026-09-02T12:05:00Z")  # déjà sorti → refus

    assert _operation("entry", "authorized") == entry_ok + 1
    assert _operation("entry", "refused") == entry_refused + 1
    assert _operation("exit", "authorized") == exit_ok + 1
    assert _operation("exit", "refused") == exit_refused + 1
    body = client.get("/metrics", headers=AUTH_HEADERS).text
    assert 'parking_operations_total{operation="entry",result="authorized"}' in body


def test_parking_operations_total_compte_un_passage_a_la_borne_publique(client):
    before = _operation("entry", "authorized")

    response = client.post("/api/v1/borne/passages", json={"licensePlate": PLATE, "type": 1})

    assert response.status_code == 200
    assert _operation("entry", "authorized") == before + 1


def test_parking_operations_total_compte_la_sortie_forcee(client):
    done = _operation("forced_exit", "authorized")
    missed = _operation("forced_exit", "refused")
    vehicle_id = _passage(client, PLATE, 1, "2026-09-02T10:00:00Z")["vehicleId"]
    release = f"/api/v1/access/presences/{vehicle_id}/release"

    assert client.post(release, headers=AUTH_HEADERS).status_code == 200
    assert client.post(release, headers=AUTH_HEADERS).status_code == 404  # plus présent

    assert _operation("forced_exit", "authorized") == done + 1
    assert _operation("forced_exit", "refused") == missed + 1
    # La route porte un identifiant de véhicule : seul son gabarit est exposé.
    body = client.get("/metrics", headers=AUTH_HEADERS).text
    assert 'handler="/api/v1/access/presences/{vehicle_id}/release"' in body
    assert vehicle_id not in body


def test_une_requete_refusee_sans_cle_ne_compte_pas_d_operation(client):
    before = sum(_operation(o, r) for o in OPERATIONS for r in RESULTS)

    response = client.post(REQUESTS, json={"licensePlate": PLATE, "type": 1, "source": 3})

    assert response.status_code == 401
    assert sum(_operation(o, r) for o in OPERATIONS for r in RESULTS) == before


def test_aucune_plaque_ni_identifiant_dans_les_metriques(client):
    """Balayage de toute l'exposition après des passages réussis, refusés et
    invalides : la plaque (sous toutes ses formes) et les identifiants rendus
    par l'API n'apparaissent nulle part."""

    entry = _passage(client, PLATE, 1, "2026-09-02T10:00:00Z")
    refused = _passage(client, PLATE, 1, "2026-09-02T10:05:00Z")
    client.post("/api/v1/borne/passages", json={"licensePlate": "ZZ#999", "type": 1})  # 422
    client.post("/api/v1/access/vehicles/known", json={"licensePlate": PLATE}, headers=AUTH_HEADERS)

    body = client.get("/metrics", headers=AUTH_HEADERS).text
    for secret in (PLATE, "AA111AA", "AA 111 AA", "ZZ#999", "ZZ999"):
        assert secret not in body
    for identifier in (entry["vehicleId"], entry["requestId"], refused["requestId"]):
        assert identifier not in body


def test_etiquettes_des_compteurs_du_tp_bornees(client):
    _passage(client, PLATE, 1, "2026-09-02T10:00:00Z")
    client.get(f"/nimporte/{PLATE}")
    families = _families(client)
    # Gabarits déclarés : ceux de la documentation, plus les pages hors schéma.
    routes = set(client.app.openapi()["paths"]) | {
        route.path for route in client.app.routes if hasattr(route, "path")
    }

    for sample in families["http_requests"].samples:
        if sample.name != "http_requests_total":
            continue
        assert set(sample.labels) == {"handler", "method", "status"}
        assert sample.labels["status"] in STATUS_CLASSES
        assert sample.labels["handler"] == "none" or sample.labels["handler"] in routes

    for sample in families["parking_operations"].samples:
        if sample.name != "parking_operations_total":
            continue
        assert set(sample.labels) == {"operation", "result"}
        assert sample.labels["operation"] in OPERATIONS
        assert sample.labels["result"] in RESULTS
