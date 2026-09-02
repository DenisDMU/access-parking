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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    port: int = int(os.getenv("PORT", "8000"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./access.db")
    api_key: str = os.getenv("API_KEY", "change-me")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: _split_urls(
            os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
        )
    )

    # Bascule GLOBALE (garde le comportement historique : tout mocké par
    # défaut). Chaque service a en plus sa PROPRE bascule ci-dessous
    # (VEHICLES_USE_MOCK, etc.) qui, si elle est définie, prend le dessus sur
    # USE_MOCKS — indispensable pour brancher les services de l'équipe un
    # par un au fur et à mesure qu'ils sont prêts, sans attendre que les 5
    # soient terminés (voir README section 5).
    use_mocks: bool = field(default_factory=lambda: _bool_env("USE_MOCKS", True))

    vehicles_service_url: str = os.getenv("VEHICLES_SERVICE_URL", "http://localhost:8001")
    booking_service_url: str = os.getenv("BOOKING_SERVICE_URL", "http://localhost:8002")
    parking_service_url: str = os.getenv("PARKING_SERVICE_URL", "http://localhost:8003")
    pricing_service_url: str = os.getenv("PRICING_SERVICE_URL", "http://localhost:8004")
    payment_service_url: str = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8005")

    vehicles_use_mock: bool = field(
        default_factory=lambda: _bool_env("VEHICLES_USE_MOCK", _bool_env("USE_MOCKS", True))
    )
    booking_use_mock: bool = field(
        default_factory=lambda: _bool_env("BOOKING_USE_MOCK", _bool_env("USE_MOCKS", True))
    )
    # Pas de parking_use_mock / pricing_use_mock : Pricing puis Parking sont
    # les premiers services réellement branchés (voir README section 5) —
    # leurs mocks ont été supprimés, plus de bascule possible pour eux
    # (toujours HttpParkingClient/HttpPricingClient). Les tests automatisés
    # utilisent des dependency overrides dédiés (FakeParkingPort,
    # FakePricingPort), pas ce toggle — voir tests/integration/conftest.py.
    payment_use_mock: bool = field(
        default_factory=lambda: _bool_env("PAYMENT_USE_MOCK", _bool_env("USE_MOCKS", True))
    )

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


_settings: Settings | None = None


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
