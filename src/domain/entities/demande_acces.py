"""Entité *Demande d'accès* (objet métier officiel du cadrage)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.value_objects.enums import SourceDetection, StatutDemande, TypeDemande


@dataclass
class DemandeAcces:
    """Une demande d'entrée ou de sortie formulée par/pour un véhicule.

    `vehicule_id` est `None` tant que le véhicule n'a pas été résolu par
    Vehicles (ou reste `None` définitivement s'il est inconnu). Il ne
    contient **jamais** la plaque brute — voir section 6/8 de la spec.
    """

    id: str
    type: TypeDemande
    date: datetime
    source: SourceDetection
    statut: StatutDemande
    vehicule_id: str | None = None
    ai_check: dict | None = None
