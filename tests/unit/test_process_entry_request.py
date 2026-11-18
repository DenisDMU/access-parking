"""Tests unitaires du use case `ProcessEntryRequest` — tous les ports mockés."""

from datetime import UTC, datetime

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
    EventType,
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

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


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
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    parking = FakeParkingPort()
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute(1, NOW, DetectionSource.LPR)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.vehicle_id == "v1"
    assert decision.status is RequestStatus.PROCESSED
    assert "P-TEST-1" in parking.occupied
    # La plaque brute n'a été utilisée qu'une seule fois par le use case.
    assert vehicles.calls == [1]


def test_entry_authorized_with_existing_reservation():
    vehicles = FakeVehiclesPort(
        {
            7: VehicleInfo(
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

    decision = use_case.execute(7, NOW, DetectionSource.MOBILE_APP)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert parking.occupied == {"P-RES-1": "v_res"}


def test_entry_refused_vehicle_already_present():
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    presence.seed("v1", PresenceStatus.IN, request_id="previous-request")
    use_case = make_use_case(vehicles, presence_repo=presence)

    decision = use_case.execute(1, NOW, DetectionSource.CAMERA)

    assert decision.result is AuthorizationResult.REFUSED
    assert "déjà présent" in decision.reason


def test_entry_refused_incompatible_vehicle_type_for_place():
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    # Parking (mal) attribue une place 2 roues à un véhicule 4 roues.
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-2W", place_type=PlaceType(category=VehicleCategory.TWO_WHEELER)
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute(1, NOW, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.vehicle_type_check_ok is False
    assert parking.occupied == {}


def test_entry_confirmation_required_disabled_without_permit():
    vehicles = FakeVehiclesPort(
        {
            6: VehicleInfo(
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

    decision = use_case.execute(6, NOW, DetectionSource.LPR)

    assert decision.result is AuthorizationResult.CONFIRMATION_REQUIRED
    assert decision.disability_check_ok is False
    # La place n'est pas occupée tant que la confirmation n'est pas obtenue.
    assert parking.occupied == {}


def test_entry_with_disability_permit_is_authorized():
    vehicles = FakeVehiclesPort(
        {
            5: VehicleInfo(
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

    decision = use_case.execute(5, NOW, DetectionSource.LPR)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.disability_check_ok is True


def test_entry_unknown_vehicle_is_rejected():
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

    decision = use_case.execute(999, NOW, DetectionSource.CAMERA)

    assert decision.vehicle_id is None
    assert decision.status is RequestStatus.REJECTED
    assert decision.result is AuthorizationResult.CONFIRMATION_REQUIRED
    request = access_repo.requests[decision.request_id]
    assert request.vehicle_id is None


def test_parking_injoignable_donne_un_motif_distinct_de_parking_complet():
    from tests.unit.fakes import DEMO_VEHICLES

    def decide(parking):
        use_case = ProcessEntryRequest(
            vehicles_port=FakeVehiclesPort(DEMO_VEHICLES),
            booking_port=FakeBookingPort(),
            parking_port=parking,
            presence_repo=FakePresenceRepo(),
            access_repo=FakeAccessRepo(),
            event_publisher=FakeEventPublisher(),
            ai_vision_port=FakeAIVisionPort(),
        )
        return use_case.execute(1, datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR)

    injoignable = decide(FakeParkingPort(unavailable=True))
    complet = decide(FakeParkingPort(has_place=False))

    assert injoignable.result is AuthorizationResult.REFUSED
    assert injoignable.reason == "Service Parking indisponible, réessayez plus tard"
    assert complet.reason == "Aucune place disponible"


def _entry_use_case(parking, presence=None, publisher=None):
    from tests.unit.fakes import DEMO_VEHICLES

    return ProcessEntryRequest(
        vehicles_port=FakeVehiclesPort(DEMO_VEHICLES),
        booking_port=FakeBookingPort(),
        parking_port=parking,
        presence_repo=presence or FakePresenceRepo(),
        access_repo=FakeAccessRepo(),
        event_publisher=publisher or FakeEventPublisher(),
        ai_vision_port=FakeAIVisionPort(),
    )


def test_le_hold_id_de_parking_est_transmis_a_la_confirmation():
    parking = FakeParkingPort()
    decision = _entry_use_case(parking).execute(
        1, datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
    )
    assert decision.result is AuthorizationResult.AUTHORIZED
    assert parking.confirmed_holds == ["H-1"]


def test_confirmation_refusee_par_parking_ferme_la_barriere():
    """Place mise de côté expirée ou déjà utilisée : le véhicule n'est pas
    compté par Parking, donc il n'entre pas (sinon les compteurs divergent)."""

    presence = FakePresenceRepo()
    publisher = FakeEventPublisher()
    decision = _entry_use_case(FakeParkingPort(confirm_ok=False), presence, publisher).execute(
        1, datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
    )

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Place non confirmée par Parking, réessayez"
    assert presence.get_status(decision.vehicle_id) is None
    assert [e.type for e in publisher.published] == [EventType.ACCESS_REFUSED]
