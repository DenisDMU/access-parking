"""Tests d'intégration — promenade multijoueur (`/borne/promenade`, sans clé).

Routes publiques : elles ne doivent accepter que des valeurs bornées, ne
jamais rendre le jeton d'un autre, et se couper avec leurs interrupteurs.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.infrastructure.config import get_settings
from src.interfaces.api.routers import promenade_router

URL = "/api/v1/borne/promenade"
A, B = "a" * 32, "b" * 32
LOOK = {
    "top": "#1e66f5",
    "pants": "#27408b",
    "hair": "#3b2a20",
    "skin": "#f0c9a4",
    "hat": "none",
    "cut": "short",
    "pet": "chihuahua",
    "pack": True,
}


def state(token: str, **extra) -> dict:
    return {"token": token, "x": 1, "y": 0, "z": 2, "rot": 0, "speed": 0, "look": LOOK, **extra}


@pytest.fixture(autouse=True)
def _salon_vide():
    promenade_router.reset_room()
    yield
    promenade_router.reset_room()


def test_deux_promeneurs_se_voient_sans_cle(client):
    first = client.post(URL, json=state(A)).json()
    assert first["players"] == [] and first["online"] == 1
    assert first["you"]["pseudo"] and first["nextMs"] >= 300
    second = client.post(URL, json=state(B, x=40, emote=1, stars=3, drive="sedan")).json()
    assert [p["pseudo"] for p in second["players"]] == [first["you"]["pseudo"]]
    again = client.post(URL, json=state(A)).json()
    other = again["players"][0]
    assert other["x"] == 40 and other["emote"] == 1 and other["stars"] == 3
    assert other["drive"] == "sedan" and other["look"]["pet"] == "chihuahua"


def test_un_spectateur_voit_les_promeneurs_sans_en_devenir_un(client):
    assert client.get(URL).json() == {"players": [], "online": 0}
    client.post(URL, json=state(A, x=12))
    body = client.get(URL)
    assert body.json()["online"] == 1 and body.json()["players"][0]["x"] == 12
    assert A not in body.text and "token" not in body.text
    assert client.post(URL, json=state(B)).json()["online"] == 2  # le spectateur ne compte pas


def test_tenue_ballon_et_passager(client):
    """Champs ajoutés en 4.18 : facultatifs, bornés, et rendus aux autres."""

    first = client.post(URL, json=state(A)).json()
    look = {
        **LOOK,
        "outfit": "salopette",
        "bottom": "short",
        "extra": "lunettes",
        "balloon": "#ffd60a",
    }
    body = client.post(URL, json=state(B, look=look, ride=first["you"]["id"])).json()
    assert body["players"][0]["look"]["outfit"] == "tshirt"  # valeur par défaut d'un ancien client
    seen = client.post(URL, json=state(A)).json()["players"][0]
    assert seen["ride"] == first["you"]["id"] and seen["look"]["balloon"] == "#ffd60a"
    assert seen["look"]["outfit"] == "salopette" and seen["look"]["extra"] == "lunettes"
    for bad in (
        {"look": {**LOOK, "balloon": "rouge"}},
        {"ride": "pas-un-id"},
        {"look": {**LOOK, "outfit": "<b>"}},
    ):
        assert client.post(URL, json={**state(A), **bad}).status_code == 422


def test_le_jeton_ne_sort_jamais(client):
    client.post(URL, json=state(A))
    body = client.post(URL, json=state(B)).text
    assert A not in body and B not in body and "token" not in body


@pytest.mark.parametrize(
    "bad",
    [
        {"token": "pas-un-jeton"},
        {"x": 1e9},
        {"rot": "nan"},
        {"look": {**LOOK, "top": "rouge"}},
        {"look": {**LOOK, "pet": "<script>"}},
        {"look": {**LOOK, "pseudo": "Moi"}},  # aucun champ en plus
        {"emote": 99},
        {"pseudo": "Texte libre"},  # personne ne choisit son pseudo
    ],
)
def test_valeurs_hors_bornes_refusees(client, bad):
    assert client.post(URL, json={**state(A), **bad}).status_code == 422


def test_scores_des_mini_jeux(client):
    assert client.get(f"{URL}/scores").json()["scores"]["canards"] == []
    client.post(f"{URL}/scores", json={"token": A, "game": "canards", "score": 9})
    body = client.post(f"{URL}/scores", json={"token": B, "game": "canards", "score": 14}).json()
    assert [line["score"] for line in body["scores"]["canards"]] == [14, 9]
    assert A not in str(body) and B not in str(body)
    for bad in ({"game": "canards", "score": 999}, {"game": "tricherie", "score": 1}):
        assert client.post(f"{URL}/scores", json={"token": A, **bad}).status_code == 422


def test_interrupteurs(client, monkeypatch):
    for off in ({"promenade_multi": False}, {"borne_public": False}):
        settings = replace(get_settings(), **off)
        monkeypatch.setattr(promenade_router, "get_settings", lambda s=settings: s)
        assert client.post(URL, json=state(A)).status_code == 403
        assert client.get(f"{URL}/scores").status_code == 403


def test_salon_plein(client, monkeypatch):
    settings = replace(get_settings(), promenade_capacity=1)
    monkeypatch.setattr(promenade_router, "get_settings", lambda: settings)
    promenade_router.reset_room()
    assert client.post(URL, json=state(A)).status_code == 200
    assert client.post(URL, json=state(B)).status_code == 503
    assert client.post(URL, json=state(A)).status_code == 200
