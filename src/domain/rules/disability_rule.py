"""Règle d'accessibilité PMR (section 5 de la spec, "Règle PMR").

- Si la place attribuée est de type Handicapé, un justificatif d'accessibilité
  (PMR) valide est requis (récupéré via `VehiclesServicePort`).
- Absence de justificatif valide → `CONFIRMATION_REQUIRED`, pas un refus
  direct.
"""

from __future__ import annotations

from src.domain.value_objects.dto import PlaceType


def requires_disability_confirmation(place_type: PlaceType, disability_permit: bool) -> bool:
    """`True` si une confirmation d'accessibilité est requise avant d'autoriser l'accès."""

    return place_type.is_handicap and not disability_permit
