"""Client HTTP réel vers le service **Vehicles** de l'équipe.

Implémente `VehiclesServicePort`. Contrat vérifié par des appels réels contre
https://parking-vehicles.onrender.com (swagger `/v3/api-docs`) :

  GET /api/vehicles/{code}
    → 200 { pseudoId (uuid), code, electric, disabled, xl, twoWheels }

- Access ne manipule jamais la plaque : Vehicles l'a déjà identifiée
  (`POST /api/vehicles/identify`, hors périmètre d'Access) et lui a associé
  un `code`. Access ne consulte que la donnée anonymisée de ce code.
- `pseudoId` devient le `vehicle_id` pseudonymisé qui circule dans tout le
  reste du système (présence, événements, audit).
- `disabled` alimente à la fois le type de véhicule (`is_handicap`) et le
  justificatif PMR : Vehicles n'expose pas de justificatif distinct (voir
  README section 16).
- Vehicles renvoie 500 (et non 404) pour un code inconnu : impossible de le
  distinguer d'une panne. Toute réponse non-200 ou erreur réseau → `None`,
  soit "véhicule inconnu" → procédure alternative à la barrière, jamais un
  plantage d'Access.
"""

from __future__ import annotations

import logging

import httpx

from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.outgoing_http import outgoing_client

logger = logging.getLogger(__name__)


class HttpVehiclesClient:
    """Implémente `VehiclesServicePort` via un vrai appel HTTP à Vehicles."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport  # injecté par les tests (httpx.MockTransport)

    def get_vehicle_info(self, vehicle_code: int) -> VehicleInfo | None:
        try:
            with outgoing_client(
                "vehicles", timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = client.get(f"{self._base_url}/api/vehicles/{vehicle_code}")
            if response.status_code != 200:
                logger.warning(
                    "Vehicles n'a pas résolu le code véhicule (HTTP %s)", response.status_code
                )
                return None
            data = response.json()
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
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # ValueError/KeyError : réponse non-JSON ou contrat inattendu.
            logger.warning("Service Vehicles indisponible : %r", exc)
            return None
