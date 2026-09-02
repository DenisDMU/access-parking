"""Entité *Événement d'accès* (objet métier officiel du cadrage)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.value_objects.enums import TypeEvenement


@dataclass
class EvenementAcces:
    """Un événement produit par Access, journalisé puis diffusé (fan-out).

    `payload` utilise exclusivement `vehiculeId` (pseudonymisé) — jamais la
    plaque brute (cf. section 6/11 de la spec).
    """

    id: str
    type: TypeEvenement
    demande_id: str
    payload: dict
    created_at: datetime
