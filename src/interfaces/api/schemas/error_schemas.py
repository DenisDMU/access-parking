"""Schéma d'erreur générique — aucune stack trace n'est jamais renvoyée."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorOut(BaseModel):
    detail: str = Field(examples=["Clé API manquante ou invalide"])
