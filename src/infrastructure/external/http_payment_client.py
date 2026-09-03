"""Client HTTP réel vers le service **Payment** — SQUELETTE À FINALISER.

Implémente `PaymentServicePort`. Voir `http_vehicles_client.py` pour le
principe général d'activation (`USE_MOCKS=false` + `PAYMENT_SERVICE_URL`).

──────────────────────────────────────────────────────────────────────────
TODO avant mise en service — À valider avec l'équipe Payment :
  [ ] TODO[PAYMENT-1] Route + méthode exactes.
      Hypothèse actuelle : POST {base_url}/payments
      { vehicleId, amount, idempotencyKey }
  [ ] TODO[PAYMENT-2] Section 2.6 des consignes projet : Payment garantit
      l'idempotence via une clé fournie par l'appelant — décider ici quelle
      valeur Access doit envoyer comme `idempotencyKey` (le `request_id` de
      la sortie est un candidat naturel, à faire remonter dans la signature
      si besoin : `request_payment(vehicle_id, amount, idempotency_key)`).
      Actuellement NON transmise — le port officiel de la spec ne prévoit
      que `(vehicle_id, amount)` : à étendre en concertation si Payment
      l'exige.
  [ ] TODO[PAYMENT-3] Noms exacts des champs de réponse (success/succès ?
      transactionReference/reference ?) et valeurs possibles de statut
      (créé/en attente/payé/refusé/annulé/remboursé — cf. consignes 2.6) :
      décider comment ces statuts intermédiaires sont traités ici (le port
      actuel ne connaît que succès/échec binaire).
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from src.domain.ports.payment_service_port import PaymentServicePort
from src.domain.value_objects.dto import PaymentResult


class HttpPaymentClient:
    """Implémente `PaymentServicePort` via un vrai appel HTTP à Payment."""

    def __init__(self, base_url: str, timeout_s: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def request_payment(self, vehicle_id: str, amount: Decimal) -> PaymentResult:
        # TODO[PAYMENT-1] confirmer route/méthode/forme du payload.
        # TODO[PAYMENT-2] ajouter une clé d'idempotence (cf. note ci-dessus).
        payload = {"vehicleId": vehicle_id, "amount": str(amount)}
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(f"{self._base_url}/payments", json=payload)
        response.raise_for_status()

        # TODO[PAYMENT-3] adapter le mapping de champs / statuts à la réponse réelle.
        data = response.json()
        return PaymentResult(
            success=bool(data.get("success", False)),
            transaction_reference=data.get("transactionReference"),
        )
