"""Tests unitaires — règle de cohérence du stationnement (`stay_rule`)."""

from datetime import UTC, datetime, timedelta

from src.domain.rules.stay_rule import is_exit_date_valid

ENTRY = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def test_sortie_apres_entree_valide():
    assert is_exit_date_valid(ENTRY, ENTRY + timedelta(hours=2))


def test_sortie_a_la_meme_heure_valide():
    # Durée nulle : cas limite accepté (gratuité éventuelle gérée par Pricing)
    assert is_exit_date_valid(ENTRY, ENTRY)


def test_sortie_avant_entree_invalide():
    assert not is_exit_date_valid(ENTRY, ENTRY - timedelta(minutes=1))
