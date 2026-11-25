"""Validation PMR par un agent, à la borne.

Un conducteur déclare « Mobilité réduite » alors que Vehicles ne connaît pas
de justificatif PMR pour son véhicule : l'entrée rend `CONFIRMATION_REQUIRED`
(règle d'accessibilité : confirmation, jamais refus direct). L'agent vérifie
la carte mobilité inclusion, puis saisit son code sur la borne :

1. Le véhicule est identifié auprès de Vehicles (jamais créé PMR sur simple
   déclaration : c'est l'étape 2 qui l'enregistre, après vérification).
2. Le justificatif est enregistré chez Vehicles (`confirm_disability`) : aux
   passages suivants, le véhicule entre directement sur une place PMR. Si
   Vehicles refuse (route protégée par une clé qu'Access n'a pas, panne),
   l'entrée n'est pas bloquée : la carte a été vérifiée par l'agent, elle
   vaut pour ce passage ; seule la mémorisation est perdue (avertissement).
3. L'entrée est rejouée par le parcours normal (`ProcessEntryRequest`), avec
   toutes ses règles (déjà présent, réservation, place PMR libre…).

Le code agent est vérifié par la route, avant ce use case. En plus, la
validation n'est acceptée que pour un véhicule **mis en attente d'agent
(PMR) à l'entrée dans les 5 dernières minutes** : sans cela, quiconque
connaît le code pourrait faire enregistrer n'importe quelle plaque comme
PMR chez Vehicles, durablement (revue de sécurité du 25/11).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.value_objects.dto import AccessFilters, VehicleType
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    RequestType,
    VehicleCategory,
)

logger = logging.getLogger(__name__)

PMR = VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True)
PENDING_WINDOW = timedelta(minutes=5)


class NoPendingDisabilityCheckError(Exception):
    """Aucune entrée en attente de validation PMR pour ce véhicule, récemment."""


@dataclass
class ConfirmDisabilityByAgent:
    vehicles_port: VehiclesServicePort
    entry_use_case: ProcessEntryRequest
    access_repo: AccessRepositoryPort

    def execute(self, plate: str, date: datetime, source: DetectionSource):
        info = self.vehicles_port.identify_vehicle(plate, declared=PMR)
        if info is not None and not info.disability_permit:
            if not self._waiting_for_agent(info.vehicle_id, date):
                raise NoPendingDisabilityCheckError
            if self.vehicles_port.confirm_disability(info.vehicle_id):
                logger.info("Justificatif PMR validé par un agent (vehicle=%s)", info.vehicle_id)
            else:
                logger.warning(
                    "Justificatif PMR validé par un agent mais non enregistré chez "
                    "Vehicles (vehicle=%s) : valable pour ce passage seulement",
                    info.vehicle_id,
                )
        # Véhicule non identifié (Vehicles en panne) : le parcours normal rend
        # « véhicule non identifié », comme à une entrée ordinaire.
        return self.entry_use_case.execute(
            plate=plate,
            date=date,
            source=source,
            declared_type=PMR,
            disability_verified=True,
        )

    def _waiting_for_agent(self, vehicle_id: str, date: datetime) -> bool:
        """Une entrée de ce véhicule a-t-elle attendu un agent (PMR) récemment ?"""

        recent = self.access_repo.list_requests(
            AccessFilters(
                vehicle_id=vehicle_id,
                type=RequestType.ENTRY,
                date_from=date - PENDING_WINDOW,
                limit=5,
            )
        )
        for request in recent:
            decision = self.access_repo.get_authorization_by_request(request.id)
            if (
                decision is not None
                and decision.result is AuthorizationResult.CONFIRMATION_REQUIRED
                and decision.disability_check_ok is False
            ):
                return True
        return False
