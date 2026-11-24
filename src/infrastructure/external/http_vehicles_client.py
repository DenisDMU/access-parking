"""Client HTTP réel vers le service **Vehicles** de l'équipe.

Implémente `VehiclesServicePort`. Contrat vérifié le 2026-11-24 (5ᵉ version
de la journée) par des appels réels contre https://parking-vehicles.onrender.com
(swagger `/v3/api-docs`) :

  POST /api/vehicle/create  { licensePlate, isElectric, isXl, isTwoWheels,
                              isHandicaped }
    → 200 "pseudoId" (uuid) ; retrouve le véhicule ou le crée (même uuid
      pour une plaque déjà connue). Un véhicule connu n'est PAS réécrit
      (ses caractéristiques sont conservées). La plaque est comparée telle
      quelle (casse et espaces comptent) : Access envoie toujours la forme
      normalisée, donc une même plaque donne toujours le même véhicule.
  GET  /api/vehicle/{vehicleId}
    → 200 { pseudoId, isElectric, isHandicaped, isXl, isTwoWheels } ; 404
      si inconnu (avant le 24/11, 14 h : electric, handicaped, xl, twoWheels)

Parcours (mode « par identifiant », par défaut) : plaque → `create` →
pseudoId → `vehicle/{pseudoId}` → caractéristiques.

Vehicles expose aussi `GET /api/vehicle/{vehicleId}/plate` (identifiant →
plaque en clair, sans clé), utile aux services de facturation : Access ne
l'appelle JAMAIS (RGPD : Access n'a pas à retrouver la plaque à partir de
l'identifiant ; recommandation à Vehicles : la protéger par une clé).

⚠️ Vehicles a changé son contrat cinq fois le 24/11 :
  1. `GET /api/vehicles/{plate}` + `POST /api/vehicles/identify` (matin) ;
  2. `GET /api/getvehicles/{plate}` + `POST /api/identify` (après-midi) ;
  3. `GET /api/getvehicles/{vehicleId}` + `POST /api/identify` (soir) ;
  4. `GET /api/vehicles/{vehicleId}` + `POST /api/vehicles/create` (soir),
     avec `disabled` renommé `handicaped` ;
  5. `GET /api/vehicle/{vehicleId}` + `POST /api/vehicle/create` (soir) ;
  6. mêmes routes, mais la réponse prend les noms du corps de création
     (`isElectric`, `isXl`, `isTwoWheels`, `isHandicaped`) : tous les
     véhicules étaient lus comme des voitures standard.
Chaque caractéristique est donc lue sous tous ses noms connus (`_FIELDS`).

D'où la **découverte automatique des routes** : si la route de création ou
de consultation répond 404 (route renommée), le client lit le Swagger de
Vehicles (`/v3/api-docs`) et y retrouve :
  - la création : la route POST dont le corps contient `licensePlate` ;
  - la consultation : la route GET à un seul paramètre dont la réponse
    contient `pseudoId` (la route qui renvoie la plaque est donc exclue).
Il réessaie alors une fois avec ces routes, les garde en mémoire pour les
passages suivants et logge un AVERTISSEMENT avec les routes trouvées (à
reporter dans `VEHICLES_IDENTIFY_PATH` / `VEHICLES_LOOKUP_PATH`). Au plus
une lecture du Swagger par minute. Si rien n'est trouvé, le 404 est loggé
en ERREUR avec la route appelée.

Les routes restent réglables sans toucher au code (`VEHICLES_LOOKUP_PATH`,
`VEHICLES_IDENTIFY_PATH`) et les deux noms du champ PMR sont acceptés. Si
la route de consultation contient `{plate}`, le client repasse en mode
« par plaque » (contrats 1 et 2 : consultation d'abord, création seulement
sur un vrai 404 ; pas de découverte automatique dans ce mode).

Depuis le contrat 3, Vehicles n'offre plus de consultation par plaque sans
création. À la sortie (ou pour la vérification), une plaque jamais vue est
donc enregistrée par Vehicles ; pour Access, rien ne change (refus
« véhicule non présent »).

- `pseudoId` devient le `vehicle_id` pseudonymisé qui circule dans tout le
  reste du système. La plaque ne sort jamais de ce client : elle n'apparaît
  dans aucun log (seul le type d'erreur est loggé, jamais l'URL appelée).
- `isHandicaped` (`handicaped`, `disabled` avant) alimente à la fois le type de
  véhicule (`is_handicap`) et le justificatif PMR : Vehicles n'expose pas de
  justificatif distinct (voir README section 16).
- Toute autre réponse ou erreur réseau → `None`, soit « véhicule non
  identifié » → procédure alternative à la barrière, jamais un plantage
  d'Access.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote

import httpx

from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.outgoing_http import outgoing_client

logger = logging.getLogger(__name__)

DEFAULT_LOOKUP_PATH = "/api/vehicle/{vehicleId}"
DEFAULT_IDENTIFY_PATH = "/api/vehicle/create"
OPENAPI_PATH = "/v3/api-docs"
DISCOVERY_MIN_INTERVAL_S = 60.0

_PATH_PARAM = re.compile(r"\{[^}]+\}")

# Routes découvertes dans le Swagger de Vehicles, par URL de base : partagées
# par toutes les instances du client (une par requête HTTP d'Access).
_discovered_routes: dict[str, tuple[str, str]] = {}
_last_discovery: dict[str, float] = {}


def reset_discovered_routes() -> None:
    """Oublie les routes découvertes (tests)."""

    _discovered_routes.clear()
    _last_discovery.clear()


class _NotFound:
    """Marqueur : Vehicles a répondu 404 (inconnu), à distinguer d'une panne (`None`)."""


_NOT_FOUND = _NotFound()


class HttpVehiclesClient:
    """Implémente `VehiclesServicePort` via de vrais appels HTTP à Vehicles."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str = "",
        lookup_path: str = DEFAULT_LOOKUP_PATH,
        identify_path: str = DEFAULT_IDENTIFY_PATH,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._lookup_path = lookup_path
        self._identify_path = identify_path
        # `{plate}` dans la route de consultation : ancien contrat (par plaque).
        self._lookup_by_plate = "{plate}" in lookup_path
        self._timeout_s = timeout_s
        # Envoyé seulement si VEHICLES_API_KEY est renseignée (authentification
        # pas encore activée côté Vehicles au 2026-11-24).
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._transport = transport  # injecté par les tests (httpx.MockTransport)

    def get_vehicle_info(self, plate: str) -> VehicleInfo | None:
        if self._lookup_by_plate:
            result = self._get(self._lookup_path, plate=plate)
            return None if isinstance(result, _NotFound) else result
        # Contrat 3 et suivants : pas de consultation par plaque sans création.
        return self._identify_then_get(plate)

    def identify_vehicle(
        self, plate: str, declared: VehicleType | None = None
    ) -> VehicleInfo | None:
        if not self._lookup_by_plate:
            return self._identify_then_get(plate, declared)
        result = self._get(self._lookup_path, plate=plate)
        if not isinstance(result, _NotFound):
            return result
        vehicle_id = self._identify(self._identify_path, plate, declared)
        if isinstance(vehicle_id, _NotFound):
            self._log_route_gone("POST", self._identify_path)
            return None
        if vehicle_id is None:
            return None
        logger.info("Véhicule inconnu enregistré auprès de Vehicles")
        created = self._get(self._lookup_path, plate=plate)
        return None if isinstance(created, _NotFound) else created

    # --- parcours par identifiant (avec découverte des routes) -------------------

    def _routes(self) -> tuple[str, str]:
        return _discovered_routes.get(self._base_url, (self._identify_path, self._lookup_path))

    def _identify_then_get(
        self, plate: str, declared: VehicleType | None = None
    ) -> VehicleInfo | None:
        identify_path, lookup_path = self._routes()

        vehicle_id = self._identify(identify_path, plate, declared)
        if isinstance(vehicle_id, _NotFound):
            routes = self._rediscover((identify_path, lookup_path))
            if routes is None:
                self._log_route_gone("POST", identify_path)
                return None
            identify_path, lookup_path = routes
            vehicle_id = self._identify(identify_path, plate, declared)
            if isinstance(vehicle_id, _NotFound):
                self._log_route_gone("POST", identify_path)
                return None
        if vehicle_id is None:
            return None

        result = self._get(lookup_path, vehicle_id=vehicle_id)
        if isinstance(result, _NotFound):
            # Juste après la création, un 404 vient d'une route renommée.
            routes = self._rediscover((identify_path, lookup_path))
            if routes is not None and routes[1] != lookup_path:
                result = self._get(routes[1], vehicle_id=vehicle_id)
        if isinstance(result, _NotFound):
            logger.warning("Vehicles : véhicule introuvable juste après son identification")
            return None
        return result

    def _rediscover(self, current: tuple[str, str]) -> tuple[str, str] | None:
        """Relit le Swagger de Vehicles ; nouvelles routes, ou `None`."""

        now = time.monotonic()
        last = _last_discovery.get(self._base_url)
        if last is not None and now - last < DISCOVERY_MIN_INTERVAL_S:
            return None
        _last_discovery[self._base_url] = now
        try:
            with self._client() as client:
                response = client.get(f"{self._base_url}{OPENAPI_PATH}")
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}")
            routes = discover_routes(response.json())
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Vehicles : Swagger illisible, routes non redécouvertes (%s)",
                type(exc).__name__,
            )
            return None
        if routes is None or routes == current:
            return None
        _discovered_routes[self._base_url] = routes
        logger.warning(
            "Vehicles a renommé ses routes : POST %s et GET %s retrouvées dans son "
            "Swagger et utilisées désormais (à reporter dans VEHICLES_IDENTIFY_PATH "
            "et VEHICLES_LOOKUP_PATH)",
            routes[0],
            routes[1],
        )
        return routes

    def _log_route_gone(self, method: str, path: str) -> None:
        logger.error(
            "Vehicles : route introuvable (%s %s → 404) et non retrouvée dans son "
            "Swagger. Contrat changé ? Vérifier VEHICLES_IDENTIFY_PATH et "
            "VEHICLES_LOOKUP_PATH",
            method,
            path,
        )

    # --- appels HTTP -------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return outgoing_client(
            "vehicles",
            timeout=self._timeout_s,
            headers=self._headers,
            transport=self._transport,
        )

    def _identify(
        self, path: str, plate: str, declared: VehicleType | None = None
    ) -> str | _NotFound | None:
        """Plaque → pseudoId (création si inconnue). `_NOT_FOUND` sur 404, `None` si échec.

        Le type déclaré à la borne n'est utilisé par Vehicles qu'à la création
        (vérifié : un véhicule connu n'est jamais modifié). `isHandicaped`
        n'est jamais envoyé : PMR n'est pas enregistré sur simple déclaration.
        """

        body: dict = {"licensePlate": plate}
        if declared is not None:
            body.update(
                isElectric=declared.is_electric,
                isXl=declared.is_xl,
                isTwoWheels=declared.category is VehicleCategory.TWO_WHEELER,
            )
        try:
            with self._client() as client:
                response = client.post(f"{self._base_url}{path}", json=body)
            if response.status_code == 404:
                # La création ne renvoie jamais 404 : la route a changé chez Vehicles.
                return _NOT_FOUND
            if response.status_code != 200:
                logger.warning(
                    "Vehicles n'a pas identifié le véhicule (HTTP %s)", response.status_code
                )
                return None
            vehicle_id = response.json()
            if not isinstance(vehicle_id, str) or not vehicle_id:
                raise ValueError("identifiant attendu")
            return vehicle_id
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Service Vehicles indisponible (%s)", type(exc).__name__)
            return None

    def _get(
        self, path_template: str, *, plate: str | None = None, vehicle_id: str | None = None
    ) -> VehicleInfo | _NotFound | None:
        path = path_template.replace("{plate}", quote(plate or "", safe="")).replace(
            "{vehicleId}", quote(vehicle_id or "", safe="")
        )
        try:
            with self._client() as client:
                response = client.get(f"{self._base_url}{path}")
            if response.status_code == 404:
                return _NOT_FOUND
            if response.status_code != 200:
                logger.warning(
                    "Vehicles n'a pas résolu le véhicule (HTTP %s)", response.status_code
                )
                return None
            return _to_vehicle_info(response.json())
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError) as exc:
            # Réponse non-JSON ou contrat inattendu. Seul le type d'erreur est
            # loggé : le message pourrait contenir l'URL (donc la plaque).
            logger.warning("Service Vehicles indisponible (%s)", type(exc).__name__)
            return None


def discover_routes(openapi: dict) -> tuple[str, str] | None:
    """Swagger de Vehicles → (route de création, route de consultation), ou `None`.

    Création : la route POST dont le corps a une propriété `licensePlate`.
    Consultation : la route GET à un seul paramètre de chemin dont la réponse
    200 a une propriété `pseudoId` (la route qui renvoie la plaque, une simple
    chaîne, est donc écartée). Le paramètre est renommé `{vehicleId}`.
    """

    schemas = openapi.get("components", {}).get("schemas", {})

    def properties(schema: dict | None) -> dict:
        schema = schema or {}
        ref = schema.get("$ref", "")
        if ref.startswith("#/components/schemas/"):
            schema = schemas.get(ref.rsplit("/", 1)[-1], {})
        return schema.get("properties", {}) or {}

    def content_schema(container: dict | None) -> dict | None:
        for media in ((container or {}).get("content") or {}).values():
            return media.get("schema")
        return None

    identify = lookup = None
    for path, operations in (openapi.get("paths") or {}).items():
        post = operations.get("post")
        if identify is None and post is not None:
            if "licensePlate" in properties(content_schema(post.get("requestBody"))):
                identify = path
        get = operations.get("get")
        if lookup is None and get is not None and len(_PATH_PARAM.findall(path)) == 1:
            ok = (get.get("responses") or {}).get("200")
            if "pseudoId" in properties(content_schema(ok)):
                lookup = _PATH_PARAM.sub("{vehicleId}", path)
    if identify is None or lookup is None:
        return None
    return identify, lookup


# Noms successifs de chaque caractéristique dans les réponses de Vehicles
# (le plus récent d'abord) : contrat 6 (`isXl`…), 4-5 (`xl`, `handicaped`),
# 1-3 (`disabled`).
_FIELDS: dict[str, tuple[str, ...]] = {
    "electric": ("isElectric", "electric"),
    "xl": ("isXl", "xl"),
    "two_wheels": ("isTwoWheels", "twoWheels"),
    "handicap": ("isHandicaped", "handicaped", "isDisabled", "disabled"),
}


def _flag(data: dict, name: str) -> bool:
    for key in _FIELDS[name]:
        if key in data:
            return bool(data[key])
    return False


def _to_vehicle_info(data: dict) -> VehicleInfo:
    disabled = _flag(data, "handicap")
    return VehicleInfo(
        vehicle_id=str(data["pseudoId"]),
        vehicle_type=VehicleType(
            category=(
                VehicleCategory.TWO_WHEELER
                if _flag(data, "two_wheels")
                else VehicleCategory.FOUR_WHEELER
            ),
            is_xl=_flag(data, "xl"),
            is_electric=_flag(data, "electric"),
            is_handicap=disabled,
        ),
        disability_permit=disabled,
    )
