"""Implémentation SQLite de la persistance `outbox_events`.

Utilisée uniquement par `OutboxEventPublisher` (infrastructure/events) —
n'est pas exposée via un port du domaine, c'est un détail d'implémentation
du mécanisme de publication d'événements (section 3 point 3 de la spec).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from src.infrastructure.db.models import OutboxEventModel


class SqliteOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_publication(self, evenement_id: str) -> None:
        row = OutboxEventModel(
            id=str(uuid4()),
            evenement_id=evenement_id,
            publie=True,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        self._session.commit()
