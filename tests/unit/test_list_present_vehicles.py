"""Tests unitaires du use case `ListPresentVehicles` (vue d'exploitation)."""

from datetime import UTC, datetime

from src.application.use_cases.list_present_vehicles import ListPresentVehicles
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.value_objects.enums import (
    DetectionSource,
    EventType,
    PresenceStatus,
    RequestStatus,
    RequestType,
    VehicleCategory,
)
from tests.unit.fakes import FakeAccessRepo, FakePresenceRepo


def _seed_entry(access_repo, presence_repo, vehicle_id, request_id, date, reservation=False):
    access_repo.save_request(
        AccessRequest(
            id=request_id,
            type=RequestType.ENTRY,
            date=date,
            source=DetectionSource.LPR,
            status=RequestStatus.PROCESSED,
            vehicle_id=vehicle_id,
        )
    )
    access_repo.save_event(
        AccessEvent(
            id="evt-" + request_id,
            type=EventType.VEHICLE_ENTERED,
            request_id=request_id,
            payload={
                "vehicleId": vehicle_id,
                "placeId": "ELECTRIC:walkin",
                "placeType": {
                    "category": int(VehicleCategory.FOUR_WHEELER),
                    "isXl": False,
                    "isElectric": True,
                    "isHandicap": False,
                },
                "reservation": reservation,
            },
            created_at=date,
        )
    )
    presence_repo.seed(vehicle_id, PresenceStatus.IN, request_id=request_id)


def test_liste_vide_quand_parking_vide():
    use_case = ListPresentVehicles(FakePresenceRepo(), FakeAccessRepo())
    assert use_case.execute() == []


def test_seuls_les_vehicules_in_sont_listes_plus_recents_dabord():
    presence, access_repo = FakePresenceRepo(), FakeAccessRepo()
    _seed_entry(access_repo, presence, "v_old", "r1", datetime(2026, 9, 2, 8, 0, tzinfo=UTC))
    _seed_entry(access_repo, presence, "v_new", "r2", datetime(2026, 9, 2, 9, 0, tzinfo=UTC), True)
    presence.seed("v_gone", PresenceStatus.OUT)

    result = ListPresentVehicles(presence, access_repo).execute()

    assert [v.vehicle_id for v in result] == ["v_new", "v_old"]
    newest = result[0]
    assert newest.entry_request_id == "r2"
    assert newest.place_id == "ELECTRIC:walkin"
    assert newest.place_type.is_electric is True
    assert newest.is_reservation is True


def test_presence_sans_demande_connue_reste_listee():
    """Robustesse : une présence sans demande d'entrée retrouvable (base
    incohérente) est quand même affichée, sans planter."""

    presence = FakePresenceRepo()
    presence.seed("v_orphan", PresenceStatus.IN, request_id=None)

    result = ListPresentVehicles(presence, FakeAccessRepo()).execute()

    assert len(result) == 1
    assert result[0].entered_at is None
    assert result[0].place_type is None
