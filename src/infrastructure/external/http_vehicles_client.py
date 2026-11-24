"""Client HTTP réel vers le service **Vehicles** de l'équipe.

Implémente `VehiclesServicePort`. Contrat vérifié le 2026-11-24 (fin
d'après-midi) par des appels réels contre https://parking-vehicles.onrender.com
(swagger `/v3/api-docs`) :

  POST /api/identify  { licensePlate }
    → 200 "pseudoId" (uuid) ; retrouve le véhicule ou le crée (même uuid
      pour une plaque déjà connue, casse et espaces ignorés). Un véhicule
      connu n'est PAS réécrit (ses caractéristiques sont conservées).
  GET  /api/getvehicles/{vehicleId}
    → 200 { pseudoId, electric, disabled, xl, twoWheels } ; 404 si inconnu

Parcours (mode « par identifiant », par défaut) : plaque → `identify` →
pseudoId → `getvehicles/{pseudoId}` → caractéristiques.

Revérifié le 24/11 au soir : `licensePlate` désormais obligatoire et
caractéristiques à `false` par défaut (déjà ce qu'envoie Access). Vehicles
expose aussi `GET /api/getplate/{vehicleId}` (identifiant → plaque en
clair, sans clé) : Access ne l'appelle JAMAIS (RGPD : Access ne doit pas
retrouver la plaque à partir de l'identifiant).

⚠️ Vehicles a changé son contrat trois fois le 24/11 :
  1. `GET /api/vehicles/{plate}` + `POST /api/vehicles/identify` (matin) ;
  2. `GET /api/getvehicles/{plate}` + `POST /api/identify` (après-midi) ;
  3. `GET /api/getvehicles/{vehicleId}` + `POST /api/identify` (soir).
Les routes sont donc réglables sans toucher au code (`VEHICLES_LOOKUP_PATH`,
`VEHICLES_IDENTIFY_PATH`). Si la route de consultation contient `{plate}`,
le client repasse en mode « par plaque » (contrats 1 et 2 : consultation
d'abord, `identify` seulement sur un vrai 404).

Conséquence du contrat 3 : Vehicles n'offre plus de consultation par plaque
sans création. À la sortie (ou pour la vérification), une plaque jamais vue
est donc enregistrée par Vehicles ; pour Access, rien ne change (refus
« véhicule non présent »).

- Un 404 sur `identify` ne peut venir que d'une route renommée : il est
  loggé en ERREUR, avec la route appelée, pour être repéré tout de suite.
- `pseudoId` devient le `vehicle_id` pseudonymisé qui circule dans tout le
  reste du système. La plaque ne sort jamais de ce client : elle n'apparaît
  dans aucun log (seul le type d'erreur est loggé, jamais l'URL appelée).
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

DEFAULT_LOOKUP_PATH = "/api/getvehicles/{vehicleId}"
DEFAULT_IDENTIFY_PATH = "/api/identify"


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
            result = self._get(plate=plate)
            return None if isinstance(result, _NotFound) else result
        # Contrat 3 : pas de consultation par plaque sans `identify`.
        return self._identify_then_get(plate)

    def identify_vehicle(
        self, plate: str, declared: VehicleType | None = None
    ) -> VehicleInfo | None:
        if not self._lookup_by_plate:
            return self._identify_then_get(plate, declared)
        result = self._get(plate=plate)
        if not isinstance(result, _NotFound):
            return result
        if self._identify(plate, declared) is None:
            return None
        logger.info("Véhicule inconnu enregistré auprès de Vehicles")
        created = self._get(plate=plate)
        return None if isinstance(created, _NotFound) else created

    # --- appels HTTP -------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return outgoing_client(
            "vehicles",
            timeout=self._timeout_s,
            headers=self._headers,
            transport=self._transport,
        )

    def _identify_then_get(
        self, plate: str, declared: VehicleType | None = None
    ) -> VehicleInfo | None:
        vehicle_id = self._identify(plate, declared)
        if vehicle_id is None:
            return None
        result = self._get(vehicle_id=vehicle_id)
        if isinstance(result, _NotFound):
            logger.warning("Vehicles : véhicule introuvable juste après son identification")
            return None
        return result

    def _identify(self, plate: str, declared: VehicleType | None = None) -> str | None:
        """Plaque → pseudoId (création si inconnue). `None` si échec.

        Le type déclaré à la borne n'est utilisé par Vehicles qu'à la création
        (vérifié : un véhicule connu n'est jamais modifié). `isDisabled` n'est
        jamais envoyé : PMR n'est pas enregistré sur simple déclaration.
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
                response = client.post(f"{self._base_url}{self._identify_path}", json=body)
            if response.status_code == 404:
                # `identify` ne renvoie jamais 404 : la route a changé chez Vehicles.
                logger.error(
                    "Vehicles : route d'identification introuvable (POST %s → 404). "
                    "Contrat changé ? Vérifier son Swagger et VEHICLES_IDENTIFY_PATH",
                    self._identify_path,
                )
                return None
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
        self, *, plate: str | None = None, vehicle_id: str | None = None
    ) -> VehicleInfo | _NotFound | None:
        path = self._lookup_path.replace("{plate}", quote(plate or "", safe="")).replace(
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
