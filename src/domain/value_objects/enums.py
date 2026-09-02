"""Enums métier (tinyint) du microservice Access.

Toutes les valeurs numériques sont figées par la spécification (section 6 du
cahier des charges) : ne pas les modifier sans mettre à jour le README et la
base existante, ces entiers sont persistés tels quels en base SQLite.
"""

from enum import IntEnum


class TypeDemande(IntEnum):
    """Type d'une Demande d'accès."""

    ENTREE = 1
    SORTIE = 2


class StatutDemande(IntEnum):
    """Statut d'une Demande d'accès.

    REJETEE est réservé au cas particulier "véhicule inconnu de Vehicles"
    (rejet avant même le déroulé complet des règles métier). Tout autre
    aboutissement (autorisé, refusé, confirmation requise) correspond à une
    demande normalement TRAITEE.
    """

    EN_COURS = 1
    TRAITEE = 2
    REJETEE = 3


class ResultatAutorisation(IntEnum):
    """Résultat d'une Autorisation d'accès."""

    AUTORISE = 1
    REFUSE = 2
    CONFIRMATION_REQUISE = 3


class TypeEvenement(IntEnum):
    """Type d'un Événement d'accès."""

    VEHICULE_ENTRE = 1
    VEHICULE_SORTI = 2
    ACCES_REFUSE = 3
    AUTRE = 4


class SourceDetection(IntEnum):
    """Source de détection à l'origine d'une Demande d'accès.

    Pour une sortie, BORNE et APP_MOBILE sont tous les deux valides (le
    conducteur peut avoir l'application ou non) : aucune restriction de
    source n'est appliquée selon le type de demande.
    """

    CAMERA = 1
    BORNE = 2
    LPR = 3
    APP_MOBILE = 4


class PresenceStatus(IntEnum):
    """Statut de présence d'un véhicule (table technique vehicle_presence)."""

    IN = 1
    OUT = 2


class VehicleCategory(IntEnum):
    """Catégorie "gabarit" d'un véhicule ou d'une place (2 roues / 4 roues)."""

    DEUX_ROUES = 1
    QUATRE_ROUES = 2
