"""Règle PMR (section 5 de la spec).

- Si la place attribuée est de type Handicapé, un justificatif PMR valide
  est requis (récupéré via `VehiclesServicePort`).
- Absence de justificatif valide → `CONFIRMATION_REQUISE`, pas un refus
  direct.
"""

from __future__ import annotations

from src.domain.value_objects.dto import PlaceType


def requires_pmr_confirmation(place_type: PlaceType, justificatif_pmr: bool) -> bool:
    """`True` si une confirmation PMR est requise avant d'autoriser l'accès."""

    return place_type.is_handicap and not justificatif_pmr
