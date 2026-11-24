"""Tests unitaires — configuration de Booking (réel par défaut)."""

from src.infrastructure.config import BOOKING_DEFAULT_URL, Settings, _booking_service_url


def test_url_par_defaut(monkeypatch):
    monkeypatch.delenv("BOOKING_SERVICE_URL", raising=False)
    assert _booking_service_url() == BOOKING_DEFAULT_URL


def test_url_localhost_ignoree_sur_render(monkeypatch):
    """L'ancienne valeur du blueprint (localhost) ne doit pas masquer le vrai service."""

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("BOOKING_SERVICE_URL", "http://localhost:8002")
    assert _booking_service_url() == BOOKING_DEFAULT_URL


def test_url_localhost_gardee_en_local(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("BOOKING_SERVICE_URL", "http://localhost:8002")
    assert _booking_service_url() == "http://localhost:8002"


def test_booking_reel_par_defaut_meme_si_use_mocks_traine(monkeypatch):
    monkeypatch.setenv("USE_MOCKS", "true")  # ancienne bascule globale : sans effet
    monkeypatch.delenv("BOOKING_USE_MOCK", raising=False)
    assert Settings().booking_use_mock is False
    monkeypatch.setenv("BOOKING_USE_MOCK", "true")
    assert Settings().booking_use_mock is True
