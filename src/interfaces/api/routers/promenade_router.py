"""Promenade multijoueur — `/borne/promenade`, sans clé.

Le plan 3D de la borne est public ; son mode « Promenade » montre les autres
visiteurs. Ces routes sont donc publiques elles aussi, et réduites au jeu :

- `POST /borne/promenade` : « je suis ici, habillé ainsi » → les autres
  promeneurs, le pseudo qu'Access m'a attribué, et le délai avant le
  prochain envoi (il s'allonge quand il y a du monde).
- `GET /borne/promenade` : les promeneurs du moment, pour qui regarde le
  plan sans se promener.
- `GET` et `POST /borne/promenade/scores` : meilleurs scores des mini-jeux.

Aucune donnée personnelle, aucun texte libre, rien en base : voir
`infrastructure/promenade_room.py`. Débit limité par adresse
(`RATE_LIMIT_PROMENADE`, large : une classe entière partage souvent la même
adresse). Interrupteurs : `BORNE_PUBLIC` et `PROMENADE_MULTI`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from src.infrastructure.config import get_settings
from src.infrastructure.promenade_room import (
    GAMES,
    DuelError,
    PromenadeRoom,
    RoomFullError,
    poll_interval_ms,
)
from src.interfaces.api.rate_limit import client_ip, limiter
from src.interfaces.api.schemas.error_schemas import ErrorOut
from src.interfaces.api.schemas.promenade_schemas import (
    PromenadeDuelIn,
    PromenadeDuelsOut,
    PromenadeScoreIn,
    PromenadeScoresOut,
    PromenadeStateIn,
    PromenadeStateOut,
    PromenadeWatchOut,
)

router = APIRouter(prefix="/borne/promenade", tags=["Promenade multijoueur"])

MULTI_OFF = "Promenade multijoueur désactivée"
ROOM_FULL = "Il y a déjà beaucoup de monde en promenade, réessayez dans un instant"
UNKNOWN_GAME = "Jeu inconnu ou score impossible"

_room = PromenadeRoom(capacity=get_settings().promenade_capacity)


def reset_room() -> None:
    """Vide le salon (tests)."""

    global _room
    _room = PromenadeRoom(capacity=get_settings().promenade_capacity)


def _require_multi() -> None:
    settings = get_settings()
    if not settings.borne_public or not settings.promenade_multi:
        raise HTTPException(status.HTTP_403_FORBIDDEN, MULTI_OFF)


_RESPONSES = {
    403: {"model": ErrorOut, "description": "Promenade multijoueur désactivée"},
    429: {"description": "Trop de demandes depuis cette adresse"},
}


@router.post(
    "",
    response_model=PromenadeStateOut,
    summary="Promenade : ma position, et les autres promeneurs (sans clé)",
    description=(
        "Le navigateur envoie la position et la tenue de son personnage ; "
        "Access répond avec les autres promeneurs vus ces dernières secondes, "
        "le pseudo attribué à ce visiteur et le délai avant le prochain envoi. "
        "Aucune donnée personnelle, aucun texte libre, rien n'est conservé."
    ),
    responses={**_RESPONSES, 503: {"model": ErrorOut, "description": "Salon complet"}},
)
@limiter.limit(lambda: get_settings().rate_limit_promenade, key_func=client_ip)
def promenade_state(request: Request, body: PromenadeStateIn) -> PromenadeStateOut:
    _require_multi()
    state = body.model_dump(exclude={"token"})
    try:
        me, others = _room.update(body.token, state)
    except RoomFullError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, ROOM_FULL) from None
    online = len(others) + 1
    return PromenadeStateOut(
        you={"id": me["id"], "pseudo": me["pseudo"]},
        players=others,
        duels=_room.duels_for(body.token),
        online=online,
        nextMs=poll_interval_ms(online),
    )


@router.get(
    "",
    response_model=PromenadeWatchOut,
    summary="Promenade : qui se promène en ce moment (sans clé)",
    description=(
        "Pour qui regarde le plan sans se promener (vue d'ensemble, dashboard) : "
        "les promeneurs du moment, avec leur pseudo attribué, leur position et "
        "leur tenue. Rien d'autre, et rien qui identifie quelqu'un."
    ),
    responses=_RESPONSES,
)
@limiter.limit(lambda: get_settings().rate_limit_promenade, key_func=client_ip)
def promenade_watch(request: Request) -> PromenadeWatchOut:
    _require_multi()
    players = _room.players()
    return PromenadeWatchOut(players=players, online=len(players))


@router.post(
    "/defi",
    response_model=PromenadeDuelsOut,
    summary="Promenade : défi amical entre deux promeneurs (sans clé)",
    description=(
        "Inviter un autre promeneur (`invite`), répondre (`accept`, `decline`) "
        "ou jouer un coup (`move`) au morpion, à pierre-feuille-ciseaux ou à "
        "pile ou face. Le serveur arbitre : il valide chaque coup, lance la "
        "pièce et ne montre le choix de l'autre qu'une fois la manche finie. "
        "Aucun texte libre ; un défi sans nouvelle est oublié."
    ),
    responses={**_RESPONSES, 409: {"model": ErrorOut, "description": "Action refusée"}},
)
@limiter.limit(lambda: get_settings().rate_limit_promenade, key_func=client_ip)
def promenade_duel(request: Request, body: PromenadeDuelIn) -> PromenadeDuelsOut:
    _require_multi()
    try:
        duels = _room.duel(body.token, body.action, body.target, body.duel, body.game, body.move)
    except DuelError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from None
    return PromenadeDuelsOut(duels=duels)


@router.get(
    "/scores",
    response_model=PromenadeScoresOut,
    summary="Promenade : meilleurs scores des mini-jeux (sans clé)",
    responses=_RESPONSES,
)
@limiter.limit(lambda: get_settings().rate_limit_promenade, key_func=client_ip)
def promenade_scores(request: Request) -> PromenadeScoresOut:
    _require_multi()
    return PromenadeScoresOut(scores=_room.scores(), online=_room.online())


@router.post(
    "/scores",
    response_model=PromenadeScoresOut,
    summary="Promenade : déclarer un score de mini-jeu (sans clé)",
    description=(
        "Le score est déclaré par le navigateur : c'est un jeu, pas un "
        f"classement officiel. Jeux connus : {', '.join(GAMES)}. Un score "
        "au-delà du maximum du jeu est refusé (422)."
    ),
    responses={**_RESPONSES, 422: {"description": UNKNOWN_GAME}},
)
@limiter.limit(lambda: get_settings().rate_limit_promenade, key_func=client_ip)
def promenade_submit_score(request: Request, body: PromenadeScoreIn) -> PromenadeScoresOut:
    _require_multi()
    try:
        _room.submit_score(body.token, body.game, body.score)
    except ValueError:
        raise HTTPException(422, UNKNOWN_GAME) from None
    return PromenadeScoresOut(scores=_room.scores(), online=_room.online())
