"""Port vers le service Payment."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from src.domain.value_objects.dto import PaymentResult


class PaymentServicePort(Protocol):
    def request_payment(self, vehicle_id: str, amount: Decimal) -> PaymentResult:
        """Demande le paiement du montant pour ce véhicule pseudonymisé."""
        ...
