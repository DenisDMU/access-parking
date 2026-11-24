"""Tests unitaires du use case `ProcessEntryRequest` — tous les ports mockés."""

from datetime import UTC, datetime, timedelta

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
        {
            "AA-111-AA": VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    presence.seed("v1", PresenceStatus.IN, request_id="previous-request")
    use_case = make_use_case(vehicles, presence_repo=presence)

    decision = use_case.execute("AA-111-AA", NOW, DetectionSource.CAMERA)

    assert decision.result is AuthorizationResult.REFUSED
    assert "déjà présent" in decision.reason


def test_entry_refused_incompatible_vehicle_type_for_place():
    vehicles = FakeVehiclesPort(
        {
            "AA-111-AA": VehicleInfo(
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


def test_entry_unknown_plate_is_created_by_vehicles():
    vehicles = FakeVehiclesPort({})
    use_case = ProcessEntryRequest(
        vehicles_port=vehicles,
        booking_port=FakeBookingPort(),
        parking_port=FakeParkingPort(),
        presence_repo=FakePresenceRepo(),
        access_repo=FakeAccessRepo(),
        event_publisher=FakeEventPublisher(),
        ai_vision_port=FakeAIVisionPort(),
    )

    decision = use_case.execute("ZZ-999-ZZ", NOW, DetectionSource.CAMERA)

    assert vehicles.created == ["ZZ-999-ZZ"]
    assert decision.vehicle_id == "v_created_1"
    assert decision.result is AuthorizationResult.AUTHORIZED


def test_entry_when_vehicles_is_down_is_rejected():
    vehicles = FakeVehiclesPort({}, available=False)
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

    decision = use_case.execute("ZZ-999-ZZ", NOW, DetectionSource.CAMERA)

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
        return use_case.execute(
            "AA-111-AA", datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
        )

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
        "AA-111-AA", datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
    )
    assert decision.result is AuthorizationResult.AUTHORIZED
    assert parking.confirmed_holds == ["H-1"]


def test_confirmation_refusee_par_parking_ferme_la_barriere():
    """Place mise de côté expirée ou déjà utilisée : le véhicule n'est pas
    compté par Parking, donc il n'entre pas (sinon les compteurs divergent)."""

    presence = FakePresenceRepo()
    publisher = FakeEventPublisher()
    decision = _entry_use_case(FakeParkingPort(confirm_ok=False), presence, publisher).execute(
        "AA-111-AA", datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
    )

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Place non confirmée par Parking, réessayez"
    assert presence.get_status(decision.vehicle_id) is None
    assert [e.type for e in publisher.published] == [EventType.ACCESS_REFUSED]


def test_categorie_inconnue_de_parking_donne_un_motif_precis():
    decision = _entry_use_case(FakeParkingPort(unknown_category="ELECTRIC")).execute(
        "AA-111-AA", datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
    )
    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Catégorie de place ELECTRIC inconnue du service Parking"


def test_le_libelle_de_parking_est_remonte():
    decision = _entry_use_case(FakeParkingPort()).execute(
        "AA-111-AA", datetime(2026, 9, 2, 10, 0, tzinfo=UTC), DetectionSource.LPR
    )
    assert decision.place_label == "Place de test"


# --- Réservation Booking (réelle) ---------------------------------------------


def test_reservation_cherchee_a_l_heure_du_passage_et_place_du_type_reserve():
    vehicles = FakeVehiclesPort(
        {
            "AA-111-AA": VehicleInfo(
                vehicle_id="v1",
                vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER, is_electric=True),
            )
        }
    )
    reservation = Reservation(
        id="482913",
        vehicle_id="v1",
        reserved_place_type=PlaceType(category=VehicleCategory.FOUR_WHEELER, is_electric=True),
        start_date=NOW,
        end_date=NOW + timedelta(hours=2),
    )
    booking = FakeBookingPort({"v1": reservation})
    parking = FakeParkingPort()
    publisher = FakeEventPublisher()
    use_case = ProcessEntryRequest(
        vehicles_port=vehicles,
        booking_port=booking,
        parking_port=parking,
        presence_repo=FakePresenceRepo(),
        access_repo=FakeAccessRepo(),
        event_publisher=publisher,
        ai_vision_port=FakeAIVisionPort(),
    )

    decision = use_case.execute("AA-111-AA", NOW, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.reservation is True
    assert booking.calls == [("v1", NOW)]
    requested_type, is_reservation = parking.calls[0]
    assert requested_type.is_electric and is_reservation is True
    payload = publisher.published[0].payload
    assert payload["reservationId"] == "482913"
    assert payload["reservationEnd"] == (NOW + timedelta(hours=2)).isoformat()
