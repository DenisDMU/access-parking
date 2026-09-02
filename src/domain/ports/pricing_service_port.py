"""Port vers le service Pricing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from src.domain.value_objects.dto import PlaceType


class PricingServicePort(Protocol):
    def calculate_price(
        self,
        vehicule_id: str,
        date_entree: datetime,
        date_sortie: datetime,
        type_place: PlaceType,
    ) -> Decimal:
        """Calcule le montant dû pour ce stationnement."""
        ...
