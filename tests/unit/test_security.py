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


# --- Clés des services de l'équipe : jamais vers une adresse sans https ----------

_SERVICES = ["vehicles", "booking", "parking", "pricing", "payment"]


def _with_service(name: str, url: str, key: str) -> Settings:
    return Settings(
        api_key="x" * 44,
        booking_use_mock=False,
        **{f"{name}_service_url": url, f"{name}_api_key": key},
    )


@pytest.mark.parametrize("name", _SERVICES)
def test_cle_d_un_service_vers_une_adresse_sans_https_refusee_en_production(name):
    settings = _with_service(name, f"http://{name}.example", "cle-de-test-du-service")
    with pytest.raises(InsecureConfigurationError, match=f"{name.upper()}_SERVICE_URL"):
        check_secrets(settings, production=True)
    # En local : simple avertissement, le démarrage continue.
    assert check_secrets(settings, production=False) == [
        f"{name.upper()}_SERVICE_URL n'est pas en https alors que "
        f"{name.upper()}_API_KEY est renseignée"
    ]


@pytest.mark.parametrize("name", _SERVICES)
def test_cle_d_un_service_vers_une_adresse_https_acceptee(name):
    settings = _with_service(name, f"HTTPS://{name}.example", "cle-de-test-du-service")
    assert check_secrets(settings, production=True) == []


@pytest.mark.parametrize("name", _SERVICES)
def test_adresse_sans_https_toleree_tant_qu_aucune_cle_ne_part(name):
    settings = _with_service(name, f"http://{name}.example", "")
    assert check_secrets(settings, production=True) == []


def test_le_message_de_refus_ne_contient_ni_la_cle_ni_l_adresse():
    settings = _with_service(
        "booking", "http://agent:motdepasse@booking.example", "cle-de-test-du-service"
    )
    with pytest.raises(InsecureConfigurationError) as refus:
        check_secrets(settings, production=True)
    for secret in ("cle-de-test-du-service", "motdepasse", "booking.example"):
        assert secret not in str(refus.value)


@pytest.mark.parametrize("url", ["", " https://parking.example", "//parking.example", "https:/x"])
def test_adresse_vide_ou_mal_saisie_refusee_quand_une_cle_part(url):
    settings = _with_service("parking", url, "cle-de-test-du-service")
    with pytest.raises(InsecureConfigurationError, match="PARKING_SERVICE_URL"):
        check_secrets(settings, production=True)


def test_booking_simule_son_adresse_n_est_pas_controlee():
    settings = Settings(
        api_key="x" * 44,
        booking_use_mock=True,
        booking_service_url="http://booking.example",
        booking_api_key="cle-de-test-du-service",
    )
    assert check_secrets(settings, production=True) == []


# --- Identifiants dans une adresse ------------------------------------------------


@pytest.mark.parametrize("name", _SERVICES)
def test_adresse_de_service_avec_identifiants_refusee_en_production(name):
    settings = _with_service(name, f"https://agent:motdepasse@{name}.example", "")
    with pytest.raises(InsecureConfigurationError, match=f"{name.upper()}_SERVICE_URL") as refus:
        check_secrets(settings, production=True)
    assert "motdepasse" not in str(refus.value)
    assert f"{name}.example" not in str(refus.value)


def test_adresse_d_abonne_avec_identifiants_refusee_en_production():
    settings = Settings(
        api_key="x" * 44,
        event_subscribers_urls=["https://ok.example/hook", "https://agent:motdepasse@b.example"],
    )
    with pytest.raises(InsecureConfigurationError, match="EVENT_SUBSCRIBERS_URLS") as refus:
        check_secrets(settings, production=True)
    assert "motdepasse" not in str(refus.value)


# --- Bus d'événements : le mot de passe ne part pas en clair ----------------------


def _with_bus(url: str, **extra) -> Settings:
    return Settings(api_key="x" * 44, event_publisher="rabbitmq", rabbitmq_url=url, **extra)


def test_bus_sans_tls_vers_un_autre_hote_refuse_en_production():
    settings = _with_bus("amqp://agent:motdepasse@bus.example/vhost")
    with pytest.raises(InsecureConfigurationError, match="RABBITMQ_URL") as refus:
        check_secrets(settings, production=True)
    assert "motdepasse" not in str(refus.value)
    assert len(check_secrets(settings, production=False)) == 1  # avertissement en local


@pytest.mark.parametrize(
    "url",
    [
        "amqps://agent:motdepasse@bus.example/vhost",
        "AMQPS://agent:motdepasse@bus.example/vhost",
        "amqp://guest:guest@localhost:5672/%2F",  # valeur par défaut
        "amqp://guest:guest@127.0.0.1:5672/%2F",
        "",  # variable vide : aucun événement publié, rien ne part
    ],
)
def test_bus_en_tls_local_ou_absent_accepte(url):
    assert check_secrets(_with_bus(url), production=True) == []


def test_bus_prive_sans_tls_accepte_sur_declaration_explicite():
    settings = _with_bus(
        "amqp://guest:guest@access-rabbitmq:5672/%2F", rabbitmq_allow_plaintext=True
    )
    assert check_secrets(settings, production=True) == []


def test_bus_non_controle_quand_les_evenements_partent_en_webhook():
    settings = Settings(
        api_key="x" * 44, event_publisher="webhook", rabbitmq_url="amqp://a:b@bus.example/v"
    )
    assert check_secrets(settings, production=True) == []


# --- Routes réglables de Vehicles ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "@autre.hote/x",
        "//autre.hote/x",
        "/api/../admin",
        "/api/create?x=1",
        "api/create",
        "/api/create\n",
        "",
    ],
)
@pytest.mark.parametrize("variable", ["vehicles_identify_path", "vehicles_lookup_path"])
def test_route_de_vehicles_qui_n_est_pas_un_simple_chemin_refusee(variable, path):
    settings = Settings(api_key="x" * 44, **{variable: path})
    with pytest.raises(InsecureConfigurationError, match=variable.upper()):
        check_secrets(settings, production=True)


@pytest.mark.parametrize(
    "path", ["/api/vehicle/create", "/api/vehicle/{vehicleId}", "/api/vehicles/{plate}"]
)
def test_route_de_vehicles_habituelle_acceptee(path):
    settings = Settings(api_key="x" * 44, vehicles_identify_path=path, vehicles_lookup_path=path)
    assert check_secrets(settings, production=True) == []


@pytest.mark.parametrize("value", ["", "   "])
def test_route_de_vehicles_laissee_vide_dans_l_environnement_valeur_par_defaut(monkeypatch, value):
    monkeypatch.setenv("VEHICLES_LOOKUP_PATH", value)
    monkeypatch.setenv("VEHICLES_IDENTIFY_PATH", value)
    settings = Settings(api_key="x" * 44)
    assert settings.vehicles_lookup_path == "/api/vehicle/{vehicleId}"
    assert settings.vehicles_identify_path == "/api/vehicle/create"
    assert check_secrets(settings, production=True) == []


def test_route_de_vehicles_reglee_dans_l_environnement_est_lue(monkeypatch):
    monkeypatch.setenv("VEHICLES_LOOKUP_PATH", " /api/vehicles/{vehicleId} ")
    assert Settings(api_key="x" * 44).vehicles_lookup_path == "/api/vehicles/{vehicleId}"
