"""Schéma d'erreur générique — aucune stack trace n'est jamais renvoyée."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    detail: str = Field(examples=["Clé API manquante ou invalide"])
    correlation_id: str | None = Field(
        default=None,
        alias="correlationId",
        description="Présent sur les erreurs 500 : à communiquer pour retrouver les logs.",
    )
