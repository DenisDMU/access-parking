"""Use case `CheckVehicleKnown` — demande à Vehicles l'identifiant d'une
plaque, sans lancer le workflow complet et **sans rien persister dans
Access**.

⚠️ Depuis le 24/11, Vehicles n'offre plus de consultation par plaque sans
création : une plaque qu'il n'a jamais vue y est enregistrée au passage
(voir `http_vehicles_client.py`). `known` vaut donc `True` dès que Vehicles
répond ; `False` signifie que Vehicles n'a pas pu identifier la plaque
(service indisponible ou réponse hors contrat).

La plaque reste locale à `execute` et n'est jamais renvoyée : seul
`vehicle_id` (pseudonymisé) peut apparaître dans le résultat.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.ports.vehicles_service_port import VehiclesServicePort


@dataclass(frozen=True)
class VehicleKnownResult:
    known: bool
    vehicle_id: str | None


class CheckVehicleKnown:
    def __init__(self, vehicles_port: VehiclesServicePort) -> None:
        self._vehicles_port = vehicles_port

    def execute(self, plate: str) -> VehicleKnownResult:
        vehicle_info = self._vehicles_port.get_vehicle_info(plate)
        del plate
        if vehicle_info is None:
            return VehicleKnownResult(known=False, vehicle_id=None)
        return VehicleKnownResult(known=True, vehicle_id=vehicle_info.vehicle_id)
