"""Pays des plaques : vérification du format et identité envoyée à Vehicles.

Pourquoi : des pays différents utilisent le même format de plaque (l'Italie
utilise exactement le format français SIV `AB 123 CD`). Sans le pays, une
voiture italienne et une voiture française de même plaque seraient le même
véhicule chez Vehicles.

Identité envoyée à Vehicles (convention à partager avec Vehicles et Booking) :
- France (ou pays non précisé) : la plaque normalisée, comme avant
  (`AB-123-CD`, `123ABC75`) — les véhicules déjà enregistrés sont retrouvés ;
- autre pays : `<code ISO>:<plaque sans séparateur>` (`IT:AB123CD`,
  `DE:BMW1234`) — jamais confondue avec une plaque française.

Format vérifié pour les pays les plus fréquents ; pour les autres (et pour
« autre pays »), contrôle générique : 2 à 10 lettres ou chiffres.
"""

from __future__ import annotations

import re
from typing import Literal

CountryCode = Literal["FR", "IT", "ES", "DE", "BE", "CH", "GB", "NL", "LU", "PT", "XX"]

# Formats nationaux, plaque sans séparateur. `None` : contrôle générique.
_FORMATS: dict[str, re.Pattern[str] | None] = {
    # SIV (AB123CD) ou ancien format FNI (123ABC75, 1234AB2A, 123ABC971)
    "FR": re.compile(r"^(?:[A-Z]{2}\d{3}[A-Z]{2}|\d{1,4}[A-Z]{1,3}(?:\d{2}|2A|2B|97\d))$"),
    "IT": re.compile(r"^[A-Z]{2}\d{3}[A-Z]{2}$"),  # AB123CD
    "ES": re.compile(r"^\d{4}[A-Z]{3}$"),  # 1234BCD
    "DE": re.compile(r"^[A-Z]{2,5}\d{1,4}[EH]?$"),  # BMW1234, MAB123E
    "BE": re.compile(r"^\d[A-Z]{3}\d{3}$"),  # 1ABC234
    "CH": re.compile(r"^[A-Z]{2}\d{1,6}$"),  # ZH123456
    "GB": re.compile(r"^[A-Z]{2}\d{2}[A-Z]{3}$"),  # AB51ABC
    "NL": None,
    "LU": None,
    "PT": None,
    "XX": None,  # autre pays
}

COUNTRY_FORMAT_ERROR = "Format de plaque non reconnu pour ce pays"


def plate_identity(normalized_plate: str, country: str | None) -> str:
    """Identité du véhicule pour Vehicles, à partir d'une plaque déjà
    normalisée (`normalize_plate`). Lève `ValueError` (sans recopier la
    plaque) si le format ne correspond pas au pays."""

    if country is None:
        return normalized_plate  # comportement d'avant 4.8.0 (appels sans pays)
    compact = normalized_plate.replace("-", "")
    pattern = _FORMATS[country]
    if pattern is not None and not pattern.match(compact):
        raise ValueError(COUNTRY_FORMAT_ERROR)
    if country == "FR":
        return normalized_plate
    return f"{country}:{compact}"
