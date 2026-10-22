"""Client HTTP réel vers le service **Vehicles** — SQUELETTE À FINALISER.

Implémente `VehiclesServicePort` avec les mêmes signatures que le mock
(`mock_vehicles_client.py`) : remplacer le mock par ce client ne touche
aucune autre couche (domain/application/interfaces), conformément à
l'architecture hexagonale — voir README section 5.

Activation : dans `.env`, `USE_MOCKS=false` + `VEHICLES_SERVICE_URL=<url
réelle>` — `deps.py::get_vehicles_port()` instancie alors automatiquement ce
client.

──────────────────────────────────────────────────────────────────────────
TODO avant mise en service — À valider avec l'équipe Vehicles :
  [ ] TODO[VEHICLES-1] Route + méthode HTTP exactes.
      Hypothèse actuelle : POST {base_url}/vehicles/resolve
      Alternative possible : GET {base_url}/vehicles?plate=...
      (⚠️ si GET, la plaque brute finirait dans l'URL donc potentiellement
      dans les logs d'accès de Vehicles — à éviter si possible, préférer un
      corps de requête POST).
  [ ] TODO[VEHICLES-2] Code retourné si la plaque est inconnue.
      Hypothèse actuelle : 404. Si Vehicles renvoie plutôt 200 avec un champ
      nul, adapter `get_vehicle_info` en conséquence.
  [ ] TODO[VEHICLES-3] Noms exacts des champs de la réponse JSON
      (vehicleId ? vehicle_id ?) et forme de `vehicleType` (objet imbriqué
      avec category/isXl/isElectric/isHandicap, ou champs à plat ?).
  [ ] TODO[VEHICLES-4] Gestion d'erreurs réseau : actuellement toute erreur
      httpx (timeout, 5xx, connexion refusée) remonte telle quelle — décider
      si Access doit dégrader la décision (ex. REFUSED) plutôt que planter
      en 500 (hors périmètre MVP officiellement, mais à trancher en équipe).
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import httpx

from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import VehicleCategory


class HttpVehiclesClient:
    """Implémente `VehiclesServicePort` via un vrai appel HTTP à Vehicles."""

    def __init__(self, base_url: str, timeout_s: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def get_vehicle_info(self, raw_plate: str) -> VehicleInfo | None:
        # TODO[VEHICLES-1] confirmer route/méthode avec l'équipe Vehicles.
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(f"{self._base_url}/vehicles/resolve", json={"plate": raw_plate})
        # `raw_plate` sort de portée ici — ne plus la référencer au-delà.

        # TODO[VEHICLES-2] confirmer le code "véhicule inconnu" (404 supposé).
        if response.status_code == 404:
            return None
        response.raise_for_status()

        # TODO[VEHICLES-3] adapter le mapping de champs à la réponse réelle.
        data = response.json()
        vehicle_type_data = data.get("vehicleType", {})
        return VehicleInfo(
            vehicle_id=data["vehicleId"],
            vehicle_type=VehicleType(
                category=VehicleCategory(
                    vehicle_type_data.get("category", VehicleCategory.FOUR_WHEELER)
                ),
                is_xl=vehicle_type_data.get("isXl", False),
                is_electric=vehicle_type_data.get("isElectric", False),
                is_handicap=vehicle_type_data.get("isHandicap", False),
            ),
            disability_permit=data.get("disabilityPermit", False),
        )
