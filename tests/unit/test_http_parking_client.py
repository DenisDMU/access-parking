"""Tests unitaires — fonctions pures de `http_parking_client.py`
(mapping catégorie), sans appel réseau au vrai service Parking."""

import json

import httpx
import pytest

from src.domain.ports.parking_service_port import (
    ParkingCategoryUnknownError,
    ParkingUnavailableError,
)
from src.domain.value_objects.dto import VehicleType
from src.domain.value_objects.enums import VehicleCategory
from src.infrastructure.external.http_parking_client import (
    REQUIRED_CATEGORIES,
    HttpParkingClient,
    _CategoriesCache,
    _map_category,
    _place_type_from_category,
)

# Port fermé en local : connexion refusée immédiatement, pas de reseau reel
# necessaire ni de delai notable (meme principe que pour RabbitMQ).
_UNREACHABLE_URL = "http://127.0.0.1:59999"

FOUR = VehicleCategory.FOUR_WHEELER
TWO = VehicleCategory.TWO_WHEELER


def test_map_category_standard():
    assert _map_category(VehicleType(category=FOUR)) == "STANDARD"


def test_map_category_xl():
    assert _map_category(VehicleType(category=FOUR, is_xl=True)) == "XL"


def test_map_category_electric():
    assert _map_category(VehicleType(category=FOUR, is_electric=True)) == "ELECTRIC"


def test_map_category_handicapped():
    assert _map_category(VehicleType(category=FOUR, is_handicap=True)) == "HANDICAPPED"


def test_map_category_two_wheels():
    assert _map_category(VehicleType(category=TWO)) == "TWO_WHEELS"


def test_map_category_priority_handicapped_over_everything_else():
    vehicle = VehicleType(category=FOUR, is_xl=True, is_electric=True, is_handicap=True)
    assert _map_category(vehicle) == "HANDICAPPED"


def test_place_type_from_category_roundtrips_each_category():
    for category in ("STANDARD", "XL", "ELECTRIC", "HANDICAPPED", "TWO_WHEELS"):
        vehicle = VehicleType(
            category=TWO if category == "TWO_WHEELS" else FOUR,
            is_xl=category == "XL",
            is_electric=category == "ELECTRIC",
            is_handicap=category == "HANDICAPPED",
        )
        place = _place_type_from_category(category)
        assert _map_category(vehicle) == category
        assert place.is_xl == vehicle.is_xl
        assert place.is_electric == vehicle.is_electric
        assert place.is_handicap == vehicle.is_handicap
        assert place.category == vehicle.category


def test_request_place_signale_parking_injoignable():
    """Parking injoignable n'est pas « aucune place » : erreur dédiée, que le
    use case transforme en refus « Service Parking indisponible »."""

    client = HttpParkingClient(_UNREACHABLE_URL, timeout_s=1.0)
    with pytest.raises(ParkingUnavailableError):
        client.request_place(VehicleType(category=FOUR))


def test_cle_api_envoyee_a_parking():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-API-Key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    client = HttpParkingClient(
        "http://parking.test", api_key="cle-parking", transport=httpx.MockTransport(handler)
    )
    assignment = client.request_place(VehicleType(category=FOUR))

    assert seen["key"] == "cle-parking"
    assert seen["body"] == {"category_name": "STANDARD", "commercial_type": "walkin"}
    assert assignment.place_id == "STANDARD:walkin"


def test_pas_den_tete_sans_cle_configuree():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={"success": True})

    HttpParkingClient("http://parking.test", transport=httpx.MockTransport(handler)).request_place(
        VehicleType(category=FOUR)
    )
    assert seen["key"] is None


def test_cle_refusee_par_parking_est_une_indisponibilite():
    client = HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"detail": "API Key invalide ou manquante"})
        ),
    )
    with pytest.raises(ParkingUnavailableError):
        client.request_place(VehicleType(category=FOUR))


def test_parking_complet_renvoie_none():
    client = HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"success": False})),
    )
    assert client.request_place(VehicleType(category=FOUR)) is None


def test_mark_place_occupied_returns_false_when_parking_unreachable():
    client = HttpParkingClient(_UNREACHABLE_URL, timeout_s=1.0)
    assert client.mark_place_occupied("STANDARD:walkin", "v1", hold_id="1") is False


def test_mark_place_free_returns_false_when_parking_unreachable():
    client = HttpParkingClient(_UNREACHABLE_URL, timeout_s=1.0)
    assert client.mark_place_free("STANDARD:walkin") is False


# --- Contrat hold → confirm_entry (hold_id, depuis le 2026-11-18) -------------

_HOLD_RESPONSE = {
    "hold_id": 12,
    "category_name": "STANDARD",
    "label": "Standard",
    "commercial_type": "walkin",
    "end_at": "2026-11-18T10:30:30",
    "success": True,
}


def test_hold_renvoie_le_hold_id():
    client = HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(201, json=_HOLD_RESPONSE)),
    )
    assignment = client.request_place(VehicleType(category=FOUR))
    assert assignment.hold_id == "12"
    assert assignment.place_id == "STANDARD:walkin"


def test_confirm_entry_envoie_le_hold_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": "ok"})

    client = HttpParkingClient("http://parking.test", transport=httpx.MockTransport(handler))
    assert client.mark_place_occupied("STANDARD:walkin", "v1", hold_id="12") is True
    assert seen["path"] == "/parking/confirm_entry"
    assert seen["body"] == {"category_name": "STANDARD", "commercial_type": "walkin", "hold_id": 12}


def test_confirm_entry_hold_expire_ou_deja_utilise():
    client = HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(409, json={"detail": "Hold expiré"})
        ),
    )
    assert client.mark_place_occupied("STANDARD:walkin", "v1", hold_id="12") is False


def test_confirm_entry_refuse_par_validation():
    client = HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(422, json={"detail": []})),
    )
    assert client.mark_place_occupied("STANDARD:walkin", "v1", hold_id="12") is False


def test_confirm_entry_sans_hold_id_n_appelle_pas_parking():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    client = HttpParkingClient("http://parking.test", transport=httpx.MockTransport(handler))
    assert client.mark_place_occupied("STANDARD:walkin", "v1") is False
    assert calls == []


# --- Parking 1.5.0 : catégories, libellés, occupation ---------------------------

_CATEGORIES = [
    {"category_name": "STANDARD", "label": "Standard"},
    {"category_name": "XL", "label": "Grand gabarit"},
    {"category_name": "ELECTRIC", "label": "Recharge électrique"},
    {"category_name": "HANDICAPPED", "label": "Place PMR"},
    {"category_name": "TWO_WHEELS", "label": "Deux-roues"},
]


class _FakeParking:
    """Faux Parking 1.5.0 qui retient les appels."""

    def __init__(self, categories=None, hold_status: int = 201, categories_status: int = 200):
        self.categories = _CATEGORIES if categories is None else categories
        self.hold_status = hold_status
        self.categories_status = categories_status
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/parking/categories":
            return httpx.Response(self.categories_status, json=self.categories)
        if request.url.path == "/parking/hold":
            if self.hold_status == 404:
                return httpx.Response(404, json={"detail": "Catégorie introuvable"})
            return httpx.Response(self.hold_status, json=_HOLD_RESPONSE)
        if request.url.path == "/parking/occupation":
            return httpx.Response(
                200,
                json={
                    "categories": [
                        {
                            "category_name": "STANDARD",
                            "label": "Standard",
                            "occupation_rate": 0.25,
                            "spot_taken": 5,
                            "total_capacity": 20,
                            "spot_held": 1,
                        },
                        # Parking < 1.5.0 : ni label ni spot_held.
                        {
                            "category_name": "XL",
                            "occupation_rate": 0.0,
                            "spot_taken": 0,
                            "total_capacity": 4,
                        },
                    ]
                },
            )
        return httpx.Response(404)


def _parking(fake: _FakeParking, cache: _CategoriesCache | None = None) -> HttpParkingClient:
    return HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(fake),
        categories_cache=cache or _CategoriesCache(),
    )


def test_list_categories():
    categories = _parking(_FakeParking()).list_categories()
    assert [(c.name, c.label) for c in categories][:2] == [
        ("STANDARD", "Standard"),
        ("XL", "Grand gabarit"),
    ]


def test_toutes_les_categories_d_access_sont_requises():
    assert set(_parking(_FakeParking()).required_categories()) == set(REQUIRED_CATEGORIES)
    assert len(REQUIRED_CATEGORIES) == 5


def test_hold_verifie_la_categorie_puis_garde_la_liste_en_cache():
    fake = _FakeParking()
    client = _parking(fake)
    client.request_place(VehicleType(category=FOUR))
    client.request_place(VehicleType(category=FOUR))
    assert fake.calls == ["GET /parking/categories", "POST /parking/hold", "POST /parking/hold"]


def test_cache_expire_apres_le_delai():
    now = [0.0]
    cache = _CategoriesCache(ttl_s=300, clock=lambda: now[0])
    fake = _FakeParking()
    client = _parking(fake, cache)
    client.request_place(VehicleType(category=FOUR))
    now[0] = 301.0
    client.request_place(VehicleType(category=FOUR))
    assert fake.calls.count("GET /parking/categories") == 2


def test_hold_remonte_le_libelle_de_parking():
    assignment = _parking(_FakeParking()).request_place(VehicleType(category=FOUR))
    assert assignment.label == "Standard"


def test_categorie_absente_de_parking_refusee_sans_hold():
    fake = _FakeParking(categories=[{"category_name": "STANDARD", "label": "Standard"}])
    with pytest.raises(ParkingCategoryUnknownError) as exc:
        _parking(fake).request_place(VehicleType(category=FOUR, is_electric=True))
    assert exc.value.category == "ELECTRIC"
    assert "POST /parking/hold" not in fake.calls


def test_hold_404_est_une_categorie_inconnue_et_vide_le_cache():
    cache = _CategoriesCache()
    fake = _FakeParking(hold_status=404)
    client = _parking(fake, cache)
    with pytest.raises(ParkingCategoryUnknownError):
        client.request_place(VehicleType(category=FOUR))
    assert cache.get("http://parking.test") is None


def test_liste_indisponible_ne_bloque_pas_l_entree():
    fake = _FakeParking(categories_status=500)
    assignment = _parking(fake).request_place(VehicleType(category=FOUR))
    assert assignment is not None and assignment.hold_id == "12"


def test_list_categories_indisponible_leve_une_erreur_de_service():
    with pytest.raises(ParkingUnavailableError):
        _parking(_FakeParking(categories_status=401)).list_categories()


def test_list_categories_reponse_inattendue():
    with pytest.raises(ParkingUnavailableError):
        _parking(_FakeParking(categories=[{"nom": "STANDARD"}])).list_categories()


def test_get_occupation_avec_et_sans_champs_1_5_0():
    occupation = _parking(_FakeParking()).get_occupation()
    standard, xl = occupation
    assert (standard.label, standard.spot_taken, standard.spot_held, standard.total_capacity) == (
        "Standard",
        5,
        1,
        20,
    )
    assert (xl.label, xl.spot_held) == ("XL", 0)


def test_get_occupation_parking_injoignable():
    client = HttpParkingClient(_UNREACHABLE_URL, timeout_s=1.0, categories_cache=_CategoriesCache())
    with pytest.raises(ParkingUnavailableError):
        client.get_occupation()


def test_comparaison_des_categories_insensible_a_la_casse():
    fake = _FakeParking(categories=[{"category_name": "standard", "label": "Standard"}])
    assert _parking(fake).request_place(VehicleType(category=FOUR)) is not None


def test_liste_vide_ne_bloque_pas_l_entree():
    fake = _FakeParking(categories=[])
    assert _parking(fake).request_place(VehicleType(category=FOUR)) is not None


# --- Catégorie pleine : « complet », pas « indisponible » (24/11) -------------------


def _full_parking(hold_status, available):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/parking/categories":
            return httpx.Response(
                200, json={"categories": [{"category_name": "XL", "label": "XL"}]}
            )
        if request.url.path == "/parking/hold":
            return httpx.Response(hold_status, json={"detail": "Aucune place disponible"})
        if request.url.path == "/parking/availability/XL/walkin":
            if available is None:
                return httpx.Response(500)
            return httpx.Response(
                200,
                json={
                    "category_name": "XL",
                    "label": "XL",
                    "commercial_type": "walkin",
                    "is_available": available,
                    "spot_available": 3 if available else 0,
                },
            )
        return httpx.Response(404)

    client = HttpParkingClient(
        "http://parking.test",
        transport=httpx.MockTransport(handler),
        categories_cache=_CategoriesCache(),
    )
    return client, calls


@pytest.mark.parametrize("status", [400, 409, 422])
def test_hold_refuse_categorie_pleine_donne_aucune_place(status):
    client, calls = _full_parking(status, available=False)
    assert client.request_place(VehicleType(category=FOUR, is_xl=True)) is None
    assert "GET /parking/availability/XL/walkin" in calls


def test_hold_refuse_mais_places_libres_reste_une_panne():
    client, _ = _full_parking(409, available=True)
    with pytest.raises(ParkingUnavailableError):
        client.request_place(VehicleType(category=FOUR, is_xl=True))


def test_hold_refuse_et_disponibilite_illisible_reste_une_panne():
    client, _ = _full_parking(409, available=None)
    with pytest.raises(ParkingUnavailableError):
        client.request_place(VehicleType(category=FOUR, is_xl=True))


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_cle_refusee_debit_ou_5xx_jamais_lus_comme_complet(status):
    client, calls = _full_parking(status, available=False)
    with pytest.raises(ParkingUnavailableError):
        client.request_place(VehicleType(category=FOUR, is_xl=True))
    assert "GET /parking/availability/XL/walkin" not in calls
