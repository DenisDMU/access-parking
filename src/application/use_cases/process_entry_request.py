"""Use case `ProcessEntryRequest` — workflow "Entrée" + "Réservation".

Orchestration pure : ne dépend que des ports du domaine (aucune dépendance
vers `infrastructure`/`interfaces`), conformément à la règle de dépendance
stricte de l'architecture hexagonale.

Déroulé (section 8 de la spec) :
1. Réceptionner la plaque brute (valeur volatile, locale à cette méthode).
2. Analyse IA optionnelle (photo) → `ai_check`.
3. Résolution Vehicles (seul endroit où la plaque brute est utilisée).
4. Véhicule inconnu → rejet journalisé sans plaque, `stop`.
5. Règle de présence → refus si déjà `IN`.
6. Réservation (Booking) sinon attribution de place (Parking).
7. Règle de compatibilité véhicule/place → refus si incompatible.
8. Règle PMR → confirmation requise si justificatif manquant.
9. Sinon autorisation, occupation de la place, mise à jour de la présence.
10-13. Persistance + publication de l'événement + retour de la décision.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from src.domain.entities.autorisation_acces import AutorisationAcces
from src.domain.entities.demande_acces import DemandeAcces
from src.domain.entities.evenement_acces import EvenementAcces
from src.domain.ports.access_repository_port import AccessRepositoryPort
from src.domain.ports.ai_vision_port import AIVisionPort
from src.domain.ports.booking_service_port import BookingServicePort
from src.domain.ports.event_publisher_port import EventPublisherPort
from src.domain.ports.parking_service_port import ParkingServicePort
from src.domain.ports.vehicle_presence_repository_port import (
    VehiclePresenceRepositoryPort,
)
from src.domain.ports.vehicles_service_port import VehiclesServicePort
from src.domain.rules.presence_rule import can_enter
from src.domain.rules.pmr_rule import requires_pmr_confirmation
from src.domain.rules.vehicle_place_compatibility_rule import is_compatible
from src.domain.value_objects.dto import EntryDecision, PlaceType
from src.domain.value_objects.enums import (
    PresenceStatus,
    ResultatAutorisation,
    SourceDetection,
    StatutDemande,
    TypeDemande,
    TypeEvenement,
)


def _place_type_to_payload(place_type: PlaceType) -> dict:
    return {
        "category": int(place_type.category),
        "isXl": place_type.is_xl,
        "isElectric": place_type.is_electric,
        "isHandicap": place_type.is_handicap,
    }


class ProcessEntryRequest:
    def __init__(
        self,
        vehicles_port: VehiclesServicePort,
        booking_port: BookingServicePort,
        parking_port: ParkingServicePort,
        presence_repo: VehiclePresenceRepositoryPort,
        access_repo: AccessRepositoryPort,
        event_publisher: EventPublisherPort,
        ai_vision_port: AIVisionPort,
    ) -> None:
        self._vehicles_port = vehicles_port
        self._booking_port = booking_port
        self._parking_port = parking_port
        self._presence_repo = presence_repo
        self._access_repo = access_repo
        self._event_publisher = event_publisher
        self._ai_vision_port = ai_vision_port

    def execute(
        self,
        plaque: str,
        date: datetime,
        source: SourceDetection,
        photo: bytes | None = None,
    ) -> EntryDecision:
        demande_id = str(uuid4())

        ai_check: dict | None = None
        if photo is not None:
            ai_result = self._ai_vision_port.analyze(photo)
            ai_check = {
                "modelAI": ai_result.model_ai,
                "confidence": ai_result.confidence,
                "timestamp": ai_result.timestamp.isoformat(),
            }

        # Seul endroit de toute la codebase où la plaque brute est utilisée.
        vehicle_info = self._vehicles_port.get_vehicle_info(plaque)
        del plaque  # ne doit plus jamais être référencée ci-dessous

        if vehicle_info is None:
            return self._reject_unknown_vehicle(demande_id, date, source, ai_check)

        vehicule_id = vehicle_info.vehicule_id

        presence_status = self._presence_repo.get_status(vehicule_id)
        if not can_enter(presence_status):
            return self._refuse(
                demande_id=demande_id,
                vehicule_id=vehicule_id,
                date=date,
                source=source,
                ai_check=ai_check,
                motif="Véhicule déjà présent dans le parking",
            )

        reservation = self._booking_port.get_reservation(vehicule_id)
        if reservation is not None:
            place_type = reservation.type_place_reservee
            place_id = reservation.place_id
            if place_id is None:
                assignment = self._parking_port.request_place(vehicle_info.type_vehicule)
                if assignment is None:
                    return self._refuse(
                        demande_id=demande_id,
                        vehicule_id=vehicule_id,
                        date=date,
                        source=source,
                        ai_check=ai_check,
                        motif="Réservation trouvée mais aucune place disponible",
                    )
                place_id, place_type = assignment.place_id, assignment.place_type
        else:
            assignment = self._parking_port.request_place(vehicle_info.type_vehicule)
            if assignment is None:
                return self._refuse(
                    demande_id=demande_id,
                    vehicule_id=vehicule_id,
                    date=date,
                    source=source,
                    ai_check=ai_check,
                    motif="Aucune place disponible",
                )
            place_id, place_type = assignment.place_id, assignment.place_type

        compat_ok = is_compatible(vehicle_info.type_vehicule, place_type)
        if not compat_ok:
            return self._refuse(
                demande_id=demande_id,
                vehicule_id=vehicule_id,
                date=date,
                source=source,
                ai_check=ai_check,
                motif="Type de véhicule incompatible avec la place attribuée",
                controle_type_vehicule_ok=False,
            )

        if requires_pmr_confirmation(place_type, vehicle_info.justificatif_pmr):
            demande = DemandeAcces(
                id=demande_id,
                type=TypeDemande.ENTREE,
                date=date,
                source=source,
                statut=StatutDemande.TRAITEE,
                vehicule_id=vehicule_id,
                ai_check=ai_check,
            )
            autorisation = AutorisationAcces(
                id=str(uuid4()),
                demande_id=demande_id,
                resultat=ResultatAutorisation.CONFIRMATION_REQUISE,
                motif="Justificatif PMR requis pour une place handicapé",
                controle_type_vehicule_ok=True,
                controle_pmr_ok=False,
            )
            self._access_repo.save_demande(demande)
            self._access_repo.save_autorisation(autorisation)
            self._event_publisher.publish(
                EvenementAcces(
                    id=str(uuid4()),
                    type=TypeEvenement.AUTRE,
                    demande_id=demande_id,
                    payload={
                        "vehiculeId": vehicule_id,
                        "motif": autorisation.motif,
                        "placeId": place_id,
                        "placeType": _place_type_to_payload(place_type),
                    },
                    created_at=date,
                )
            )
            return EntryDecision(
                demande_id=demande_id,
                vehicule_id=vehicule_id,
                type=TypeDemande.ENTREE,
                statut=demande.statut,
                resultat=autorisation.resultat,
                motif=autorisation.motif,
                controle_type_vehicule_ok=True,
                controle_pmr_ok=False,
            )

        # Tout est valide : autorisation.
        self._parking_port.mark_place_occupied(place_id, vehicule_id)
        self._presence_repo.set_status(vehicule_id, PresenceStatus.IN, demande_id)

        controle_pmr_ok = True if place_type.is_handicap else None

        demande = DemandeAcces(
            id=demande_id,
            type=TypeDemande.ENTREE,
            date=date,
            source=source,
            statut=StatutDemande.TRAITEE,
            vehicule_id=vehicule_id,
            ai_check=ai_check,
        )
        autorisation = AutorisationAcces(
            id=str(uuid4()),
            demande_id=demande_id,
            resultat=ResultatAutorisation.AUTORISE,
            motif="Accès autorisé",
            controle_type_vehicule_ok=True,
            controle_pmr_ok=controle_pmr_ok,
        )
        self._access_repo.save_demande(demande)
        self._access_repo.save_autorisation(autorisation)
        self._event_publisher.publish(
            EvenementAcces(
                id=str(uuid4()),
                type=TypeEvenement.VEHICULE_ENTRE,
                demande_id=demande_id,
                payload={
                    "vehiculeId": vehicule_id,
                    "placeId": place_id,
                    "placeType": _place_type_to_payload(place_type),
                },
                created_at=date,
            )
        )

        return EntryDecision(
            demande_id=demande_id,
            vehicule_id=vehicule_id,
            type=TypeDemande.ENTREE,
            statut=demande.statut,
            resultat=autorisation.resultat,
            motif=autorisation.motif,
            controle_type_vehicule_ok=True,
            controle_pmr_ok=controle_pmr_ok,
        )

    def _reject_unknown_vehicle(
        self,
        demande_id: str,
        date: datetime,
        source: SourceDetection,
        ai_check: dict | None,
    ) -> EntryDecision:
        demande = DemandeAcces(
            id=demande_id,
            type=TypeDemande.ENTREE,
            date=date,
            source=source,
            statut=StatutDemande.REJETEE,
            vehicule_id=None,
            ai_check=ai_check,
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
        return EntryDecision(
            demande_id=demande_id,
            vehicule_id=None,
            type=TypeDemande.ENTREE,
            statut=demande.statut,
            resultat=autorisation.resultat,
            motif=motif,
            controle_type_vehicule_ok=None,
            controle_pmr_ok=None,
        )

    def _refuse(
        self,
        *,
        demande_id: str,
        vehicule_id: str,
        date: datetime,
        source: SourceDetection,
        ai_check: dict | None,
        motif: str,
        controle_type_vehicule_ok: bool | None = None,
    ) -> EntryDecision:
        demande = DemandeAcces(
            id=demande_id,
            type=TypeDemande.ENTREE,
            date=date,
            source=source,
            statut=StatutDemande.TRAITEE,
            vehicule_id=vehicule_id,
            ai_check=ai_check,
        )
        autorisation = AutorisationAcces(
            id=str(uuid4()),
            demande_id=demande_id,
            resultat=ResultatAutorisation.REFUSE,
            motif=motif,
            controle_type_vehicule_ok=controle_type_vehicule_ok,
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
        return EntryDecision(
            demande_id=demande_id,
            vehicule_id=vehicule_id,
            type=TypeDemande.ENTREE,
            statut=demande.statut,
            resultat=autorisation.resultat,
            motif=motif,
            controle_type_vehicule_ok=controle_type_vehicule_ok,
            controle_pmr_ok=None,
        )
