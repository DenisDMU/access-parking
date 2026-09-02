"""Use case `CheckPlateKnown` — vérifie si une plaque est connue par
Vehicles, sans lancer le workflow complet et **sans rien persister**.

La plaque brute reste locale à `execute` et n'est jamais renvoyée : seul
`vehicule_id` (pseudonymisé) peut apparaître dans le résultat.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.ports.vehicles_service_port import VehiclesServicePort


@dataclass(frozen=True)
class PlateKnownResult:
    known: bool
    vehicule_id: str | None


class CheckPlateKnown:
    def __init__(self, vehicles_port: VehiclesServicePort) -> None:
        self._vehicles_port = vehicles_port

    def execute(self, plaque: str) -> PlateKnownResult:
        vehicle_info = self._vehicles_port.get_vehicle_info(plaque)
        del plaque
        if vehicle_info is None:
            return PlateKnownResult(known=False, vehicule_id=None)
        return PlateKnownResult(known=True, vehicule_id=vehicle_info.vehicule_id)
