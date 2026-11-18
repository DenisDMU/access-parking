"""Test d'intégration — dashboard statique (borne + journal) servi par Access."""


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/static/dashboard.html"


def test_dashboard_served_with_borne_tab(client):
    response = client.get("/static/dashboard.html")
    assert response.status_code == 200
    # Les quatre onglets sont présents : borne (par défaut), état du parking,
    # journal, recherche
    for tab in ('id="tab-borne"', 'id="tab-state"', 'id="tab-journal"', 'id="tab-search"'):
        assert tab in response.text
