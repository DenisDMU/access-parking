"""Mock du service Payment.

`v_payment_fail` (plaque de démo `HH-888-HH`) échoue systématiquement, pour
exercer le scénario "sortie refusée : paiement échoué" sans dépendre d'un
montant ou d'un timing particulier.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.domain.value_objects.dto import PaymentResult

_ALWAYS_FAIL_VEHICLE_IDS = {"v_payment_fail"}


class MockPaymentClient:
    """Implémente `PaymentServicePort`."""

    def request_payment(self, vehicle_id: str, amount: Decimal) -> PaymentResult:
        if vehicle_id in _ALWAYS_FAIL_VEHICLE_IDS:
            return PaymentResult(success=False, transaction_reference=None)
        return PaymentResult(success=True, transaction_reference=f"TX-{uuid4()}")
