"""Client HTTP réel vers le service **Vehicles** de l'équipe.

Implémente `VehiclesServicePort`. Contrat vérifié le 2026-11-24 (après
midi) par des appels réels contre https://parking-vehicles.onrender.com
(swagger `/v3/api-docs`) :

  GET  /api/getvehicles/{plate}
    → 200 { pseudoId (uuid), electric, disabled, xl, twoWheels }
    → 404 si la plaque est inconnue
  POST /api/identify  { licensePlate, isElectric, isDisabled, isXl, isTwoWheels }
    → 200 "pseudoId" (uuid) ; retrouve le véhicule ou le crée (même uuid
      pour une plaque déjà connue)

Vehicles a renommé ses routes deux fois le 24/11 (`/api/vehicles/{plate}`
et `/api/vehicles/identify` le matin) : elles sont réglables
(`VEHICLES_LOOKUP_PATH`, `VEHICLES_IDENTIFY_PATH`). Un 404 sur `identify`
ne peut venir que d'une route renommée (la création ne renvoie jamais 404) :
il est loggé en ERREUR, avec la route appelée, pour être repéré tout de suite.

- `get_vehicle_info` ne fait que consulter (sortie, vérification).
- `identify_vehicle` (entrée) consulte d'abord, et n'appelle `identify` que
  sur un vrai 404 : un véhicule connu n'est jamais réécrit, et une panne de
  Vehicles n'entraîne jamais une création. Le véhicule créé l'est sans
  caractéristique (4 roues standard), Access ne les connaissant pas.
- `pseudoId` devient le `vehicle_id` pseudonymisé qui circule dans tout le
  reste du système (présence, événements, audit). La plaque, elle, ne sort
  jamais de ce client : elle n'apparaît dans aucun log (seul le type
  d'erreur est loggé, jamais l'URL appelée).
- `disabled` alimente à la fois le type de véhicule (`is_handicap`) et le
  justificatif PMR : Vehicles n'expose pas de justificatif distinct (voir
  README section 16).
- Toute autre réponse ou erreur réseau → `None`, soit « véhicule non
  identifié » → procédure alternative à la barrière, jamais un plantage
  d'Access.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.outgoing_http import outgoing_client

logger = logging.getLogger(__name__)


class _NotFound:
    """Marqueur : Vehicles a répondu 404 (plaque inconnue), à distinguer
    d'une panne (`None`)."""


_NOT_FOUND = _NotFound()


class HttpVehiclesClient:
    """Implémente `VehiclesServicePort` via de vrais appels HTTP à Vehicles."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str = "",
        lookup_path: str = "/api/getvehicles/{plate}",
        identify_path: str = "/api/identify",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._lookup_path = lookup_path
        self._identify_path = identify_path
        self._timeout_s = timeout_s
        # Envoyé seulement si VEHICLES_API_KEY est renseignée (authentification
        # pas encore activée côté Vehicles au 2026-11-24).
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._transport = transport  # injecté par les tests (httpx.MockTransport)

    def get_vehicle_info(self, plate: str) -> VehicleInfo | None:
        result = self._lookup(plate)
        return None if isinstance(result, _NotFound) else result

    def identify_vehicle(self, plate: str) -> VehicleInfo | None:
        result = self._lookup(plate)
        if not isinstance(result, _NotFound):
            return result
        if not self._create(plate):
            return None
        logger.info("Véhicule inconnu enregistré auprès de Vehicles")
        created = self._lookup(plate)
        return None if isinstance(created, _NotFound) else created

    def _client(self) -> httpx.Client:
        return outgoing_client(
            "vehicles",
            timeout=self._timeout_s,
            headers=self._headers,
            transport=self._transport,
        )

    def _lookup(self, plate: str) -> VehicleInfo | _NotFound | None:
        try:
            with self._client() as client:
                path = self._lookup_path.replace("{plate}", quote(plate, safe=""))
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
            # Autres exceptions : réponse non-JSON ou contrat inattendu.
            # Seul le type d'erreur est loggé : le message pourrait contenir l'URL.
            logger.warning("Service Vehicles indisponible (%s)", type(exc).__name__)
            return None

    def _create(self, plate: str) -> bool:
        body = {
            "licensePlate": plate,
            "isElectric": False,
            "isDisabled": False,
            "isXl": False,
            "isTwoWheels": False,
        }
        try:
            with self._client() as client:
                response = client.post(f"{self._base_url}{self._identify_path}", json=body)
        except httpx.HTTPError as exc:
            logger.warning("Service Vehicles indisponible (%s)", type(exc).__name__)
            return False
        if response.status_code == 404:
            # La création ne renvoie jamais 404 : la route a changé chez Vehicles.
            logger.error(
                "Vehicles : route d'identification introuvable (POST %s → 404). "
                "Contrat changé ? Vérifier son Swagger et VEHICLES_IDENTIFY_PATH",
                self._identify_path,
            )
            return False
        if response.status_code != 200:
            logger.warning(
                "Vehicles n'a pas enregistré le véhicule (HTTP %s)", response.status_code
            )
            return False
        return True


def _to_vehicle_info(data: dict) -> VehicleInfo:
    disabled = bool(data.get("disabled", False))
    return VehicleInfo(
        vehicle_id=str(data["pseudoId"]),
        vehicle_type=VehicleType(
            category=(
                VehicleCategory.TWO_WHEELER
                if data.get("twoWheels")
                else VehicleCategory.FOUR_WHEELER
            ),
            is_xl=bool(data.get("xl", False)),
            is_electric=bool(data.get("electric", False)),
            is_handicap=disabled,
        ),
        disability_permit=disabled,
    )
