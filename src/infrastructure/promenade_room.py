"""Salon de la promenade — qui se promène en ce moment dans le plan 3D.

Le mode « Promenade » du plan 3D est multijoueur : chaque visiteur voit les
autres dans le parking et dans le village. Ce module tient le salon, en
mémoire, dans le processus d'Access.

Ce qui est gardé, et pourquoi c'est sans risque :

- **Aucune donnée personnelle.** Un visiteur est un jeton aléatoire tiré par
  son navigateur. Le serveur en tire un identifiant public (début d'un
  SHA-256, non réversible) et un **pseudo attribué** (« Renard Malin 42 ») :
  personne ne saisit de texte, donc rien à modérer. Pas de discussion libre.
- **Rien n'est écrit sur disque ni en base.** Une position qui n'est plus
  rafraîchie disparaît au bout de quelques secondes (`ttl`).
- **Taille bornée.** Au plus `capacity` promeneurs à la fois (au-delà :
  `RoomFullError`), et un tableau des scores plafonné par jeu.

Les scores des mini-jeux sont déclarés par le navigateur : c'est un jeu, pas
un classement officiel. Ils sont bornés par jeu et vivent le temps du
processus (un redéploiement ou une mise en veille les remet à zéro).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable

NOUNS = (
    "Chihuahua", "Renard", "Shiba", "Lapin", "Chat", "Panda", "Castor", "Hérisson",
    "Pilote", "Copilote", "Écureuil", "Mouton", "Canard", "Koala", "Lynx", "Poney",
)  # fmt: skip
ADJECTIVES = (
    "Malin", "Zen", "Pressé", "Joyeux", "Curieux", "Prudent", "Rêveur", "Vaillant",
    "Futé", "Solaire", "Tranquille", "Rapide", "Discret", "Gourmand", "Chanceux", "Farceur",
)  # fmt: skip

# Score maximal plausible par mini-jeu (au-delà : refusé).
GAMES: dict[str, int] = {
    "canards": 60,
    "crepes": 100,
    "frites": 80,
    "barbe": 100,
    "tambour": 40,
    "plein": 100,
    "creneau": 100,
}
BOARD_SIZE = 5
BOARD_KEEP = 50


class RoomFullError(Exception):
    """Trop de promeneurs en même temps."""


def identity(token: str) -> tuple[str, str]:
    """Identifiant public et pseudo attribué, toujours les mêmes pour un jeton."""

    digest = hashlib.sha256(token.encode()).digest()
    pseudo = f"{NOUNS[digest[0] % len(NOUNS)]} {ADJECTIVES[digest[1] % len(ADJECTIVES)]}"
    return digest.hex()[:10], f"{pseudo} {10 + digest[2] % 90}"


class PromenadeRoom:
    def __init__(
        self,
        ttl: float = 12.0,
        capacity: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._capacity = capacity
        self._clock = clock
        self._lock = threading.Lock()
        self._players: dict[str, dict] = {}
        self._seen: dict[str, float] = {}
        self._scores: dict[str, dict[str, tuple[int, str]]] = {game: {} for game in GAMES}

    def _prune(self, now: float) -> None:
        for pid in [pid for pid, seen in self._seen.items() if now - seen > self._ttl]:
            self._seen.pop(pid, None)
            self._players.pop(pid, None)

    def update(self, token: str, state: dict) -> tuple[dict, list[dict]]:
        """Enregistre la position d'un promeneur, renvoie (lui, les autres)."""

        pid, pseudo = identity(token)
        now = self._clock()
        with self._lock:
            self._prune(now)
            if pid not in self._players and len(self._players) >= self._capacity:
                raise RoomFullError
            me = {"id": pid, "pseudo": pseudo, **state}
            self._players[pid] = me
            self._seen[pid] = now
            others = [player for other, player in self._players.items() if other != pid]
        return me, others

    def players(self) -> list[dict]:
        """Tous les promeneurs du moment (pour qui regarde le plan sans se promener)."""

        now = self._clock()
        with self._lock:
            self._prune(now)
            return list(self._players.values())

    def online(self) -> int:
        now = self._clock()
        with self._lock:
            self._prune(now)
            return len(self._players)

    def submit_score(self, token: str, game: str, score: int) -> None:
        """Garde le meilleur score de chacun (jeu connu, score plausible)."""

        if game not in GAMES or not 0 <= score <= GAMES[game]:
            raise ValueError(game)
        pid, pseudo = identity(token)
        with self._lock:
            board = self._scores[game]
            if pid not in board or score > board[pid][0]:
                board[pid] = (score, pseudo)
            if len(board) > BOARD_KEEP:
                keep = sorted(board.items(), key=lambda item: -item[1][0])[:BOARD_KEEP]
                self._scores[game] = dict(keep)

    def scores(self) -> dict[str, list[dict]]:
        """Les meilleurs scores par jeu, du plus haut au plus bas."""

        with self._lock:
            return {
                game: [
                    {"pseudo": pseudo, "score": score}
                    for score, pseudo in sorted(board.values(), key=lambda entry: -entry[0])[
                        :BOARD_SIZE
                    ]
                ]
                for game, board in self._scores.items()
            }


def poll_interval_ms(online: int) -> int:
    """Plus il y a de monde, moins chacun rafraîchit souvent (offre gratuite de Render)."""

    if online <= 6:
        return 450
    if online <= 16:
        return 700
    if online <= 30:
        return 1000
    return 1500
