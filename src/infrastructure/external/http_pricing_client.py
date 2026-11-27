"""Client HTTP réel vers le service **Pricing** de l'équipe.

Contrat confirmé le 2026-09-02 contre le déploiement réel
(https://pricing-9khk.onrender.com/docs) — plus un squelette, testé
end-to-end (`POST /quote`, `GET /rates`, `GET /grids/current`) :

    POST {base_url}/quote
    { "zone": "standard"|"xl"|"handicapped"|"electric"|"two_wheels",
      "mode": "walk_in"|"reserved",
      "duration_min": <entier, minutes> }
    -> 201 { quote_id, grid_id, grid_version, amount_eur (string décimal),
             currency, breakdown, computed_at }
    -> 404 { code: "ZONE_NOT_FOUND", message: ... } si zone inconnue

Grille v2 (24/11, 10 h 29) : la zone PMR `disabled` est devenue
`handicapped`. Access envoyait encore `disabled` : chaque sortie d'un
véhicule PMR était refusée (« service de tarification indisponible »).
Access envoie désormais `handicapped` et, sur un `ZONE_NOT_FOUND`, réessaie
avec l'ancien nom (`ZONE_ALIASES`) au cas où Pricing reviendrait en arrière.
    -> 422 si `duration_min` vaut 0 ou dépasse 10 080 (7 jours) — d'où le
       bornage fait par `_duration_minutes` (vérifié le 2026-11-18).
    -> 400 { code: "INVALID_DURATION", message: ... } si `mode="reserved"`
       et `duration_min` n'est pas un multiple de 60 (cohérent avec les
       créneaux de réservation Booking, toujours alignés sur l'heure pleine
       — cf. consignes projet section 2.7).

⚠️ Points restés des hypothèses (à confirmer avec l'équipe Pricing si un
comportement inattendu apparaît) :
  - TODO[PRICING-1] Mapping `PlaceType` → `zone` : priorité déduite des 5
    zones réellement configurées (`GET /rates`) — handicap d'abord (zone
    "handicapped" a un tarif préférentiel), puis 2 roues, électrique, XL,
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
  - Authentification : depuis le 2026-11-27 (15 h 17, commit `b52c726` de
    Pricing), `POST /quote` exige `X-API-Key` et répond sinon
    401 `{ detail: { code: "UNAUTHORIZED", ... } }`. Access envoie
    `PRICING_API_KEY` (saisie sur Render). Une clé refusée (401/403) est
    écrite en erreur dans le journal, avec le nom de la variable à corriger ;
    la sortie est refusée, comme pour une panne. `GET /health`, `GET /rates`
    et le nouveau `POST /simulate` (devis non enregistré) restent sans clé ;
    Access n'utilise pas `/simulate` : le devis d'une sortie doit rester
    tracé chez Pricing.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from decimal import Decimal

import httpx

from src.domain.value_objects.dto import PlaceType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.outgoing_http import COLD_START_TIMEOUT_S, outgoing_client

logger = logging.getLogger(__name__)


def _map_zone(place_type: PlaceType) -> str:
    """Traduit un `PlaceType` (attributs indépendants côté Access) en une
    des 5 zones tarifaires réelles de Pricing (mutuellement exclusives).
    Voir TODO[PRICING-1] dans le docstring du module pour l'ordre de
    priorité choisi et ses limites."""

    if place_type.is_handicap:
        return "handicapped"
    if place_type.category is VehicleCategory.TWO_WHEELER:
        return "two_wheels"
    if place_type.is_electric:
        return "electric"
    if place_type.is_xl:
        return "xl"
    return "standard"


# Noms successifs d'une même zone chez Pricing, essayés dans l'ordre sur un
# `ZONE_NOT_FOUND` (la zone PMR a été renommée le 24/11).
ZONE_ALIASES: dict[str, tuple[str, ...]] = {"handicapped": ("handicapped", "disabled")}


# Règle métier 2.4 : « la durée du stationnement est plafonnée à sept jours ».
# Pricing refuse d'ailleurs toute durée au-delà (422 si > 10 080 min).
MAX_STAY_MINUTES = 7 * 24 * 60


def _duration_minutes(entry_date: datetime, exit_date: datetime, is_reservation: bool) -> int:
    """Durée facturable envoyée à Pricing, en minutes entières.

    - Arrondie à la minute **supérieure** : « tout quart d'heure entamé est
      dû » (règle 2.5), on ne fait jamais disparaître des secondes.
    - Au moins 1 minute : Pricing refuse 0 (422). Une sortie juste après
      l'entrée tombe ainsi dans la gratuité de Pricing au lieu d'être bloquée.
    - Au plus 7 jours (règle 2.4) : au-delà, la durée est plafonnée plutôt
      que de bloquer définitivement la sortie du véhicule.
    """

    elapsed_min = max((exit_date - entry_date).total_seconds() / 60, 0)
    if is_reservation:
        # TODO[PRICING-2] : Pricing exige un multiple de 60 en mode "reserved".
        minutes = max(math.ceil(elapsed_min / 60) * 60, 60)
    else:
        minutes = max(math.ceil(elapsed_min), 1)
    return min(minutes, MAX_STAY_MINUTES)  # 10 080 est un multiple de 60


class HttpPricingClient:
    """Implémente `PricingServicePort` via un vrai appel HTTP à Pricing."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = COLD_START_TIMEOUT_S,
        api_key: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport  # injecté par les tests (httpx.MockTransport)
        self._timeout_s = timeout_s
        # Envoyé seulement si PRICING_API_KEY est renseignée.
        self._headers = {"X-API-Key": api_key} if api_key else {}

    def calculate_price(
        self,
        vehicle_id: str,
        entry_date: datetime,
        exit_date: datetime,
        place_type: PlaceType,
        is_reservation: bool = False,
    ) -> Decimal | None:
        zone = _map_zone(place_type)
        payload = {
            "zone": zone,
            "mode": "reserved" if is_reservation else "walk_in",
            "duration_min": _duration_minutes(entry_date, exit_date, is_reservation),
        }
        try:
            with outgoing_client(
                "pricing",
                timeout=self._timeout_s,
                headers=self._headers,
                transport=self._transport,
            ) as client:
                for name in ZONE_ALIASES.get(zone, (zone,)):
                    payload["zone"] = name
                    response = client.post(f"{self._base_url}/quote", json=payload)
                    if not _zone_not_found(response):
                        break
                    logger.warning("Pricing ne connaît pas la zone %r", name)
            if response.status_code in (401, 403):
                # Pas une panne : la clé manque ou n'est plus la bonne.
                logger.error(
                    "Pricing refuse la clé d'Access (%s) : vérifier PRICING_API_KEY",
                    response.status_code,
                )
                return None
            response.raise_for_status()
            return Decimal(str(response.json()["amount_eur"]))
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
            # Panne/429/timeout Pricing : hors périmètre MVP. On ne fabrique
            # jamais un montant inventé — None fait refuser la sortie
            # proprement côté ProcessExitRequest (jamais de 500 brute).
            logger.warning(
                "Pricing indisponible sur calculate_price (%s) : %s",
                vehicle_id,
                type(exc).__name__,
            )
            return None


def _zone_not_found(response: httpx.Response) -> bool:
    if response.status_code != 404:
        return False
    try:
        return response.json().get("code") == "ZONE_NOT_FOUND"
    except (ValueError, AttributeError):
        return False
