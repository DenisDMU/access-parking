"""Système de logs (exigence commune à tous les microservices, section 1).

Ajoute une protection RGPD en profondeur (section 11) : un `logging.Filter`
masque toute sous-chaîne ressemblant à une plaque française
(`AB-123-CD`) dans le message final, au cas où une variable serait un jour
passée à un logger par erreur. Cette redondance ne remplace pas la
discipline de code (ne jamais passer `plate` à un logger) mais réduit le
risque en cas d'erreur humaine.
"""

from __future__ import annotations

import logging
import re

from src.infrastructure.config import get_settings

_PLATE_PATTERN = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b")


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
    handler = logging.StreamHandler()
    handler.addFilter(RedactPlateFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers = [handler]
