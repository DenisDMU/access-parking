"""Port vers le service Vehicles.

Access reçoit la plaque lue par la borne et la transmet à Vehicles, seul
service qui la conserve (règle 3.7 : Access *demande* l'identifiant à
Vehicles). En retour, Access ne garde que l'identifiant pseudonymisé et les
caractéristiques du véhicule : la plaque n'existe que le temps de la
requête, elle n'est jamais persistée, publiée, renvoyée ni loggée.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import VehicleInfo, VehicleType


class VehiclesServicePort(Protocol):
    def get_vehicle_info(self, plate: str) -> VehicleInfo | None:
        """Consultation seule : identité pseudonymisée du véhicule, ou `None`
        s'il est inconnu (ou si Vehicles est indisponible)."""
        ...

    def identify_vehicle(
        self, plate: str, declared: VehicleType | None = None
    ) -> VehicleInfo | None:
        """Retrouve le véhicule ou le crée s'il est inconnu (règle 3.2 :
        Vehicles « recherche ou crée » l'identifiant pseudonymisé).

        `declared` : type choisi par le conducteur à la borne. Il ne sert qu'à
        créer un véhicule inconnu avec les bonnes caractéristiques (électrique,
        XL, deux-roues) ; un véhicule connu n'est jamais modifié. PMR n'est
        jamais enregistré sur simple déclaration.

        `None` seulement si Vehicles est indisponible ou répond hors contrat.
        """
        ...
