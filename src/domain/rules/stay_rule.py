"""Règle de cohérence du stationnement (cas limite du workflow "Sortie").

Une sortie ne peut pas être datée **avant** l'entrée correspondante : la
durée de stationnement serait négative, et le montant demandé à Pricing
n'aurait aucun sens. Sortie à la même minute que l'entrée : acceptée
(durée nulle, couverte par la gratuité éventuelle de Pricing).
"""

from __future__ import annotations

from datetime import datetime


def is_exit_date_valid(entry_date: datetime, exit_date: datetime) -> bool:
    """`True` si la sortie n'est pas antérieure à l'entrée."""

    return exit_date >= entry_date
