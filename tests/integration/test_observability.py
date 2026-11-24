"""Tests d'intégration — métriques métier, jauge des présences et en-têtes de
sécurité (jalons 13 et 15)."""

from prometheus_client import REGISTRY
from sqlalchemy.orm import sessionmaker

from src.infrastructure.db.repositories.sql_vehicle_presence_repository import (
    SqlVehiclePresenceRepository,
)
from src.infrastructure.metrics import register_presence_collector
from tests.integration.conftest import AUTH_HEADERS

URL = "/api/v1/access/requests"


def _sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _passage(client, plate: str, type_: int, date: str):
    return client.post(
        URL,
        json={"licensePlate": plate, "type": type_, "date": date, "source": 3},
        headers=AUTH_HEADERS,
    )


def test_metrics_metier_exposees_apres_des_passages(client):
    before_ok = _sample("access_decisions_total", type="entry", result="authorized")
    before_refused = _sample(
        "access_refusals_total", type="entry", reason="Véhicule déjà présent dans le parking"
    )

    _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z")
    _passage(client, "AA-111-AA", 1, "2026-09-02T10:05:00Z")  # déjà présent → refus

    assert _sample("access_decisions_total", type="entry", result="authorized") == before_ok + 1
    assert (
        _sample(
            "access_refusals_total", type="entry", reason="Véhicule déjà présent dans le parking"
        )
        == before_refused + 1
    )
    body = client.get("/metrics", headers=AUTH_HEADERS).text
    assert "access_decisions_total" in body
    assert "access_refusals_total" in body


def test_jauge_des_vehicules_presents(client):
    session_factory = sessionmaker(bind=client.test_engine)

    def count() -> int:
        session = session_factory()
        try:
            return SqlVehiclePresenceRepository(session).count_present()
        finally:
            session.close()

    register_presence_collector(count)
    assert _sample("access_vehicles_present") == 0

    _passage(client, "AA-111-AA", 1, "2026-09-02T10:00:00Z")
    _passage(client, "BB-222-BB", 1, "2026-09-02T10:00:00Z")
    assert _sample("access_vehicles_present") == 2

    _passage(client, "AA-111-AA", 2, "2026-09-02T12:00:00Z")
    assert _sample("access_vehicles_present") == 1


def test_metrics_requiert_la_cle_api(client):
    assert client.get("/metrics").status_code == 401


def test_entetes_de_securite(client):
    response = client.get(URL, headers=AUTH_HEADERS)
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_hsts_derriere_le_proxy_https(client):
    response = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
