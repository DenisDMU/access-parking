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

Parking 1.5.0 (vérifié sur son Swagger le 2026-11-24, champs uniquement
ajoutés) :

    GET  {base_url}/parking/categories -> [{category_name, label}, ...]
    `label` ajouté aux réponses de hold, availability et occupation ;
    `spot_held` (places mises de côté) ajouté à occupation.

Avant chaque `hold`, la catégorie demandée est comparée à la liste de
Parking (mise en cache 5 min) : une catégorie renommée ou supprimée donne
`ParkingCategoryUnknownError` (motif précis) au lieu d'une « panne ». Si la
liste est indisponible, la vérification est sautée : elle ne bloque jamais
une entrée à elle seule.

TODO restés ouverts (à confirmer avec l'équipe Parking si besoin) :
  - Mapping `VehicleType` → `category_name` : priorité identique à celle
    utilisée pour Pricing (handicap > 2 roues > électrique > XL > standard),
    voir `_map_category` ci-dessous.
  - Authentification : `X-API-Key` exigé depuis le 2026-11-18 (variable
    `PARKING_API_KEY`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from src.domain.ports.parking_service_port import (
    ParkingCategoryUnknownError,
    ParkingUnavailableError,
)
from src.domain.value_objects.dto import (
    CategoryOccupation,
    ParkingCategory,
    PlaceAssignment,
    PlaceType,
    VehicleType,
)
from src.infrastructure.external.outgoing_http import COLD_START_TIMEOUT_S, outgoing_client
from src.infrastructure.external.place_categories import (
    code_from_place_type,
    place_type_from_code,
)

logger = logging.getLogger(__name__)

# Les 5 catégories qu'Access peut demander (voir `_map_category`).
# Refus de hold qui ne peuvent pas venir d'un parking plein : clé refusée,
# catégorie inconnue (traitée à part), trop de requêtes.
_NOT_FULL = (401, 403, 404, 429)

REQUIRED_CATEGORIES = ["STANDARD", "XL", "ELECTRIC", "HANDICAPPED", "TWO_WHEELS"]

CATEGORIES_TTL_S = 300.0


class _CategoriesCache:
    """Noms des catégories de Parking, par URL, gardés `ttl_s` secondes.

    Partagé entre les requêtes (le client est recréé à chaque requête) :
    au plus un appel à `/parking/categories` toutes les 5 minutes.
    """

    def __init__(
        self, ttl_s: float = CATEGORIES_TTL_S, clock: Callable[[], float] = time.monotonic
    ):
        self._ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[str, tuple[float, frozenset[str]]] = {}

    def get(self, key: str) -> frozenset[str] | None:
        entry = self._entries.get(key)
        if entry is None or self._clock() - entry[0] > self._ttl_s:
            return None
        return entry[1]

    def put(self, key: str, names: frozenset[str]) -> None:
        self._entries[key] = (self._clock(), names)

    def forget(self, key: str) -> None:
        self._entries.pop(key, None)


_categories_cache = _CategoriesCache()


def _map_category(vehicle_type: VehicleType) -> str:
    """Traduit un `VehicleType` en une des 5 catégories réelles de Parking
    (mutuellement exclusives). Même ordre de priorité que
    `http_pricing_client._map_zone` pour rester cohérent entre les deux
    services de l'équipe (`place_categories.code_from_place_type`)."""

    return code_from_place_type(vehicle_type)


def _place_type_from_category(category: str) -> PlaceType:
    return place_type_from_code(category)


class HttpParkingClient:
    """Implémente `ParkingServicePort` via un vrai appel HTTP à Parking.

    Délai de 45 s (`COLD_START_TIMEOUT_S`) : Parking tourne sur l'offre
    gratuite de Render, qui l'endort après 15 min sans trafic ; son réveil
    prend 30 à 60 s. Avec 20 s, le premier passage après une pause était
    refusé (« Service Parking indisponible ») alors que Parking n'était pas
    en panne. Access le réveille aussi d'avance (`warm_up.py`).
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = COLD_START_TIMEOUT_S,
        api_key: str = "",
        transport: httpx.BaseTransport | None = None,
        categories_cache: _CategoriesCache | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._categories_cache = categories_cache or _categories_cache
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
        self._check_category(category)
        payload = {"category_name": category, "commercial_type": commercial_type}
        try:
            with self._client() as client:
                response = client.post(f"{self._base_url}/parking/hold", json=payload)
            if response.status_code == 404:
                # « Catégorie <x> introuvable » : la liste en cache est périmée.
                self._categories_cache.forget(self._base_url)
                raise ParkingCategoryUnknownError(category)
            if 400 <= response.status_code < 500 and response.status_code not in _NOT_FULL:
                # Parking refuse la place. Catégorie pleine ? On lui demande :
                # « complet » n'est pas « indisponible » (constaté le 24/11 :
                # XL et deux-roues pleins rendaient « Service Parking
                # indisponible » à la borne).
                if self._is_full(category, commercial_type):
                    logger.info(
                        "Parking : plus de place %s/%s (hold refusé, HTTP %s)",
                        category,
                        commercial_type,
                        response.status_code,
                    )
                    return None
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

        body = response.json()
        hold_id = body.get("hold_id")
        return PlaceAssignment(
            place_id=f"{category}:{commercial_type}",
            place_type=_place_type_from_category(category),
            hold_id=str(hold_id) if hold_id is not None else None,
            label=body.get("label") or None,
        )

    def required_categories(self) -> list[str]:
        return list(REQUIRED_CATEGORIES)

    def list_categories(self) -> list[ParkingCategory]:
        data = self._get("/parking/categories", "list_categories")
        try:
            categories = [
                ParkingCategory(name=str(item["category_name"]), label=str(item["label"]))
                for item in data
            ]
        except (KeyError, TypeError) as exc:
            raise ParkingUnavailableError(f"réponse inattendue : {exc!r}") from exc
        self._categories_cache.put(self._base_url, frozenset(c.name for c in categories))
        return categories

    def get_occupation(self) -> list[CategoryOccupation]:
        data = self._get("/parking/occupation", "get_occupation")
        try:
            return [
                CategoryOccupation(
                    name=str(item["category_name"]),
                    label=str(item.get("label") or item["category_name"]),
                    spot_taken=int(item["spot_taken"]),
                    spot_held=int(item.get("spot_held", 0)),
                    total_capacity=int(item["total_capacity"]),
                    occupation_rate=float(item["occupation_rate"]),
                )
                for item in data["categories"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ParkingUnavailableError(f"réponse inattendue : {exc!r}") from exc

    def _get(self, path: str, operation: str):
        try:
            with self._client() as client:
                response = client.get(f"{self._base_url}{path}")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Parking indisponible sur %s : %s", operation, exc)
            raise ParkingUnavailableError(str(exc)) from exc

    def _is_full(self, category: str, commercial_type: str) -> bool:
        """`True` seulement si Parking dit lui-même qu'il n'y a plus de place
        (`is_available: false`) ; en cas de doute, `False` (panne signalée)."""

        path = f"/parking/availability/{quote(category, safe='')}/{commercial_type}"
        try:
            data = self._get(path, "availability")
            return data.get("is_available") is False or data.get("spot_available") == 0
        except (ParkingUnavailableError, AttributeError):
            return False

    def _check_category(self, category: str) -> None:
        """Refuse une catégorie absente de Parking ; ne bloque jamais si la
        liste ne peut pas être obtenue ou est vide (le `hold` dira alors ce
        qu'il en est). Comparaison sans tenir compte de la casse."""

        names = self._categories_cache.get(self._base_url)
        if names is None:
            try:
                names = frozenset(c.name for c in self.list_categories())
            except ParkingUnavailableError:
                return
        if not names:
            return
        if category.upper() not in {name.upper() for name in names}:
            logger.warning(
                "Catégorie %s absente de Parking (connues : %s)", category, sorted(names)
            )
            raise ParkingCategoryUnknownError(category)

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
