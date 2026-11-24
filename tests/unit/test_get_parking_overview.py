"""Tests unitaires du use case `GetParkingOverview` (Parking mocké)."""

from src.application.use_cases.get_parking_overview import GetParkingOverview
from src.domain.value_objects.dto import ParkingCategory
from tests.unit.fakes import PARKING_CATEGORIES, FakeParkingPort


def test_vue_complete_quand_parking_repond():
    overview = GetParkingOverview(FakeParkingPort()).execute()
    assert overview.available is True
    assert overview.missing_categories == []
    standard = overview.categories[0]
    assert (standard.name, standard.label, standard.used_by_access) == (
        "STANDARD",
        "Standard",
        True,
    )
    assert (standard.spot_taken, standard.spot_held, standard.total_capacity) == (3, 1, 10)


def test_categorie_manquante_et_categorie_en_plus():
    categories = [c for c in PARKING_CATEGORIES if c.name != "XL"] + [
        ParkingCategory("VIP", "Abonnés")
    ]
    overview = GetParkingOverview(FakeParkingPort(categories=categories)).execute()
    assert overview.missing_categories == ["XL"]
    vip = next(c for c in overview.categories if c.name == "VIP")
    assert vip.used_by_access is False


def test_parking_injoignable():
    overview = GetParkingOverview(FakeParkingPort(unavailable=True)).execute()
    assert overview.available is False
    assert overview.categories == [] and overview.missing_categories == []
