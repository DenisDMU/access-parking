"""Client HTTP réel vers le service **Pricing** de l'équipe.

Contrat confirmé le 2026-09-02 contre le déploiement réel
(https://pricing-9khk.onrender.com/docs) — plus un squelette, testé
end-to-end (`POST /quote`, `GET /rates`, `GET /grids/current`) :

    POST {base_url}/quote
    { "zone": "standard"|"xl"|"disabled"|"electric"|"two_wheels",
      "mode": "walk_in"|"reserved",
      "duration_min": <entier, minutes> }
    -> 201 { quote_id, grid_id, grid_version, amount_eur (string décimal),
             currency, breakdown, computed_at }
    -> 404 { code: "ZONE_NOT_FOUND", message: ... } si zone inconnue
    -> 400 { code: "INVALID_DURATION", message: ... } si `mode="reserved"`
       et `duration_min` n'est pas un multiple de 60 (cohérent avec les
       créneaux de réservation Booking, toujours alignés sur l'heure pleine
       — cf. consignes projet section 2.7).

⚠️ Points restés des hypothèses (à confirmer avec l'équipe Pricing si un
comportement inattendu apparaît) :
  - TODO[PRICING-1] Mapping `PlaceType` → `zone` : priorité déduite des 5
    zones réellement configurées (`GET /rates`) — handicap d'abord (zone
    "disabled" a un tarif préférentiel), puis 2 roues, électrique, XL,
    standard en dernier recours. Une place cumulant plusieurs attributs
    (ex. XL + électrique) ne peut être envoyée que sous UNE zone : à
    valider avec l'équipe si ce cas doit exister dans le vrai parking.
  - TODO[PRICING-2] Pour une sortie réservée (`is_reservation=True`), la
    durée réelle écoulée est arrondie À LA HAUSSE au multiple de 60 le plus
    proche avant l'appel (règle de validation du service). Hypothèse
    pragmatique cohérente avec "les véhicules respectent les horaires
    prévus" (hors périmètre MVP) — à confirmer si un jour un dépassement de
    créneau doit être facturé différemment.
  - TODO[PRICING-3] `grid_id`/`grid_version` (traçabilité de la grille
    tarifaire, cf. consignes 2.5) sont bien renvoyés par Pricing mais ne
    sont pas encore répercutés dans `AccessAuthorization` ni dans le
    payload de l'événement `VEHICLE_EXITED` côté Access — actuellement
    seul `amount_eur` est utilisé. À étendre si la traçabilité doit
    remonter jusqu'à Access.
  - Aucune authentification n'a été nécessaire lors des tests (endpoint
    public) — à revoir si Pricing ajoute une clé API plus tard.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from decimal import Decimal

import httpx

from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory

logger = logging.getLogger(__name__)


def _map_zone(place_type: PlaceType) -> str:
    """Traduit un `PlaceType` (attributs indépendants côté Access) en une
    des 5 zones tarifaires réelles de Pricing (mutuellement exclusives).
    Voir TODO[PRICING-1] dans le docstring du module pour l'ordre de
    priorité choisi et ses limites."""

    if place_type.is_handicap:
        return "disabled"
    if place_type.category is VehicleCategory.TWO_WHEELER:
        return "two_wheels"
    if place_type.is_electric:
        return "electric"
    if place_type.is_xl:
        return "xl"
    return "standard"


def _duration_minutes(entry_date: datetime, exit_date: datetime, is_reservation: bool) -> int:
    duration_min = max((exit_date - entry_date).total_seconds() / 60, 0)
    if is_reservation:
        # TODO[PRICING-2] : Pricing exige un multiple de 60 en mode "reserved".
        return max(math.ceil(duration_min / 60) * 60, 60)
    return max(round(duration_min), 0)


class HttpPricingClient:
    """Implémente `PricingServicePort` via un vrai appel HTTP à Pricing."""

    def __init__(self, base_url: str, timeout_s: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def calculate_price(
        self,
        vehicle_id: str,
        entry_date: datetime,
        exit_date: datetime,
        place_type: PlaceType,
        is_reservation: bool = False,
    ) -> Decimal | None:
        payload = {
            "zone": _map_zone(place_type),
            "mode": "reserved" if is_reservation else "walk_in",
            "duration_min": _duration_minutes(entry_date, exit_date, is_reservation),
        }
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.post(f"{self._base_url}/quote", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Panne/429/timeout Pricing : hors périmètre MVP. On ne fabrique
            # jamais un montant inventé — None fait refuser la sortie
            # proprement côté ProcessExitRequest (jamais de 500 brute).
            logger.warning("Pricing indisponible sur calculate_price (%s) : %s", vehicle_id, exc)
            return None

        data = response.json()
        return Decimal(str(data["amount_eur"]))
