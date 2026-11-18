"""Use case `CheckVehicleKnown` — vérifie si un code véhicule est connu par
Vehicles, sans lancer le workflow complet et **sans rien persister**.

Seul `vehicle_id` (pseudonymisé) peut apparaître dans le résultat.
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

    def execute(self, vehicle_code: int) -> VehicleKnownResult:
        vehicle_info = self._vehicles_port.get_vehicle_info(vehicle_code)
        if vehicle_info is None:
            return VehicleKnownResult(known=False, vehicle_id=None)
        return VehicleKnownResult(known=True, vehicle_id=vehicle_info.vehicle_id)
