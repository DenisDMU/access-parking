"""Port vers le service Payment."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from src.domain.value_objects.dto import PaymentResult


class PaymentServicePort(Protocol):
    def request_payment(self, stay_id: str, amount: Decimal) -> PaymentResult | None:
        """Demande le paiement du montant (en euros) d'un stationnement.

        `stay_id` identifie le stationnement payé (consignes 3.4, workflow
        "Sortie" : "une demande de paiement est envoyée avec l'identifiant du
        stationnement concerné") — il sert aussi de base à la clé
        d'idempotence : rejouer la même sortie ne provoque jamais un second
        encaissement.

        Renvoie `None` si le résultat est indéterminé (Payment injoignable,
        ou paiement encore en attente après le délai de polling) — à ne PAS
        confondre avec un refus de paiement (`success=False`).
        """
        ...
