"""Client HTTP réel vers le service **Payment** de l'équipe.

Implémente `PaymentServicePort`. Contrat vérifié par des appels réels contre
https://payment-xp8n.onrender.com (openapi.json + guide d'intégration de
l'équipe Payment, `docs/INTEGRATION_BOOKING_ACCESS.md` de leur dépôt) :

  POST /payments
    { idempotency_key, amount (entier, centimes, > 0), currency: "EUR",
      reference: { type: "PARKING_EXIT", id: <stationnement> },
      source_service: "access" }
    → 202 (créé, status PENDING) ou 200 (rejeu d'une clé déjà connue)
  GET /payments/{payment_id}
    → 200 { status: PENDING | ACCEPTED | REFUSED, ... }

- Pas de callback : le statut final s'obtient par polling (recette de
  l'équipe Payment : toutes les 2 s, 40 s max). Constaté en réel : ~16 s
  jusqu'à ACCEPTED, ~30 s si Payment a fait un retry interne.
- Idempotence : clé `access:{stay_id}:exit` (convention de l'équipe
  Payment). Le `stay_id` est stable pour un stationnement donné, donc
  rejouer une sortie (timeout, nouvel essai à la barrière) renvoie le même
  paiement — jamais de double encaissement.
- Un statut REFUSED est définitif (Payment a déjà retenté une fois).
- Authentification : en-tête `X-API-Key` envoyé seulement si
  `PAYMENT_API_KEY` est renseignée (l'équipe Payment l'active de son côté
  quand tout le monde est prêt — rétro-compatible d'ici là).
- Toute erreur (429/5xx/timeout/connexion refusée) ou un paiement encore
  PENDING après le délai → `None` (résultat indéterminé, pas un refus).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

import httpx

from src.domain.value_objects.dto import PaymentResult

logger = logging.getLogger(__name__)


def _to_cents(amount: Decimal) -> int:
    """Payment attend un entier en centimes (4.60 € → 460)."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class HttpPaymentClient:
    """Implémente `PaymentServicePort` via un vrai appel HTTP à Payment."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_s: float = 20.0,
        poll_interval_s: float = 2.0,
        poll_timeout_s: float = 40.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._transport = transport  # injecté par les tests (httpx.MockTransport)
        self._sleep = sleep

    def request_payment(self, stay_id: str, amount: Decimal) -> PaymentResult | None:
        payload = {
            "idempotency_key": f"access:{stay_id}:exit",
            "amount": _to_cents(amount),
            "currency": "EUR",
            "reference": {"type": "PARKING_EXIT", "id": stay_id},
            "source_service": "access",
        }
        try:
            with httpx.Client(
                timeout=self._timeout_s, headers=self._headers, transport=self._transport
            ) as client:
                response = client.post(f"{self._base_url}/payments", json=payload)
                response.raise_for_status()
                data = response.json()
                payment_id = data["payment_id"]

                deadline = time.monotonic() + self._poll_timeout_s
                while data["status"] == "PENDING":
                    if time.monotonic() >= deadline:
                        logger.warning(
                            "Paiement %s toujours en attente après %ss", payment_id, self._poll_timeout_s
                        )
                        return None
                    self._sleep(self._poll_interval_s)
                    response = client.get(f"{self._base_url}/payments/{payment_id}")
                    response.raise_for_status()
                    data = response.json()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # ValueError/KeyError : réponse non-JSON ou contrat inattendu.
            logger.warning("Service Payment indisponible : %r", exc)
            return None

        return PaymentResult(
            success=data["status"] == "ACCEPTED",
            transaction_reference=payment_id,
        )
