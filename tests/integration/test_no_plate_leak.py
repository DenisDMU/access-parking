"""Test dédié (Definition of Done, section 15) :

  "Aucune plaque en clair stockée en base, publiée dans un événement,
  renvoyée par l'API, ou écrite dans un log — un test dédié vérifie
  qu'aucune table ne contient de valeur correspondant au format plaque."

Exerce plusieurs plaques du registre mock (dont certaines déclenchent un
refus, une confirmation d'accessibilité, ou un rejet "véhicule inconnu")
puis inspecte directement chaque table SQLite.
"""

from __future__ import annotations

import re

from sqlalchemy import inspect, text

from tests.integration.conftest import AUTH_HEADERS

PLATE_PATTERN = re.compile(r"^[A-Z]{2}-\d{3}-[A-Z]{2}$")

_SCENARIOS = [
    {"plate": "AA-111-AA", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"plate": "AA-111-AA", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    {"plate": "FF-666-FF", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"plate": "HH-888-HH", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"plate": "HH-888-HH", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
    {"plate": "GG-777-GG", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"plate": "UN-000-KN", "type": 1, "date": "2026-09-02T10:00:00Z", "source": 3},
    {"plate": "CC-333-CC", "type": 2, "date": "2026-09-02T11:00:00Z", "source": 2},
]


def _contains_plate(value: str) -> bool:
    return bool(PLATE_PATTERN.search(value))


def test_no_raw_plate_in_any_table(client):
    for scenario in _SCENARIOS:
        response = client.post(
            "/api/v1/access/requests", json=scenario, headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        # ... et jamais renvoyée par l'API.
        assert not _contains_plate(str(response.json()))

    engine = client.test_engine
    inspector = inspect(engine)
    offending: list[str] = []

    with engine.connect() as conn:
        for table_name in inspector.get_table_names():
            rows = conn.execute(text(f"SELECT * FROM {table_name}")).fetchall()
            for row in rows:
                row_repr = str(tuple(row))
                if _contains_plate(row_repr):
                    offending.append(f"{table_name}: {row_repr}")

    assert offending == [], f"Plaque(s) trouvée(s) en base : {offending}"
