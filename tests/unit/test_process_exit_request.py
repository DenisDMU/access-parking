"""Tests unitaires du use case `ProcessExitRequest` — tous les ports mockés."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.entities.access_event import AccessEvent
from src.domain.entities.access_request import AccessRequest
from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import (
    AuthorizationResult,
    DetectionSource,
    EventType,
    PresenceStatus,
    RequestStatus,
    RequestType,
    VehicleCategory,
)
from tests.unit.fakes import (
    FakeAccessRepo,
    FakeEventPublisher,
    FakeParkingPort,
    FakePaymentPort,
    FakePresenceRepo,
    FakePricingPort,
    FakeVehiclesPort,
)

ENTRY_AT = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
EXIT_AT = ENTRY_AT + timedelta(hours=1)


def _seed_vehicle_present(access_repo, presence_repo, vehicle_id="v1", place_id="P-1"):
    """Simule qu'un véhicule est entré : demande d'entrée + événement
    VEHICLE_ENTERED (porteur du placeId/placeType, cf. process_exit_request)
    + présence IN."""

    request_id = "entry-request-1"
    access_repo.save_request(
        AccessRequest(
            id=request_id,
            type=RequestType.ENTRY,
            date=ENTRY_AT,
            source=DetectionSource.LPR,
            status=RequestStatus.PROCESSED,
            vehicle_id=vehicle_id,
        )
    )
    access_repo.save_event(
        AccessEvent(
            id="evt-entry-1",
            type=EventType.VEHICLE_ENTERED,
            request_id=request_id,
            payload={
                "vehicleId": vehicle_id,
                "placeId": place_id,
                "placeType": {
                    "category": int(VehicleCategory.FOUR_WHEELER),
                    "isXl": False,
                    "isElectric": False,
                    "isHandicap": False,
                },
            },
            created_at=ENTRY_AT,
        )
    )
    presence_repo.seed(vehicle_id, PresenceStatus.IN, request_id=request_id)


def make_use_case(vehicles_port, parking_port, pricing_port, payment_port, presence_repo, access_repo):
    return ProcessExitRequest(
        vehicles_port=vehicles_port,
        parking_port=parking_port,
        pricing_port=pricing_port,
        payment_port=payment_port,
        presence_repo=presence_repo,
        access_repo=access_repo,
        event_publisher=FakeEventPublisher(),
    )


def test_exit_authorized_pricing_and_payment_ok():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=Decimal("7.50"))
    payment = FakePaymentPort(success=True)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("AA-111-AA", EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.payment_amount == Decimal("7.50")
    assert parking.freed == ["P-1"]
    assert presence.get_status("v1") is PresenceStatus.OUT


def test_exit_refused_payment_failed():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=Decimal("7.50"))
    payment = FakePaymentPort(success=False)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("AA-111-AA", EXIT_AT, DetectionSource.MOBILE_APP)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Paiement refusé"
    # Le véhicule reste marqué présent : il n'a pas physiquement quitté la place.
    assert presence.get_status("v1") is PresenceStatus.IN
    assert parking.freed == []


def test_exit_refused_pricing_unavailable():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=None)  # simule Pricing indisponible (429/5xx/timeout)
    payment = FakePaymentPort()
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("AA-111-AA", EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Service de tarification indisponible, réessayez plus tard"
    assert decision.payment_amount is None
    # Jamais de paiement tente sans montant fiable, jamais la place liberee.
    assert payment.calls == []
    assert parking.freed == []
    assert presence.get_status("v1") is PresenceStatus.IN


def test_exit_refused_vehicle_not_present():
    vehicles = FakeVehiclesPort(
        {"CC-333-CC": VehicleInfo(vehicle_id="v_absent", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    parking = FakeParkingPort()
    pricing = FakePricingPort()
    payment = FakePaymentPort()
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("CC-333-CC", EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Véhicule non présent dans le parking"
    assert pricing.calls == []
    assert payment.calls == []
