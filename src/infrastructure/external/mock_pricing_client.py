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

_FORFAIT_BASE = Decimal("2.00")
_TARIF_HORAIRE = Decimal("1.50")


class MockPricingClient:
    """Implémente `PricingServicePort`."""

    def calculate_price(
        self,
        vehicule_id: str,
        date_entree: datetime,
        date_sortie: datetime,
        type_place: PlaceType,
    ) -> Decimal:
        duree_secondes = max((date_sortie - date_entree).total_seconds(), 0)
        duree_heures = Decimal(duree_secondes) / Decimal(3600)
        montant = _FORFAIT_BASE + (_TARIF_HORAIRE * duree_heures)
        return montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
