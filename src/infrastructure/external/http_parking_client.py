"""Client HTTP réel vers le service **Parking** de l'équipe.

Contrat confirmé le 2026-09-02 contre le déploiement réel
(https://parking-6r73.onrender.com/docs) — testé end-to-end (cycle complet
`hold` → `confirm_entry` → `free`, vérifié sans effet de bord résiduel sur
`GET /parking/occupation`) :

    GET  {base_url}/parking/occupation
         -> {"categories": [{category_name, occupation_rate, spot_taken,
                             total_capacity}, ...]}
         catégories réelles : STANDARD, XL, ELECTRIC, HANDICAPPED, TWO_WHEELS

    GET  {base_url}/parking/availability/{category_name}/{commercial_type}
         commercial_type: "walkin" | "booking"
         -> {category_name, commercial_type, is_available, spot_available}

    POST {base_url}/parking/hold
         { "category_name": ..., "commercial_type": "walkin"|"booking" }
         -> { category_name, commercial_type, success } (ne compte PAS
            encore dans occupation_rate/spot_taken tant que confirm_entry
            n'est pas appelé — vérifié empiriquement)

    POST {base_url}/parking/hold renvoie aussi `hold_id` et `end_at` : la
         place est mise de côté 30 s (depuis le 2026-11-18).
    POST {base_url}/parking/confirm_entry  { category_name, commercial_type, hold_id }
         -> 200 (incrémente spot_taken) · 409 hold expiré/déjà utilisé · 422 sans hold_id
    Toutes les routes /parking/* exigent l'en-tête X-API-Key (PARKING_API_KEY).

    POST {base_url}/parking/free           { category_name, commercial_type }
         -> { "message": ... }  (décrémente spot_taken)

    404 { "detail": "Catégorie <x> introuvable" } si categorie inconnue.

⚠️ Différence structurelle importante avec la spec initiale (cf. TODO
historique et section 16 "Écarts assumés") : **ce service ne gère aucun
identifiant de place individuel** — juste un compteur de places libres par
(catégorie, walkin|booking), conformément aux consignes projet section 2.1
("Les places sont gérées par nombre disponible par catégorie. Il n'y a pas
d'affectation d'une place nominalement."). Le `place_id` renvoyé par
`request_place` est donc **synthétique**, fabriqué ici uniquement pour que
le reste d'Access (qui a besoin d'identifier "quelle place libérer" à la
sortie) continue de fonctionner sans changement : il encode simplement
`"{category_name}:{commercial_type}"`, reparsé par `mark_place_occupied`/
`mark_place_free`. `vehicle_id` (paramètre du port) n'est pas utilisé par ce
client : le service Parking réel ne connaît aucun véhicule, uniquement des
compteurs de catégories.

TODO restés ouverts (à confirmer avec l'équipe Parking si besoin) :
  - Mapping `VehicleType` → `category_name` : priorité identique à celle
    utilisée pour Pricing (handicap > 2 roues > électrique > XL > standard),
    voir `_map_category` ci-dessous.
  - Authentification : `X-API-Key` exigé depuis le 2026-11-18 (variable
    `PARKING_API_KEY`).
"""

from __future__ import annotations

import logging

import httpx

from src.domain.ports.parking_service_port import ParkingUnavailableError
from src.domain.value_objects.dto import PlaceAssignment, PlaceType, VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.outgoing_http import outgoing_client

logger = logging.getLogger(__name__)


def _map_category(vehicle_type: VehicleType) -> str:
    """Traduit un `VehicleType` en une des 5 catégories réelles de Parking
    (mutuellement exclusives). Même ordre de priorité que
    `http_pricing_client._map_zone` pour rester cohérent entre les deux
    services de l'équipe."""

    if vehicle_type.is_handicap:
        return "HANDICAPPED"
    if vehicle_type.category is VehicleCategory.TWO_WHEELER:
        return "TWO_WHEELS"
    if vehicle_type.is_electric:
        return "ELECTRIC"
    if vehicle_type.is_xl:
        return "XL"
    return "STANDARD"


def _place_type_from_category(category: str) -> PlaceType:
    return PlaceType(
        category=VehicleCategory.TWO_WHEELER
        if category == "TWO_WHEELS"
        else VehicleCategory.FOUR_WHEELER,
        is_xl=category == "XL",
        is_electric=category == "ELECTRIC",
        is_handicap=category == "HANDICAPPED",
    )


class HttpParkingClient:
    """Implémente `ParkingServicePort` via un vrai appel HTTP à Parking.

    `timeout_s=20.0` par défaut (au lieu des 3-5s habituels) : les services
    de l'équipe tournent sur le plan Free de Render, qui met le service en
    veille après 15 min d'inactivité — un cold start peut prendre plusieurs
    secondes à se réveiller. Un timeout trop court provoquait un
    `httpx.ReadTimeout` en production sur une requête pourtant valide.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 20.0,
        api_key: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        # Parking exige l'en-tête X-API-Key sur toutes ses routes (constaté le
        # 2026-11-18) ; clé fournie en privé par l'équipe (PARKING_API_KEY).
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._transport = transport  # injecté par les tests (httpx.MockTransport)

    def _client(self) -> httpx.Client:
        return outgoing_client(
            "parking", timeout=self._timeout_s, headers=self._headers, transport=self._transport
        )

    def request_place(
        self, vehicle_type: VehicleType, is_reservation: bool = False
    ) -> PlaceAssignment | None:
        category = _map_category(vehicle_type)
        commercial_type = "booking" if is_reservation else "walkin"
        payload = {"category_name": category, "commercial_type": commercial_type}
        try:
            with self._client() as client:
                response = client.post(f"{self._base_url}/parking/hold", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Panne, 429, timeout ou clé API refusée (401/403) : ce n'est PAS
            # « aucune place ». Le use case refuse l'entrée proprement avec
            # un motif distinct (jamais de 500).
            logger.warning(
                "Parking indisponible sur request_place (%s/%s) : %s",
                category,
                commercial_type,
                exc,
            )
            raise ParkingUnavailableError(str(exc)) from exc

        if not response.json().get("success", False):
            return None

        hold_id = response.json().get("hold_id")
        return PlaceAssignment(
            place_id=f"{category}:{commercial_type}",
            place_type=_place_type_from_category(category),
            hold_id=str(hold_id) if hold_id is not None else None,
        )

    def mark_place_occupied(
        self, place_id: str, vehicle_id: str, hold_id: str | None = None
    ) -> bool:
        # `vehicle_id` non utilisé par ce client : Parking ne connaît que
        # des compteurs de catégories, aucun véhicule (cf. docstring module).
        if hold_id is None:
            # Parking exige le hold_id (422 sans lui) : inutile d'appeler.
            logger.warning("confirm_entry impossible sans hold_id (%s)", place_id)
            return False
        category, commercial_type = place_id.split(":", 1)
        try:
            with self._client() as client:
                response = client.post(
                    f"{self._base_url}/parking/confirm_entry",
                    json={
                        "category_name": category,
                        "commercial_type": commercial_type,
                        "hold_id": int(hold_id),
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("Parking indisponible sur confirm_entry (%s) : %s", place_id, exc)
            return False
        if response.status_code == 409:
            # Place mise de côté expirée (30 s) ou déjà confirmée.
            logger.warning("Parking : hold %s expiré ou déjà utilisé (%s)", hold_id, place_id)
            return False
        return self._accepted(response, "confirm_entry", place_id)

    def mark_place_free(self, place_id: str) -> bool:
        category, commercial_type = place_id.split(":", 1)
        try:
            with self._client() as client:
                response = client.post(
                    f"{self._base_url}/parking/free",
                    json={"category_name": category, "commercial_type": commercial_type},
                )
        except httpx.HTTPError as exc:
            logger.warning("Parking indisponible sur mark_place_free (%s) : %s", place_id, exc)
            return False
        return self._accepted(response, "free", place_id)

    @staticmethod
    def _accepted(response: httpx.Response, operation: str, place_id: str) -> bool:
        if response.status_code >= 300:
            # Ex. clé API refusée : le compteur de Parking n'a pas bougé.
            logger.warning(
                "Parking a refusé %s (%s) : HTTP %s", operation, place_id, response.status_code
            )
            return False
        return True
