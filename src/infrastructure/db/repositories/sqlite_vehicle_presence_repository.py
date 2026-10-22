"""Implémentation SQLite du `VehiclePresenceRepositoryPort`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.domain.value_objects.enums import PresenceStatus
from src.infrastructure.db.models import VehiclePresenceModel


class SqliteVehiclePresenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_status(self, vehicle_id: str) -> PresenceStatus | None:
        row = self._session.get(VehiclePresenceModel, vehicle_id)
        return PresenceStatus(row.status) if row else None

    def get_current_request_id(self, vehicle_id: str) -> str | None:
        row = self._session.get(VehiclePresenceModel, vehicle_id)
        return row.current_request_id if row else None

    def set_status(
        self,
        vehicle_id: str,
        status: PresenceStatus,
        request_id: str | None,
    ) -> None:
        row = VehiclePresenceModel(
            vehicle_id=vehicle_id,
            status=int(status),
            current_request_id=request_id,
            updated_at=datetime.now(UTC),
        )
        self._session.merge(row)
        self._session.commit()
