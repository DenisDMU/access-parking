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
    PresenceStatus,
    ResultatAutorisation,
    SourceDetection,
    StatutDemande,
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


def test_entree_autorisee_sans_reservation_avec_attribution_parking():
    vehicles = FakeVehiclesPort(
        {
            "AA-111-AA": VehicleInfo(
                vehicule_id="v1", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES)
            )
        }
    )
    parking = FakeParkingPort()
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("AA-111-AA", NOW, SourceDetection.LPR)

    assert decision.resultat is ResultatAutorisation.AUTORISE
    assert decision.vehicule_id == "v1"
    assert decision.statut is StatutDemande.TRAITEE
    assert "P-TEST-1" in parking.occupied
    # La plaque brute n'a été utilisée qu'une seule fois par le use case.
    assert vehicles.calls == ["AA-111-AA"]


def test_entree_autorisee_avec_reservation_existante():
    vehicles = FakeVehiclesPort(
        {
            "GG-777-GG": VehicleInfo(
                vehicule_id="v_res", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES)
            )
        }
    )
    reservation = Reservation(
        id="res-1",
        vehicule_id="v_res",
        type_place_reservee=PlaceType(category=VehicleCategory.QUATRE_ROUES),
        date_debut=NOW,
        date_fin=NOW,
        place_id="P-RES-1",
    )
    booking = FakeBookingPort({"v_res": reservation})
    parking = FakeParkingPort()
    use_case = make_use_case(vehicles, booking_port=booking, parking_port=parking)

    decision = use_case.execute("GG-777-GG", NOW, SourceDetection.APP_MOBILE)

    assert decision.resultat is ResultatAutorisation.AUTORISE
    assert parking.occupied == {"P-RES-1": "v_res"}


def test_entree_refusee_vehicule_deja_present():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicule_id="v1", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES))}
    )
    presence = FakePresenceRepo()
    presence.seed("v1", PresenceStatus.IN, demande_id="demande-precedente")
    use_case = make_use_case(vehicles, presence_repo=presence)

    decision = use_case.execute("AA-111-AA", NOW, SourceDetection.CAMERA)

    assert decision.resultat is ResultatAutorisation.REFUSE
    assert "déjà présent" in decision.motif


def test_entree_refusee_type_vehicule_incompatible_avec_place():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicule_id="v1", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES))}
    )
    # Parking (mal) attribue une place 2 roues à un véhicule 4 roues.
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-2R", place_type=PlaceType(category=VehicleCategory.DEUX_ROUES)
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("AA-111-AA", NOW, SourceDetection.BORNE)

    assert decision.resultat is ResultatAutorisation.REFUSE
    assert decision.controle_type_vehicule_ok is False
    assert parking.occupied == {}


def test_entree_confirmation_requise_pmr_sans_justificatif():
    vehicles = FakeVehiclesPort(
        {
            "FF-666-FF": VehicleInfo(
                vehicule_id="v_pmr",
                type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True),
                justificatif_pmr=False,
            )
        }
    )
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-H",
            place_type=PlaceType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True),
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("FF-666-FF", NOW, SourceDetection.LPR)

    assert decision.resultat is ResultatAutorisation.CONFIRMATION_REQUISE
    assert decision.controle_pmr_ok is False
    # La place n'est pas occupée tant que la confirmation n'est pas obtenue.
    assert parking.occupied == {}


def test_entree_pmr_avec_justificatif_est_autorisee():
    vehicles = FakeVehiclesPort(
        {
            "EE-555-EE": VehicleInfo(
                vehicule_id="v_pmr_ok",
                type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True),
                justificatif_pmr=True,
            )
        }
    )
    parking = FakeParkingPort(
        assignment=PlaceAssignment(
            place_id="P-H",
            place_type=PlaceType(category=VehicleCategory.QUATRE_ROUES, is_handicap=True),
        )
    )
    use_case = make_use_case(vehicles, parking_port=parking)

    decision = use_case.execute("EE-555-EE", NOW, SourceDetection.LPR)

    assert decision.resultat is ResultatAutorisation.AUTORISE
    assert decision.controle_pmr_ok is True


def test_entree_vehicule_inconnu_est_rejetee_sans_plaque_persistee():
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

    decision = use_case.execute("UN-000-KN", NOW, SourceDetection.CAMERA)

    assert decision.vehicule_id is None
    assert decision.statut is StatutDemande.REJETEE
    assert decision.resultat is ResultatAutorisation.CONFIRMATION_REQUISE
    # Aucune donnée persistée ne doit référencer la plaque brute.
    demande = access_repo.demandes[decision.demande_id]
    assert demande.vehicule_id is None
    for evenement in access_repo.evenements.values():
        assert "UN-000-KN" not in str(evenement.payload)
