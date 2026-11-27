"""Filtre des chemins de route ajoutés à l'adresse d'un service de l'équipe.

Un chemin réglable (`VEHICLES_IDENTIFY_PATH`, `VEHICLES_LOOKUP_PATH`) ou lu
dans le Swagger de Vehicles est collé derrière l'adresse du service. Sans
filtre, « @autre.hote/x » ferait partir la plaque et la clé vers un autre
serveur (revue de sécurité du 25/11). Module sans dépendance : il est lu par
la configuration au démarrage comme par le client Vehicles.
"""

from __future__ import annotations

import re

# Un simple chemin (« /api/… ») : jamais un hôte, un « @ », une requête ou « .. ».
_SAFE_PATH = re.compile(r"^/(?!/)[A-Za-z0-9_./{}-]+$")


def safe_route_path(path: object) -> bool:
    return isinstance(path, str) and bool(_SAFE_PATH.match(path)) and ".." not in path
