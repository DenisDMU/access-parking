"""Simulateur d'événements Access sur le bus partagé de l'équipe (CloudAMQP).

Publie à intervalles réguliers des événements d'entrée (`access.entry`) et
de sortie (`access.exit`) **au format exact des vrais événements d'Access**
(voir `src/infrastructure/external/rabbitmq_event_publisher.py`), pour que
les autres services puissent tester leur consommateur sans attendre de
vrais passages à la borne — et sans rien déclencher chez Parking, Pricing
ou Payment.

Les événements sont reconnaissables comme simulés :
- `vehicleId` préfixé par `sim-` ;
- `payload.simulated = true` ;
- propriété AMQP `app_id = "access-simulator"`.

Pour avoir des tickets cohérents sans attendre des heures, chaque entrée est
datée dans le passé (20 min à 5 h) ; la sortie, envoyée 30 s plus tard, porte
la vraie durée (`enteredAt`, `durationMinutes`) et un montant indicatif
calculé comme Pricing (1re heure gratuite, puis 0,75 € par quart d'heure).

Usage (lit `RABBITMQ_URL` / `RABBITMQ_EXCHANGE` comme Access, depuis
l'environnement ou `.env`) :

    python scripts/simulate_bus_events.py                      # toutes les 30 s, sans fin
    python scripts/simulate_bus_events.py --interval 10 --count 20
    python scripts/simulate_bus_events.py --dry-run            # affiche sans publier

Chaque cycle fait entrer un véhicule simulé, ou fait sortir un véhicule déjà
entré (avec un montant), en alternance, sur un parc de 5 véhicules. Ctrl+C
pour arrêter.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import ssl
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import certifi
import pika
from dotenv import load_dotenv

load_dotenv()

EXCHANGE_NAME = os.getenv("RABBITMQ_EXCHANGE", "microservice-event-bus")
VEHICLE_ENTERED, VEHICLE_EXITED = 1, 2

# Catégories de place telles qu'Access les publie (cf. http_parking_client.py)
PLACES = [
    ("STANDARD", {"category": 2, "isXl": False, "isElectric": False, "isHandicap": False}),
    ("ELECTRIC", {"category": 2, "isXl": False, "isElectric": True, "isHandicap": False}),
    ("XL", {"category": 2, "isXl": True, "isElectric": False, "isHandicap": False}),
    ("TWO_WHEELS", {"category": 1, "isXl": False, "isElectric": False, "isHandicap": False}),
]


def _connection_params(amqp_url: str) -> pika.URLParameters:
    params = pika.URLParameters(amqp_url)
    if amqp_url.startswith("amqps://"):
        params.ssl_options = pika.SSLOptions(ssl.create_default_context(cafile=certifi.where()))
    return params


def _event(event_type: int, payload: dict, created_at: datetime | None = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "requestId": str(uuid.uuid4()),
        "payload": {**payload, "simulated": True},
        "createdAt": (created_at or datetime.now(UTC)).isoformat(),
    }


def _indicative_amount(minutes: int) -> str:
    """Montant indicatif façon grille Pricing « standard sans réservation » :
    1re heure gratuite, puis 0,75 € par quart d'heure entamé."""

    quarters = max(math.ceil((minutes - 60) / 15), 0)
    return f"{quarters * 0.75:.2f}"


class Simulator:
    """Parc de véhicules simulés : entre / sort en alternance."""

    def __init__(self, fleet_size: int = 5) -> None:
        self._parked: dict[str, tuple[str, datetime]] = {}  # vehicleId -> (placeId, entrée)
        self._fleet = [f"sim-vehicle-{i}" for i in range(1, fleet_size + 1)]
        self._next_is_entry = True

    def next_event(self) -> tuple[str, dict]:
        outside = [v for v in self._fleet if v not in self._parked]
        do_entry = (self._next_is_entry and outside) or not self._parked
        self._next_is_entry = not self._next_is_entry
        if do_entry:
            vehicle_id = random.choice(outside)  # noqa: S311 - données de test
            category, place_type = random.choice(PLACES)  # noqa: S311
            reservation = random.random() < 0.3  # noqa: S311
            place_id = f"{category}:{'booking' if reservation else 'walkin'}"
            # Stationnement réaliste sans attendre des heures : l'entrée est
            # datée dans le passé (entre 20 min et 5 h), la sortie maintenant.
            entered_at = datetime.now(UTC) - timedelta(minutes=random.randint(20, 300))  # noqa: S311
            self._parked[vehicle_id] = (place_id, entered_at)
            return "access.entry", _event(
                VEHICLE_ENTERED,
                {
                    "vehicleId": vehicle_id,
                    "placeId": place_id,
                    "placeType": place_type,
                    "reservation": reservation,
                },
                created_at=entered_at,
            )
        vehicle_id = random.choice(list(self._parked))  # noqa: S311
        place_id, entered_at = self._parked.pop(vehicle_id)
        duration_min = max(math.ceil((datetime.now(UTC) - entered_at).total_seconds() / 60), 0)
        amount = _indicative_amount(duration_min)
        return "access.exit", _event(
            VEHICLE_EXITED,
            {
                "vehicleId": vehicle_id,
                "placeId": place_id,
                "amount": amount,
                "paymentId": None if amount == "0.00" else str(uuid.uuid4()),
                # Mêmes champs que les vrais événements d'Access (3.6.2+)
                "enteredAt": entered_at.isoformat(),
                "durationMinutes": duration_min,
            },
        )


def publish(amqp_url: str, routing_key: str, event: dict) -> None:
    connection = pika.BlockingConnection(_connection_params(amqp_url))
    try:
        channel = connection.channel()
        # L'exchange est administré par l'équipe : vérification passive seulement.
        channel.exchange_declare(exchange=EXCHANGE_NAME, passive=True)
        channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=routing_key,
            body=json.dumps(event).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json", delivery_mode=2, app_id="access-simulator"
            ),
        )
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interval", type=float, default=30.0, help="secondes entre 2 événements")
    parser.add_argument("--count", type=int, default=0, help="nombre d'événements (0 = sans fin)")
    parser.add_argument("--dry-run", action="store_true", help="affiche sans publier")
    args = parser.parse_args()

    amqp_url = os.getenv("RABBITMQ_URL", "")
    if not args.dry_run and not amqp_url:
        print("RABBITMQ_URL manquant (environnement ou .env).", file=sys.stderr)
        return 1

    simulator = Simulator()
    sent = 0
    print(f"Publication sur {EXCHANGE_NAME!r} toutes les {args.interval:g} s (Ctrl+C pour arrêter)")
    try:
        while args.count == 0 or sent < args.count:
            routing_key, event = simulator.next_event()
            if not args.dry_run:
                try:
                    publish(amqp_url, routing_key, event)
                except pika.exceptions.AMQPError as exc:
                    print(f"[✗] échec de publication ({exc!r}), nouvel essai au prochain cycle")
                    time.sleep(args.interval)
                    continue
            sent += 1
            p = event["payload"]
            print(
                f"[✓ {datetime.now():%H:%M:%S}] {routing_key:<13} {p['vehicleId']} "
                f"place={p['placeId']}" + (f" montant={p['amount']} €" if "amount" in p else ""),
                flush=True,
            )
            if args.count == 0 or sent < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    print(f"{sent} événement(s) publié(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
