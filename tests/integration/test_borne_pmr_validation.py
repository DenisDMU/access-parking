"""Tests d'intégration — validation PMR par un agent (`POST /borne/pmr-validation`).

Un conducteur déclare « Mobilité réduite » sans justificatif connu de
Vehicles : l'entrée attend un agent. L'agent vérifie la carte et saisit son
code sur la borne : le justificatif est enregistré chez Vehicles et l'entrée
est rejouée sur une place PMR. Aux passages suivants, plus besoin d'agent.
"""

from __future__ import annotations

from dataclasses import replace

from src.interfaces.api.routers import borne_router

PASSAGE = "/api/v1/borne/passages"
URL = "/api/v1/borne/pmr-validation"
PLATE = "PM-123-RA"


def _pmr_entry(client):
    return client.post(
        PASSAGE, json={"licensePlate": PLATE, "type": 1, "vehicleType": "HANDICAPPED"}
    )


def _validate(client, code="123", plate=PLATE, **extra):
    return client.post(URL, json={"licensePlate": plate, "agentCode": code, **extra})


def test_pmr_declare_sans_justificatif_attend_un_agent(client):
    body = _pmr_entry(client).json()
    assert body["result"] == 3 and body["vehicleIdentified"] is True


def test_agent_valide_entree_sur_place_pmr(client):
    _pmr_entry(client)
    response = _validate(client, plate="pm 123 ra")
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == 1
    assert body["placeType"]["isHandicap"] is True
    assert "vehicleId" not in body and "requestId" not in body
    assert PLATE not in response.text
    assert client.vehicles.confirmed  # justificatif enregistré chez Vehicles


def test_justificatif_retenu_pour_les_passages_suivants(client):
    _pmr_entry(client)
    _validate(client)
    assert client.post(PASSAGE, json={"licensePlate": PLATE, "type": 2}).json()["result"] == 1
    body = _pmr_entry(client).json()
    assert body["result"] == 1 and body["placeType"]["isHandicap"] is True


def test_code_agent_faux(client):
    _pmr_entry(client)
    response = _validate(client, code="999")
    assert response.status_code == 403
    assert response.json() == {"detail": "Code agent incorrect"}
    assert not client.vehicles.confirmed  # rien n'est enregistré


def test_code_agent_vide_refuse_par_la_validation(client):
    assert _validate(client, code="").status_code == 422


def test_code_agent_reglable(client, monkeypatch):
    settings = borne_router.get_settings()
    monkeypatch.setattr(borne_router, "get_settings", lambda: replace(settings, agent_code="4242"))
    _pmr_entry(client)
    assert _validate(client, code="123").status_code == 403
    assert _validate(client, code="4242").json()["result"] == 1


def test_vehicule_deja_pmr_pas_de_nouvel_enregistrement(client):
    _pmr_entry(client)
    _validate(client)
    client.post(PASSAGE, json={"licensePlate": PLATE, "type": 2})
    client.vehicles.confirmed.clear()
    assert _validate(client).json()["result"] == 1
    assert client.vehicles.confirmed == []


def test_vehicles_injoignable_vehicule_non_identifie(client):
    _pmr_entry(client)
    client.vehicles.available = False
    response = _validate(client)
    # Plus identifiable : le parcours normal rend « véhicule non identifié ».
    assert response.status_code == 200 and response.json()["vehicleIdentified"] is False


def test_vehicles_refuse_enregistrement_entree_pmr_quand_meme(client, monkeypatch):
    """Vehicles protège son `PUT` (24/11) : la carte vérifiée par l'agent vaut
    pour ce passage, seule la mémorisation est perdue."""

    _pmr_entry(client)
    monkeypatch.setattr(client.vehicles, "confirm_disability", lambda vehicle_id: False)
    response = _validate(client)
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == 1 and body["placeType"]["isHandicap"] is True
    assert PLATE not in response.text
    # Non mémorisé : au passage suivant, l'agent est de nouveau demandé.
    client.post(PASSAGE, json={"licensePlate": PLATE, "type": 2})
    assert _pmr_entry(client).json()["result"] == 3


def test_borne_publique_desactivee(client, monkeypatch):
    settings = borne_router.get_settings()
    monkeypatch.setattr(borne_router, "get_settings", lambda: replace(settings, borne_public=False))
    assert _validate(client).status_code == 403


def test_plaque_invalide_sans_la_plaque(client):
    response = _validate(client, plate="AB#123")
    assert response.status_code == 422 and "AB#123" not in response.text


def test_pays_pris_en_compte(client):
    client.post(
        PASSAGE,
        json={
            "licensePlate": "AB 123 CD",
            "type": 1,
            "vehicleType": "HANDICAPPED",
            "country": "IT",
        },
    )
    body = _validate(client, plate="AB 123 CD", country="IT").json()
    assert body["result"] == 1
    # La plaque française identique n'a pas été touchée.
    assert (
        "AB-123-CD" not in client.vehicles.registry
        or not client.vehicles.registry["AB-123-CD"].disability_permit
    )


# --- Revue de sécurité du 25/11 -------------------------------------------------------


def test_validation_refusee_sans_entree_pmr_en_attente(client):
    """Le code agent seul ne suffit pas : impossible de faire enregistrer
    n'importe quelle plaque comme PMR chez Vehicles."""

    response = _validate(client)
    assert response.status_code == 409
    assert "Mobilité réduite" in response.json()["detail"]
    assert client.vehicles.confirmed == []
    assert PLATE not in response.text


def test_validation_refusee_apres_le_delai(client, monkeypatch):
    from datetime import timedelta

    from src.application.use_cases import confirm_disability_by_agent as module

    _pmr_entry(client)
    monkeypatch.setattr(module, "PENDING_WINDOW", timedelta(seconds=-1))
    assert _validate(client).status_code == 409
    assert client.vehicles.confirmed == []


def test_entree_standard_ne_permet_pas_de_valider_pmr(client):
    client.post(PASSAGE, json={"licensePlate": PLATE, "type": 1, "vehicleType": "STANDARD"})
    client.post(PASSAGE, json={"licensePlate": PLATE, "type": 2})
    assert _validate(client).status_code == 409


def test_borne_tres_sollicitee_503(client, monkeypatch):
    import threading

    from src.interfaces.api.routers import borne_router

    full = threading.BoundedSemaphore(1)
    full.acquire()
    monkeypatch.setattr(borne_router, "_slots", full)
    for response in (
        client.post(PASSAGE, json={"licensePlate": PLATE, "type": 1}),
        _validate(client),
    ):
        assert response.status_code == 503
        assert response.json()["detail"] == borne_router.BORNE_BUSY
    full.release()
    assert client.post(PASSAGE, json={"licensePlate": PLATE, "type": 1}).status_code == 200


def test_place_rendue_meme_en_cas_d_erreur(client, monkeypatch):
    import threading

    from src.interfaces.api.routers import borne_router

    one = threading.BoundedSemaphore(1)
    monkeypatch.setattr(borne_router, "_slots", one)
    client.vehicles.available = False
    client.post(PASSAGE, json={"licensePlate": PLATE, "type": 1})
    assert one.acquire(blocking=False)  # la place a bien été rendue
    one.release()
