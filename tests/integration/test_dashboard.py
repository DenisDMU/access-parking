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


def test_dashboard_embarque_theme_et_police(client):
    html = client.get("/static/dashboard.html").text
    # Thèmes Catppuccin (Latte par défaut, Mocha au choix) et police Meslo
    assert 'data-theme="latte"' in html
    assert '[data-theme="mocha"]' in html
    assert "MesloLGS NF" in html
    # Aucune ressource externe : tout est servi par Access lui-même
    assert "https://" not in html.replace("http://www.w3.org/2000/svg", "")


def test_police_servie_par_access(client):
    for weight in ("Regular", "Bold"):
        response = client.get(f"/static/fonts/MesloLGS-NF-{weight}.woff2")
        assert response.status_code == 200
        assert response.headers["content-type"] == "font/woff2"
        assert response.content[:4] == b"wOF2"
