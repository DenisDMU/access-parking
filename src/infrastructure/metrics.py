"""Métriques Prometheus d'Access (jalon 13 — observabilité).

Les métriques **techniques** HTTP entrantes (requêtes, latences, codes par
route) sont produites par `prometheus-fastapi-instrumentator` (voir
`interfaces/api/main.py`). Ce module ajoute :

- les métriques **métier** : décisions d'entrée/sortie par résultat et par
  motif, paiements par issue, montants encaissés, véhicules présents ;
- les métriques d'**intégration** : appels sortants vers chaque service de
  l'équipe (issue, durée) et publication des événements.

Toutes les étiquettes ont un ensemble de valeurs **borné** (types, résultats,
motifs constants du code, noms de services) : jamais d'identifiant de
véhicule, de demande ni de correlation ID, pour ne pas exploser la
cardinalité ni exposer de donnée personnelle.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

ACCESS_DECISIONS = Counter(
    "access_decisions_total",
    "Décisions d'accès rendues, par type de demande et résultat",
    ["type", "result"],
)

ACCESS_REFUSALS = Counter(
    "access_refusals_total",
    "Refus et demandes de confirmation, par type de demande et motif",
    ["type", "reason"],
)

PAYMENTS = Counter(
    "access_payments_total",
    "Paiements demandés à Payment lors des sorties, par issue",
    ["outcome"],  # accepted | refused | unavailable
)

PAYMENT_AMOUNT_EUROS = Counter(
    "access_payment_amount_euros_total",
    "Montant total des paiements acceptés (euros)",
)

OUTGOING_REQUESTS = Counter(
    "access_outgoing_requests_total",
    "Appels HTTP sortants vers les autres microservices, par service et issue",
    ["service", "outcome"],  # outcome : 2xx | 3xx | 4xx | 5xx | error
)

OUTGOING_DURATION = Histogram(
    "access_outgoing_request_duration_seconds",
    "Durée des appels HTTP sortants, par service",
    ["service"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40),
)

EVENTS_PUBLISHED = Counter(
    "access_events_published_total",
    "Événements diffusés aux autres services, par canal, type et issue",
    ["channel", "event_type", "outcome"],  # outcome : ok | error
)

REQUEST_TYPE_LABEL = {1: "entry", 2: "exit"}
RESULT_LABEL = {1: "authorized", 2: "refused", 3: "confirmation_required"}
EVENT_TYPE_LABEL = {1: "vehicle_entered", 2: "vehicle_exited", 3: "access_refused", 4: "other"}


def record_decision(request_type: int, result: int, reason: str | None) -> None:
    type_label = REQUEST_TYPE_LABEL.get(int(request_type), "unknown")
    result_label = RESULT_LABEL.get(int(result), "unknown")
    ACCESS_DECISIONS.labels(type=type_label, result=result_label).inc()
    if result_label != "authorized":
        ACCESS_REFUSALS.labels(type=type_label, reason=reason or "inconnu").inc()


def status_outcome(status_code: int) -> str:
    return f"{status_code // 100}xx"


class PresenceCollector(Collector):
    """Jauge `access_vehicles_present`, calculée à chaque collecte.

    Lue directement en base (source de vérité d'Access) plutôt que tenue à
    jour en mémoire : reste juste même après un redémarrage du service.
    """

    def __init__(self, count_present: Callable[[], int]) -> None:
        self._count_present = count_present

    def collect(self) -> Iterator[GaugeMetricFamily]:
        gauge = GaugeMetricFamily(
            "access_vehicles_present", "Véhicules actuellement présents dans le parking"
        )
        try:
            gauge.add_metric([], self._count_present())
        except Exception:  # noqa: BLE001 - une base indisponible ne casse pas /metrics
            return
        yield gauge


_presence_collector: PresenceCollector | None = None


def register_presence_collector(count_present: Callable[[], int]) -> None:
    """Enregistre (une seule fois par process) la jauge des présences."""

    global _presence_collector
    if _presence_collector is not None:
        REGISTRY.unregister(_presence_collector)
    _presence_collector = PresenceCollector(count_present)
    REGISTRY.register(_presence_collector)
