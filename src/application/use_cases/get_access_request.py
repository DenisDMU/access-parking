"""Use case `GetAccessRequest` — détail d'une demande + décision associée."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities.autorisation_acces import AutorisationAcces
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.ports.access_repository_port import AccessRepositoryPort


@dataclass(frozen=True)
class AccessRequestDetail:
    demande: DemandeAcces
    autorisation: AutorisationAcces | None


class GetAccessRequest:
    def __init__(self, access_repo: AccessRepositoryPort) -> None:
        self._access_repo = access_repo

    def execute(self, demande_id: str) -> AccessRequestDetail | None:
        demande = self._access_repo.get_demande(demande_id)
        if demande is None:
            return None
        autorisation = self._access_repo.get_autorisation_by_demande(demande_id)
        return AccessRequestDetail(demande=demande, autorisation=autorisation)
