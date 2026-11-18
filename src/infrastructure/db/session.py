"""Création du moteur SQLAlchemy et des sessions.

`init_db(engine)` crée les 5 tables automatiquement au démarrage (Definition
of Done, section 15) — pas de migration Alembic pour ce MVP.

SQLite en local et dans les tests ; Postgres (Neon) en production, pour que
les données survivent aux redémarrages de Render (disque éphémère).
"""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.db.models import Base


def normalize_database_url(database_url: str) -> str:
    """Accepte les URL Postgres telles que fournies par Neon / Render
    (`postgres://` ou `postgresql://`) et choisit le pilote psycopg 3."""

    for prefix in ("postgres://", "postgresql://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix) :]
    return database_url


def enforce_sqlite_foreign_keys(engine: Engine) -> None:
    """SQLite ignore les clés étrangères par défaut, Postgres les impose :
    on les active aussi en SQLite (local, tests) pour se comporter pareil."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def make_engine(database_url: str) -> Engine:
    url = normalize_database_url(database_url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})
        enforce_sqlite_foreign_keys(engine)
        return engine
    # Base hébergée (Neon) : elle se met en pause après quelques minutes sans
    # activité et coupe alors les connexions ouvertes. pool_pre_ping vérifie
    # chaque connexion avant usage et la recrée si besoin.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


def make_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)


def check_connection(engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
