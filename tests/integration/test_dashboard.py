"""Test d'intégration — dashboard statique (borne + journal) servi par Access."""

import hashlib

# three.js 0.160.0 (MIT), copie figée : voir static/vendor/README.md.
THREE_SHA256 = "3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6"


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/static/dashboard.html"


def test_dashboard_served_with_borne_tab(client):
    response = client.get("/static/dashboard.html")
    assert response.status_code == 200
    # Les cinq onglets sont présents : borne (par défaut), état du parking,
    # plan 3D, journal, recherche
    for tab in (
        'id="tab-borne"',
        'id="tab-state"',
        'id="tab-plan3d"',
        'id="tab-journal"',
        'id="tab-search"',
    ):
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


# --- Plan 3D (onglet du dashboard, three.js servi par Access) -------------------


def test_onglet_plan_3d_present(client):
    html = client.get("/static/dashboard.html").text
    assert 'data-tab="plan3d"' in html and ">Plan 3D<" in html
    assert 'id="plan3d"' in html
    # Module chargé seulement à l'ouverture de l'onglet, depuis Access.
    assert 'import("/static/parking3d.js' in html


def test_plan_3d_servi_sans_ressource_externe(client):
    response = client.get("/static/parking3d.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    source = response.text
    assert 'from "./vendor/three-0.160.0.module.min.js"' in source
    assert "export function createParking3D" in source
    # Ni CDN, ni image, ni police externe : la page détient la clé d'exploitation.
    assert "https://" not in source and "http://" not in source
    # Les libellés de Parking sont écrits en texte, jamais interprétés en HTML.
    assert "innerHTML" not in source


def test_plan_3d_ne_connait_aucune_plaque(client):
    """Le plan ne reçoit que des compteurs et des identifiants pseudonymisés."""

    source = client.get("/static/parking3d.js").text
    for word in ("licensePlate", "license_plate", "plaque d'immatriculation"):
        assert word not in source


def test_three_js_fige_et_intact(client):
    response = client.get("/static/vendor/three-0.160.0.module.min.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert hashlib.sha256(response.content).hexdigest() == THREE_SHA256


def test_plan_3d_mode_promenade(client):
    """Personnage à la troisième personne, chihuahua, borne de réservation."""

    source = client.get("/static/parking3d.js").text
    # Touches lues par leur position : ZQSD sur un clavier français, WASD ailleurs.
    for code in ("KeyW", "KeyA", "KeyS", "KeyD", "ShiftLeft", "KeyE", "KeyF", "Escape"):
        assert code in source
    assert "Promenade" in source and "Borne de réservation" in source
    assert "function collide" in source  # on ne traverse ni haies ni véhicules garés
    assert "onUseBorne" in source  # la borne du décor lance le vrai parcours


def test_plan_3d_saut_conduite_et_agent(client):
    """On saute, on conduit trois véhicules, un agent fait sa ronde tout seul."""

    source = client.get("/static/parking3d.js").text
    assert "Space" in source  # saut à pied, frein à main au volant
    for name in (
        "const RENTALS",
        "function stepDrive",
        "function enterVehicle",
        "function stepAgent",
    ):
        assert name in source
    # Un trajet d'un seul point (agent déjà arrivé) ne doit pas arrêter l'animation.
    assert "if (P.length < 2)" in source


def test_plan_3d_village_boutiques_et_carnet(client):
    """Bonneplace, le village du parking : boutiques offertes, compagnons, carnet."""

    source = client.get("/static/parking3d.js").text
    assert 'const CITY_NAME = "Bonneplace"' in source
    for shop in ("BOUTIQUE ACCESS", "COIFFURE LE CRÉNEAU", "ANIMALERIE DU COPILOTE"):
        assert shop in source
    for name in ("function openShop", "function buildPet", "function stamp", "function photo"):
        assert name in source
    for pet in ("chihuahua:", "chat:", "shiba:", "lapin:", "renard:"):
        assert pet in source
    # Tenue, compagnon et carnet restent sur l'appareil : deux clés, une seule
    # écriture, et le module n'envoie rien (ni tenue, ni photo souvenir).
    assert "access.plan3d.look" in source and "access.plan3d.carnet" in source
    assert source.count("localStorage.setItem") == 1
    for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket"):
        assert word not in source
    # Le carnet est un jeu : il ne promet aucun avantage tarifaire.
    assert "il ne donne droit à aucun tarif" in source


def test_dashboard_propose_de_liberer_les_vehicules_presents(client):
    html = client.get("/static/dashboard.html").text
    assert 'id="releaseAll"' in html and "Tout libérer" in html
    assert "/release" in html and "window.confirm" in html  # jamais sans confirmation
