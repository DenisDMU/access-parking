"""Use case `ListAccessRequests` — liste/filtre des demandes (audit).

Chaque demande est renvoyée avec sa décision (`AccessAuthorization`), pour
que l'audit et le dashboard montrent directement le résultat de chaque
passage sans un appel par demande.
"""

from __future__ import annotations

from src.application.use_cases.get_access_request import AccessRequestDetail
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.value_objects.dto import AccessFilters


class ListAccessRequests:
    def __init__(self, access_repo: AccessRepositoryPort) -> None:
        self._access_repo = access_repo

    def execute(self, filters: AccessFilters) -> list[AccessRequestDetail]:
        return [
            AccessRequestDetail(
                request=request,
                authorization=self._access_repo.get_authorization_by_request(request.id),
            )
            for request in self._access_repo.list_requests(filters)
        ]
