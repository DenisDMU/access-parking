"""Port vers le service Pricing.

`is_reservation` a été ajouté (écart mineur assumé, cf. README section 14)
après intégration du vrai service Pricing de l'équipe : son API distingue
tarifairement une entrée réservée ("reserved") d'une entrée walk-in
("walk_in"), information qu'Access connaît déjà à l'entrée (résultat de
`BookingServicePort.get_reservation`) mais que la spec initiale ne faisait
pas remonter jusqu'à ce port.
"""

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
        is_reservation: bool,
    ) -> Decimal | None:
        """Calcule le montant dû pour ce stationnement.

        `None` si Pricing est indisponible (429/5xx/timeout) — traité comme
        un refus propre de la sortie par `ProcessExitRequest`, jamais comme
        un montant inventé (cf. même principe que `ParkingServicePort`,
        écarts assumés section 16 du README)."""
        ...
