"""Port vers le service Parking.

`is_reservation` a été ajouté (écart mineur assumé, cf. README section 16)
après intégration du vrai service Parking de l'équipe : sa capacité est
scindée en deux pools par catégorie — "walkin" et "booking" (cf. consignes
projet section 2.1, "répartition entre capacité réservée à la réservation
et capacité disponible pour les entrées immédiates") — Access connaît déjà
cette information à l'entrée (résultat de `BookingServicePort`) mais la
spec initiale ne la faisait pas remonter jusqu'à ce port.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import PlaceAssignment, VehicleType


class ParkingUnavailableError(Exception):
    """Parking n'a pas pu répondre (panne, délai dépassé, clé API refusée).

    À distinguer de « aucune place disponible » (`None`) : le conducteur et
    l'exploitant ne doivent pas croire le parking complet quand c'est le
    service qui est injoignable.
    """


class ParkingServicePort(Protocol):
    def request_place(
        self, vehicle_type: VehicleType, is_reservation: bool = False
    ) -> PlaceAssignment | None:
        """Demande l'attribution d'une place adaptée, ou `None` si aucune
        disponible. Lève `ParkingUnavailableError` si Parking ne répond pas."""
        ...

    def mark_place_occupied(
        self, place_id: str, vehicle_id: str, hold_id: str | None = None
    ) -> bool:
        """Confirme l'entrée sur la place mise de côté (`hold_id`).

        `False` si Parking refuse (place expirée ou déjà utilisée) ou ne
        répond pas : l'entrée ne doit alors pas être autorisée.
        """
        ...

    def mark_place_free(self, place_id: str) -> bool:
        """Libère la place."""
        ...
