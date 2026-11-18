"""Implémentation SQL (SQLAlchemy) du `VehiclePresenceRepositoryPort` —
SQLite en local et dans les tests, Postgres (Neon) en production."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.domain.entities.vehicle_presence import VehiclePresence
from src.domain.value_objects.enums import PresenceStatus
from src.infrastructure.db.models import VehiclePresenceModel


class SqlVehiclePresenceRepository:
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

    def list_present(self) -> list[VehiclePresence]:
        stmt = (
            select(VehiclePresenceModel)
            .where(VehiclePresenceModel.status == int(PresenceStatus.IN))
            .order_by(VehiclePresenceModel.updated_at.desc())
        )
        rows = self._session.execute(stmt).scalars().all()
        return [
            VehiclePresence(
                vehicle_id=row.vehicle_id,
                status=PresenceStatus(row.status),
                updated_at=row.updated_at
                if row.updated_at.tzinfo
                else row.updated_at.replace(tzinfo=UTC),
                current_request_id=row.current_request_id,
            )
            for row in rows
        ]

    def count_present(self) -> int:
        stmt = select(func.count()).where(VehiclePresenceModel.status == int(PresenceStatus.IN))
        return int(self._session.execute(stmt).scalar_one())
