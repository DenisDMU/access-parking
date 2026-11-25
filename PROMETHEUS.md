# Prometheus — quoi faire, pas à pas

TP « Observabilité avec Prometheus » : superviser les microservices du projet
Parking Management. Tout est dans [`tp/prometheus`](tp/prometheus) ; cette
page est le résumé à suivre, du lancement à la démonstration.

## Où on en est

- **Access expose `GET /metrics`** en ligne, sans clé :
  <https://access-api-a1u7.onrender.com/metrics>. On y trouve
  `http_requests_total` (requêtes HTTP, succès et erreurs) et
  `parking_operations_total` (entrées, sorties, sorties forcées).
- **Le `Dockerfile` et `prometheus.yml` sont prêts** dans `tp/prometheus`.
  Prometheus y surveille Access et les cinq autres microservices.
- Il reste à **lancer Prometheus sur votre ordinateur** et à faire la
  démonstration. Aucun mot de passe à choisir, aucune clé à fournir.

## Les 3 gestes

**1. Ouvrir Docker Desktop** et attendre que l'icône de la baleine soit fixe.

**2. Démarrer Prometheus :**

```bash
cd tp/prometheus && ./demarrer.sh
```

Le script construit l'image `tp-prometheus`, démarre le conteneur et affiche
« Prometheus est prêt ».

**3. Ouvrir <http://localhost:9090/targets>** : la liste des services
surveillés, avec leur état **UP** ou **DOWN**. Laisser passer 30 secondes
pour la première mesure.

Pour arrêter (les mesures déjà prises sont conservées) :

```bash
cd tp/prometheus && ./arreter.sh
```

> Tant que Prometheus tourne, il interroge chaque service toutes les
> 15 secondes : les services hébergés sur l'offre gratuite de Render ne
> s'endorment donc plus. Arrêtez-le quand vous avez fini.

## Ce qu'on voit sur la page des cibles

État constaté le 25 novembre 2026 (il changera quand les autres équipes
ajouteront leur route `/metrics`) :

| Cible | Service | État | Pourquoi |
|---|---|---|---|
| `access` | Access en ligne (Render) | **UP** | `/metrics` répond, sans clé |
| `parking` | Parking (Render) | **UP** | expose déjà `/metrics` |
| `vehicles` | Vehicles (Render) | DOWN | `/metrics` renvoie vers la page de connexion |
| `pricing` | Pricing (Render) | DOWN | pas encore de route `/metrics` (404) |
| `payment` | Payment (Render) | DOWN | pas encore de route `/metrics` (404) |
| `booking` | Booking (Render) | DOWN | le service ne répondait pas du tout ce jour-là (503) |
| `access-local` | Access lancé sur cet ordinateur | DOWN, puis UP | sert à la démonstration ci-dessous |
| `prometheus` | Prometheus lui-même | **UP** | témoin |

À savoir dire : **DOWN veut dire « Prometheus n'a pas réussi à lire
`/metrics` »**. Le service peut être arrêté, endormi, ou simplement ne pas
exposer la route. La colonne « Error » de la page donne la raison (404,
délai dépassé…). Un service de Render endormi met jusqu'à une minute à se
réveiller : il passe DOWN puis UP tout seul.

## Faire bouger les compteurs

Les compteurs partent de zéro au démarrage d'Access et montent à chaque usage.

- **Requêtes HTTP** : ouvrir <https://access-api-a1u7.onrender.com/borne>,
  ou lancer plusieurs fois :

```bash
curl -s https://access-api-a1u7.onrender.com/api/v1/borne/status
```

- **Opération métier** : faire une entrée puis une sortie sur la borne
  (<https://access-api-a1u7.onrender.com/borne>). Chaque passage ajoute 1 à
  `parking_operations_total`, avec le résultat (autorisé, refusé,
  confirmation demandée).
- **Lire les compteurs à la main :**

```bash
curl -s https://access-api-a1u7.onrender.com/metrics | grep -E '^(http_requests_total|parking_operations_total)'
```

`/health`, `/metrics` et `/static` ne sont pas comptés : les lectures de
Prometheus et la sonde de Render ne gonflent pas l'activité mesurée.

## Les trois graphiques

Ouvrir <http://localhost:9090/query>, coller la requête, cliquer **Execute**,
puis l'onglet **Graph**. Régler la durée affichée sur 15 ou 30 minutes.

**1. Disponibilité** — 1 quand le service répond, 0 sinon :

```promql
up
```

**2. Requêtes HTTP par seconde** — l'activité d'Access (en ligne et en local) :

```promql
sum by (job) (rate(http_requests_total[2m]))
```

**3. Erreurs HTTP** — les réponses 4xx et 5xx par seconde :

```promql
sum by (job, status) (rate(http_requests_total{status=~"4xx|5xx"}[2m]))
```

**3 bis. Opérations métier** — passages des cinq dernières minutes, par
opération et résultat :

```promql
sum by (operation, result) (increase(parking_operations_total{job="access"}[5m]))
```

Pour aller plus loin :

| Question | Requête |
|---|---|
| Quels services sont indisponibles en ce moment ? | `up == 0` |
| Total des opérations depuis le démarrage d'Access | `sum by (operation, result) (parking_operations_total)` |
| Part des requêtes en erreur | `sum(rate(http_requests_total{status=~"4xx\|5xx"}[5m])) / sum(rate(http_requests_total[5m]))` |
| Activité par route | `sum by (handler) (rate(http_requests_total[2m]))` |
| Activité de Parking (son compteur porte un autre nom) | `sum(rate(parking_http_requests_total[2m]))` |

`rate(...[2m])` : un compteur ne fait que monter ; `rate` calcule de combien
il monte **par seconde** en moyenne sur les deux dernières minutes.

## Démonstration : un service tombe, Prometheus le voit

La cible `access-local` est un Access lancé sur votre ordinateur : on peut
l'arrêter sans gêner personne.

**1. Le démarrer**, dans un second terminal, depuis la racine du dépôt :

```bash
.venv/bin/uvicorn src.interfaces.api.main:app --port 8010
```

(Le port 8010 est celui écrit dans `prometheus.yml` ; il laisse le 8000 au
TP Splunk.)

**2. Vérifier** sur <http://localhost:9090/targets> : `access-local` passe
**UP** en moins de 15 secondes.

**3. Le faire travailler** (requêtes réussies, puis une erreur 401) :

```bash
for i in 1 2 3 4 5; do curl -s -o /dev/null http://localhost:8010/api/v1/borne/status; curl -s -o /dev/null http://localhost:8010/api/v1/access/requests; done
```

**4. L'arrêter** : `Ctrl+C` dans le second terminal. En moins de 15
secondes, `access-local` passe **DOWN** (erreur « connection refused »).

**5. Montrer le graphique `up`** : la courbe d'`access-local` tombe de 1 à 0,
celle d'`access` (en ligne) reste à 1. Relancer la commande de l'étape 1 : la
courbe remonte.

## Bonus : le tableau de bord Grafana

```bash
cd tp/prometheus && ./demarrer.sh --grafana
```

Puis ouvrir <http://localhost:3000/> : le tableau de bord « Parking
Management — supervision » s'affiche directement, sans connexion (lecture
seule). La source Prometheus et le tableau de bord sont créés au démarrage à
partir des fichiers de `tp/prometheus/grafana` : rien à configurer.

On y voit la disponibilité de chaque service (UP en vert, DOWN en rouge, et
son historique), les requêtes et erreurs HTTP d'Access, les opérations
métier, les véhicules présents et les appels d'Access vers les autres
services.

## Quoi montrer au rendu

1. `https://access-api-a1u7.onrender.com/metrics` dans le navigateur : les
   lignes `http_requests_total` et `parking_operations_total`.
2. `tp/prometheus/Dockerfile` et `tp/prometheus/prometheus.yml`.
3. La page des cibles : Access et Parking UP, les autres DOWN, et pourquoi.
4. Les trois graphiques ci-dessus.
5. La démonstration : arrêter `access-local`, le voir passer DOWN, puis un
   passage sur la borne et le compteur `parking_operations_total` qui monte.
6. (Bonus) le tableau de bord Grafana.

Le critère du sujet tient en trois verbes : **identifier** un service
indisponible (`up == 0`), **mesurer** son activité (`rate(http_requests_total…)`),
**observer** ses opérations métier (`parking_operations_total`).

## Ce qu'il faut savoir expliquer

**Le Dockerfile**, deux lignes utiles :

| Ligne | Ce qu'elle fait |
|---|---|
| `FROM docker.io/prom/prometheus:latest` | Part de l'image officielle de Prometheus : rien à installer. |
| `COPY prometheus.yml /etc/prometheus/prometheus.yml` | Remplace la configuration par défaut par la nôtre : la liste des services à surveiller. |

**`prometheus.yml`** : `scrape_interval: 15s` (une mesure toutes les 15
secondes), puis un bloc `job_name` par service, avec son adresse et
`scheme: https` pour ceux hébergés sur Render.

**Le principe** : chaque service publie ses compteurs sur `/metrics` ; c'est
Prometheus qui vient les lire (il « tire », le service ne pousse rien), les
date et les garde. `up` est fabriqué par Prometheus lui-même à chaque
lecture.

**Pourquoi `/metrics` est lisible sans clé** : le Prometheus de chaque équipe
doit pouvoir le lire, et la route ne contient que des compteurs. Aucune
plaque, aucun identifiant de véhicule : les routes sont comptées par leur
modèle (`/api/v1/access/requests/{request_id}`), jamais par l'adresse reçue.

**Dans le code** : `src/infrastructure/metrics.py` (les compteurs),
`src/interfaces/api/routers/metrics_router.py` (la route), et l'appel
`record_decision` dans les routes de passage. Le domaine et les cas d'usage
ne connaissent pas Prometheus.

## Si ça coince

| Ce que vous voyez | Quoi faire |
|---|---|
| `Docker ne répond pas` | Docker Desktop n'est pas démarré : le lancer et recommencer. |
| `port is already allocated` | Le port 9090 (ou 3000 pour Grafana) est pris : arrêter l'autre programme. |
| `access` est DOWN | Render l'a endormi ou le redéploie : attendre une minute. |
| `access-local` reste DOWN | Access n'est pas lancé sur le port 8010 (étape 1 de la démonstration). |
| Un graphique est vide | Laisser passer deux mesures (30 s), et vérifier la durée affichée. |
| J'ai modifié `prometheus.yml` | Relancer `./demarrer.sh` : il reconstruit l'image et recrée le conteneur. |

La notice complète, commande par commande : [`tp/prometheus/README.md`](tp/prometheus/README.md).
