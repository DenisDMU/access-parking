"""Use case `GetAccessRequest` — détail d'une demande + décision associée."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_request import AccessRequest
from src.domain.ports.access_repository_port import AccessRepositoryPort


@dataclass(frozen=True)
class AccessRequestDetail:
    request: AccessRequest
    authorization: AccessAuthorization | None


class GetAccessRequest:
    def __init__(self, access_repo: AccessRepositoryPort) -> None:
        self._access_repo = access_repo

    def execute(self, request_id: str) -> AccessRequestDetail | None:
        request = self._access_repo.get_request(request_id)
        if request is None:
            return None
        authorization = self._access_repo.get_authorization_by_request(request_id)
        return AccessRequestDetail(request=request, authorization=authorization)
