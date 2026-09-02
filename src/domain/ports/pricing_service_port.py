"""Port vers le service Pricing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from src.domain.value_objects.dto import PlaceType


class PricingServicePort(Protocol):
    def calculate_price(
        self,
        vehicle_id: str,
        entry_date: datetime,
        exit_date: datetime,
        place_type: PlaceType,
    ) -> Decimal:
        """Calcule le montant dû pour ce stationnement."""
        ...
