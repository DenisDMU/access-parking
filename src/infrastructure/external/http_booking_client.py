"""Client HTTP réel vers le service **Booking** de l'équipe.

Implémente `BookingServicePort`. Contrat lu sur le Swagger de Booking 0.4.0
(https://booking-api-vhy5.onrender.com/docs) le 2026-11-24, puis vérifié par
appels réels :

    GET {base_url}/reservations/active?vehicle_id=<pseudoId>&at=<ISO 8601 UTC>
    -> 200 toujours :
       { vehicle_id, at, valid: bool,
         reservations: [{ id (code à 6 chiffres), place_type, start_at, end_at }] }

- `valid` vaut true si une réservation **confirmée** (paiement accepté)
  couvre l'instant : `start_at <= at < end_at`, sans tolérance.
- `place_type` : mêmes codes que Parking (STANDARD, XL, ELECTRIC,
  HANDICAPPED, TWO_WHEELS).
- La réservation est **payée à l'avance** à Booking : à la sortie, Access ne
  facture que le dépassement éventuel après `end_at` (voir
  `ProcessExitRequest`).
- Pas d'authentification côté Booking au 2026-11-24.
- Booking ne gère aucune place nominative : `place_id=None`, Access demande
  alors la place à Parking dans le quota « booking ».

Toute panne (réseau, délai, 5xx, réponse inattendue) → `None` : l'entrée est
traitée comme une entrée sans réservation, jamais une erreur 500.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from src.domain.value_objects.dto import Reservation
from src.infrastructure.external.outgoing_http import COLD_START_TIMEOUT_S, outgoing_client
from src.infrastructure.external.place_categories import place_type_from_code

logger = logging.getLogger(__name__)

INFO_TIMEOUT_S = 5.0  # lectures d'affichage (places réservables), jamais bloquantes


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class HttpBookingClient:
    """Implémente `BookingServicePort` via un vrai appel HTTP à Booking."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = COLD_START_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
        api_key: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._transport = transport  # injecté par les tests (httpx.MockTransport)

    def get_reservation(self, vehicle_id: str, at: datetime | None = None) -> Reservation | None:
        at = (at or datetime.now(UTC)).astimezone(UTC)
        try:
            with outgoing_client(
                "booking", timeout=self._timeout_s, headers=self._headers, transport=self._transport
            ) as client:
                response = client.get(
                    f"{self._base_url}/reservations/active",
                    params={"vehicle_id": vehicle_id, "at": at.isoformat()},
                )
            response.raise_for_status()
            data = response.json()
            if not data.get("valid") or not data.get("reservations"):
                return None
            # Plusieurs réservations peuvent couvrir l'instant : la première.
            item = data["reservations"][0]
            return Reservation(
                id=str(item["id"]),
                vehicle_id=vehicle_id,
                reserved_place_type=place_type_from_code(str(item["place_type"])),
                start_date=_parse(item["start_at"]),
                end_date=_parse(item["end_at"]),
                place_id=None,
            )
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError) as exc:
            # Booking indisponible ou réponse inattendue : on poursuit comme
            # une entrée sans réservation (Parking attribue une place) plutôt
            # que de renvoyer une 500 — même principe que les autres clients.
            logger.warning(
                "Booking indisponible, entrée traitée sans réservation (%s)", type(exc).__name__
            )
            return None

    def free_capacity(self, place_type: str, at: datetime | None = None) -> int | None:
        """`GET /availability` sur l'heure pleine en cours : `min_free_capacity`.

        Sert au plan 3D (borne de réservation) : une information, jamais une
        décision. Délai court (`INFO_TIMEOUT_S`) : Booking endormi ne doit pas
        retenir un thread d'Access 45 s pour un simple affichage.
        """

        start = (at or datetime.now(UTC)).astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        try:
            with outgoing_client(
                "booking", timeout=INFO_TIMEOUT_S, headers=self._headers, transport=self._transport
            ) as client:
                response = client.get(
                    f"{self._base_url}/availability",
                    params={
                        "place_type": place_type,
                        "start_at": start.isoformat(),
                        "end_at": (start + timedelta(hours=1)).isoformat(),
                    },
                )
            response.raise_for_status()
            return max(0, int(response.json()["min_free_capacity"]))
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.info("Booking : places réservables indisponibles (%s)", type(exc).__name__)
            return None
