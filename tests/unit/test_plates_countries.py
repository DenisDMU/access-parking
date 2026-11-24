"""Tests unitaires — pays des plaques (4.8.0) : formats et identité Vehicles."""

import pytest

from src.interfaces.api.plates import plate_identity
from src.interfaces.api.schemas.access_request_schemas import normalize_plate


def _identity(raw: str, country):
    return plate_identity(normalize_plate(raw), country)


def test_meme_plaque_france_italie_deux_identites_distinctes():
    assert _identity("AB 123 CD", "FR") == "AB-123-CD"
    assert _identity("AB 123 CD", "IT") == "IT:AB123CD"


def test_france_garde_la_forme_d_avant():
    assert _identity("ab123cd", "FR") == "AB-123-CD"
    assert _identity("123 ABC 75", "FR") == "123ABC75"
    assert _identity("1234 AB 2A", "FR") == "1234AB2A"


def test_sans_pays_comportement_d_avant():
    assert _identity("b-mw 1234", None) == "BMW1234"
    assert _identity("ab 123 cd", None) == "AB-123-CD"


@pytest.mark.parametrize(
    ("raw", "country", "identity"),
    [
        ("1234 BCD", "ES", "ES:1234BCD"),
        ("B-MW 1234", "DE", "DE:BMW1234"),
        ("1-ABC-234", "BE", "BE:1ABC234"),
        ("ZH 123456", "CH", "CH:ZH123456"),
        ("AB51 ABC", "GB", "GB:AB51ABC"),
        ("AB-12-CD", "NL", "NL:AB12CD"),
        ("XYZ 99", "XX", "XX:XYZ99"),
    ],
)
def test_plaques_etrangeres(raw, country, identity):
    assert _identity(raw, country) == identity


@pytest.mark.parametrize(
    ("raw", "country"),
    [
        ("B-MW 1234", "FR"),  # allemande déclarée française
        ("1234 BCD", "IT"),  # espagnole déclarée italienne
        ("AB 123 CD", "ES"),
        ("AB123", "GB"),
    ],
)
def test_format_refuse_sans_recopier_la_plaque(raw, country):
    with pytest.raises(ValueError) as exc:
        _identity(raw, country)
    assert normalize_plate(raw) not in str(exc.value)
