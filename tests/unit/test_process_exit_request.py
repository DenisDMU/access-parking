"""Tests unitaires du use case `ProcessExitRequest` — tous les ports mockés."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.application.use_cases.process_exit_request import ProcessExitRequest
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.entities.evenement_acces import EvenementAcces
from src.domain.value_objects.dto import VehicleInfo, VehicleType
from src.domain.value_objects.enums import (
    PresenceStatus,
    ResultatAutorisation,
    SourceDetection,
    StatutDemande,
    TypeDemande,
    TypeEvenement,
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

ENTREE_AT = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
SORTIE_AT = ENTREE_AT + timedelta(hours=1)


def _seed_vehicule_present(access_repo, presence_repo, vehicule_id="v1", place_id="P-1"):
    """Simule qu'un véhicule est entré : demande d'entrée + événement
    VEHICULE_ENTRE (porteur du placeId/placeType, cf. process_exit_request)
    + présence IN."""

    demande_id = "demande-entree-1"
    access_repo.save_demande(
        DemandeAcces(
            id=demande_id,
            type=TypeDemande.ENTREE,
            date=ENTREE_AT,
            source=SourceDetection.LPR,
            statut=StatutDemande.TRAITEE,
            vehicule_id=vehicule_id,
        )
    )
    access_repo.save_evenement(
        EvenementAcces(
            id="evt-entree-1",
            type=TypeEvenement.VEHICULE_ENTRE,
            demande_id=demande_id,
            payload={
                "vehiculeId": vehicule_id,
                "placeId": place_id,
                "placeType": {
                    "category": int(VehicleCategory.QUATRE_ROUES),
                    "isXl": False,
                    "isElectric": False,
                    "isHandicap": False,
                },
            },
            created_at=ENTREE_AT,
        )
    )
    presence_repo.seed(vehicule_id, PresenceStatus.IN, demande_id=demande_id)


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


def test_sortie_autorisee_pricing_et_payment_ok():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicule_id="v1", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicule_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(montant=Decimal("7.50"))
    payment = FakePaymentPort(succes=True)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("AA-111-AA", SORTIE_AT, SourceDetection.BORNE)

    assert decision.resultat is ResultatAutorisation.AUTORISE
    assert decision.montant_paiement == Decimal("7.50")
    assert parking.freed == ["P-1"]
    assert presence.get_status("v1") is PresenceStatus.OUT


def test_sortie_refusee_paiement_echoue():
    vehicles = FakeVehiclesPort(
        {"AA-111-AA": VehicleInfo(vehicule_id="v1", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    _seed_vehicule_present(access_repo, presence)
    parking = FakeParkingPort()
    pricing = FakePricingPort(montant=Decimal("7.50"))
    payment = FakePaymentPort(succes=False)
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("AA-111-AA", SORTIE_AT, SourceDetection.APP_MOBILE)

    assert decision.resultat is ResultatAutorisation.REFUSE
    assert decision.motif == "Paiement refusé"
    # Le véhicule reste marqué présent : il n'a pas physiquement quitté la place.
    assert presence.get_status("v1") is PresenceStatus.IN
    assert parking.freed == []


def test_sortie_refusee_vehicule_non_present():
    vehicles = FakeVehiclesPort(
        {"CC-333-CC": VehicleInfo(vehicule_id="v_absent", type_vehicule=VehicleType(category=VehicleCategory.QUATRE_ROUES))}
    )
    presence = FakePresenceRepo()
    access_repo = FakeAccessRepo()
    parking = FakeParkingPort()
    pricing = FakePricingPort()
    payment = FakePaymentPort()
    use_case = make_use_case(vehicles, parking, pricing, payment, presence, access_repo)

    decision = use_case.execute("CC-333-CC", SORTIE_AT, SourceDetection.BORNE)

    assert decision.resultat is ResultatAutorisation.REFUSE
    assert decision.motif == "Véhicule non présent dans le parking"
    assert pricing.calls == []
    assert payment.calls == []
