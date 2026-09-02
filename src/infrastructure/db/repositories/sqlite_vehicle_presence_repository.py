"""Implémentation SQLite du `VehiclePresenceRepositoryPort`."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.domain.value_objects.enums import PresenceStatus
from src.infrastructure.db.models import VehiclePresenceModel


class SqliteVehiclePresenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_status(self, vehicule_id: str) -> PresenceStatus | None:
        row = self._session.get(VehiclePresenceModel, vehicule_id)
        return PresenceStatus(row.statut) if row else None

    def get_current_demande_id(self, vehicule_id: str) -> str | None:
        row = self._session.get(VehiclePresenceModel, vehicule_id)
        return row.demande_id_courante if row else None

    def set_status(
        self,
        vehicule_id: str,
        status: PresenceStatus,
        demande_id: str | None,
    ) -> None:
        row = VehiclePresenceModel(
            vehicule_id=vehicule_id,
            statut=int(status),
            demande_id_courante=demande_id,
            updated_at=datetime.now(timezone.utc),
        )
        self._session.merge(row)
        self._session.commit()
