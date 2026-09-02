"""Mock du service Pricing.

Formule simple et déterministe : un forfait de base + un tarif horaire,
arrondie au centime, avec un minimum d'un forfait de base — suffisante pour
exercer le workflow "Sortie" de bout en bout sans modéliser une vraie
grille tarifaire (hors périmètre MVP).
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from src.domain.value_objects.dto import PlaceType

_BASE_FEE = Decimal("2.00")
_HOURLY_RATE = Decimal("1.50")


class MockPricingClient:
    """Implémente `PricingServicePort`."""

    def calculate_price(
        self,
        vehicle_id: str,
        entry_date: datetime,
        exit_date: datetime,
        place_type: PlaceType,
    ) -> Decimal:
        duration_seconds = max((exit_date - entry_date).total_seconds(), 0)
        duration_hours = Decimal(duration_seconds) / Decimal(3600)
        amount = _BASE_FEE + (_HOURLY_RATE * duration_hours)
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
