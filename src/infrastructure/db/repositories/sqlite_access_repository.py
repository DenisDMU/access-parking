"""Implémentation SQLite du `AccessRepositoryPort`."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.entities.autorisation_acces import AutorisationAcces
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.entities.evenement_acces import EvenementAcces
from src.domain.value_objects.dto import AccessFilters
from src.domain.value_objects.enums import SourceDetection, StatutDemande, TypeDemande
from src.infrastructure.db.models import (
    AutorisationAccesModel,
    DemandeAccesModel,
    EvenementAccesModel,
)


def _ensure_utc(dt: datetime) -> datetime:
    """SQLite ne conserve pas le fuseau horaire : les datetimes relues sont
    naïves alors qu'elles représentent toujours un instant UTC (les dates
    entrantes sont normalisées en UTC dès la validation Pydantic, cf.
    `AccessRequestIn`). On la réattache pour permettre des soustractions
    sûres (calcul de durée pour Pricing)."""

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _demande_to_entity(row: DemandeAccesModel) -> DemandeAcces:
    return DemandeAcces(
        id=row.id,
        type=TypeDemande(row.type),
        date=_ensure_utc(row.date),
        source=SourceDetection(row.source),
        statut=StatutDemande(row.statut),
        vehicule_id=row.vehicule_id,
        ai_check=row.ai_check,
    )


def _autorisation_to_entity(row: AutorisationAccesModel) -> AutorisationAcces:
    from src.domain.value_objects.enums import ResultatAutorisation

    return AutorisationAcces(
        id=row.id,
        demande_id=row.demande_id,
        resultat=ResultatAutorisation(row.resultat),
        motif=row.motif,
        autorisation_service_ok=row.autorisation_service_ok,
        controle_type_vehicule_ok=row.controle_type_vehicule_ok,
        controle_pmr_ok=row.controle_pmr_ok,
        montant_paiement=row.montant_paiement,
    )


def _evenement_to_entity(row: EvenementAccesModel) -> EvenementAcces:
    from src.domain.value_objects.enums import TypeEvenement

    return EvenementAcces(
        id=row.id,
        type=TypeEvenement(row.type),
        demande_id=row.demande_id,
        payload=row.payload,
        created_at=_ensure_utc(row.created_at),
    )


class SqliteAccessRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_demande(self, demande: DemandeAcces) -> None:
        row = DemandeAccesModel(
            id=demande.id,
            vehicule_id=demande.vehicule_id,
            type=int(demande.type),
            date=demande.date,
            source=int(demande.source),
            ai_check=demande.ai_check,
            statut=int(demande.statut),
        )
        self._session.merge(row)
        self._session.commit()

    def save_autorisation(self, autorisation: AutorisationAcces) -> None:
        row = AutorisationAccesModel(
            id=autorisation.id,
            demande_id=autorisation.demande_id,
            resultat=int(autorisation.resultat),
            motif=autorisation.motif,
            autorisation_service_ok=autorisation.autorisation_service_ok,
            controle_type_vehicule_ok=autorisation.controle_type_vehicule_ok,
            controle_pmr_ok=autorisation.controle_pmr_ok,
            montant_paiement=autorisation.montant_paiement,
        )
        self._session.merge(row)
        self._session.commit()

    def save_evenement(self, evenement: EvenementAcces) -> None:
        row = EvenementAccesModel(
            id=evenement.id,
            type=int(evenement.type),
            demande_id=evenement.demande_id,
            payload=evenement.payload,
            created_at=evenement.created_at,
        )
        self._session.merge(row)
        self._session.commit()

    def get_demande(self, demande_id: str) -> DemandeAcces | None:
        row = self._session.get(DemandeAccesModel, demande_id)
        return _demande_to_entity(row) if row else None

    def list_demandes(self, filters: AccessFilters) -> list[DemandeAcces]:
        stmt = select(DemandeAccesModel)
        if filters.vehicule_id is not None:
            stmt = stmt.where(DemandeAccesModel.vehicule_id == filters.vehicule_id)
        if filters.type is not None:
            stmt = stmt.where(DemandeAccesModel.type == int(filters.type))
        if filters.date_from is not None:
            stmt = stmt.where(DemandeAccesModel.date >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(DemandeAccesModel.date <= filters.date_to)
        stmt = stmt.order_by(DemandeAccesModel.date.desc())
        rows = self._session.execute(stmt).scalars().all()
        return [_demande_to_entity(row) for row in rows]

    def get_autorisation_by_demande(self, demande_id: str) -> AutorisationAcces | None:
        stmt = select(AutorisationAccesModel).where(
            AutorisationAccesModel.demande_id == demande_id
        )
        row = self._session.execute(stmt).scalars().first()
        return _autorisation_to_entity(row) if row else None

    def get_evenement_by_demande(self, demande_id: str) -> EvenementAcces | None:
        stmt = (
            select(EvenementAccesModel)
            .where(EvenementAccesModel.demande_id == demande_id)
            .order_by(EvenementAccesModel.created_at.desc())
        )
        row = self._session.execute(stmt).scalars().first()
        return _evenement_to_entity(row) if row else None

    def list_evenements(self, limit: int = 100, offset: int = 0) -> list[EvenementAcces]:
        stmt = (
            select(EvenementAccesModel)
            .order_by(EvenementAccesModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_evenement_to_entity(row) for row in rows]
