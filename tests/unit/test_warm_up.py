"""Tests unitaires — réveil des services de l'équipe (`warm_up.py`)."""

import logging
import threading

import httpx
import pytest

from src.infrastructure.external import warm_up
from src.infrastructure.external.warm_up import warm_up_services

SERVICES = {"vehicles": "https://vehicles.test/", "parking": "https://parking.test", "vide": ""}


@pytest.fixture(autouse=True)
def _oubli():
    warm_up.reset_warm_up()
    yield
    warm_up.reset_warm_up()


def _transport(seen, status=200):
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            seen.append((request.method, str(request.url)))
        return httpx.Response(status, json={"status": "ok"})

    return httpx.MockTransport(handler)


def test_un_get_health_par_service_sans_donnee():
    seen = []
    assert warm_up_services(SERVICES, transport=_transport(seen), wait=True) is True
    assert sorted(seen) == [
        ("GET", "https://parking.test/health"),
        ("GET", "https://vehicles.test/health"),
    ]


def test_pas_de_nouveau_reveil_avant_le_delai():
    seen = []
    transport = _transport(seen)
    assert warm_up_services(SERVICES, transport=transport, wait=True) is True
    assert warm_up_services(SERVICES, transport=transport, wait=True) is False
    assert len(seen) == 2


def test_nouveau_reveil_une_fois_le_delai_passe():
    seen = []
    transport = _transport(seen)
    warm_up_services(SERVICES, transport=transport, wait=True)
    assert warm_up_services(SERVICES, transport=transport, wait=True, min_interval_s=0) is True
    assert len(seen) == 4


def test_service_injoignable_sans_consequence(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    with caplog.at_level(logging.INFO):
        assert warm_up_services(SERVICES, transport=httpx.MockTransport(handler), wait=True) is True
    assert any("pas de réponse" in r.getMessage() for r in caplog.records)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_l_appel_ne_bloque_pas():
    """Sans `wait`, l'appel rend la main même si un service met du temps."""

    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        release.wait(5)
        return httpx.Response(200)

    assert warm_up_services(SERVICES, transport=httpx.MockTransport(handler)) is True
    release.set()
