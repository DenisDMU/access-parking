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
    for shop in ("BOUTIQUE KINGPAR", "COIFFURE LE CRÉNEAU", "ANIMALERIE DU COPILOTE"):
        assert shop in source
    for name in ("function openShop", "function buildPet", "function stamp", "function photo"):
        assert name in source
    for pet in ("chihuahua:", "chat:", "shiba:", "lapin:", "renard:"):
        assert pet in source
    # Tenue, compagnon et carnet restent sur l'appareil : deux clés, une seule
    # écriture, et le module n'envoie rien (ni tenue, ni photo souvenir).
    for key in (
        "access.plan3d.look",
        "access.plan3d.carnet",
        "access.plan3d.joueur",
        "access.plan3d.accueil",
    ):
        assert key in source
    assert source.count("localStorage.setItem") == 1
    # Le carnet est un jeu : il ne promet aucun avantage tarifaire.
    assert "il ne donne droit à aucun tarif" in source


def test_plan_3d_multijoueur_sans_cle_ni_texte_libre(client):
    """Le plan ne parle qu'à la route que la page lui donne, sans clé ni cookie."""

    source = client.get("/static/parking3d.js").text
    # Cinq appels, tous vers la route du multijoueur : ma position, le regard
    # d'un spectateur, un score, les meilleurs scores, un défi amical.
    assert source.count("fetch(") == 5
    assert source.count("fetch(net.url") == 5
    assert source.count('credentials: "omit"') == 5
    for word in ("X-API-Key", "XMLHttpRequest", "sendBeacon", "WebSocket", "document.cookie"):
        assert word not in source
    # Pseudo attribué par le serveur, saluts choisis dans une liste : aucune saisie.
    assert "const EMOTES" in source
    for tag in ("<input", "<textarea", 'elem("input"', 'elem("textarea"'):
        assert tag not in source
    for page in ("/static/dashboard.html", "/static/borne.html"):
        html = client.get(page).text
        assert 'multi: "/api/v1/borne/promenade"' in html
        assert 'import("/static/parking3d.js?v=' in html


def test_plan_3d_succes_station_et_surprises(client):
    source = client.get("/static/parking3d.js").text
    for name in (
        "const WINS",
        "function win(",
        "function gameDone",
        "function openGame",
        "function stepLive",
    ):
        assert name in source
    assert "STATION KINGPAR" in source and "PLACES LIBRES" in source
    for pet in ("cochon:", "panda:", "mouton:", "tortue:", "canard:"):
        assert pet in source


def test_plan_3d_marque_kingpar_accueil_tenues_et_covoiturage(client):
    """KingPar : logo, popup d'accueil, tenues variées, ballons, covoiturage."""

    source = client.get("/static/parking3d.js").text
    for name in (
        "function drawLogo",
        "function openWelcome",
        "function openBalloons",
        "function rideWith",
    ):
        assert name in source
    assert "Bienvenue chez KingPar" in source and "l'amour gagne toujours" in source
    for word in (
        "const OUTFITS",
        "const BOTTOMS",
        "const EXTRAS",
        "const BALLOONS",
        '"salopette"',
        '"couronne"',
    ):
        assert word in source
    logo = client.get("/static/kingpar-logo.svg")
    assert logo.status_code == 200 and "svg" in logo.headers["content-type"]
    assert "KingPar" in logo.text and "<script" not in logo.text


def test_plan_3d_visage_peint_quetes_coupes_et_vehicules(client):
    """Personnages au visage peint, quêtes des habitants, coupes et véhicules en plus."""

    source = client.get("/static/parking3d.js").text
    for name in (
        "function drawFace",
        "const QUESTS",
        "function talk(",
        "function stepQuests",
        "function questEvent",
    ):
        assert name in source
    for word in (
        "const EYES",
        '"manga"',
        '"tresses"',
        '"boucles"',
        "const BIKES",
        'model: "moto"',
        'model: "suv"',
    ):
        assert word in source
    # Six habitants, six quêtes ; rien de saisi par le visiteur.
    assert source.count('{ id: "') >= 6 and "Mamie Gisèle" in source


def test_plan_3d_defis_ferme_et_decor_doux(client):
    """Défis entre promeneurs, Suppositofarm, animaux et maisons dans le même style."""

    source = client.get("/static/parking3d.js").text
    for name in (
        "function openWheel",
        "function setDuels",
        "function duelSend",
        "function hitNode",
        "function stepFarm",
    ):
        assert name in source
    for word in (
        "SUPPOSITOFARM",
        "Pierre feuille ciseaux",
        "Je prends pile",
        "p3d-grid3",
        "function grassTexture",
    ):
        assert word in source
    # Les défis passent par le serveur, qui arbitre ; rien n'est décidé dans la page.
    assert 'net.url + "/defi"' in source and 'Math.random() < 0.5 ? "win"' not in source


def test_plan_3d_decor_de_village(client):
    """Toits à deux pans, chemins de terre, clôture : le décor suit les personnages."""

    source = client.get("/static/parking3d.js").text
    assert (
        "const gable" in source
        and "SphereGeometry(1, 30, 12, 0, Math.PI * 2, 0, Math.PI / 2)" not in source
    )
    assert "clôture en bois" in source and "// pommes" in source
    assert "function tileTexture" in source and "roofSlab" in source  # pans de toit en tuiles


def test_mini_jeux_servis_sans_ressource_externe(client):
    from src.infrastructure.promenade_room import GAMES

    response = client.get("/static/promenade-jeux.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]
    source = response.text
    assert "export function startGame" in source and "export const GAMES" in source
    for word in ("https://", "http://", "innerHTML", "fetch(", "localStorage"):
        assert word not in source
    # Les jeux du navigateur et les plafonds du serveur vont ensemble.
    for game, maximum in GAMES.items():
        if game == "creneau":  # jugé dans le plan 3D, pas dans un panneau
            continue
        assert f"  {game}: {{" in source
        assert f"max: {maximum}" in source
    assert source.count("title:") == len(GAMES) - 1  # onze jeux en panneau, plus le créneau
    plan = client.get("/static/parking3d.js").text
    assert 'from "./promenade-jeux.js?v=' in plan


def test_dashboard_propose_de_liberer_les_vehicules_presents(client):
    html = client.get("/static/dashboard.html").text
    assert 'id="releaseAll"' in html and "Tout libérer" in html
    assert "/release" in html and "window.confirm" in html  # jamais sans confirmation
