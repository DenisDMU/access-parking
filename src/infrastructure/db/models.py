"""Modèles SQLAlchemy — reflètent exactement le modèle de données de la
section 6 de la spec (5 tables, tous les enums tinyint en `Integer`)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DemandeAccesModel(Base):
    """Table `demandes_acces` — objet officiel *Demande d'accès*."""

    __tablename__ = "demandes_acces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    vehicule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_check: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    statut: Mapped[int] = mapped_column(Integer, nullable=False)


class AutorisationAccesModel(Base):
    """Table `autorisations_acces` — objet officiel *Autorisation d'accès*."""

    __tablename__ = "autorisations_acces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    demande_id: Mapped[str] = mapped_column(
        String, ForeignKey("demandes_acces.id"), nullable=False
    )
    resultat: Mapped[int] = mapped_column(Integer, nullable=False)
    motif: Mapped[str | None] = mapped_column(String, nullable=True)
    autorisation_service_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    controle_type_vehicule_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    controle_pmr_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    montant_paiement: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class EvenementAccesModel(Base):
    """Table `evenements_acces` — objet officiel *Événement d'accès*."""

    __tablename__ = "evenements_acces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False)
    demande_id: Mapped[str] = mapped_column(
        String, ForeignKey("demandes_acces.id"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VehiclePresenceModel(Base):
    """Table technique `vehicle_presence`, interne à Access."""

    __tablename__ = "vehicle_presence"

    vehicule_id: Mapped[str] = mapped_column(String, primary_key=True)
    statut: Mapped[int] = mapped_column(Integer, nullable=False)
    demande_id_courante: Mapped[str | None] = mapped_column(
        String, ForeignKey("demandes_acces.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class OutboxEventModel(Base):
    """Table technique `outbox_events` — publication asynchrone."""

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    evenement_id: Mapped[str] = mapped_column(
        String, ForeignKey("evenements_acces.id"), nullable=False
    )
    publie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
