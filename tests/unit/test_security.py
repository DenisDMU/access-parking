"""Tests unitaires — gestion des secrets au démarrage (jalon 15)."""

import pytest

from src.infrastructure.config import InsecureConfigurationError, Settings, check_secrets


def _settings(api_key: str, borne_api_key: str = "") -> Settings:
    return Settings(api_key=api_key, borne_api_key=borne_api_key)


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


def test_cle_borne_trop_courte_refusee_en_production():
    with pytest.raises(InsecureConfigurationError, match="BORNE_API_KEY"):
        check_secrets(_settings("x" * 44, borne_api_key="court"), production=True)


def test_cle_borne_identique_a_la_cle_admin_refusee():
    with pytest.raises(InsecureConfigurationError, match="différente"):
        check_secrets(_settings("x" * 44, borne_api_key="x" * 44), production=True)


def test_cle_borne_absente_ou_solide_acceptee():
    assert check_secrets(_settings("x" * 44), production=True) == []
    assert check_secrets(_settings("x" * 44, borne_api_key="b" * 32), production=True) == []


def test_jeton_des_metriques_trop_court_refuse_en_production():
    settings = Settings(api_key="x" * 44, metrics_token="court")
    with pytest.raises(InsecureConfigurationError, match="METRICS_TOKEN"):
        check_secrets(settings, production=True)


@pytest.mark.parametrize("same_as", ["api_key", "borne_api_key"])
def test_jeton_des_metriques_identique_a_une_cle_refuse(same_as):
    keys = {"api_key": "x" * 44, "borne_api_key": "b" * 32}
    settings = Settings(**keys, metrics_token=keys[same_as])
    with pytest.raises(InsecureConfigurationError, match="différent"):
        check_secrets(settings, production=True)


def test_jeton_des_metriques_absent_ou_solide_accepte():
    assert check_secrets(Settings(api_key="x" * 44, metrics_token="m" * 32), production=True) == []
