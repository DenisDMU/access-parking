"""Use case `ProcessExitRequest` — workflow "Sortie".

Déroulé (section 8 de la spec) :
1. Résolution Vehicles (seul endroit où la plaque brute est utilisée).
2. Création de la Demande d'accès (SORTIE).
3. Règle de présence → refus si le véhicule n'est pas `IN`.
4. Récupération du stationnement en cours (demande d'entrée associée).
5. Calcul du prix (Pricing).
6. Paiement (Payment) → refus si échec.
7. Autorisation, libération de la place.
8. Mise à jour de la présence (`OUT`).
9-11. Persistance + publication de l'événement + retour de la décision.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from src.domain.entities.autorisation_acces import AutorisationAcces
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.entities.evenement_acces import EvenementAcces
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.ports.payment_service_port import PaymentServicePort
from src.domain.ports.pricing_service_port import PricingServicePort
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.rules.presence_rule import can_exit
from src.domain.value_objects.dto import ExitDecision, PlaceType
from src.domain.value_objects.enums import (
    PresenceStatus,
    ResultatAutorisation,
    SourceDetection,
    StatutDemande,
    TypeDemande,
    TypeEvenement,
    VehicleCategory,
)


def _place_type_from_payload(payload: dict | None) -> PlaceType:
    """Reconstruit le `PlaceType` attribué à l'entrée depuis le payload de
    l'événement `VEHICULE_ENTRE` (le schéma SQL officiel ne persiste pas de
    colonne place/place_type dédiée — voir README, section "Écarts assumés
    par rapport à la spec")."""

    data = (payload or {}).get("placeType") or {}
    return PlaceType(
        category=VehicleCategory(data.get("category", VehicleCategory.QUATRE_ROUES)),
        is_xl=bool(data.get("isXl", False)),
        is_electric=bool(data.get("isElectric", False)),
        is_handicap=bool(data.get("isHandicap", False)),
    )


class ProcessExitRequest:
    def __init__(
        self,
        vehicles_port: VehiclesServicePort,
        parking_port: ParkingServicePort,
        pricing_port: PricingServicePort,
        payment_port: PaymentServicePort,
        presence_repo: VehiclePresenceRepositoryPort,
        access_repo: AccessRepositoryPort,
        event_publisher,
    ) -> None:
        self._vehicles_port = vehicles_port
        self._parking_port = parking_port
        self._pricing_port = pricing_port
        self._payment_port = payment_port
        self._presence_repo = presence_repo
        self._access_repo = access_repo
        self._event_publisher = event_publisher

    def execute(
        self,
        plaque: str,
        date: datetime,
        source: SourceDetection,
    ) -> ExitDecision:
        demande_id = str(uuid4())

        # Seul endroit de toute la codebase où la plaque brute est utilisée.
        vehicle_info = self._vehicles_port.get_vehicle_info(plaque)
        del plaque  # ne doit plus jamais être référencée ci-dessous

        if vehicle_info is None:
            return self._reject_unknown_vehicle(demande_id, date, source)

        vehicule_id = vehicle_info.vehicule_id

        presence_status = self._presence_repo.get_status(vehicule_id)
        if not can_exit(presence_status):
            return self._refuse(
                demande_id=demande_id,
                vehicule_id=vehicule_id,
                date=date,
                source=source,
                motif="Véhicule non présent dans le parking",
            )

        demande_id_courante = self._presence_repo.get_current_demande_id(vehicule_id)
        entry_demande = (
            self._access_repo.get_demande(demande_id_courante)
            if demande_id_courante
            else None
        )
        entry_evenement = (
            self._access_repo.get_evenement_by_demande(demande_id_courante)
            if demande_id_courante
            else None
        )
        date_entree = entry_demande.date if entry_demande else date
        place_id = (entry_evenement.payload.get("placeId") if entry_evenement else None)
        place_type = _place_type_from_payload(
            entry_evenement.payload if entry_evenement else None
        )

        montant = self._pricing_port.calculate_price(
            vehicule_id, date_entree, date, place_type
        )

        payment_result = self._payment_port.request_payment(vehicule_id, montant)
        if not payment_result.succes:
            return self._refuse(
                demande_id=demande_id,
                vehicule_id=vehicule_id,
                date=date,
                source=source,
                motif="Paiement refusé",
                montant=montant,
            )

        if place_id:
            self._parking_port.mark_place_free(place_id)
        self._presence_repo.set_status(vehicule_id, PresenceStatus.OUT, None)

        demande = DemandeAcces(
            id=demande_id,
            type=TypeDemande.SORTIE,
            date=date,
            source=source,
            statut=StatutDemande.TRAITEE,
            vehicule_id=vehicule_id,
        )
        autorisation = AutorisationAcces(
            id=str(uuid4()),
            demande_id=demande_id,
            resultat=ResultatAutorisation.AUTORISE,
            motif="Sortie autorisée",
            montant_paiement=montant,
        )
        self._access_repo.save_demande(demande)
        self._access_repo.save_autorisation(autorisation)
        self._event_publisher.publish(
            EvenementAcces(
                id=str(uuid4()),
                type=TypeEvenement.VEHICULE_SORTI,
                demande_id=demande_id,
                payload={
                    "vehiculeId": vehicule_id,
                    "placeId": place_id,
                    "montant": str(montant),
                },
                created_at=date,
            )
        )

        return ExitDecision(
            demande_id=demande_id,
            vehicule_id=vehicule_id,
            type=TypeDemande.SORTIE,
            statut=demande.statut,
            resultat=autorisation.resultat,
            motif=autorisation.motif,
            montant_paiement=montant,
        )

    def _reject_unknown_vehicle(
        self, demande_id: str, date: datetime, source: SourceDetection
    ) -> ExitDecision:
        demande = DemandeAcces(
            id=demande_id,
            type=TypeDemande.SORTIE,
            date=date,
            source=source,
            statut=StatutDemande.REJETEE,
            vehicule_id=None,
        )
        motif = "Véhicule inconnu de Vehicles — procédure alternative requise"
        autorisation = AutorisationAcces(
            id=str(uuid4()),
            demande_id=demande_id,
            resultat=ResultatAutorisation.CONFIRMATION_REQUISE,
            motif=motif,
        )
        self._access_repo.save_demande(demande)
        self._access_repo.save_autorisation(autorisation)
        self._event_publisher.publish(
            EvenementAcces(
                id=str(uuid4()),
                type=TypeEvenement.ACCES_REFUSE,
                demande_id=demande_id,
                payload={"vehiculeId": None, "motif": motif},
                created_at=date,
            )
        )
        return ExitDecision(
            demande_id=demande_id,
            vehicule_id=None,
            type=TypeDemande.SORTIE,
            statut=demande.statut,
            resultat=autorisation.resultat,
            motif=motif,
        )

    def _refuse(
        self,
        *,
        demande_id: str,
        vehicule_id: str,
        date: datetime,
        source: SourceDetection,
        motif: str,
        montant=None,
    ) -> ExitDecision:
        demande = DemandeAcces(
            id=demande_id,
            type=TypeDemande.SORTIE,
            date=date,
            source=source,
            statut=StatutDemande.TRAITEE,
            vehicule_id=vehicule_id,
        )
        autorisation = AutorisationAcces(
            id=str(uuid4()),
            demande_id=demande_id,
            resultat=ResultatAutorisation.REFUSE,
            motif=motif,
            montant_paiement=montant,
        )
        self._access_repo.save_demande(demande)
        self._access_repo.save_autorisation(autorisation)
        self._event_publisher.publish(
            EvenementAcces(
                id=str(uuid4()),
                type=TypeEvenement.ACCES_REFUSE,
                demande_id=demande_id,
                payload={"vehiculeId": vehicule_id, "motif": motif},
                created_at=date,
            )
        )
        return ExitDecision(
            demande_id=demande_id,
            vehicule_id=vehicule_id,
            type=TypeDemande.SORTIE,
            statut=demande.statut,
            resultat=autorisation.resultat,
            motif=motif,
            montant_paiement=montant,
        )
