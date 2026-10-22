"""Fixtures d'intégration — `TestClient` FastAPI sur SQLite de test.

La base de test est un SQLite en mémoire dédié (StaticPool, une seule
connexion partagée) injecté via `app.dependency_overrides`, isolé de la
base de développement (`access.db`).
"""

from __future__ import annotations

import os

# Variables d'environnement de test — définies AVANT tout import de `src.*`
# pour que `infrastructure.config.get_settings()` les lise dès le départ.
# Chaque bascule PAR SERVICE encore mockée est fixée explicitement (pas
# seulement USE_MOCKS) pour que les tests restent hermétiques même si le
# `.env` local du développeur active un vrai service — sinon
# `load_dotenv()` (appelé par `infrastructure/config.py`) le ferait fuiter
# dans l'environnement de test, rendant la suite dépendante du réseau et
# non déterministe. Pricing, Parking et Payment n'ont plus de bascule (mocks
# supprimés du code) : ils sont remplacés ci-dessous par des dependency
# overrides dédiés.
os.environ["API_KEY"] = "test-api-key"
os.environ["USE_MOCKS"] = "true"
os.environ["VEHICLES_USE_MOCK"] = "true"
os.environ["BOOKING_USE_MOCK"] = "true"
os.environ["PAYMENT_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["EVENT_SUBSCRIBERS_URLS"] = ""
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ.pop("RENDER_GIT_COMMIT", None)

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.session import init_db  # noqa: E402
from src.interfaces.api import deps  # noqa: E402
from src.interfaces.api.main import app  # noqa: E402
from src.interfaces.api.rate_limit import limiter  # noqa: E402
from tests.unit.fakes import FakeParkingPort, FakePaymentPort, FakePricingPort  # noqa: E402

AUTH_HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture()
def client():
    limiter.reset()  # isole chaque test du rate limiting (état global partagé)
    test_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(test_engine)
    test_session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def _override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    def _override_get_engine():
        return test_engine

    app.dependency_overrides[deps.get_db_session] = _override_get_db_session
    app.dependency_overrides[deps.get_engine] = _override_get_engine
    # Pricing, Parking et Payment n'ont plus de mock dans infrastructure/external/
    # (branchés sur les vrais services de l'équipe) — les tests remplacent
    # ces ports par des doubles déterministes pour ne jamais dépendre du
    # réseau.
    app.dependency_overrides[deps.get_pricing_port] = lambda: FakePricingPort(
        amount=Decimal("9.99")
    )
    app.dependency_overrides[deps.get_parking_port] = lambda: FakeParkingPort()
    app.dependency_overrides[deps.get_payment_port] = lambda: FakePaymentPort()

    with TestClient(app) as test_client:
        test_client.test_engine = (
            test_engine  # exposé pour les tests qui inspectent la DB directement
        )
        yield test_client

    app.dependency_overrides.clear()
    test_engine.dispose()
