"""Use case `ListAccessRequests` — liste/filtre des demandes (audit)."""

from __future__ import annotations

from src.domain.entities.access_request import AccessRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.value_objects.dto import AccessFilters


class ListAccessRequests:
    def __init__(self, access_repo: AccessRepositoryPort) -> None:
        self._access_repo = access_repo

    def execute(self, filters: AccessFilters) -> list[AccessRequest]:
        return self._access_repo.list_requests(filters)
