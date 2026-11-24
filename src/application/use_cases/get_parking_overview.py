"""Use case `GetParkingOverview` — l'état du parking vu par le service Parking.

Vue d'exploitation (dashboard, onglet « État du parking ») qui complète la
vue d'Access (`ListPresentVehicles`) : catégories déclarées par Parking avec
leur libellé, places prises, mises de côté et capacité, et les catégories
dont Access a besoin mais que Parking ne déclare pas (à corriger avant
qu'une entrée ne soit refusée). Rien n'est persisté.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.ports.parking_service_port import ParkingServicePort, ParkingUnavailableError


@dataclass(frozen=True)
class ParkingCategoryView:
    name: str
    label: str
    used_by_access: bool
    spot_taken: int | None = None
    spot_held: int | None = None
    total_capacity: int | None = None
    occupation_rate: float | None = None


@dataclass(frozen=True)
class ParkingOverview:
    available: bool
    categories: list[ParkingCategoryView]
    missing_categories: list[str]


class GetParkingOverview:
    def __init__(self, parking_port: ParkingServicePort) -> None:
        self._parking_port = parking_port

    def execute(self) -> ParkingOverview:
        try:
            categories = self._parking_port.list_categories()
            occupation = {o.name: o for o in self._parking_port.get_occupation()}
        except ParkingUnavailableError:
            return ParkingOverview(available=False, categories=[], missing_categories=[])

        required = self._parking_port.required_categories()
        declared = {c.name for c in categories}
        views = []
        for category in categories:
            occ = occupation.get(category.name)
            views.append(
                ParkingCategoryView(
                    name=category.name,
                    label=category.label,
                    used_by_access=category.name in required,
                    spot_taken=occ.spot_taken if occ else None,
                    spot_held=occ.spot_held if occ else None,
                    total_capacity=occ.total_capacity if occ else None,
                    occupation_rate=occ.occupation_rate if occ else None,
                )
            )
        return ParkingOverview(
            available=True,
            categories=views,
            missing_categories=[name for name in required if name not in declared],
        )
