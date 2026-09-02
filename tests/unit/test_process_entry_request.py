"""Tests unitaires du use case `ProcessEntryRequest` — tous les ports mockés."""

from datetime import datetime, timezone

from src.application.use_cases.process_entry_request import ProcessEntryRequest
from src.domain.value_objects.dto import (
    PlaceAssignment,
    PlaceType,
    Reservation,
    VehicleInfo,
    VehicleType,
)
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    PresenceStatus,
    RequestStatus,
    VehicleCategory,
)
from tests.unit.fakes import (
    FakeAccessRepo,
    FakeAIVisionPort,
    FakeBookingPort,
    FakeEventPublisher,
    FakeParkingPort,
    FakePresenceRepo,
    FakeVehiclesPort,
)

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)


def make_use_case(vehicles_port, booking_port=None, parking_port=None, presence_repo=None):
    return ProcessEntryRequest(
        vehicles_port=vehicles_port,
        booking_port=booking_port or FakeBookingPort(),
        parking_port=parking_port or FakeParkingPort(),
        presence_repo=presence_repo or FakePresenceRepo(),
        access_repo=FakeAccessRepo(),
        event_publisher=FakeEventPublisher(),
        ai_vision_port=FakeAIVisionPort(),
    )


def test_entry_authorized_without_reservation_with_parking_assignment():
    vehicles = FakeVehiclesPort(
        {
            "AA-111-AA": VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    parking = FakeParkingPort()
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("AA-111-AA", NOW, DetectionSource.LPR)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.vehicle_id == "v1"
    assert decision.status is RequestStatus.PROCESSED
    assert "P-TEST-1" in parking.occupied
    # La plaque brute n'a été utilisée qu'une seule fois par le use case.
    assert vehicles.calls == ["AA-111-AA"]


def test_entry_authorized_with_existing_reservation():
    vehicles = FakeVehiclesPort(
        {
            "GG-777-GG": VehicleInfo(
                vehicle_id="v_res", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    reservation = Reservation(
        id="res-1",
        vehicle_id="v_res",
        reserved_place_type=PlaceType(category=VehicleCategory.FOUR_WHEELER),
        start_date=NOW,
        end_date=NOW,
        place_id="P-RES-1",
    )
    booking = FakeBookingPort({"v_res": reservation})
    parking = FakeParkingPort()
    use_case = make_use_case(vehicles, booking_port=booking, parking_port=parking)

    decision = use_case.execute("GG-777-GG", NOW, DetectionSource.MOBILE_APP)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert parking.occupied == {"P-RES-1": "v_res"}


def test_entry_refused_vehicle_already_present():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER))}
    )
    presence = FakePresenceRepo()
    presence.seed("v1", PresenceStatus.IN, request_id="previous-request")
    use_case = make_use_case(vehicles, presence_repo=presence)

    decision = use_case.execute("AA-111-AA", NOW, DetectionSource.CAMERA)

    assert decision.result is AuthorizationResult.REFUSED
    assert "déjà présent" in decision.reason


def test_entry_refused_incompatible_vehicle_type_for_place():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER))}
    )
    # Parking (mal) attribue une place 2 roues à un véhicule 4 roues.
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-2W", place_type=PlaceType(category=VehicleCategory.TWO_WHEELER)
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("AA-111-AA", NOW, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.vehicle_type_check_ok is False
    assert parking.occupied == {}


def test_entry_confirmation_required_disabled_without_permit():
    vehicles = FakeVehiclesPort(
        {
            "FF-666-FF": VehicleInfo(
                vehicle_id="v_disabled",
                vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
                disability_permit=False,
            )
        }
    )
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-H",
            place_type=PlaceType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("FF-666-FF", NOW, DetectionSource.LPR)

    assert decision.result is AuthorizationResult.CONFIRMATION_REQUIRED
    assert decision.disability_check_ok is False
    # La place n'est pas occupée tant que la confirmation n'est pas obtenue.
    assert parking.occupied == {}


def test_entry_with_disability_permit_is_authorized():
    vehicles = FakeVehiclesPort(
        {
            "EE-555-EE": VehicleInfo(
                vehicle_id="v_disabled_ok",
                vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
                disability_permit=True,
            )
        }
    )
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-H",
            place_type=PlaceType(category=VehicleCategory.FOUR_WHEELER, is_handicap=True),
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("EE-555-EE", NOW, DetectionSource.LPR)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.disability_check_ok is True


def test_entry_unknown_vehicle_is_rejected_without_plate_persisted():
    vehicles = FakeVehiclesPort({})
    access_repo = FakeAccessRepo()
    use_case = ProcessEntryRequest(
        vehicles_port=vehicles,
        booking_port=FakeBookingPort(),
        parking_port=FakeParkingPort(),
        presence_repo=FakePresenceRepo(),
        access_repo=access_repo,
        event_publisher=FakeEventPublisher(),
        ai_vision_port=FakeAIVisionPort(),
    )

    decision = use_case.execute("UN-000-KN", NOW, DetectionSource.CAMERA)

    assert decision.vehicle_id is None
    assert decision.status is RequestStatus.REJECTED
    assert decision.result is AuthorizationResult.CONFIRMATION_REQUIRED
    # Aucune donnée persistée ne doit référencer la plaque brute.
    request = access_repo.requests[decision.request_id]
    assert request.vehicle_id is None
    for event in access_repo.events.values():
        assert "UN-000-KN" not in str(event.payload)
