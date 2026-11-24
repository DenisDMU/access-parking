"""Tests unitaires — normalisation des plaques (toutes plaques, 4.3.0)."""

import pytest

from src.interfaces.api.schemas.access_request_schemas import normalize_plate


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        # Plaque française SIV : forme AB-123-CD conservée (déjà connue de Vehicles).
        ("AB-123-CD", "AB-123-CD"),
        ("ab 123 cd", "AB-123-CD"),
        ("AB123CD", "AB-123-CD"),
        # Ancien format français (FNI) et plaques étrangères : séparateurs retirés.
        ("123 ABC 75", "123ABC75"),
        ("1234 AB 975", "1234AB975"),
        ("b-mw 1234", "BMW1234"),
        ("AB51 ABC", "AB51ABC"),
        ("1-ABC-234", "1ABC234"),
        ("M.AB.1234", "MAB1234"),
        ("CD", "CD"),
        ("ABCDE12345", "ABCDE12345"),
    ],
)
def test_plaques_acceptees(saisie, attendu):
    assert normalize_plate(saisie) == attendu


@pytest.mark.parametrize("saisie", ["", "A", "ABCDEFGHIJK", "AB#123", "Ö-123", "AB_123", "   "])
def test_plaques_refusees_sans_recopier_la_valeur(saisie):
    with pytest.raises(ValueError) as exc:
        normalize_plate(saisie)
    if len(saisie.strip()) > 2:  # une lettre seule figure forcément dans le message
        assert saisie not in str(exc.value)
