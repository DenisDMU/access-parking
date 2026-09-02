"""Entité *Autorisation d'accès* (objet métier officiel du cadrage)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.value_objects.enums import ResultatAutorisation


@dataclass
class AutorisationAcces:
    """Décision rendue pour une Demande d'accès donnée."""

    id: str
    demande_id: str
    resultat: ResultatAutorisation
    motif: str | None = None
    autorisation_service_ok: bool | None = None
    controle_type_vehicule_ok: bool | None = None
    controle_pmr_ok: bool | None = None
    montant_paiement: Decimal | None = None
