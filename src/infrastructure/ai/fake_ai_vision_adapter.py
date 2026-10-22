"""Adaptateur fake déterministe pour la détection LPR / vision.

Ne renvoie jamais de plaque détectée en clair (section 6/7 de la spec) :
uniquement un score de confiance et le nom du modèle simulé.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.value_objects.dto import AICheckResult


class FakeAIVisionAdapter:
    """Implémente `AIVisionPort`."""

    def __init__(self, model_name: str = "fake-vision-v1") -> None:
        self._model_name = model_name

    def analyze(self, photo: bytes | None) -> AICheckResult:
        confidence = 0.95 if photo else 0.0
        return AICheckResult(
            ai_model=self._model_name,
            confidence=confidence,
            timestamp=datetime.now(UTC),
        )
