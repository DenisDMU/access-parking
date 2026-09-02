"""Port de persistance des objets métier d'Access.

Note (écart mineur assumé par rapport à la liste de la spec — voir README
section "Écarts assumés par rapport à la spec") : trois méthodes de lecture
ont été ajoutées (`get_authorization_by_request`, `get_event_by_request`,
`list_events`) car le schéma SQL officiel ne conserve la place attribuée
(`placeId`/type de place) que dans le payload JSON de l'événement d'accès
associé à la demande d'entrée — il n'existe pas de colonne dédiée. Ces
méthodes restent de la simple lecture, aucune règle métier n'y est ajoutée.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.entities.access_authorization import AccessAuthorization
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.value_objects.dto import AccessFilters


class AccessRepositoryPort(Protocol):
    def save_request(self, request: AccessRequest) -> None: ...

    def save_authorization(self, authorization: AccessAuthorization) -> None: ...

    def save_event(self, event: AccessEvent) -> None: ...

    def get_request(self, request_id: str) -> AccessRequest | None: ...

    def list_requests(self, filters: AccessFilters) -> list[AccessRequest]: ...

    def get_authorization_by_request(self, request_id: str) -> AccessAuthorization | None: ...

    def get_event_by_request(self, request_id: str) -> AccessEvent | None: ...

    def list_events(self, limit: int = 100, offset: int = 0) -> list[AccessEvent]: ...
