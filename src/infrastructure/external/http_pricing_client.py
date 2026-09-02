"""Client HTTP réel vers le service **Pricing** — SQUELETTE À FINALISER.

Implémente `PricingServicePort`. Voir `http_vehicles_client.py` pour le
principe général d'activation (`USE_MOCKS=false` + `PRICING_SERVICE_URL`).

──────────────────────────────────────────────────────────────────────────
TODO avant mise en service — À valider avec l'équipe Pricing :
  [ ] TODO[PRICING-1] Route + méthode exactes.
      Hypothèse actuelle : POST {base_url}/pricing/calculate
      { vehicleId, entryDate, exitDate, placeType }
  [ ] TODO[PRICING-2] Nom exact du champ montant dans la réponse
      (amount ? price ?) et son type (nombre JSON, ou string pour préserver
      la précision décimale ?).
  [ ] TODO[PRICING-3] Section 2.5 des consignes projet : Pricing doit
      garantir la traçabilité de la grille tarifaire utilisée (identifiant +
      version). Si cette info doit remonter jusqu'à Access (ex. pour
      l'afficher dans l'autorisation ou l'événement), prévoir un champ
      supplémentaire ici ET dans `AccessAuthorization`/le payload d'événement
      — à décider en équipe, actuellement non modélisé côté Access.
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import httpx

from src.domain.ports.pricing_service_port import PricingServicePort
from src.domain.value_objects.dto import PlaceType


class HttpPricingClient:
    """Implémente `PricingServicePort` via un vrai appel HTTP à Pricing."""

    def __init__(self, base_url: str, timeout_s: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def calculate_price(
        self,
        vehicle_id: str,
        entry_date: datetime,
        exit_date: datetime,
        place_type: PlaceType,
    ) -> Decimal:
        # TODO[PRICING-1] confirmer route/méthode/forme du payload.
        payload = {
            "vehicleId": vehicle_id,
            "entryDate": entry_date.isoformat(),
            "exitDate": exit_date.isoformat(),
            "placeType": {
                "category": int(place_type.category),
                "isXl": place_type.is_xl,
                "isElectric": place_type.is_electric,
                "isHandicap": place_type.is_handicap,
            },
        }
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(f"{self._base_url}/pricing/calculate", json=payload)
        response.raise_for_status()

        # TODO[PRICING-2] confirmer le nom/type exact du champ montant.
        data = response.json()
        return Decimal(str(data["amount"]))
