"""Tests unitaires — gestion des secrets au démarrage (jalon 15)."""

import pytest

from src.infrastructure.config import InsecureConfigurationError, Settings, check_secrets


def _settings(api_key: str) -> Settings:
    return Settings(api_key=api_key)


def test_cle_par_defaut_refusee_en_production():
    with pytest.raises(InsecureConfigurationError):
        check_secrets(_settings("change-me"), production=True)


def test_cle_trop_courte_refusee_en_production():
    with pytest.raises(InsecureConfigurationError):
        check_secrets(_settings("court"), production=True)


def test_cle_par_defaut_toleree_en_local_avec_avertissement():
    assert check_secrets(_settings("change-me"), production=False) == [
        "API_KEY vaut la valeur par défaut 'change-me'"
    ]


def test_cle_solide_acceptee_en_production():
    assert check_secrets(_settings("x" * 44), production=True) == []
