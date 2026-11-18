"""Tests unitaires — configuration de la base (SQLite local, Postgres en production)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.infrastructure.db.session import init_db, make_engine, normalize_database_url


@pytest.mark.parametrize(
    "url, attendu",
    [
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///./access.db", "sqlite:///./access.db"),
    ],
)
def test_url_postgres_utilise_psycopg(url, attendu):
    assert normalize_database_url(url) == attendu


def test_sqlite_applique_les_cles_etrangeres_comme_postgres():
    engine = make_engine("sqlite://")
    init_db(engine)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicle_presence (vehicle_id, status, current_request_id, updated_at)"
                " VALUES ('v1', 1, 'demande-inexistante', '2026-11-18 10:00:00')"
            )
        )
