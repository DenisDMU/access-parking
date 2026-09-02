"""Port de détection LPR / vision (simulé pour le MVP)."""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.dto import AICheckResult


class AIVisionPort(Protocol):
    def analyze(self, photo: bytes | None) -> AICheckResult:
        """Analyse une photo. Ne renvoie jamais de plaque détectée en clair."""
        ...
