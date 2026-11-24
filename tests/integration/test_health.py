"""Test d'intégration — `GET /health` (sans authentification)."""

from src import __version__
from tests.integration.conftest import AUTH_HEADERS  # noqa: F401 (réexport pour lisibilité)


def test_health_sans_api_key(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert isinstance(body["uptimeSeconds"], int)
    # Moteur seulement (jamais l'URL ni ses identifiants)
    assert body["databaseEngine"] in ("sqlite", "postgresql")


def test_health_expose_version_et_commit(client):
    body = client.get("/health").json()
    assert body["version"] == __version__
    # Hors Render, RENDER_GIT_COMMIT n'est pas défini
    assert body["commit"] == "local"


def test_health_indique_si_booking_est_reel_ou_simule(client):
    # Les tests simulent Booking (BOOKING_USE_MOCK=true dans conftest).
    assert client.get("/health").json()["booking"] == "simulé"


# --- Réveil des services de l'équipe (offre gratuite de Render) ------------------


def test_reveil_desactive_pendant_les_tests(client):
    from src.interfaces.api import deps

    assert deps.wake_services() is False


def test_reveil_demande_a_l_ouverture_de_la_borne_et_du_dashboard(client, monkeypatch):
    from src.interfaces.api import deps

    calls = []
    monkeypatch.setattr(deps, "wake_services", lambda: calls.append(1) or True)
    assert client.get("/api/v1/borne/status").status_code == 200
    assert client.get("/health").status_code == 200
    assert len(calls) == 2


def test_reveil_vise_les_cinq_services(client, monkeypatch):
    from dataclasses import replace

    from src.interfaces.api import deps

    seen = {}
    settings = replace(deps.get_settings(), warm_up_services=True, booking_use_mock=False)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "warm_up_services", lambda services: seen.update(services) or True)
    assert deps.wake_services() is True
    assert set(seen) == {"vehicles", "parking", "pricing", "payment", "booking"}
