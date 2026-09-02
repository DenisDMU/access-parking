"""Mock du service Payment.

`v_payment_fail` (plaque de démo `HH-888-HH`) échoue systématiquement, pour
exercer le scénario "sortie refusée : paiement échoué" sans dépendre d'un
montant ou d'un timing particulier.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.domain.value_objects.dto import PaymentResult

_ALWAYS_FAIL_VEHICULE_IDS = {"v_payment_fail"}


class MockPaymentClient:
    """Implémente `PaymentServicePort`."""

    def request_payment(self, vehicule_id: str, montant: Decimal) -> PaymentResult:
        if vehicule_id in _ALWAYS_FAIL_VEHICULE_IDS:
            return PaymentResult(succes=False, reference_transaction=None)
        return PaymentResult(succes=True, reference_transaction=f"TX-{uuid4()}")
