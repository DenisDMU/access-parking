"""Test dédié (Definition of Done, section 15) :

  "Aucune plaque en clair stockée en base, publiée dans un événement,
  renvoyée par l'API, ou écrite dans un log — un test dédié vérifie
  qu'aucune table ne contient de valeur correspondant au format plaque."

Rejoue des entrées et sorties (autorisées, refusées, véhicule créé par
Vehicles, Vehicles en panne, plaque invalide) puis inspecte chaque réponse,
chaque table, les événements publiés et les logs.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import inspect, text

from tests.integration.conftest import AUTH_HEADERS

# Forme canonique (celle transmise à Vehicles), avec bornes de mot pour ne
# pas confondre avec un morceau d'UUID hexadécimal.
_CANONICAL = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b")
URL = "/api/v1/access/requests"

_SCENARIOS = [
    {"licensePlate": "AA-111-AA", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"licensePlate": "aa 111 aa", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    {"licensePlate": "FF-666-FF", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"licensePlate": "ZZ-999-ZZ", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"licensePlate": "ZZ-999-ZZ", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    {"licensePlate": "CC-333-CC", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    {"licensePlate": "YY-888-YY", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    # Plaques étrangères et ancien format français (4.3.0).
    {"licensePlate": "B-MW 1234", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"licensePlate": "BMW1234", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    {"licensePlate": "123 ABC 75", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    # Plaque italienne au format français (4.8.0).
    {
        "licensePlate": "AB 456 CD",
        "type": 1,
        "date": "2026-09-02T10:00:00Z",
        "source": 3,
        "country": "IT",
    },
]
_SENT = {scenario["licensePlate"] for scenario in _SCENARIOS} | {
    "AA-111-AA",
    "AB#123",
    "BMW1234",
    "123ABC75",
    "IT:AB456CD",  # identité envoyée à Vehicles pour la plaque italienne
    "AB456CD",
    "BO-111-RN",
    "BO-222-RN",
    "BO-333-RN",
    "DE:BO222RN",
}


class _Plate:
    """`PLATE.search(texte)` : vrai si le texte contient une plaque, sous sa
    forme canonique ou telle qu'envoyée (insensible à la casse)."""

    @staticmethod
    def search(value: str) -> bool:
        lowered = value.lower()
        return bool(_CANONICAL.search(value)) or any(p.lower() in lowered for p in _SENT)


PLATE = _Plate()


def test_no_plate_in_responses_tables_events_or_logs(client, caplog):
    with caplog.at_level(logging.DEBUG):
        for scenario in _SCENARIOS:
            response = client.post(URL, json=scenario, headers=AUTH_HEADERS)
            assert response.status_code == 200
            assert not PLATE.search(response.text), response.text

        invalid = client.post(
            URL, json={**_SCENARIOS[0], "licensePlate": "AB#123"}, headers=AUTH_HEADERS
        )
        assert invalid.status_code == 422
        assert "AB#123" not in invalid.text

        known = client.post(
            "/api/v1/access/vehicles/known",
            json={"licensePlate": "AA-111-AA"},
            headers=AUTH_HEADERS,
        )
        assert not PLATE.search(known.text)

        # Validation PMR par un agent, à la borne (4.10.0).
        pmr = {"licensePlate": "PM-321-RA", "type": 1, "vehicleType": "HANDICAPPED"}
        assert client.post("/api/v1/borne/passages", json=pmr).json()["result"] == 3
        validated = client.post(
            "/api/v1/borne/pmr-validation", json={"licensePlate": "PM-321-RA", "agentCode": "123"}
        )
        assert validated.json()["result"] == 1
        assert not PLATE.search(validated.text)

        # Borne publique : entrée et sortie, erreurs de saisie, code faux (revue du 25/11).
        for passage in (
            {"licensePlate": "BO-111-RN", "type": 1},
            {"licensePlate": "BO-111-RN", "type": 2},
        ):
            response = client.post("/api/v1/borne/passages", json=passage)
            assert response.status_code == 200 and not PLATE.search(response.text), response.text
        for path, body in (
            ("/api/v1/borne/passages", {"licensePlate": "BO-222-RN"}),
            ("/api/v1/borne/passages", {"licensePlate": "BO-222-RN", "type": 1, "country": "DE"}),
            ("/api/v1/borne/pmr-validation", {"licensePlate": "BO-222-RN"}),
            (
                "/api/v1/borne/pmr-validation",
                {"licensePlate": "BO-222-RN", "country": "DE", "agentCode": "1"},
            ),
        ):
            response = client.post(path, json=body)
            assert response.status_code == 422 and not PLATE.search(response.text), response.text
        for body in ({"type": 1}, {"licensePlate": "BO-222-RN", "country": "US"}):
            response = client.post("/api/v1/access/vehicles/known", json=body, headers=AUTH_HEADERS)
            assert response.status_code == 422 and not PLATE.search(response.text), response.text
        wrong = client.post(
            "/api/v1/borne/pmr-validation", json={"licensePlate": "BO-333-RN", "agentCode": "999"}
        )
        assert wrong.status_code == 403 and not PLATE.search(wrong.text)

        client.vehicles.available = False
        down = client.post(URL, json=_SCENARIOS[2], headers=AUTH_HEADERS)
        assert not PLATE.search(down.text)

    events = client.get("/api/v1/access/events", headers=AUTH_HEADERS)
    assert events.json(), "des événements doivent avoir été publiés"
    assert not PLATE.search(events.text)

    # Message et trace d'exception éventuelle.
    leaked_logs = [
        r.getMessage()
        for r in caplog.records
        if PLATE.search(r.getMessage()) or (r.exc_text and PLATE.search(r.exc_text))
    ]
    assert leaked_logs == []

    engine = client.test_engine
    offending: list[str] = []
    with engine.connect() as conn:
        for table_name in inspect(engine).get_table_names():
            # table_name vient de l'inspecteur SQLAlchemy (schéma), pas d'une saisie
            rows = conn.execute(text(f"SELECT * FROM {table_name}")).fetchall()  # noqa: S608
            offending += [
                f"{table_name}: {tuple(row)}" for row in rows if PLATE.search(str(tuple(row)))
            ]
    assert offending == [], f"Plaque(s) trouvée(s) en base : {offending}"
