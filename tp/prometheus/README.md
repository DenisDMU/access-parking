# TP — Observabilité avec Prometheus

Un **Prometheus** local, dans un conteneur Docker, qui supervise les
microservices du projet Parking Management : Access (le nôtre) et ceux des
autres équipes. Interface sur `http://localhost:9090/`. En bonus, un
**Grafana** avec un tableau de bord prêt à l'emploi.

Le pas-à-pas de la démonstration est dans [`PROMETHEUS.md`](../../PROMETHEUS.md),
à la racine du dépôt. Cette notice décrit le contenu du dossier.

## En deux commandes

```bash
cd tp/prometheus
```

```bash
./demarrer.sh
```

Puis ouvrir <http://localhost:9090/targets>. Avec Grafana :
`./demarrer.sh --grafana`, puis <http://localhost:3000/>. Pour arrêter :

```bash
./arreter.sh
```

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `Dockerfile` | L'image du TP : l'image officielle de Prometheus, plus notre configuration. |
| `prometheus.yml` | Les services à surveiller et la fréquence des mesures. |
| `demarrer.sh` | Construit l'image, démarre Prometheus (et Grafana avec `--grafana`). |
| `arreter.sh` | Arrête les conteneurs sans rien supprimer. |
| `grafana/provisioning/` | Source de données Prometheus et chargement du tableau de bord, créés au démarrage de Grafana. |
| `grafana/dashboards/parking-management.json` | Le tableau de bord « Parking Management — supervision ». |

## 1. Le Dockerfile

```dockerfile
# Image officielle Prometheus
FROM docker.io/prom/prometheus:latest

# Configuration de la collecte (à créer dans le même dossier)
COPY prometheus.yml /etc/prometheus/prometheus.yml
```

`prometheus.yml` est **copié dans l'image** : après une modification, il faut
reconstruire l'image et recréer le conteneur. `./demarrer.sh` le fait tout
seul.

## 2. Les services surveillés (`prometheus.yml`)

| `job_name` | Adresse lue | Remarque |
|---|---|---|
| `access` | `https://access-api-a1u7.onrender.com/metrics` | notre service, en ligne |
| `parking` | `https://parking-6r73.onrender.com/metrics` | |
| `vehicles` | `https://parking-vehicles.onrender.com/metrics` | |
| `booking` | `https://booking-api-vhy5.onrender.com/metrics` | |
| `pricing` | `https://pricing-9khk.onrender.com/metrics` | |
| `payment` | `https://payment-xp8n.onrender.com/metrics` | |
| `access-local` | `http://host.docker.internal:8010/metrics` | Access lancé sur cet ordinateur, pour simuler une panne |
| `prometheus` | `http://localhost:9090/metrics` | Prometheus lui-même |

Aucune clé dans ce fichier : chaque `/metrics` est lu tel qu'il est publié.
Un service qui n'expose pas la route apparaît **DOWN**, avec la raison dans
la colonne « Error » de la page des cibles. `host.docker.internal` est le nom
de l'ordinateur vu depuis le conteneur.

## 3. Construire et démarrer à la main

```bash
docker build -t tp-prometheus .
```

```bash
docker network create tp-prometheus
```

```bash
docker run -d --name tp-prometheus --network tp-prometheus --add-host=host.docker.internal:host-gateway -p 127.0.0.1:9090:9090 -v tp-prometheus-data:/prometheus tp-prometheus
```

- `-p 127.0.0.1:9090:9090` : l'interface n'est joignable **que depuis cet
  ordinateur**.
- `-v tp-prometheus-data:/prometheus` : les mesures sont gardées dans un
  volume ; elles survivent à la recréation du conteneur.
- `--add-host=…` : rend `host.docker.internal` disponible aussi sous Linux.
- `--network tp-prometheus` : Grafana joint Prometheus par son nom sur ce
  réseau.

## 4. Simuler une indisponibilité

Depuis la racine du dépôt, démarrer la cible locale :

```bash
.venv/bin/uvicorn src.interfaces.api.main:app --port 8010
```

`access-local` passe UP. `Ctrl+C` : il passe DOWN à la mesure suivante (15
secondes au plus). Le graphique `up` garde la trace de la coupure.

## 5. Grafana (bonus)

`./demarrer.sh --grafana` démarre un second conteneur, `tp-grafana`, sur
`127.0.0.1:3000`.

- **Aucun mot de passe dans le dépôt.** Le tableau de bord s'ouvre sans
  connexion, en lecture seule. Le mot de passe du compte `admin` est tiré au
  hasard à la création du conteneur ; il n'est ni affiché ni écrit dans un
  fichier.
- La source de données et le tableau de bord sont **provisionnés** : Grafana
  les lit dans `grafana/` (monté en lecture seule) à chaque démarrage.
- Pour modifier le tableau de bord : éditer le fichier JSON, puis
  `docker restart tp-grafana`.

## Tout supprimer

```bash
docker rm -f tp-grafana tp-prometheus
```

```bash
docker volume rm tp-prometheus-data
```

```bash
docker network rm tp-prometheus
```

## En cas de souci

| Symptôme | Cause probable | Quoi faire |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop n'est pas démarré | Le lancer, attendre l'icône stable, recommencer |
| `port is already allocated` | Le port 9090 ou 3000 est pris | Arrêter l'autre programme |
| Toutes les cibles Render sont DOWN | Pas de réseau, ou services endormis | Vérifier la connexion, attendre une minute |
| `access-local` reste DOWN | Access n'écoute pas sur 8010 | Relancer la commande de la section 4 |
| Le tableau de bord Grafana est vide | Prometheus n'a pas encore de mesures | Attendre 30 secondes, vérifier <http://localhost:9090/targets> |

Documentation : *Prometheus — Getting started* et *Configuration* sur
prometheus.io.
