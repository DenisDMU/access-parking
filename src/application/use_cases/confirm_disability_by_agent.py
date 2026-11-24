"""Validation PMR par un agent, à la borne.

Un conducteur déclare « Mobilité réduite » alors que Vehicles ne connaît pas
de justificatif PMR pour son véhicule : l'entrée rend `CONFIRMATION_REQUIRED`
(règle d'accessibilité : confirmation, jamais refus direct). L'agent vérifie
la carte mobilité inclusion, puis saisit son code sur la borne :

1. Le véhicule est identifié auprès de Vehicles (jamais créé PMR sur simple
   déclaration : c'est l'étape 2 qui l'enregistre, après vérification).
2. Le justificatif est enregistré chez Vehicles (`confirm_disability`) : aux
   passages suivants, le véhicule entre directement sur une place PMR.
3. L'entrée est rejouée par le parcours normal (`ProcessEntryRequest`), avec
   toutes ses règles (déjà présent, réservation, place PMR libre…).

Le code agent est vérifié par la route, avant ce use case.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.value_objects.dto import VehicleType
from src.domain.value_objects.enums import DetectionSource, VehicleCategory

logger = logging.getLogger(__name__)

PMR = VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True)


class DisabilityNotRecordedError(Exception):
    """Vehicles n'a pas enregistré le justificatif PMR : rien n'est autorisé."""


@dataclass
class ConfirmDisabilityByAgent:
    vehicles_port: VehiclesServicePort
    entry_use_case: ProcessEntryRequest

    def execute(self, plate: str, date: datetime, source: DetectionSource):
        info = self.vehicles_port.identify_vehicle(plate, declared=PMR)
        if info is not None and not info.disability_permit:
            if not self.vehicles_port.confirm_disability(info.vehicle_id):
                raise DisabilityNotRecordedError
            logger.info("Justificatif PMR validé par un agent (vehicle=%s)", info.vehicle_id)
        # Véhicule non identifié (Vehicles en panne) : le parcours normal rend
        # « véhicule non identifié », comme à une entrée ordinaire.
        return self.entry_use_case.execute(plate=plate, date=date, source=source, declared_type=PMR)
