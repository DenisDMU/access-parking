"""Configuration centralisée du service, lue depuis l'environnement (.env).

Fichier ajouté par rapport à l'arborescence indicative de la spec (section
4) : un point unique de lecture des variables d'environnement (section 12)
évite de disperser des `os.environ.get(...)` dans `deps.py` et les
adaptateurs. Reste dans `infrastructure`, ne fuit pas vers `domain`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _split_urls(raw: str) -> list[str]:
    return [url.strip() for url in raw.split(",") if url.strip()]


BOOKING_DEFAULT_URL = "https://booking-api-vhy5.onrender.com"


def _booking_service_url() -> str:
    """URL de Booking. Sur Render, une valeur locale (`localhost`, héritée du
    blueprint d'avant la mise en service de Booking) est ignorée au profit
    du vrai service : sinon Access chercherait les réservations sur sa
    propre machine et n'en trouverait jamais."""

    url = os.getenv("BOOKING_SERVICE_URL", "").strip()
    on_render = os.getenv("RENDER", "").lower() == "true"
    if not url or (on_render and ("localhost" in url or "127.0.0.1" in url)):
        return BOOKING_DEFAULT_URL
    return url


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    port: int = int(os.getenv("PORT", "8000"))
    # `or` : une variable définie mais vide (Render, sync: false) retombe sur SQLite.
    database_url: str = os.getenv("DATABASE_URL") or "sqlite:///./access.db"
    api_key: str = os.getenv("API_KEY", "change-me")  # voir check_secrets()
    # Clé des bornes client (écran public) : elle ne permet QUE de faire passer
    # un véhicule (`POST /access/requests`), jamais de consulter l'historique,
    # les présences, les événements ou les métriques. Vide = pas de clé borne
    # (seule API_KEY est acceptée partout).
    borne_api_key: str = os.getenv("BORNE_API_KEY", "")
    # Jeton de lecture des métriques : il ne permet QUE de lire `GET /metrics`
    # (le Prometheus qui supervise Access). Vide = seule API_KEY lit les métriques.
    metrics_token: str = os.getenv("METRICS_TOKEN", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    # SHA du commit déployé, fourni automatiquement par Render à chaque
    # build — permet de prouver quel code tourne réellement en ligne
    # (exposé dans /health). "local" hors Render.
    git_commit: str = os.getenv("RENDER_GIT_COMMIT", "local")
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: _split_urls(
            os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
        )
    )

    vehicles_service_url: str = os.getenv("VEHICLES_SERVICE_URL", "http://localhost:8001")
    booking_service_url: str = field(default_factory=_booking_service_url)
    parking_service_url: str = os.getenv("PARKING_SERVICE_URL", "http://localhost:8003")
    pricing_service_url: str = os.getenv("PRICING_SERVICE_URL", "http://localhost:8004")
    payment_service_url: str = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8005")

    booking_use_mock: bool = field(
        # Booking est réel depuis le 24/11 : seul BOOKING_USE_MOCK=true le
        # simule encore (USE_MOCKS, ancienne bascule globale, n'a plus d'effet).
        default_factory=lambda: _bool_env("BOOKING_USE_MOCK", False)
    )
    # Pas de parking_use_mock / pricing_use_mock (ni payment_use_mock, voir
    # plus bas) : Pricing puis Parking sont les premiers services réellement branchés (voir README section 5) —
    # leurs mocks ont été supprimés, plus de bascule possible pour eux
    # (toujours HttpParkingClient/HttpPricingClient). Les tests automatisés
    # utilisent des dependency overrides dédiés (FakeParkingPort,
    # FakePricingPort), pas ce toggle — voir tests/integration/conftest.py.
    # Payment puis Vehicles sont branchés à leur tour (mocks supprimés) : pas
    # de bascule.
    # Clé fournie en privé par l'équipe Payment ; vide = pas d'en-tête
    # X-API-Key envoyé (tant que Payment n'a pas activé son authentification).
    payment_api_key: str = os.getenv("PAYMENT_API_KEY", "")
    # Même principe pour les autres services : clé envoyée dans X-API-Key si
    # elle est renseignée. Parking l'exige depuis le 2026-11-18.
    parking_api_key: str = os.getenv("PARKING_API_KEY", "")
    pricing_api_key: str = os.getenv("PRICING_API_KEY", "")
    vehicles_api_key: str = os.getenv("VEHICLES_API_KEY", "")
    # Booking l'exige depuis sa version 2.x (constaté le 2026-11-27).
    booking_api_key: str = os.getenv("BOOKING_API_KEY", "")
    # Routes de Vehicles (renommées deux fois le 24/11) : réglables dans
    # Render pour suivre un futur changement sans toucher au code.
    # `{plate}` est remplacé par la plaque (encodée).
    # `{vehicleId}` : consultation par identifiant après `identify` (contrat du
    # 24/11 au soir) ; `{plate}` : ancien contrat, consultation par plaque.
    vehicles_lookup_path: str = os.getenv("VEHICLES_LOOKUP_PATH", "/api/vehicle/{vehicleId}")
    vehicles_identify_path: str = os.getenv("VEHICLES_IDENTIFY_PATH", "/api/vehicle/create")

    ai_model_name: str = os.getenv("AI_MODEL_NAME", "fake-vision-v1")

    event_subscribers_urls: list[str] = field(
        default_factory=lambda: _split_urls(os.getenv("EVENT_SUBSCRIBERS_URLS", ""))
    )
    event_publish_timeout_ms: int = int(os.getenv("EVENT_PUBLISH_TIMEOUT_MS", "1000"))

    # "webhook" (fan-out HTTP, par défaut, cf. section 3 point 3 de la spec)
    # ou "rabbitmq" (voir infrastructure/external/rabbitmq_event_publisher.py).
    event_publisher: str = os.getenv("EVENT_PUBLISHER", "webhook")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
    # Exchange partagé de l'équipe (bus d'événements commun à tous les
    # microservices) — chacun publie sous sa propre routing key
    # (access.entry, access.exit, ... pour Access) sur le même exchange.
    rabbitmq_exchange: str = os.getenv("RABBITMQ_EXCHANGE", "microservice-event-bus")

    rate_limit_access_requests: str = os.getenv("RATE_LIMIT_ACCESS_REQUESTS", "20/minute")

    # Borne publique : le lien /borne s'ouvre pour tout le monde, sans clé, avec
    # le plan 3D et la promenade (routes publiques en lecture, débit limité par
    # adresse). false = tout ferme, la borne exige sa clé (BORNE_API_KEY).
    borne_public: bool = field(default_factory=lambda: _bool_env("BORNE_PUBLIC", True))
    # Passage d'un véhicule sans clé (POST /borne/passages, jalon 15 : un
    # endpoint métier ne doit pas être accessible librement). false par
    # défaut : seule une borne mise en service avec sa clé fait entrer ou
    # sortir un véhicule. true rouvre le passage public (démonstration).
    borne_passages_public: bool = field(
        default_factory=lambda: _bool_env("BORNE_PASSAGES_PUBLIC", False)
    )
    rate_limit_borne: str = os.getenv("RATE_LIMIT_BORNE", "10/minute")
    # Réveil des services de l'équipe (offre gratuite de Render, voir
    # infrastructure/external/warm_up.py). `false` : aucun réveil envoyé.
    warm_up_services: bool = field(default_factory=lambda: _bool_env("WARM_UP_SERVICES", True))
    # Occupation publique pour le plan 3D de la borne : débit par adresse, et
    # durée pendant laquelle une réponse de Parking est resservie telle quelle
    # (Parking est sur l'offre gratuite de Render : jamais sollicité par visiteur).
    # Passages traités en même temps par la borne publique (au-delà : 503,
    # « réessayez »). Chaque passage peut attendre 45 s un service de l'équipe
    # endormi : sans plafond, quelques visiteurs suffiraient à occuper tous
    # les threads d'Access (40), /health compris.
    borne_max_concurrent: int = int(os.getenv("BORNE_MAX_CONCURRENT", "8"))
    rate_limit_borne_parking: str = os.getenv("RATE_LIMIT_BORNE_PARKING", "30/minute")
    borne_parking_cache_s: float = float(os.getenv("BORNE_PARKING_CACHE_S", "10"))
    # Promenade multijoueur du plan 3D (routes publiques /borne/promenade) :
    # interrupteur, promeneurs en même temps, débit par adresse (large : une
    # classe entière partage souvent la même adresse).
    promenade_multi: bool = field(default_factory=lambda: _bool_env("PROMENADE_MULTI", True))
    promenade_capacity: int = int(os.getenv("PROMENADE_CAPACITY", "60"))
    rate_limit_promenade: str = os.getenv("RATE_LIMIT_PROMENADE", "2400/minute")
    # Code saisi par l'agent sur la borne pour valider un PMR (carte mobilité
    # inclusion vérifiée). Volontairement simple pour la démonstration.
    agent_code: str = os.getenv("AGENT_CODE", "123")


_settings: Settings | None = None


DEFAULT_API_KEY = "change-me"
MIN_API_KEY_LENGTH = 16


class InsecureConfigurationError(RuntimeError):
    """Configuration refusée au démarrage (jalon 15 — gestion des secrets)."""


def check_secrets(settings: Settings, *, production: bool) -> list[str]:
    """Vérifie les secrets au démarrage.

    En production (Render définit `RENDER=true`), une clé API par défaut ou
    trop courte **empêche le démarrage** : mieux vaut un déploiement en échec
    qu'une API ouverte avec `change-me`. Même refus si la clé d'un service de
    l'équipe partirait vers une adresse qui n'est pas en https. En local,
    simple avertissement (renvoyé à l'appelant pour être loggé).
    """

    problems = []
    if settings.api_key == DEFAULT_API_KEY:
        problems.append("API_KEY vaut la valeur par défaut 'change-me'")
    elif len(settings.api_key) < MIN_API_KEY_LENGTH:
        problems.append(f"API_KEY fait moins de {MIN_API_KEY_LENGTH} caractères")
    if settings.borne_api_key:
        if len(settings.borne_api_key) < MIN_API_KEY_LENGTH:
            problems.append(f"BORNE_API_KEY fait moins de {MIN_API_KEY_LENGTH} caractères")
        elif settings.borne_api_key == settings.api_key:
            problems.append("BORNE_API_KEY doit être différente d'API_KEY")
    if settings.metrics_token:
        if len(settings.metrics_token) < MIN_API_KEY_LENGTH:
            problems.append(f"METRICS_TOKEN fait moins de {MIN_API_KEY_LENGTH} caractères")
        elif settings.metrics_token in (settings.api_key, settings.borne_api_key):
            problems.append("METRICS_TOKEN doit être différent d'API_KEY et de BORNE_API_KEY")
    problems += _keys_sent_in_clear(settings)
    if problems and production:
        raise InsecureConfigurationError("; ".join(problems))
    return problems


def _keys_sent_in_clear(settings: Settings) -> list[str]:
    """Une clé d'un service de l'équipe suit l'adresse de ce service : si
    l'adresse n'est pas en `https://`, la clé part en clair à chaque appel
    (une faute de frappe dans Render suffit). Sans clé renseignée, rien à
    protéger : l'adresse n'est pas contrôlée."""

    services = [
        ("VEHICLES", settings.vehicles_service_url, settings.vehicles_api_key),
        ("PARKING", settings.parking_service_url, settings.parking_api_key),
        ("PRICING", settings.pricing_service_url, settings.pricing_api_key),
        ("PAYMENT", settings.payment_service_url, settings.payment_api_key),
    ]
    if not settings.booking_use_mock:
        services.append(("BOOKING", settings.booking_service_url, settings.booking_api_key))
    return [
        f"{name}_SERVICE_URL n'est pas en https alors que {name}_API_KEY est renseignée"
        for name, url, key in services
        if key and not url.strip().lower().startswith("https://")
    ]


def is_production() -> bool:
    return os.getenv("RENDER", "").lower() == "true"


def get_settings() -> Settings:
    """Singleton simple — relit l'environnement une seule fois par process.

    Les tests qui ont besoin d'une configuration différente peuvent appeler
    `reset_settings_cache()` après avoir modifié `os.environ`.
    """

    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    global _settings
    _settings = None
