"""Système de logs (exigence commune à tous les microservices, section 1).

- Chaque ligne porte un **correlation ID** (`[cid=...]`) : l'identifiant de
  la requête HTTP en cours, reçu dans l'en-tête `X-Correlation-ID` ou généré
  par Access (voir `interfaces/api/middleware.py`). Toutes les lignes d'une
  même demande d'accès (appel Vehicles, Parking, Pricing, Payment, décision,
  publication d'événement) se retrouvent donc avec un simple `grep`. Hors
  requête (démarrage...), `cid=-`.
- Protection RGPD en profondeur (section 11) : un `logging.Filter` masque
  toute sous-chaîne ressemblant à une plaque française (`AB-123-CD`) dans le
  message final, au cas où une variable serait un jour passée à un logger
  par erreur. Cette redondance ne remplace pas la discipline de code (ne
  jamais passer `plate` à un logger) mais réduit le risque en cas d'erreur
  humaine.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

from src.infrastructure.config import get_settings

_PLATE_PATTERN = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b")

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [cid=%(correlation_id)s] %(message)s"

# Correlation ID de la requête en cours (contexte asyncio/thread courant).
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_correlation_id() -> str:
    return correlation_id_var.get()


_base_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    """Chaque log créé porte `correlation_id`, quel que soit le handler qui
    le traite (console, outil de test, futur collecteur de logs)."""

    record = _base_record_factory(*args, **kwargs)
    record.correlation_id = correlation_id_var.get()
    return record


class RedactPlateFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - défense en profondeur
            return True
        if _PLATE_PATTERN.search(message):
            record.msg = _PLATE_PATTERN.sub("[PLATE_REDACTED]", message)
            record.args = ()
        return True


def configure_logging() -> None:
    settings = get_settings()
    logging.setLogRecordFactory(_record_factory)
    handler = logging.StreamHandler()
    handler.addFilter(RedactPlateFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers = [handler]
    # httpx logge chaque requête sortante en INFO (URL comprise) : redondant
    # avec nos propres logs d'appel, on ne garde que ses avertissements.
    logging.getLogger("httpx").setLevel(logging.WARNING)
