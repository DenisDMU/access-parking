"""Schémas du mode multijoueur de la promenade (`/borne/promenade`).

Tout ce qui entre est borné : des nombres finis dans les limites du décor,
des couleurs au format `#rrggbb`, des mots courts en minuscules. Aucun texte
libre n'est accepté (pas de pseudo saisi, pas de message).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HEX32 = r"^[0-9a-f]{32}$"  # forme du jeton aléatoire tiré par le navigateur
COLOR = r"^#[0-9a-f]{6}$"
WORD = r"^[a-z]{1,12}$"


class PromenadeLook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top: str = Field(pattern=COLOR)
    pants: str = Field(pattern=COLOR)
    hair: str = Field(pattern=COLOR)
    skin: str = Field(pattern=COLOR)
    hat: str = Field(pattern=WORD)
    cut: str = Field(pattern=WORD)
    pet: str = Field(pattern=WORD)
    pack: bool
    # Ajoutés en 4.18 ; facultatifs pour les pages encore ouvertes sur l'ancienne version.
    outfit: str = Field(default="tshirt", pattern=WORD)
    bottom: str = Field(default="pants", pattern=WORD)
    extra: str = Field(default="none", pattern=WORD)
    balloon: str = Field(default="none", pattern=r"^(none|#[0-9a-f]{6})$")
    eyes: str = Field(default="ronds", pattern=WORD)


class PromenadeStateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(pattern=HEX32, description="Jeton aléatoire tiré par le navigateur")
    x: float = Field(ge=-5000, le=5000, allow_inf_nan=False)
    y: float = Field(ge=-50, le=200, allow_inf_nan=False)
    z: float = Field(ge=-5000, le=5000, allow_inf_nan=False)
    rot: float = Field(ge=-1000, le=1000, allow_inf_nan=False)
    speed: float = Field(ge=0, le=80, allow_inf_nan=False)
    look: PromenadeLook
    drive: str | None = Field(default=None, pattern=WORD, description="Véhicule conduit")
    emote: int | None = Field(default=None, ge=0, le=7, description="Salut choisi dans une liste")
    ride: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{10}$", description="Promeneur dont on est le passager"
    )
    stars: int = Field(default=0, ge=0, le=99, description="Nombre de succès obtenus")


class PromenadePlayerOut(BaseModel):
    id: str
    pseudo: str
    x: float
    y: float
    z: float
    rot: float
    speed: float
    look: PromenadeLook
    drive: str | None = None
    emote: int | None = None
    ride: str | None = None
    stars: int = 0


class PromenadeYouOut(BaseModel):
    id: str
    pseudo: str


class PromenadeDuelOut(BaseModel):
    """Un défi amical vu par un de ses deux joueurs."""

    id: str
    game: str
    role: str
    other: str
    status: str
    board: list[int]
    turn: bool
    mine: int | None = None
    theirs: int | None = None
    coin: int | None = None
    result: str | None = None


class PromenadeDuelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(pattern=HEX32)
    action: Literal["invite", "accept", "decline", "move"]
    target: str | None = Field(default=None, pattern=r"^[0-9a-f]{10}$")
    duel: str | None = Field(default=None, pattern=r"^[0-9a-f]{8}$")
    game: Literal["morpion", "pfc", "piece"] | None = None
    move: int | None = Field(default=None, ge=0, le=8)


class PromenadeDuelsOut(BaseModel):
    duels: list[PromenadeDuelOut]


class PromenadeStateOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    you: PromenadeYouOut
    players: list[PromenadePlayerOut]
    duels: list[PromenadeDuelOut] = []
    online: int
    next_ms: int = Field(alias="nextMs", description="Délai avant le prochain envoi")


class PromenadeWatchOut(BaseModel):
    players: list[PromenadePlayerOut]
    online: int


class PromenadeScoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(pattern=HEX32)
    game: str = Field(pattern=WORD)
    score: int = Field(ge=0, le=1000)


class PromenadeScoreLine(BaseModel):
    pseudo: str
    score: int


class PromenadeScoresOut(BaseModel):
    scores: dict[str, list[PromenadeScoreLine]]
    online: int
