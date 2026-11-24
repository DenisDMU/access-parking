"""Fixtures d'intégration — `TestClient` FastAPI sur SQLite de test.

La base de test est un SQLite en mémoire dédié (StaticPool, une seule
connexion partagée) injecté via `app.dependency_overrides`, isolé de la
base de développement (`access.db`).
"""

from __future__ import annotations

import os

# Variables d'environnement de test — définies AVANT tout import de `src.*`
# pour que `infrastructure.config.get_settings()` les lise dès le départ.
# La bascule de Booking (seul service encore mocké) est fixée explicitement
# (pas seulement USE_MOCKS) pour que les tests restent hermétiques même si
# le `.env` local du développeur active le vrai service — sinon
# `load_dotenv()` (appelé par `infrastructure/config.py`) le ferait fuiter
# dans l'environnement de test, rendant la suite dépendante du réseau et
# non déterministe. Vehicles, Pricing, Parking et Payment n'ont plus de
# bascule (mocks supprimés du code) : ils sont remplacés ci-dessous par des
# dependency overrides dédiés.
os.environ["API_KEY"] = "test-api-key"
os.environ["BORNE_API_KEY"] = "test-borne-key-0001"
os.environ["BORNE_PUBLIC"] = "true"
os.environ["RATE_LIMIT_BORNE"] = "10/minute"
os.environ["BOOKING_USE_MOCK"] = "true"
os.environ["PAYMENT_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["EVENT_SUBSCRIBERS_URLS"] = ""
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ.pop("RENDER_GIT_COMMIT", None)

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.session import (  # noqa: E402
    enforce_sqlite_foreign_keys,
    init_db,
    normalize_database_url,
)
from src.interfaces.api import deps  # noqa: E402
from src.interfaces.api.main import app  # noqa: E402
from src.interfaces.api.rate_limit import limiter  # noqa: E402
from src.interfaces.api.routers import borne_router  # noqa: E402
from tests.unit.fakes import (  # noqa: E402
    DEMO_VEHICLES,
    FakeParkingPort,
    FakePaymentPort,
    FakePricingPort,
    FakeVehiclesPort,
)

AUTH_HEADERS = {"X-API-Key": "test-api-key"}
BORNE_HEADERS = {"X-API-Key": "test-borne-key-0001"}


@pytest.fixture()
def client():
    limiter.reset()  # isole chaque test du rate limiting (état global partagé)
    borne_router.reset_parking_cache()  # et de l'occupation gardée pour la borne
    pg_url = os.getenv("ACCESS_TEST_DATABASE_URL")
    pg_schema = None
    if pg_url:
        # Mode « vraie base Postgres » (ex. Neon) : chaque test travaille dans
        # un schéma jetable, supprimé à la fin — les tables de production
        # (schéma public) ne sont jamais touchées.
        pg_schema = "access_test_" + uuid.uuid4().hex[:12]
        test_engine = create_engine(
            normalize_database_url(pg_url),
            connect_args={"options": f"-csearch_path={pg_schema}"},
            poolclass=StaticPool,
        )
        with test_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{pg_schema}"'))
    else:
        test_engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        # Clés étrangères appliquées comme en Postgres (production).
        enforce_sqlite_foreign_keys(test_engine)
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
    # Vehicles, Pricing, Parking et Payment n'ont plus de mock dans infrastructure/external/
    # (branchés sur les vrais services de l'équipe) — les tests remplacent
    # ces ports par des doubles déterministes pour ne jamais dépendre du
    # réseau.
    app.dependency_overrides[deps.get_pricing_port] = lambda: FakePricingPort(
        amount=Decimal("9.99")
    )
    app.dependency_overrides[deps.get_parking_port] = lambda: FakeParkingPort()
    app.dependency_overrides[deps.get_payment_port] = lambda: FakePaymentPort()
    # Une seule instance par test : un véhicule créé à l'entrée est retrouvé
    # à la sortie, comme avec le vrai Vehicles.
    vehicles = FakeVehiclesPort(DEMO_VEHICLES)
    app.dependency_overrides[deps.get_vehicles_port] = lambda: vehicles

    with TestClient(app) as test_client:
        test_client.test_engine = (
            test_engine  # exposé pour les tests qui inspectent la DB directement
        )
        test_client.vehicles = vehicles  # faux Vehicles, pour simuler une panne
        yield test_client

    app.dependency_overrides.clear()
    if pg_schema:
        with test_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{pg_schema}" CASCADE'))
    test_engine.dispose()
