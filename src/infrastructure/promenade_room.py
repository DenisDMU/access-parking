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
import secrets
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
    "paires": 100,
    "ballons": 60,
    "passage": 30,
    "olives": 60,
    "feu": 100,
    "creneau": 100,
}
BOARD_SIZE = 5
BOARD_KEEP = 50


# Défis amicaux entre deux promeneurs : morpion, pierre-feuille-ciseaux, pile ou face.
DUEL_GAMES = ("morpion", "pfc", "piece")
DUEL_TTL = 90.0  # un défi sans nouvelle depuis ce délai est oublié
DUEL_SHOWN = 15.0  # le résultat reste visible ce temps-là
_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


class RoomFullError(Exception):
    """Trop de promeneurs en même temps."""


class DuelError(Exception):
    """Action de défi refusée ; le message est fait pour être montré au joueur."""


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
        coin: Callable[[], int] = lambda: secrets.randbelow(2),
    ) -> None:
        self._ttl = ttl
        self._capacity = capacity
        self._clock = clock
        self._lock = threading.Lock()
        self._players: dict[str, dict] = {}
        self._seen: dict[str, float] = {}
        self._scores: dict[str, dict[str, tuple[int, str]]] = {game: {} for game in GAMES}
        self._coin = coin
        self._duels: dict[str, dict] = {}

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

    # --- Défis amicaux -----------------------------------------------------------

    def _prune_duels(self, now: float) -> None:
        for key, duel in list(self._duels.items()):
            age = now - duel["at"]
            gone = duel["a"] not in self._players or duel["b"] not in self._players
            if age > DUEL_TTL or (duel["status"] == "done" and age > DUEL_SHOWN) or gone:
                del self._duels[key]

    def _busy(self, pid: str) -> bool:
        return any(
            pid in (duel["a"], duel["b"]) and duel["status"] != "done"
            for duel in self._duels.values()
        )

    def duel(
        self,
        token: str,
        action: str,
        target: str | None = None,
        duel_id: str | None = None,
        game: str | None = None,
        move: int | None = None,
    ) -> list[dict]:
        """Inviter, accepter, refuser ou jouer un coup. Rend les défis du joueur."""

        pid, _ = identity(token)
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._prune_duels(now)
            if pid not in self._players:
                raise DuelError("Entrez d'abord en promenade.")
            if action == "invite":
                if game not in DUEL_GAMES or target is None or target == pid:
                    raise DuelError("Défi impossible.")
                if target not in self._players:
                    raise DuelError("Ce promeneur est parti.")
                if self._busy(pid) or self._busy(target):
                    raise DuelError("Un défi est déjà en cours.")
                picks = {"a": None, "b": None}
                if game == "piece":
                    if move not in (0, 1):
                        raise DuelError("Choisissez pile ou face.")
                    picks = {"a": move, "b": 1 - move}
                key = secrets.token_hex(4)
                self._duels[key] = {
                    "id": key, "game": game, "a": pid, "b": target, "status": "invite",
                    "board": [0] * 9, "turn": "a", "picks": picks, "winner": None,
                    "coin": None, "at": now,
                }  # fmt: skip
            else:
                duel = self._duels.get(duel_id or "")
                if duel is None or pid not in (duel["a"], duel["b"]):
                    raise DuelError("Ce défi n'existe plus.")
                side = "a" if pid == duel["a"] else "b"
                duel["at"] = now
                if action == "decline":
                    del self._duels[duel["id"]]
                elif action == "accept":
                    if duel["status"] != "invite" or side != "b":
                        raise DuelError("Ce défi n'attend pas votre réponse.")
                    duel["status"] = "play"
                    if duel["game"] == "piece":  # le serveur lance la pièce
                        duel["coin"] = self._coin()
                        duel["winner"] = "a" if duel["coin"] == duel["picks"]["a"] else "b"
                        duel["status"] = "done"
                elif action == "move":
                    self._play(duel, side, move)
                else:
                    raise DuelError("Action inconnue.")
            return self._duels_of(pid)

    @staticmethod
    def _play(duel: dict, side: str, move: int | None) -> None:
        if duel["status"] != "play" or move is None:
            raise DuelError("Ce n'est pas le moment de jouer.")
        if duel["game"] == "morpion":
            if duel["turn"] != side or not 0 <= move <= 8 or duel["board"][move]:
                raise DuelError("Coup impossible.")
            mark = 1 if side == "a" else 2
            duel["board"][move] = mark
            if any(all(duel["board"][i] == mark for i in line) for line in _LINES):
                duel["winner"], duel["status"] = side, "done"
            elif all(duel["board"]):
                duel["winner"], duel["status"] = "draw", "done"
            else:
                duel["turn"] = "b" if side == "a" else "a"
        elif duel["game"] == "pfc":
            if not 0 <= move <= 2 or duel["picks"][side] is not None:
                raise DuelError("Coup impossible.")
            duel["picks"][side] = move
            mine, theirs = duel["picks"]["a"], duel["picks"]["b"]
            if mine is not None and theirs is not None:  # pierre 0, feuille 1, ciseaux 2
                duel["winner"] = ("draw", "a", "b")[(mine - theirs) % 3]
                duel["status"] = "done"
        else:
            raise DuelError("Ce jeu ne se joue pas coup par coup.")

    def _duels_of(self, pid: str) -> list[dict]:
        views = []
        for duel in self._duels.values():
            if pid not in (duel["a"], duel["b"]):
                continue
            side = "a" if pid == duel["a"] else "b"
            other = "b" if side == "a" else "a"
            done = duel["status"] == "done"
            winner = duel["winner"]
            views.append(
                {
                    "id": duel["id"],
                    "game": duel["game"],
                    "role": side,
                    "other": self._players.get(duel[other], {}).get("pseudo", "un promeneur"),
                    "status": duel["status"],
                    "board": list(duel["board"]),
                    "turn": duel["status"] == "play" and duel["turn"] == side,
                    "mine": duel["picks"][side],
                    # Le choix de l'autre reste caché tant que la manche n'est pas finie.
                    "theirs": duel["picks"][other] if done or duel["game"] == "piece" else None,
                    "coin": duel["coin"],
                    "result": None
                    if not done
                    else "draw"
                    if winner == "draw"
                    else "win"
                    if winner == side
                    else "lose",
                }
            )
        return views

    def duels_for(self, token: str) -> list[dict]:
        pid, _ = identity(token)
        now = self._clock()
        with self._lock:
            self._prune_duels(now)
            return self._duels_of(pid)

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
