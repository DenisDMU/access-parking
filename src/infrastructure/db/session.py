"""Création du moteur SQLAlchemy et des sessions.

`init_db(engine)` crée les 5 tables automatiquement au démarrage (Definition
of Done, section 15) — pas de migration Alembic pour ce MVP.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.db.models import Base


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


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
