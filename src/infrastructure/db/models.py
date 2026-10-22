"""Modèles SQLAlchemy — reflètent le modèle de données de la section 6 de la
spec (5 tables, tous les enums tinyint en `Integer`), avec noms de
tables/colonnes traduits en anglais (voir README, "Tables de correspondance
FR/EN")."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccessRequestModel(Base):
    """Table `access_requests` — objet officiel *Demande d'accès*."""

    __tablename__ = "access_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    vehicle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_check: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False)


class AccessAuthorizationModel(Base):
    """Table `access_authorizations` — objet officiel *Autorisation d'accès*."""

    __tablename__ = "access_authorizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("access_requests.id"), nullable=False
    )
    result: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    authorization_service_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    vehicle_type_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    disability_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class AccessEventModel(Base):
    """Table `access_events` — objet officiel *Événement d'accès*."""

    __tablename__ = "access_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("access_requests.id"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VehiclePresenceModel(Base):
    """Table technique `vehicle_presence`, interne à Access."""

    __tablename__ = "vehicle_presence"

    vehicle_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    current_request_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("access_requests.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class OutboxEventModel(Base):
    """Table technique `outbox_events` — publication asynchrone."""

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("access_events.id"), nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
