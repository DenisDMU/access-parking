"""Petit script de diagnostic — écoute en direct le bus d'événements partagé
de l'équipe (CloudAMQP) et affiche chaque événement publié par Access (ou
par n'importe quel service utilisant la même routing key `access.*`).

Usage :
    source .venv/bin/activate
    python listen_event_bus.py

Puis, PENDANT que ce script tourne, lance un POST /access/requests (Postman
ou curl) : le payload complet s'affiche ici en direct. Ctrl+C pour arrêter.

Lit `RABBITMQ_URL` / `RABBITMQ_EXCHANGE` depuis `.env` — exactement les
mêmes variables que celles utilisées par Access lui-même
(`infrastructure/config.py`), rien à configurer en plus.

Queue de test temporaire et exclusive : créée à l'exécution, supprimée
automatiquement à l'arrêt (Ctrl+C) — ne laisse jamais rien traîner sur le
broker partagé de l'équipe.
"""

from __future__ import annotations

import json
import os
import ssl

import certifi
import pika
from dotenv import load_dotenv

load_dotenv()

AMQP_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
EXCHANGE_NAME = os.getenv("RABBITMQ_EXCHANGE", "microservice-event-bus")
ROUTING_KEY = "access.#"  # tout ce que publie Access (entry/exit/refused/other)


def _connection_params() -> pika.URLParameters:
    params = pika.URLParameters(AMQP_URL)
    if AMQP_URL.startswith("amqps://"):
        # Même approche que rabbitmq_event_publisher.py : magasin de
        # certificats certifi explicite, pour éviter un
        # CERTIFICATE_VERIFY_FAILED sur certains environnements.
        context = ssl.create_default_context(cafile=certifi.where())
        params.ssl_options = pika.SSLOptions(context)
    return params


def main() -> None:
    connection = pika.BlockingConnection(_connection_params())
    channel = connection.channel()

    # Vérifie juste que l'exchange existe — ne le (re)crée jamais (il est
    # administré ailleurs par l'équipe, cf. rabbitmq_event_publisher.py).
    channel.exchange_declare(exchange=EXCHANGE_NAME, passive=True)

    result = channel.queue_declare(queue="", exclusive=True, auto_delete=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange=EXCHANGE_NAME, queue=queue_name, routing_key=ROUTING_KEY)

    print(f"Connecté à l'exchange {EXCHANGE_NAME!r}.")
    print(f"En écoute sur routing_key={ROUTING_KEY!r} (queue temporaire {queue_name!r}).")
    print("Fais un POST /access/requests maintenant... (Ctrl+C pour arrêter)\n")

    def on_message(ch, method, properties, body):
        try:
            data = json.loads(body.decode("utf-8"))
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pretty = body.decode("utf-8", errors="replace")
        print(f"[✓ reçu | routing_key={method.routing_key}]\n{pretty}\n")

    channel.basic_consume(queue=queue_name, on_message_callback=on_message, auto_ack=True)

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("\nArrêt demandé, fermeture propre...")
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
