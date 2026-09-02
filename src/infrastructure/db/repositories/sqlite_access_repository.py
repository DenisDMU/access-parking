"""Implémentation SQLite du `AccessRepositoryPort`."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.value_objects.dto import AccessFilters
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    EventType,
    RequestStatus,
    RequestType,
)
from src.infrastructure.db.models import (
    AccessAuthorizationModel,
    AccessEventModel,
    AccessRequestModel,
)


def _ensure_utc(dt: datetime) -> datetime:
    """SQLite ne conserve pas le fuseau horaire : les datetimes relues sont
    naïves alors qu'elles représentent toujours un instant UTC (les dates
    entrantes sont normalisées en UTC dès la validation Pydantic, cf.
    `AccessRequestIn`). On la réattache pour permettre des soustractions
    sûres (calcul de durée pour Pricing)."""

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _request_to_entity(row: AccessRequestModel) -> AccessRequest:
    return AccessRequest(
        id=row.id,
        type=RequestType(row.type),
        date=_ensure_utc(row.date),
        source=DetectionSource(row.source),
        status=RequestStatus(row.status),
        vehicle_id=row.vehicle_id,
        ai_check=row.ai_check,
    )


def _authorization_to_entity(row: AccessAuthorizationModel) -> AccessAuthorization:
    return AccessAuthorization(
        id=row.id,
        request_id=row.request_id,
        result=AuthorizationResult(row.result),
        reason=row.reason,
        authorization_service_ok=row.authorization_service_ok,
        vehicle_type_check_ok=row.vehicle_type_check_ok,
        disability_check_ok=row.disability_check_ok,
        payment_amount=row.payment_amount,
    )


def _event_to_entity(row: AccessEventModel) -> AccessEvent:
    return AccessEvent(
        id=row.id,
        type=EventType(row.type),
        request_id=row.request_id,
        payload=row.payload,
        created_at=_ensure_utc(row.created_at),
    )


class SqliteAccessRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_request(self, request: AccessRequest) -> None:
        row = AccessRequestModel(
            id=request.id,
            vehicle_id=request.vehicle_id,
            type=int(request.type),
            date=request.date,
            source=int(request.source),
            ai_check=request.ai_check,
            status=int(request.status),
        )
        self._session.merge(row)
        self._session.commit()

    def save_authorization(self, authorization: AccessAuthorization) -> None:
        row = AccessAuthorizationModel(
            id=authorization.id,
            request_id=authorization.request_id,
            result=int(authorization.result),
            reason=authorization.reason,
            authorization_service_ok=authorization.authorization_service_ok,
            vehicle_type_check_ok=authorization.vehicle_type_check_ok,
            disability_check_ok=authorization.disability_check_ok,
            payment_amount=authorization.payment_amount,
        )
        self._session.merge(row)
        self._session.commit()

    def save_event(self, event: AccessEvent) -> None:
        row = AccessEventModel(
            id=event.id,
            type=int(event.type),
            request_id=event.request_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        self._session.merge(row)
        self._session.commit()

    def get_request(self, request_id: str) -> AccessRequest | None:
        row = self._session.get(AccessRequestModel, request_id)
        return _request_to_entity(row) if row else None

    def list_requests(self, filters: AccessFilters) -> list[AccessRequest]:
        stmt = select(AccessRequestModel)
        if filters.vehicle_id is not None:
            stmt = stmt.where(AccessRequestModel.vehicle_id == filters.vehicle_id)
        if filters.type is not None:
            stmt = stmt.where(AccessRequestModel.type == int(filters.type))
        if filters.date_from is not None:
            stmt = stmt.where(AccessRequestModel.date >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(AccessRequestModel.date <= filters.date_to)
        stmt = stmt.order_by(AccessRequestModel.date.desc())
        rows = self._session.execute(stmt).scalars().all()
        return [_request_to_entity(row) for row in rows]

    def get_authorization_by_request(self, request_id: str) -> AccessAuthorization | None:
        stmt = select(AccessAuthorizationModel).where(
            AccessAuthorizationModel.request_id == request_id
        )
        row = self._session.execute(stmt).scalars().first()
        return _authorization_to_entity(row) if row else None

    def get_event_by_request(self, request_id: str) -> AccessEvent | None:
        stmt = (
            select(AccessEventModel)
            .where(AccessEventModel.request_id == request_id)
            .order_by(AccessEventModel.created_at.desc())
        )
        row = self._session.execute(stmt).scalars().first()
        return _event_to_entity(row) if row else None

    def list_events(self, limit: int = 100, offset: int = 0) -> list[AccessEvent]:
        stmt = (
            select(AccessEventModel)
            .order_by(AccessEventModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_event_to_entity(row) for row in rows]
