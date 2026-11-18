"""Tests unitaires du use case `ProcessExitRequest` — tous les ports mockés."""

from datetime import UTC, datetime, timedelta
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

ENTRY_AT = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
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


def make_use_case(
    vehicles_port, parking_port, pricing_port, payment_port, presence_repo, access_repo
):
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
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=Decimal("7.50"))
    payment = FakePaymentPort(success=True)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute(1, EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert decision.payment_amount == Decimal("7.50")
    assert parking.freed == ["P-1"]
    assert presence.get_status("v1") is PresenceStatus.OUT


def test_exit_refused_payment_failed():
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=Decimal("7.50"))
    payment = FakePaymentPort(success=False)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute(1, EXIT_AT, DetectionSource.MOBILE_APP)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Paiement refusé"
    # Le véhicule reste marqué présent : il n'a pas physiquement quitté la place.
    assert presence.get_status("v1") is PresenceStatus.IN
    assert parking.freed == []


def test_exit_refused_pricing_unavailable():
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=None)  # simule Pricing indisponible (429/5xx/timeout)
    payment = FakePaymentPort()
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute(1, EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Service de tarification indisponible, réessayez plus tard"
    assert decision.payment_amount is None
    # Jamais de paiement tente sans montant fiable, jamais la place liberee.
    assert payment.calls == []
    assert parking.freed == []
    assert presence.get_status("v1") is PresenceStatus.IN


def test_exit_refused_vehicle_not_present():
    vehicles = FakeVehiclesPort(
        {
            3: VehicleInfo(
                vehicle_id="v_absent",
                vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER),
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    parking = FakeParkingPort()
    pricing = FakePricingPort()
    payment = FakePaymentPort()
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute(3, EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Véhicule non présent dans le parking"
    assert pricing.calls == []
    assert payment.calls == []


def test_exit_payment_uses_entry_request_as_stay_id():
    # L'identifiant du stationnement (= demande d'entrée) est stable : c'est
    # lui qui fonde la clé d'idempotence côté Payment.
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    payment = FakePaymentPort(success=True)
    use_case = make_use_case(
        vehicles,
        FakeParkingPort(),
        FakePricingPort(amount=Decimal("7.50")),
        payment,
        presence,
        access_repo,
    )

    use_case.execute(1, EXIT_AT, DetectionSource.TERMINAL)

    assert payment.calls == [("entry-request-1", Decimal("7.50"))]


def test_exit_refused_payment_undetermined():
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    payment = FakePaymentPort(success=None)  # Payment injoignable / toujours PENDING
    use_case = make_use_case(
        vehicles, parking, FakePricingPort(amount=Decimal("7.50")), payment, presence, access_repo
    )

    decision = use_case.execute(1, EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert "réessayez" in decision.reason
    assert parking.freed == []
    assert presence.get_status("v1") is PresenceStatus.IN


def test_exit_free_stay_skips_payment():
    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    payment = FakePaymentPort()
    use_case = make_use_case(
        vehicles,
        FakeParkingPort(),
        FakePricingPort(amount=Decimal("0")),
        payment,
        presence,
        access_repo,
    )

    decision = use_case.execute(1, EXIT_AT, DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.AUTHORIZED
    assert payment.calls == []


def test_exit_refused_when_exit_date_before_entry():
    """Cas limite : sortie datée avant l'entrée → refus, sans appel à Pricing
    ni Payment, et le véhicule reste présent."""

    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(amount=Decimal("7.50"))
    payment = FakePaymentPort(success=True)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute(1, ENTRY_AT - timedelta(hours=1), DetectionSource.TERMINAL)

    assert decision.result is AuthorizationResult.REFUSED
    assert decision.reason == "Date de sortie antérieure à la date d'entrée"
    assert pricing.calls == []
    assert payment.calls == []
    assert presence.get_status("v1") is PresenceStatus.IN


def test_evenement_de_sortie_donne_heure_entree_et_duree():
    """Le ticket de sortie (service Messages) a besoin de l'heure d'entrée et
    de la durée : elles sont dans le payload de `access.exit`."""

    vehicles = FakeVehiclesPort(
        {
            1: VehicleInfo(
                vehicle_id="v1", vehicle_type=VehicleType(category=VehicleCategory.FOUR_WHEELER)
            )
        }
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicle_present(access_repo, presence)
    publisher = FakeEventPublisher()
    use_case = ProcessExitRequest(
        vehicles_port=vehicles,
        parking_port=FakeParkingPort(),
        pricing_port=FakePricingPort(amount=Decimal("7.50")),
        payment_port=FakePaymentPort(success=True),
        presence_repo=presence,
        access_repo=access_repo,
        event_publisher=publisher,
    )

    use_case.execute(
        1, ENTRY_AT + timedelta(hours=2, minutes=30, seconds=10), DetectionSource.TERMINAL
    )

    exit_event = next(e for e in publisher.published if e.type is EventType.VEHICLE_EXITED)
    assert exit_event.payload["enteredAt"] == ENTRY_AT.isoformat()
    assert exit_event.payload["durationMinutes"] == 151  # 2 h 30 min 10 s : minute entamée
    assert exit_event.payload["amount"] == "7.50"
