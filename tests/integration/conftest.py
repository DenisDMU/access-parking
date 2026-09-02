"""Fixtures d'intégration — `TestClient` FastAPI sur SQLite de test.

La base de test est un SQLite en mémoire dédié (StaticPool, une seule
connexion partagée) injecté via `app.dependency_overrides`, isolé de la
base de développement (`access.db`).
"""

from __future__ import annotations

import os

# Variables d'environnement de test — définies AVANT tout import de `src.*`
# pour que `infrastructure.config.get_settings()` les lise dès le départ.
os.environ["API_KEY"] = "test-api-key"
os.environ["USE_MOCKS"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["EVENT_SUBSCRIBERS_URLS"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.session import init_db  # noqa: E402
from src.interfaces.api import deps  # noqa: E402
from src.interfaces.api.main import app  # noqa: E402
from src.interfaces.api.rate_limit import limiter  # noqa: E402

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

    with TestClient(app) as test_client:
        test_client.test_engine = test_engine  # exposé pour les tests qui inspectent la DB directement
        yield test_client

    app.dependency_overrides.clear()
    test_engine.dispose()
