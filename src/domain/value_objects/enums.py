"""Enums métier (tinyint) du microservice Access.

Toutes les valeurs numériques sont figées par la spécification (section 6 du
cahier des charges) : ne pas les modifier sans mettre à jour le README et la
base existante, ces entiers sont persistés tels quels en base SQLite.

Noms en anglais (identifiants de code) ; correspondance avec les termes
français de la spec d'origine rappelée entre parenthèses pour traçabilité.
"""

from enum import IntEnum


class RequestType(IntEnum):
    """Type d'une demande d'accès (spec FR : "Demande d'accès" / "type")."""

    ENTRY = 1
    EXIT = 2


class RequestStatus(IntEnum):
    """Statut d'une demande d'accès (spec FR : "statut").

    REJECTED est réservé au cas particulier "véhicule inconnu de Vehicles"
    (rejet avant même le déroulé complet des règles métier). Tout autre
    aboutissement (autorisé, refusé, confirmation requise) correspond à une
    demande normalement PROCESSED.
    """

    IN_PROGRESS = 1
    PROCESSED = 2
    REJECTED = 3


class AuthorizationResult(IntEnum):
    """Résultat d'une autorisation d'accès (spec FR : "resultat")."""

    AUTHORIZED = 1
    REFUSED = 2
    CONFIRMATION_REQUIRED = 3


class EventType(IntEnum):
    """Type d'un événement d'accès (spec FR : "Événement d'accès")."""

    VEHICLE_ENTERED = 1
    VEHICLE_EXITED = 2
    ACCESS_REFUSED = 3
    OTHER = 4


class DetectionSource(IntEnum):
    """Source de détection à l'origine d'une demande d'accès (spec FR :
    "source" — CAMERA/BORNE/LPR/APP_MOBILE).

    Pour une sortie, TERMINAL et MOBILE_APP sont tous les deux valides (le
    conducteur peut avoir l'application ou non) : aucune restriction de
    source n'est appliquée selon le type de demande.
    """

    CAMERA = 1
    TERMINAL = 2
    LPR = 3
    MOBILE_APP = 4


class PresenceStatus(IntEnum):
    """Statut de présence d'un véhicule (table technique vehicle_presence)."""

    IN = 1
    OUT = 2


class VehicleCategory(IntEnum):
    """Catégorie "gabarit" d'un véhicule ou d'une place (2 roues / 4 roues)."""

    TWO_WHEELER = 1
    FOUR_WHEELER = 2
