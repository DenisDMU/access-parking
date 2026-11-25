"""Tests unitaires — salon de la promenade multijoueur (en mémoire)."""

from __future__ import annotations

import pytest

from src.infrastructure.promenade_room import (
    BOARD_SIZE,
    GAMES,
    PromenadeRoom,
    RoomFullError,
    identity,
    poll_interval_ms,
)

A, B, C = "a" * 32, "b" * 32, "c" * 32
STATE = {"x": 1.0, "y": 0.0, "z": 2.0}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_pseudo_attribue_stable_et_sans_le_jeton():
    pid, pseudo = identity(A)
    assert identity(A) == (pid, pseudo)  # même jeton, même pseudo
    assert identity(B) != (pid, pseudo)
    assert A not in pid and len(pid) == 10  # identifiant public non réversible
    assert len(pseudo.split()) == 3 and pseudo.split()[-1].isdigit()


def test_chacun_voit_les_autres_mais_pas_lui_meme():
    room = PromenadeRoom()
    me, others = room.update(A, STATE)
    assert others == [] and me["pseudo"] == identity(A)[1]
    me_b, others_b = room.update(B, {**STATE, "x": 9.0})
    assert [p["id"] for p in others_b] == [identity(A)[0]]
    assert "token" not in others_b[0]
    assert room.online() == 2 and me_b["x"] == 9.0


def test_un_promeneur_silencieux_disparait():
    clock = Clock()
    room = PromenadeRoom(ttl=12, clock=clock)
    room.update(A, STATE)
    clock.now += 5
    room.update(B, STATE)
    clock.now += 8  # A n'a rien envoyé depuis 13 s
    _, others = room.update(B, STATE)
    assert others == [] and room.online() == 1


def test_salon_plein_refuse_les_nouveaux_pas_les_presents():
    room = PromenadeRoom(capacity=2)
    room.update(A, STATE)
    room.update(B, STATE)
    with pytest.raises(RoomFullError):
        room.update(C, STATE)
    room.update(A, STATE)  # un promeneur déjà là continue


def test_scores_meilleur_de_chacun_et_bornes():
    room = PromenadeRoom()
    room.submit_score(A, "canards", 7)
    room.submit_score(A, "canards", 3)  # moins bien : ignoré
    room.submit_score(B, "canards", 11)
    board = room.scores()["canards"]
    assert [line["score"] for line in board] == [11, 7]
    assert board[0]["pseudo"] == identity(B)[1]
    with pytest.raises(ValueError):
        room.submit_score(A, "canards", GAMES["canards"] + 1)
    with pytest.raises(ValueError):
        room.submit_score(A, "inconnu", 1)


def test_tableau_limite_aux_meilleurs():
    room = PromenadeRoom()
    for i in range(BOARD_SIZE + 4):
        room.submit_score(f"{i:032x}", "frites", i)
    assert len(room.scores()["frites"]) == BOARD_SIZE


def test_on_rafraichit_moins_souvent_quand_il_y_a_du_monde():
    assert poll_interval_ms(1) < poll_interval_ms(10) < poll_interval_ms(25) < poll_interval_ms(50)
