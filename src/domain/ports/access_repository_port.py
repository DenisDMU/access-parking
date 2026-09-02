"""Port de persistance des objets métier d'Access.

Note (écart mineur assumé par rapport à la liste de la spec — voir README
section "Écarts assumés par rapport à la spec") : deux méthodes de lecture
ont été ajoutées (`get_autorisation_by_demande`, `get_evenement_by_demande`,
`list_evenements`) car le schéma SQL officiel ne conserve la place attribuée
(`place_id`/type de place) que dans le payload JSON de l'Événement d'accès
associé à la demande d'entrée — il n'existe pas de colonne dédiée. Ces
méthodes restent de la simple lecture, aucune règle métier n'y est ajoutée.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.entities.autorisation_acces import AutorisationAcces
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.entities.evenement_acces import EvenementAcces
from src.domain.value_objects.dto import AccessFilters


class AccessRepositoryPort(Protocol):
    def save_demande(self, demande: DemandeAcces) -> None: ...

    def save_autorisation(self, autorisation: AutorisationAcces) -> None: ...

    def save_evenement(self, evenement: EvenementAcces) -> None: ...

    def get_demande(self, demande_id: str) -> DemandeAcces | None: ...

    def list_demandes(self, filters: AccessFilters) -> list[DemandeAcces]: ...

    def get_autorisation_by_demande(self, demande_id: str) -> AutorisationAcces | None: ...

    def get_evenement_by_demande(self, demande_id: str) -> EvenementAcces | None: ...

    def list_evenements(self, limit: int = 100, offset: int = 0) -> list[EvenementAcces]: ...
