# Access — microservice de gestion des accès parking

> Décide si un véhicule peut **entrer** ou **sortir** du parking et coordonne les
> échanges nécessaires avec les services **Vehicles**, **Booking**, **Parking**,
> **Pricing** et **Payment**. Fait partie du projet fil rouge "Gestion d'un
> parking" ; la référence fonctionnelle est le document commun « Règles
> métier » du projet.

> **Convention de nommage** : tous les identifiants de code (classes, champs,
> colonnes SQL, clés JSON de l'API) sont en **anglais**. Les *messages*
> métier retournés au format texte (`reason`, ex. "Accès autorisé") restent
> volontairement en **français** : ce sont des données/du contenu destiné à
> des usagers/exploitants français, pas des identifiants de code — voir
> détail en [section 16](#16-écarts-assumés-par-rapport-à-la-spec).

---

## Fiche d'identité (rendu)

| | |
|---|---|
| **Rôle** | Décide si un véhicule peut entrer/sortir du parking et coordonne les échanges avec Vehicles, Booking, Parking, Pricing, Payment (aucune donnée métier des autres services). |
| **Version actuelle** | `4.28.0` ([CHANGELOG](CHANGELOG.md)) — la version et le SHA du commit déployé sont exposés par `GET /health` |
| **Dernière mise à jour** | 24 novembre 2026 (plaques de tous pays ; Parking 1.5.0 : catégories et occupation ; borne client ; Vehicles par plaque) |
| **URL du service déployé** | https://access-api-a1u7.onrender.com |
| **Documentation Swagger/OpenAPI** | https://access-api-a1u7.onrender.com/docs (ReDoc : `/redoc`, spec brute : `/openapi.json`) |
| **Dépendances (services appelés)** | **Vehicles**, **Booking**, **Parking**, **Pricing**, **Payment** : tous réels |
| **Tester le service** | Borne client [`/borne`](https://access-api-a1u7.onrender.com/borne) (écran public, voir [section 12](#borne-client-écran-public)), dashboard d'exploitation `/` (borne de test + état du parking), script reproductible [`scripts/smoke_test.sh`](scripts/smoke_test.sh) (voir [section 9](#9-tests-et-qualité)), Swagger `/docs`. Sans clé : `GET /health`. |

### Fonctionnalités

- [x] Identifier un véhicule par sa plaque auprès de Vehicles, qui le retrouve ou le crée ; **toutes les plaques** sont acceptées (françaises SIV ou ancien format, étrangères : 2 à 10 lettres ou chiffres) ; la plaque n'est ni stockée, ni publiée, ni renvoyée, ni loggée (seul l'identifiant pseudonymisé circule).
- [x] Autoriser l'entrée d'un véhicule sans réservation (place attribuée automatiquement).
- [x] Autoriser l'entrée d'un véhicule avec réservation active.
- [x] Refuser l'entrée d'un véhicule déjà présent.
- [x] Refuser l'entrée en cas d'incompatibilité véhicule/place.
- [x] Demander une confirmation (pas un refus direct) si le justificatif PMR manque.
- [x] Calculer et faire payer une sortie (montant et paiement réels).
- [x] Refuser une sortie en cas de paiement refusé ou de véhicule non présent.
- [x] Publier un événement (webhook ou RabbitMQ) à chaque entrée/sortie/refus.
- [x] Lister/consulter l'historique des demandes et des événements publiés (audit).
- [x] **Borne client** (`/borne`) : le lien marche pour tout le monde, sans réglage ; le conducteur saisit sa plaque, entre ou sort, voit sa place ou son ticket (durée, montant payé) ; protégée par une clé borne qui ne permet que le passage d'un véhicule.
- [x] Simuler une borne d'entrée/sortie depuis le dashboard (décision, montant et paiement en direct).
- [x] Voir l'état du parking vu par Access : véhicules présents, dernières décisions, santé et version du service (dashboard + `GET /access/presences`).
- [x] Refuser une sortie datée avant l'entrée (cas limite, jamais transmis à Pricing/Payment).
- [x] Tracer chaque requête dans les logs par un correlation ID (`X-Correlation-ID`, reçu ou généré, renvoyé dans la réponse) et le **transmettre** à chaque service appelé et dans chaque événement publié.
- [x] Exposer des métriques métier Prometheus (opérations du parking, décisions, refus par motif, paiements, montants, véhicules présents, appels aux autres services, événements publiés).
- [x] Protéger toutes les routes par clé API (sauf `/health`, qui ne livre que l'état) ; clé borne distincte, limitée au passage d'un véhicule ; jeton de lecture distinct pour `/metrics`.
- [x] Exposer la version et le commit déployés (`/health`) et des métriques d'exploitation (`/metrics`, lisible par Prometheus avec un jeton de lecture).
- [x] Conserver les données (stationnements, décisions, événements) dans une base Postgres (Neon) qui survit aux redémarrages.
- [x] Plafonner la durée facturée à 7 jours et compter tout début de minute (règles 2.4 et 2.5).
- [x] Vérifier une réservation via le vrai service **Booking** (`GET /reservations/active`, à l'heure du passage) ; la place est prise dans le quota « réservation » de Parking, et la sortie ne refait pas payer le créneau déjà réglé (seul un dépassement est facturé).
- [x] Identifier un véhicule via le vrai service **Vehicles** (`POST /api/vehicle/create` : plaque → identifiant, création si inconnue ; puis `GET /api/vehicle/{identifiant}` ; routes réglables, et retrouvées automatiquement dans le Swagger de Vehicles s'il les renomme).
- [x] Attribuer/occuper/libérer une place via le vrai service **Parking** (place mise de côté puis confirmée avec son `hold_id`).
- [x] Vérifier que chaque catégorie demandée existe chez Parking (`GET /parking/categories`, en cache 5 min) : une catégorie renommée donne un motif précis, pas « Parking indisponible ».
- [x] Afficher l'occupation par catégorie vue par Parking (prises, mises de côté, capacité) et ses libellés (dashboard, borne, `GET /access/presences`).
- [x] Calculer un prix via le vrai service **Pricing**.
- [x] Exécuter un paiement via le vrai service **Payment** (idempotent : rejouer une sortie ne débite jamais deux fois).

> Une case n'est cochée que si le comportement est réellement vérifié
> (tests automatisés, et pour les services réels : passages de bout en bout
> depuis la borne du dashboard contre les services déployés de l'équipe).

### Tableau de suivi (axes de maturité)

| Axe | État | Ce qui le prouve |
|---|---|---|
| **Métier** | ✅ Entrée (avec/sans réservation), sortie payée, refus (présence, compatibilité, paiement, date incohérente), confirmation PMR / véhicule inconnu | Règles pures dans `src/domain/rules/`, use cases `ProcessEntryRequest` / `ProcessExitRequest`, tests unitaires |
| **API** | ✅ REST documentée (`/docs`), entrées/sorties validées, erreurs normalisées, `/health` | [section 11](#11-endpoints) |
| **Intégration** | ✅ Les 5 services réels (Vehicles, Booking, Parking, Pricing, Payment, en REST) ; événements publiés sur RabbitMQ (bus d'équipe) | [section 5](#5-brancher-un-vrai-microservice-à-la-place-dun-mock), [section 6](#6-publication-dévénements--webhook-ou-rabbitmq) |
| **UI** | ✅ Borne client `/borne` (entrée/sortie, clavier à l'écran, ticket, clair/sombre, mobile) et dashboard servi par Access : borne d'entrée/sortie, état du parking (présences, occupation vue par Parking, décisions, santé), journal d'événements, recherche | [section 12](#12-borne-et-journal-de-bord-dashboard) |
| **Qualité** | ✅ 491 tests (unitaires + intégration), entrées invalides et cas limites couverts, `ruff` (lint + format), script de vérification reproductible | [section 9](#9-tests-et-qualité) |
| **Observabilité** | ✅ Correlation ID propagé à tous les services et événements, logs par décision, `/metrics` Prometheus (techniques + métier + intégration), Prometheus et Grafana fournis ([`tp/prometheus`](tp/prometheus/README.md)), `/health` avec version et commit | [section 9](#métriques-prometheus) |
| **CI/CD et déploiement** | ✅ GitHub Actions (lint → tests → bandit → pip-audit → gitleaks), déploiement Render après CI verte, smoke test de l'instance déployée (version vérifiée), CHANGELOG, Dependabot | [section 9](#intégration-continue-cicd), [section 14](#14-déploiement-sur-render) |
| **Sécurité** | ✅ Clé API (comparaison en temps constant) sur toutes les routes sauf `/health`, clé borne limitée au passage d'un véhicule, refus de démarrer en production avec une clé faible, validation stricte, erreurs sans stack trace, en-têtes de sécurité, CORS restreint, rate limiting, secrets hors Git, plaque jamais stockée/publiée/renvoyée/loggée (test dédié) | [section 10](#10-sécurité) |
| **Version** | `4.28.0` (`src/__init__.py`, exposée par `/health` et `/docs`) | [CHANGELOG](CHANGELOG.md) |
| **Dernière mise à jour** | 24 novembre 2026 | |

### Suivi des jalons

| Jalon | Date | État |
|---|---|---|
| 5 — Structuration du rendu | 3 septembre | ✅ README, fiche d'identité, axes de maturité, version, date |
| 6 — MVP métier et API | 22 octobre | ✅ Workflows entrée/sortie, API documentée, `/health` |
| 7 — Première intégration | 28 octobre | ✅ Pricing, Parking, Payment puis Vehicles branchés en réel |
| 8 — UI de démonstration et d'exploitation | 18 novembre (matin) | ✅ Onglet « État du parking » ajouté (objets métier, état, opérations, résultats) |
| 9 — Qualité et fiabilité | 18 novembre (après-midi) | ✅ Validation renforcée, cas limites, logs avec correlation ID, smoke test |
| 10-11 — Revue de code et d'intégration | 24 novembre | ✅ Dossier préparé : [docs/REVUE.md](docs/REVUE.md) (contrats, échanges, workflows, écarts constatés) |
| 12 — Traçabilité | 25 novembre (matin) | ✅ Correlation ID reçu ou généré, loggé, transmis à tous les services appelés et dans les événements |
| 13 — Observabilité | 25 novembre (après-midi) | ✅ `/metrics` : métriques techniques, métier et d'intégration ; [config Prometheus](tp/prometheus/prometheus.yml) |
| 14 — CI/CD et déploiement | 27 novembre (matin) | ✅ CI 5 étapes, déploiement après CI verte, smoke test de l'instance déployée, CHANGELOG |
| 15 — Sécurisation | 27 novembre (après-midi) | ✅ Authentification, validation, secrets, erreurs, en-têtes de sécurité |
| 16-18 — Synthèse et présentation | 16 et 18 décembre | ⏳ À préparer |

---

## Sommaire

1. [Présentation](#1-présentation)
2. [Prérequis & installation](#2-prérequis--installation)
3. [Lancement & Swagger](#3-lancement--swagger)
4. [Architecture hexagonale](#4-architecture-hexagonale)
5. [Brancher un vrai microservice à la place d'un mock](#5-brancher-un-vrai-microservice-à-la-place-dun-mock)
6. [Publication d'événements : webhook ou RabbitMQ](#6-publication-dévénements--webhook-ou-rabbitmq)
7. [Ajouter une règle métier](#7-ajouter-une-règle-métier)
8. [Enums (tables de correspondance)](#8-enums-tables-de-correspondance)
9. [Tests et qualité](#9-tests-et-qualité)
10. [Sécurité](#10-sécurité)
11. [Endpoints](#11-endpoints)
12. [Borne et journal de bord (dashboard)](#12-borne-et-journal-de-bord-dashboard)
13. [Postman](#13-postman)
14. [Déploiement sur Render](#14-déploiement-sur-render)
15. [Rejoindre l'équipe : brancher vos microservices](#15-rejoindre-léquipe--brancher-vos-microservices)
16. [Écarts assumés par rapport à la spec](#16-écarts-assumés-par-rapport-à-la-spec)
17. [TP Splunk (à côté du service)](#17-tp-splunk-à-côté-du-service)
18. [TP Prometheus (supervision des microservices)](#18-tp-prometheus-supervision-des-microservices)

---

## 1. Présentation

Access est le **point central** du workflow d'entrée/sortie du parking. Il ne
possède **aucune donnée métier des autres services** (identité véhicule,
réservations, disponibilité des places, tarifs, transactions) : il les
interroge via 5 ports dédiés (Vehicles, Booking, Parking, Pricing et
Payment, tous réels) et ne conserve en propre
que ses propres objets métier (`AccessRequest`, `AccessAuthorization`,
`AccessEvent`) plus un cache technique de présence (`vehicle_presence`).

```mermaid
sequenceDiagram
    participant V as Véhicule
    participant A as Access
    participant Ve as Vehicles
    participant B as Booking
    participant P as Parking
    participant Pr as Pricing
    participant Pa as Payment

    V->>A: Entrée (plaque)
    A->>Ve: POST /api/vehicle/create (plaque → pseudoId, crée si inconnue)
    A->>Ve: GET /api/vehicle/{pseudoId}
    Ve-->>A: pseudoId (= vehicleId) + attributs
    A->>B: GET /reservations/active?vehicle_id=…&at=…
    alt réservation valable
        A->>P: hold (type réservé, quota « booking ») puis confirm_entry
    else pas de réservation
        A->>P: hold (type du véhicule, quota « walkin ») puis confirm_entry
    end
    A-->>V: Autorisation (AUTHORIZED / REFUSED / CONFIRMATION_REQUIRED)
    A--)A: Publie VEHICLE_ENTERED / ACCESS_REFUSED

    V->>A: Sortie (plaque)
    A->>Ve: POST /api/vehicle/create puis GET /api/vehicle/{pseudoId}
    A->>Pr: calculate_price(...)
    Pr-->>A: amount
    A->>Pa: POST /payments (clé d'idempotence = stationnement)
    loop toutes les 2 s, 40 s max
        A->>Pa: GET /payments/{id}
    end
    Pa-->>A: ACCEPTED / REFUSED
    A-->>V: Autorisation de sortie
    A--)A: Publie VEHICLE_EXITED / ACCESS_REFUSED
```

**Règle absolue (RGPD) : la plaque ne fait que traverser Access.** La borne
envoie la plaque lue ; Access la transmet à Vehicles (règle 3.7 : Access
*demande* l'identifiant à Vehicles), seul service qui la conserve, puis
l'oublie (`del plate` dans `ProcessEntryRequest` / `ProcessExitRequest` /
`CheckVehicleKnown`). À l'entrée, `identify_vehicle` retrouve le véhicule ou
le fait créer par Vehicles s'il est inconnu (règle 3.2) ; à la sortie et
pour la vérification, `get_vehicle_info` ne fait que consulter. Seul le
`pseudoId` renvoyé par Vehicles (le `vehicleId`) est persisté, publié et
renvoyé. La plaque n'apparaît dans aucune table, aucun événement, aucune
réponse (y compris les erreurs 422, dont la valeur reçue est retirée) ni
aucun log : `tests/integration/test_no_plate_leak.py` le vérifie, et un
filtre de logging masque en plus toute sous-chaîne au format plaque, en
défense en profondeur (voir [section 10](#10-sécurité)).

---

## 2. Prérequis & installation

- Python 3.11+ (testé avec 3.12)

```bash
# Toujours travailler dans un environnement virtuel — jamais d'installation globale.
python -m venv .venv

# Activation
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate            # Windows

pip install -r requirements.txt

# Configuration
cp .env.example .env
# Ajustez .env si besoin (API_KEY, EVENT_SUBSCRIBERS_URLS pour brancher vos
# coéquipiers en local, EVENT_PUBLISHER=rabbitmq si vous préférez un vrai
# broker, etc.)
```

---

## 3. Lancement & Swagger

```bash
uvicorn src.interfaces.api.main:app --reload --port 8000
```

- Swagger UI : http://localhost:8000/docs
- ReDoc : http://localhost:8000/redoc
- Journal de bord (dashboard) : http://localhost:8000/ (redirige vers `/static/dashboard.html`)
- Healthcheck (sans clé API) : http://localhost:8000/health

Toutes les autres routes exigent l'en-tête `X-API-Key` (valeur de `API_KEY`
dans `.env`, `change-me` par défaut). Dans Swagger, cliquez sur **Authorize**
et collez la clé.

Les véhicules sont ceux du vrai service Vehicles (voir son
[Swagger](https://parking-vehicles.onrender.com/swagger-ui/index.html)) : il
suffit d'envoyer une plaque, française ou étrangère (voir « Formats de
plaque » ci-dessous). Une plaque inconnue est créée chez Vehicles à l'entrée, comme un
4 roues standard ; pour tester un profil précis (PMR, électrique, XL, 2
roues), enregistrez-le d'abord chez Vehicles (`POST /api/vehicle/create`).

**Formats de plaque** : toutes les plaques sont acceptées, en majuscules ou
minuscules, avec ou sans espaces, tirets ou points :

| Saisie | Envoyé à Vehicles | Règle |
|---|---|---|
| `ab 123 cd`, `AB123CD` | `AB-123-CD` | plaque française SIV : forme avec tirets conservée (déjà connue de Vehicles) |
| `123 ABC 75` | `123ABC75` | ancien format français (FNI) : séparateurs retirés |
| `B-MW 1234` + pays `DE` | `DE:BMW1234` | plaque étrangère : pays en préfixe, séparateurs retirés |
| `AB 123 CD` + pays `IT` | `IT:AB123CD` | plaque italienne : **jamais confondue** avec la française `AB-123-CD` |
| `B-MW 1234` sans pays | `BMW1234` | appel sans pays (avant 4.8.0) : plaque traitée comme française |

**Pays de la plaque** (`country`, 4.8.0) : l'Italie utilise exactement le
format français `AB 123 CD` ; sans le pays, deux voitures différentes
seraient le même véhicule chez Vehicles. La borne demande donc le pays
(France par défaut), et Access l'envoie à Vehicles sous la forme
`<code ISO>:<plaque>` pour toute plaque non française. Les plaques
françaises gardent leur forme : les véhicules déjà enregistrés sont
retrouvés. Le format est vérifié pour la France (SIV ou FNI), l'Italie,
l'Espagne, l'Allemagne, la Belgique, la Suisse et le Royaume-Uni ; pour les
Pays-Bas, le Luxembourg, le Portugal et « autre pays » (`XX`), contrôle
générique. Une plaque qui ne correspond pas au pays choisi est refusée (422,
sans recopier la plaque).

Une même plaque saisie de deux façons donne toujours le même véhicule chez
Vehicles (entrée « B-MW 1234 », sortie « bmw1234 », même pays). Refusé
(422) : moins de 2 ou plus de 10 lettres et chiffres, ou un autre caractère
(`#`, `_`, lettres accentuées…).
Les tests automatisés utilisent un registre déterministe de plaques
`AA-111-AA` à `HH-888-HH` (`DEMO_VEHICLES`, dans
[`tests/unit/fakes.py`](tests/unit/fakes.py)) qui couvre chaque profil
(2 roues, XL, électrique, PMR avec/sans justificatif, réservation...).

---

## 4. Architecture hexagonale

```
src/
├── domain/            # Cœur métier pur — ZÉRO dépendance externe
│   ├── entities/       # AccessRequest, AccessAuthorization, AccessEvent, VehiclePresence
│   ├── value_objects/  # Enums tinyint + DTO (VehicleType, PlaceType, VehicleInfo, ...)
│   ├── rules/          # Fonctions pures : présence, compatibilité véhicule/place, accessibilité
│   └── ports/          # Protocol — contrats vers l'extérieur (aucune implémentation)
│
├── application/
│   └── use_cases/      # Orchestration : ProcessEntryRequest, ProcessExitRequest, ...
│                         # Ne dépend QUE de domain (ports + entités + règles)
│
├── infrastructure/     # Implémentations concrètes des ports
│   ├── db/              # SQLAlchemy : modèles, session, repositories SQL (SQLite local, Postgres Neon en prod)
│   ├── external/        # Clients HTTP (5 services, mock Booking) + OutboxEventPublisher/
│   │                      # RabbitMQEventPublisher (publication d'événements — aussi des
│   │                      # appels vers l'extérieur, donc regroupés ici plutôt qu'à part)
│   ├── ai/              # Adaptateur LPR/vision fake déterministe
│   ├── security/        # Authentification X-API-Key
│   ├── config.py        # Lecture centralisée de l'environnement (.env)
│   └── logging_config.py# Logs + filtre anti-fuite de plaque
│
└── interfaces/api/     # FastAPI : point d'entrée HTTP
    ├── main.py           # App, middlewares, gestion d'erreurs centralisée, dashboard
    ├── deps.py           # Composition root — SEUL endroit qui relie tout
    ├── rate_limit.py      # Limiter slowapi partagé
    ├── static/            # Dashboard (journal de bord, page statique)
    ├── routers/           # access_router, events_router, health_router
    └── schemas/           # Pydantic (requêtes/réponses), jamais la plaque en sortie
```

**Règle de dépendance stricte** : `domain` ne dépend de rien.
`application` ne dépend que de `domain`. `infrastructure` implémente les ports
de `domain`. `interfaces/api` est le seul endroit qui connaît à la fois
`application` et `infrastructure` (via `deps.py`, la *composition root*).

Pourquoi ce découpage ? Parce que la vraie complexité d'Access n'est pas
technique mais **métier** (règles de compatibilité, présence, accessibilité)
— les isoler dans `domain`, sans aucune dépendance à
FastAPI/SQLAlchemy/httpx, permet de les tester unitairement en une fraction
de seconde, et de changer n'importe quel détail d'infrastructure (base de
données, broker d'événements, vrais clients HTTP) sans jamais toucher à la
logique de décision.

### Comment une requête traverse les couches

Exemple concret, `POST /access/requests` (entrée) :

1. **`interfaces/api`** reçoit le JSON, le valide via un schéma Pydantic
   (`AccessRequestIn`), résout les dépendances via `deps.py` (composition
   root), et appelle `ProcessEntryRequest.execute(...)`.
2. **`application`** (`ProcessEntryRequest`) orchestre l'appel : résout le
   véhicule, vérifie la présence, cherche une réservation ou une place,
   applique les règles de compatibilité/accessibilité — **en ne
   manipulant que des types de `domain`** (`VehicleInfo`, `PlaceType`,
   `AuthorizationResult`...), jamais un détail HTTP ou SQL.
3. **`domain/rules`** exécute les fonctions pures (`is_compatible`,
   `requires_disability_confirmation`...) — aucune dépendance, testables
   isolément.
4. **`infrastructure`** exécute le travail concret derrière chaque port
   appelé par le use case : `HttpParkingClient` fait le vrai appel HTTP,
   `SqlAccessRepository` écrit en base, `RabbitMQEventPublisher` publie
   sur le bus.
5. Le use case renvoie un DTO (`EntryDecision`) à `interfaces/api`, qui le
   sérialise en JSON de réponse.

À aucun moment `ProcessEntryRequest` ne sait si `ParkingServicePort` est
un mock, un vrai appel HTTP, ou (en test) un double — **c'est tout l'intérêt**.

### Preuve concrète : la résilience, gratuite grâce au découpage

Quand Parking ou Pricing renvoient une erreur inattendue (429, 5xx,
timeout — cf. `infrastructure/external/http_parking_client.py` et
`http_pricing_client.py`), Access doit refuser proprement plutôt que
planter. Grâce au découpage hexagonal, **ce correctif tient entièrement
dans la couche `infrastructure`** :

```python
# domain/ports/pricing_service_port.py — le contrat autorise déjà l'échec
def calculate_price(...) -> Decimal | None: ...  # None = indisponible

# infrastructure/external/http_pricing_client.py — seul endroit qui change
try:
    response = client.post(f"{self._base_url}/quote", json=payload)
    response.raise_for_status()
except httpx.HTTPError:
    return None  # jamais un montant inventé, jamais un crash
```

`ProcessExitRequest` (couche `application`) n'a **pas eu besoin d'être
réécrit** : il savait déjà gérer un port qui répond "indisponible" pour
Parking (`request_place` renvoie déjà `None` → refus "Aucune place
disponible" depuis l'intégration initiale) — il a suffi d'ajouter la même
vérification pour le montant Pricing. Aucun test existant n'a cassé,
aucune route, aucun schéma n'a changé.

---

## 5. Brancher un vrai microservice à la place d'un mock

Chaque service externe a eu sa **propre bascule mock/réel**
(`VEHICLES_USE_MOCK`, `BOOKING_USE_MOCK`, `PARKING_USE_MOCK`,
`PRICING_USE_MOCK`, `PAYMENT_USE_MOCK` — seule `BOOKING_USE_MOCK` subsiste,
les autres ont disparu depuis que ces services sont branchés en réel) — `USE_MOCKS` reste la valeur par
défaut globale tant qu'aucune bascule individuelle n'est définie. **C'est
volontaire** : vos camarades finissent leur service chacun à son rythme, pas
question d'attendre que les 5 soient prêts pour en brancher un premier. Les
5 squelettes HTTP existent déjà (`infrastructure/external/http_*_client.py`),
chacun avec des `TODO` explicites listant ce qui reste à confirmer avec
l'équipe du service concerné (route exacte, méthode HTTP, noms de champs
JSON, codes d'erreur). **Depuis le 24/11, les 5 services sont réels**, Booking
compris (dernier branché, 4.6.0). `BOOKING_USE_MOCK=true` le simule encore
pour les tests et le développement hors ligne ; `USE_MOCKS` n'a plus
d'effet. `GET /health` indique `"booking": "réel"` ou `"simulé"` : c'est la
façon la plus simple de vérifier ce que Render utilise vraiment. Une
ancienne valeur `BOOKING_SERVICE_URL=http://localhost…` restée dans Render
est ignorée (Access utilise alors `https://booking-api-vhy5.onrender.com`).

> ⚠️ **CORS n'a rien à voir avec ce branchement.** `CORS_ALLOWED_ORIGINS`
> ne concerne que du JavaScript exécuté **dans un navigateur** qui
> appellerait l'API Access depuis un autre domaine — pas les appels
> serveur-à-serveur (Access → Booking via `httpx`, ou l'inverse). Rien à
> configurer côté CORS pour brancher un microservice de l'équipe.

**Aucune autre couche à toucher** : ni `domain`, ni `application`, ni les
routers, ni les schémas — c'est toute la promesse de l'architecture
hexagonale. Le même principe s'applique identiquement à Booking, Parking,
Pricing et Payment (`get_booking_port`, `get_parking_port`, etc., dans le
même fichier `deps.py`) — chaque squelette liste ses propres `TODO` :

| Service  | Fichier squelette                      | Points ouverts principaux |
|----------|------------------------------------------|----------------------------|
| **Vehicles** | `http_vehicles_client.py` | **✅ Branché** (`POST /api/vehicle/create` : plaque → pseudoId, création si inconnue, véhicule connu jamais réécrit ; puis `GET /api/vehicle/{pseudoId}` ; routes réglables par `VEHICLES_IDENTIFY_PATH` et `VEHICLES_LOOKUP_PATH`, Vehicles ayant changé son contrat cinq fois le 24/11 ; **sur un 404, routes retrouvées automatiquement dans son Swagger** (`/v3/api-docs`), réessai immédiat, routes mémorisées et loggées en avertissement ; `GET /api/vehicle/{id}/plate`, qui redonne la plaque pour la facturation, n'est jamais appelé par Access (à protéger par une clé côté Vehicles, REVUE 28) ; `{plate}` dans la route de consultation rétablit l'ancien mode « par plaque ») — `pseudoId` devient le `vehicleId`, `disabled` vaut type PMR **et** justificatif, toute autre réponse = véhicule non identifié, voir section 16 |
| **Booking** | `http_booking_client.py` | **✅ Branché** (`GET /reservations/active?vehicle_id=…&at=…`, toujours 200 : `valid` + réservations confirmées couvrant l'instant ; mêmes codes de type de place que Parking ; panne → entrée sans réservation). Pas de place nominative : la place est prise chez Parking, type réservé, quota « booking » |
| **Parking** | `http_parking_client.py` | **✅ Branché** (`hold` → `confirm_entry` avec le `hold_id` reçu, place mise de côté 30 s → `free` ; catégories STANDARD/XL/ELECTRIC/HANDICAPPED/TWO_WHEELS vérifiées sur `GET /parking/categories` avant chaque `hold` (liste en cache 5 min ; une catégorie absente ou un 404 sur `hold` → « Catégorie de place X inconnue du service Parking ») ; libellé de Parking remonté ; occupation lue sur `GET /parking/occupation` ; en-tête `X-API-Key` = `PARKING_API_KEY`) — pas de `placeId` réel, encodage synthétique `"CATEGORIE:walkin\|booking"`, voir section 16 |
| **Pricing** | `http_pricing_client.py` | **✅ Branché** (`PRICING_USE_MOCK=false`) contre le vrai service (`POST /quote`) — **Pricing calcule seul le montant** à partir de la zone, du mode et de la durée envoyés par Access (gratuité initiale et quarts d'heure appliqués par Pricing) ; zone PMR `handicapped` depuis sa grille v2 du 24/11 (ancien nom `disabled` réessayé sur `ZONE_NOT_FOUND`) — mapping `PlaceType → zone` et arrondi de durée pour les réservations restent des hypothèses documentées dans le fichier, voir aussi section 16 |
| **Payment** | `http_payment_client.py` | **✅ Branché** (`POST /payments` puis polling `GET /payments/{id}` jusqu'à `ACCEPTED`/`REFUSED`, 2 s / 40 s max) — montant en centimes, clé d'idempotence `access:{stationnement}:exit`, en-tête `X-API-Key` envoyé si `PAYMENT_API_KEY` est renseignée, voir section 16 |

---

## 6. Publication d'événements : webhook ou RabbitMQ

Deux implémentations d'`EventPublisherPort` sont prêtes, sélectionnées par
`EVENT_PUBLISHER` dans `.env` (bascule dans `deps.py::get_event_publisher()`)
— dans les deux cas, l'événement est **toujours** persisté (`access_events`
+ `outbox_events`) avant toute tentative de diffusion, et un échec de
diffusion est loggé mais ne bloque jamais la décision d'accès :

- **`webhook`** (par défaut) — fan-out HTTP best-effort vers chaque URL de
  `EVENT_SUBSCRIBERS_URLS` (voir `outbox_event_publisher.py`). Pas de vrai
  broker : chaque coéquipier expose sa propre route (ex. `POST
  /webhooks/access`) et te donne son URL.
- **`rabbitmq`** (utilisé actuellement) — publie sur l'exchange **partagé
  de l'équipe** `microservice-event-bus` (routing keys `access.entry` /
  `access.exit` / `access.refused` / `access.other`) via
  `rabbitmq_event_publisher.py`, hébergé sur **CloudAMQP** (broker externe,
  gratuit, pas de service Render supplémentaire). Dans `.env` :
  `EVENT_PUBLISHER=rabbitmq` et `RABBITMQ_URL=amqps://user:pass@host/vhost`
  (fourni par CloudAMQP). ⚠️ L'exchange est créé/administré ailleurs (par
  l'équipe) : Access le vérifie en passif (`exchange_declare(...,
  passive=True)`) sans jamais tenter de le recréer — évite l'erreur `406
  PRECONDITION_FAILED` si les paramètres ne correspondent pas exactement.
  Chaque coéquipier intéressé déclare sa propre queue et la lie aux routing
  keys qui l'intéressent (`access.#` pour tout recevoir de nous). Pour
  tester avec un broker RabbitMQ local à la place (Docker) :

  ```bash
  docker run -d --name local-rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
  ```

  Puis `RABBITMQ_URL=amqp://guest:guest@localhost:5672/%2F` — mais il
  faudra déclarer l'exchange soi-même (`durable=True`, pas seulement
  `passive=True`) puisqu'il n'existera pas encore localement ; voir
  l'historique git de `rabbitmq_event_publisher.py` pour un exemple de
  déclaration active si besoin.

**Simuler des événements pour les autres services** :
[`scripts/simulate_bus_events.py`](scripts/simulate_bus_events.py) publie à
intervalles réguliers des entrées (`access.entry`) et sorties
(`access.exit`, avec heure d'entrée, durée et montant cohérents) au
format exact d'Access, sans passer par la borne ni
appeler Parking/Pricing/Payment. Ils sont marqués comme simulés
(`vehicleId` en `sim-…`, `payload.simulated = true`, `app_id =
access-simulator`). `listen_event_bus.py` permet de vérifier la réception.

```bash
RABBITMQ_URL=amqps://… python scripts/simulate_bus_events.py --interval 30
```

Dans les deux cas, `GET /access/events` reste disponible pour relire les
événements journalisés côté Access (utile même avec RabbitMQ, pour du debug
local sans ouvrir l'interface de gestion).

---

## 7. Ajouter une règle métier

1. Ajoutez une fonction pure dans `src/domain/rules/` (ex.
   `my_new_rule.py`), sans import vers `infrastructure`/`interfaces`.
2. Testez-la unitairement dans `tests/unit/` sur toute sa matrice de cas.
3. Branchez-la dans le use case concerné
   (`src/application/use_cases/process_entry_request.py` ou
   `process_exit_request.py`), en l'appelant au bon endroit du déroulé.
4. Ajoutez un test d'intégration si la règle change une réponse API visible.

Exemple concret déjà en place : `vehicle_place_compatibility_rule.py` (règle
2 roues/4 roues/XL/électrique/handicapé) et `disability_rule.py`, toutes deux
appelées depuis `ProcessEntryRequest.execute`.

---

## 8. Enums (tables de correspondance)

Toutes les valeurs sont définies dans
[`src/domain/value_objects/enums.py`](src/domain/value_objects/enums.py).

**RequestType** — `1=ENTRY` · `2=EXIT`

**RequestStatus** — `1=IN_PROGRESS` · `2=PROCESSED` · `3=REJECTED` (réservé
au cas "véhicule non identifié par Vehicles")

**AuthorizationResult** — `1=AUTHORIZED` · `2=REFUSED` · `3=CONFIRMATION_REQUIRED`

**EventType** — `1=VEHICLE_ENTERED` · `2=VEHICLE_EXITED` · `3=ACCESS_REFUSED` · `4=OTHER`

**DetectionSource** — `1=CAMERA` · `2=TERMINAL` · `3=LPR` · `4=MOBILE_APP`
(pour une sortie, `TERMINAL` et `MOBILE_APP` sont tous deux valides)

**PresenceStatus** *(technique)* — `1=IN` · `2=OUT`

**VehicleCategory** *(technique, véhicule ET place)* — `1=TWO_WHEELER` · `2=FOUR_WHEELER`

---

## 9. Tests et qualité

```bash
source .venv/bin/activate
pytest              # unitaires + intégration
pytest tests/unit           # règles métier + use cases (ports mockés)
pytest tests/integration    # endpoints via TestClient FastAPI (SQLite en mémoire, clés étrangères actives)
ACCESS_TEST_DATABASE_URL=<url Postgres> pytest tests/integration   # idem contre une vraie base Postgres
pytest -v            # détail de chaque cas
```

Couverture (491 tests) :

- **Unitaires** — matrice complète de la règle de compatibilité
  véhicule/place, règle de présence, règle d'accessibilité ; chaque use case
  (`ProcessEntryRequest`, `ProcessExitRequest`) avec tous les ports mockés ;
  comportement best-effort de `RabbitMQEventPublisher` (broker injoignable) ;
  clients Payment et Vehicles contre un faux serveur (`httpx.MockTransport`) :
  contrat du payload, polling, refus définitif, rejeu idempotent, délai
  dépassé, erreurs serveur ; mapping de la réponse Vehicles, plaque inconnue
  (404) créée seulement à l'entrée, jamais sur une panne, panne réseau,
  réponse inattendue, plaque absente des logs ; règle `stay_rule` (sortie
  avant l'entrée) ; vue des véhicules présents (`ListPresentVehicles`).
- **Intégration** — entrée autorisée (sans/avec réservation), entrée refusée
  (déjà présent, type incompatible), entrée en confirmation requise
  (accessibilité), plaque inconnue créée puis autorisée, Vehicles en panne
  (agent requis), plaque normalisée, sortie autorisée,
  sortie refusée (paiement échoué, véhicule non présent), `/health`,
  `/access/vehicles/known`, `/access/presences` (suit entrée puis
  sortie). `test_quality.py` couvre les **entrées invalides** (corps vide,
  plaque avec caractère interdit, vide, trop courte ou trop longue (toutes
  les formes acceptées sont testées : SIV, ancien format, étrangères), type/source inconnus, date illisible, JSON
  mal formé, photo corrompue, période inversée, `limit` hors bornes, clé
  invalide), les **cas limites** (sortie datée avant l'entrée, date sans
  fuseau) et les **logs** (correlation ID reçu/généré/assaini, décision
  loggée avec son cid, niveaux de log). `test_correlation_propagation.py`
  vérifie la transmission du correlation ID (HTTP et RabbitMQ) et les
  métriques des appels sortants ; `test_observability.py` les métriques
  métier, la jauge des présences et les en-têtes de sécurité ;
  `test_security.py` la gestion des secrets au démarrage ;
  `test_no_plate_leak.py` rejoue des passages variés et vérifie qu'aucune
  plaque n'apparaît dans les réponses, la base, les événements ni les logs.

### Intégration continue (CI/CD)

Chaque push sur `main` et chaque pull request déclenche le pipeline
GitHub Actions [`.github/workflows/ci.yml`](.github/workflows/ci.yml), composé
de 5 jobs qui s'enchaînent **en file** (chaque étape attend la réussite de la
précédente, `needs:` dans le workflow) et doivent **tous** passer — si une
étape échoue, les suivantes ne sont pas lancées :

| Job | Outil | Ce qu'il vérifie |
|---|---|---|
| Lint | `ruff` | Erreurs, imports, bugs probables, règles de sécurité, **formatage homogène** (config : `ruff.toml`) |
| Tests | `pytest` | Les 491 tests unitaires + intégration, sans aucun secret |
| Sécurité du code | `bandit` | Analyse statique (SAST) : injections, appels dangereux, secrets en dur… |
| Dépendances | `pip-audit` | Vulnérabilités connues (CVE) dans `requirements.txt` |
| Secrets | `gitleaks` | Aucun secret (clé API, URL CloudAMQP…) dans tout l'historique git |

Un second workflow, [`smoke.yml`](.github/workflows/smoke.yml), vérifie
l'**instance déployée** (manuellement ou chaque matin de semaine) avec
`scripts/smoke_test.sh`, y compris que la version en ligne est bien celle du
dépôt. Il a besoin du secret GitHub `ACCESS_API_KEY` (sinon il s'ignore).

**Procédure de déploiement reproductible** : fusion d'une PR dans `main` →
CI → déploiement automatique Render (`render.yaml`, configuration par
variables d'environnement) → `GET /health` doit afficher la nouvelle
`version` et le `commit` fusionné → workflow « Smoke test ». Chaque version
est décrite dans le [CHANGELOG](CHANGELOG.md). ⚠️ Après une modification
des variables de `render.yaml`, vérifier dans **Render → Environment**
qu'elles sont bien appliquées (incident du 18/11, voir
[docs/REVUE.md](docs/REVUE.md)).

Render est configuré en **Auto-Deploy : After CI Checks Pass** : un commit
sur `main` n'est déployé que si le pipeline est entièrement vert. En
complément, **Dependabot** ([`.github/dependabot.yml`](.github/dependabot.yml))
ouvre chaque semaine une PR de mise à jour des dépendances Python et des
actions GitHub, elle-même validée par la CI.

Reproduire la CI en local :

```bash
pip install -r requirements-dev.txt
ruff check src tests && ruff format --check src tests && pytest && bandit -r src -q && pip-audit -r requirements.txt
```

### Vérifier une instance déployée (smoke test)

[`scripts/smoke_test.sh`](scripts/smoke_test.sh) rejoue les contrôles
essentiels contre n'importe quelle instance (locale ou Render) et sort en
erreur si l'un d'eux échoue : santé et version, authentification (401),
validation des entrées (422/400/404), `/metrics`, `/access/presences`.
Avec `VEHICLE_PLATE` (une plaque de test, créée chez Vehicles si besoin), il enchaîne en plus
un vrai passage entrée → présence → sortie payée — ⚠️ ce mode appelle
réellement Parking, Pricing et Payment.

```bash
BASE_URL=http://localhost:8000 API_KEY=change-me ./scripts/smoke_test.sh
```

```bash
BASE_URL=https://access-api-a1u7.onrender.com API_KEY=<clé Render> VEHICLE_PLATE=<plaque de test> ./scripts/smoke_test.sh
```

Toutes ses requêtes portent le même `X-Correlation-ID` (affiché en tête) :
il suffit de le chercher dans les logs Render pour retrouver tout le passage.

### Batterie de tests en ligne (borne publique)

[`scripts/tests_en_ligne.py`](scripts/tests_en_ligne.py) fait 59 contrôles
contre le service en ligne, sans clé : santé et version, pages, routes
protégées (401), en-têtes de sécurité, erreurs de saisie, puis de **vrais
passages** avec les cinq services (un par type de véhicule, refus attendus,
plaques française et italienne identiques). Toujours dans la première heure
gratuite : 0 €, aucun paiement. Environ 3 minutes (10 passages par minute
au plus sur la borne publique).

```bash
python3 scripts/tests_en_ligne.py
```

Avec `VEHICLES_API_KEY`, les véhicules de test sont ensuite supprimés chez
Vehicles (son `DELETE` exige une clé depuis le 24/11).

### Bilan du journal après un test

[`scripts/bilan_journal.py`](scripts/bilan_journal.py) résume ce qui s'est
passé pendant un test, avec la clé d'exploitation (gardée sur votre
machine) : décisions par sens, motifs de refus du plus fréquent au plus
rare, activité minute par minute (pour repérer un pic ou une panne), et
véhicules restés dans le parking avec leur ancienneté. Aucune plaque : les
véhicules sont désignés par le début de leur identifiant pseudonymisé.

```bash
API_KEY=<clé Render> python3 scripts/bilan_journal.py --depuis 2026-11-24T14:00:00Z
```

### Agents Claude Code du projet

Le dossier [`.claude/agents/`](.claude/agents) contient quatre agents
spécialisés, à lancer depuis Claude Code en le demandant simplement
(« lance l'agent veille-api », « check les API des autres ») :

| Agent | Rôle |
|---|---|
| [`veille-api`](.claude/agents/veille-api.md) | Relit les Swagger de Vehicles, Booking, Parking, Pricing et Payment, les compare champ par champ à ce qu'Access envoie et lit, confirme par des appels réels en lecture seule, et dit quoi corriger |
| [`tests-complets`](.claude/agents/tests-complets.md) | Lint, tests locaux, version déployée et batterie en ligne ; diagnostique chaque échec (bug d'Access ou changement d'un autre service) |
| [`securite`](.claude/agents/securite.md) | Revue sécurité et RGPD : plaque jamais stockée, loggée ni renvoyée, routes protégées, secrets, dépendances, en-têtes, contrôles en ligne |
| [`doc-sharepoint`](.claude/agents/doc-sharepoint.md) | Vérifie que README, CHANGELOG et REVUE collent au code et au service en ligne (version, tests, routes, contrats), et corrige la doc |

Aucun agent ne crée de réservation ni de paiement réels, n'appelle la route
de Vehicles qui renvoie la plaque, ni ne tente de contourner une
authentification.

### Logs exploitables

Format : `date niveau module [cid=<correlation ID>] message`. Exemple réel
d'une entrée refusée :

```
2026-11-18 08:52:40,216 WARNING src.infrastructure.external.http_vehicles_client [cid=febf097b-…] Service Vehicles indisponible (ConnectError)
2026-11-18 08:52:40,219 WARNING src.application.use_cases.process_entry_request [cid=febf097b-…] Entrée rejetée : véhicule non identifié par Vehicles (request=a8e81710-…)
2026-11-18 08:52:40,221 INFO access.http [cid=febf097b-…] POST /api/v1/access/requests -> 200 (77 ms)
```

- **Correlation ID** (`src/interfaces/api/middleware.py`) : repris de
  l'en-tête `X-Correlation-ID` s'il est bien formé (`[A-Za-z0-9._-]`, 64
  caractères max — sinon ignoré, pour empêcher l'injection de fausses lignes
  de log), généré sinon (UUID), renvoyé dans l'en-tête de réponse et dans le
  corps des erreurs 500. Identifiant technique opaque : jamais de plaque ni
  de donnée personnelle.
- **Une ligne par décision métier** (use cases) : entrée/sortie autorisée,
  refusée (avec le motif), en attente de confirmation, véhicule inconnu —
  toujours avec l'id de la demande et le `vehicleId` pseudonymisé.
- **Log d'accès** : `INFO` pour les écritures (passages à la borne),
  `WARNING` pour toute réponse 4xx/5xx, `DEBUG` pour les lectures réussies
  (polling du dashboard), `/health` et les fichiers statiques — visibles
  avec `LOG_LEVEL=DEBUG`. Le log d'accès natif d'uvicorn est désactivé sur
  Render (`--no-access-log`) pour éviter les doublons sans cid.
- **Appels aux autres services** : chaque échec (timeout, 5xx, réponse
  inattendue) est loggé en `WARNING` par le client HTTP concerné.
- **Propagation (jalon 12)** : le même correlation ID est transmis dans
  l'en-tête `X-Correlation-ID` de **chaque appel sortant** (Vehicles, Booking,
  Parking, Pricing, Payment, webhooks — `infrastructure/external/outgoing_http.py`)
  et dans chaque **événement RabbitMQ** (propriété AMQP `correlation_id`,
  en-tête `X-Correlation-ID`, champ `correlationId` du corps). Un service qui
  le reprend dans ses logs permet de suivre un passage de bout en bout.

### Métriques Prometheus

`GET /metrics`, format Prometheus, servi par `prometheus_client`. **Protégé** :
il faut la clé d'exploitation ou le jeton de lecture `METRICS_TOKEN`, dans
`X-API-Key` ou `Authorization: Bearer` ; sans l'un des deux, 401 (voir
[section 10](#10-sécurité)). La réponse ne contient que des agrégats.

| Métrique | Type | Ce qu'elle mesure |
|---|---|---|
| `http_requests_total{method,handler,status}` | technique | Requêtes reçues par méthode, **gabarit de route** (`/api/v1/access/requests/{request_id}`, jamais le chemin reçu ; `none` pour une adresse inconnue) et classe de statut (`2xx`, `4xx`, `5xx`) : de quoi séparer succès et erreurs |
| `http_request_duration_seconds` | technique | Latences par gabarit de route |
| `parking_operations_total{operation,result}` | métier | Opérations du parking : `entry`, `exit`, `forced_exit` (sortie forcée par l'exploitation) × `authorized`, `refused`, `confirmation_required`. Séries présentes à zéro dès le démarrage |
| `access_decisions_total{type,result}` | métier | Entrées/sorties autorisées, refusées, en confirmation |
| `access_refusals_total{type,reason}` | métier | Refus par motif (déjà présent, aucune place, paiement refusé…) |
| `access_payments_total{outcome}` | métier | Paiements acceptés, refusés, indisponibles |
| `access_payment_amount_euros_total` | métier | Montant total encaissé |
| `access_vehicles_present` | métier | Véhicules actuellement dans le parking (lu en base) |
| `access_outgoing_requests_total{service,outcome}` | intégration | Appels vers chaque service, par issue (2xx, 4xx, 5xx, error) |
| `access_outgoing_request_duration_seconds{service}` | intégration | Durée des appels sortants |
| `access_events_published_total{channel,event_type,outcome}` | intégration | Événements diffusés (RabbitMQ / webhook), succès ou échec |

Les étiquettes ne contiennent jamais d'identifiant (véhicule, demande,
correlation ID) ni de plaque : valeurs bornées, aucune donnée personnelle.
`/health`, `/metrics` et `/static` ne sont pas comptés dans
`http_requests_total` : les lectures de Prometheus (toutes les 15 s) et la
sonde de Render ne gonflent pas l'activité mesurée. `/metrics` est hors
limitation de débit et hors du log d'accès courant (un 401 est loggé). Les compteurs vivent en
mémoire : ils repartent de zéro à chaque redémarrage du service (`rate()` et
`increase()` s'en accommodent).

Architecture : Prometheus reste dans `infrastructure/metrics.py`. Le domaine
et les cas d'usage ne l'importent pas ; les routes enregistrent la décision
rendue par le cas d'usage (`record_decision`, `record_forced_exit`).

**Visualiser avec Prometheus** : le dossier [`tp/prometheus`](tp/prometheus/README.md)
fournit l'image, la configuration (Access et les cinq autres services) et un
tableau de bord Grafana — pas-à-pas dans [`PROMETHEUS.md`](PROMETHEUS.md) :

```bash
cd tp/prometheus && ./demarrer.sh
```

Puis <http://localhost:9090> — requêtes utiles :

- `up` — quels services répondent
- `sum by (job) (rate(http_requests_total[2m]))` — requêtes par seconde
- `sum by (operation, result) (increase(parking_operations_total[5m]))` — opérations métier récentes
- `sum by (result) (increase(access_decisions_total[1h]))` — décisions de la dernière heure
- `sum by (reason) (increase(access_refusals_total[1h]))` — pourquoi on refuse
- `sum by (service, outcome) (rate(access_outgoing_requests_total[5m]))` — santé des services appelés
- `histogram_quantile(0.95, sum by (le, service) (rate(access_outgoing_request_duration_seconds_bucket[5m])))` — latence p95 par service
- `access_vehicles_present` — occupation vue par Access

---

## 10. Sécurité

- **Authentification** : clé API (`X-API-Key`) sur toutes les routes sauf
  `/health` (`src/infrastructure/security/api_key_auth.py`), comparée en
  temps constant (`hmac.compare_digest`). Jamais loggée.
- **Clé borne séparée** (`BORNE_API_KEY`) : les bornes client sont des écrans
  publics, la clé d'exploitation n'y est donc jamais saisie. La clé borne
  n'ouvre **que** `POST /access/requests` (faire passer un véhicule) : elle
  est refusée (401) sur l'historique, les présences, les événements,
  l'occupation Parking, la vérification de plaque et `/access/borne/key`.
  Seule la clé d'exploitation permet d'obtenir la clé borne
  (`GET /access/borne/key`, jamais loggée), pour mettre une borne en
  service depuis le dashboard. Elle doit faire 16 caractères au
  moins et différer d'`API_KEY` (sinon Access refuse de démarrer en
  production). Vide = pas de clé borne.
- **Borne publique** (`BORNE_PUBLIC`, activée par défaut) : pour que le
  lien `/borne` marche pour tout le monde sans réglage, la borne sans clé
  passe par `POST /borne/passages`, **sans clé**. Une page web publique ne
  peut pas cacher de secret : cette route est donc réduite au strict
  nécessaire. Elle ne fait que le passage d'un véhicule (mêmes règles
  métier), la date est imposée par le serveur (impossible d'antidater une
  entrée) et la source forcée à « borne », la réponse ne contient ni
  identifiant de demande ni identifiant du véhicule, et le débit est limité
  à 10 passages par minute et par adresse (`RATE_LIMIT_BORNE`, adresse
  réelle lue derrière le proxy de Render). Tout le reste de l'API garde sa
  clé. Contrepartie assumée pour la démonstration : n'importe qui ayant le
  lien peut faire entrer ou sortir un véhicule (et déclencher un paiement
  de test). En production, une borne serait un appareil géré, avec sa clé
  installée par l'exploitant : `BORNE_PUBLIC=false` ferme la route
  publique (403) sans changer le code.
- **Occupation publique** (`GET /borne/parking`, 4.12.0) : pour le plan 3D
  de la borne. Ne rend que des compteurs par catégorie, déjà visibles de
  quiconque regarde le parking ; ni véhicule, ni identifiant, ni demande.
  La réponse de Parking est gardée 10 s côté Access : mille visiteurs ne
  font pas plus d'appels à Parking qu'un seul. Débit limité par adresse.
- **Passages simultanés plafonnés** (4.13.1) : la borne publique traite au
  plus 8 passages à la fois (`BORNE_MAX_CONCURRENT`), les suivants reçoivent
  503 et la borne affiche « réessayez ». Un passage peut attendre jusqu'à
  45 s un service endormi : sans plafond, quelques visiteurs auraient suffi
  à occuper tous les threads d'Access, `/health` compris.
- **Validation PMR par un agent** (`POST /borne/pmr-validation`, 4.10.0) :
  protégée par le code agent (`AGENT_CODE`, comparaison à temps constant),
  même débit limité par adresse, et **acceptée seulement pour un véhicule mis
  en attente d'agent (PMR) à l'entrée dans les 5 dernières minutes** (sinon
  409) : connaître le code ne permet pas de faire enregistrer n'importe
  quelle plaque comme PMR chez Vehicles. Code volontairement simple (`123`) pour la
  démonstration : en production, un code par agent, plus long, ou une
  validation depuis un poste authentifié.
- **Gestion des secrets** : aucun secret dans Git (`gitleaks` en CI) ; clé API
  générée par Render, URL CloudAMQP et clé Payment saisies dans Render
  (`sync: false`). **En production, Access refuse de démarrer** si `API_KEY`
  vaut `change-me` ou fait moins de 16 caractères (`config.check_secrets`) ;
  en local, simple avertissement.
- **En-têtes de sécurité** : `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store` sur `/api/*`, HSTS derrière le proxy HTTPS.
- **Validation stricte** : Pydantic, y compris la plaque (2 à 10 lettres
  ou chiffres, normalisée avant l'appel à Vehicles, voir section 3) dans le corps de
  `POST /access/requests` et de `POST /access/vehicles/known` (jamais dans
  une URL, qui finirait dans les journaux des proxys), la taille de `photoBase64`
  (4 Mo max), les filtres d'audit (`limit` 1-500, `from` ≤ `to`, longueur des
  identifiants). Toute entrée invalide → 422 (400 pour une photo non
  décodable), sans rien persister ni appeler d'autre service.
- **CORS restrictif** : liste blanche configurable (`CORS_ALLOWED_ORIGINS`,
  limitée à l'URL du service sur Render), méthodes `GET`/`POST` et en-têtes
  `Content-Type`/`X-API-Key` uniquement, sans credentials (l'authentification
  passe par l'en-tête, pas par des cookies).
- **Métriques protégées (4.27.2)** : `/metrics` exige la clé d'exploitation
  ou un **jeton de lecture** (`METRICS_TOKEN`, généré par Render), présenté
  dans `X-API-Key` ou `Authorization: Bearer`. Ce jeton ne lit que
  `/metrics` : c'est lui qu'on confie à un Prometheus, jamais la clé
  d'exploitation. La clé borne ne lit pas les métriques. Au démarrage, un
  jeton trop court ou égal à l'une des clés est refusé en production.
  La route ne livre que des agrégats (étiquettes à valeurs bornées, aucune
  plaque, aucun identifiant, aucun chemin brut : une adresse inconnue est
  comptée sous `none`), mais elle montre l'activité du parking : volume,
  refus par motif, montant total encaissé, véhicules présents. De la 4.26.0
  à la 4.27.1 elle a été lisible sans clé (TP Prometheus) ; cette ouverture
  a été refermée.
- **Rate limiting** : `POST /access/requests` limité (`RATE_LIMIT_ACCESS_REQUESTS`,
  `20/minute` par défaut) via `slowapi`.
- **Gestion d'erreurs centralisée** : `main.py` intercepte `HTTPException`,
  les erreurs de validation et toute exception non prévue — **aucune stack
  trace n'est jamais renvoyée au client** (500 générique, détail loggé côté
  serveur uniquement, avec un `correlationId` permettant de retrouver la
  ligne de log correspondante).
- **RGPD / minimisation des données** : voir la règle absolue en
  [section 1](#1-présentation). En complément de la discipline de code, un
  `logging.Filter` (`RedactPlateFilter`) masque toute sous-chaîne au format
  plaque dans les logs, en défense en profondeur, et les erreurs 422 ne
  recopient jamais la valeur reçue.

---
TY765YU

## 11. Endpoints

Préfixe `/api/v1` (sauf `/health` et `/metrics`).

| Méthode | Route | Auth | Description |
|---|---|---|---|
| POST | `/access/requests` | Oui (clé API ou clé borne) | Crée et traite une demande d'accès (entrée ou sortie) ; `vehicleType` facultatif à l'entrée (type choisi à la borne). Si le passage est autorisé, la réponse indique aussi `placeType`, `placeLabel` et `reservation` (entrée) ou `enteredAt` et `durationMinutes` (sortie) |
| GET | `/access/requests/{id}` | Oui | Détail d'une demande + décision |
| GET | `/access/requests?vehicleId=&type=&from=&to=&limit=` | Oui | Liste/filtre (audit), plus récentes d'abord, avec la décision (`result`, `reason`, `paymentAmount`) |
| GET | `/access/presences` | Oui | Véhicules actuellement présents (heure d'entrée, place attribuée, réservation) |
| GET | `/borne/status` | Non | `{"publicAccess": true}` si la borne publique est ouverte (lu par `/borne` au démarrage) |
| GET | `/borne/parking` | Non (borne publique) | Occupation pour le plan 3D de la borne : `available` et, par catégorie, `name`, `label`, `totalCapacity`, `spotTaken`, `spotHeld`, `reserved` (véhicules entrés avec une réservation), `reservable` (places encore réservables chez Booking pour l'heure en cours, gardé 60 s, `null` si Booking ne répond pas) ; aucun véhicule ni identifiant ; réponse de Parking gardée 10 s (`BORNE_PARKING_CACHE_S`), 30/min par adresse (`RATE_LIMIT_BORNE_PARKING`) ; 403 si `BORNE_PUBLIC=false` |
| POST | `/borne/promenade` | Non (borne publique) | Promenade multijoueur du plan 3D : le navigateur envoie la position, la tenue de son personnage et, au volant, le tuning du véhicule (jeton aléatoire, nombres bornés, couleurs `#rrggbb`, mots courts ; aucun texte libre) et reçoit les autres promeneurs, le **pseudo attribué** par Access, `online` et `nextMs` (délai avant le prochain envoi, plus long quand il y a du monde). Rien en base ; un promeneur silencieux disparaît en 12 s ; 60 promeneurs au plus (`PROMENADE_CAPACITY`, sinon 503) ; `RATE_LIMIT_PROMENADE` par adresse ; 403 si `BORNE_PUBLIC=false` ou `PROMENADE_MULTI=false` |
| GET | `/borne/promenade` | Non (borne publique) | Les promeneurs du moment, pour qui regarde le plan sans se promener (vue d'ensemble, dashboard) |
| GET, POST | `/borne/promenade/scores` | Non (borne publique) | Meilleurs scores des mini-jeux (5 par jeu, pseudo et score), et déclaration d'un score par le navigateur : jeu connu et score plafonné par jeu, sinon 422. En mémoire : remis à zéro au redémarrage du service |
| POST | `/borne/promenade/defi` | Non (borne publique) | Défi amical entre deux promeneurs : `invite` (cible, jeu : `morpion`, `pfc`, `piece`), `accept`, `decline`, `move`. Le serveur arbitre (coups validés, pièce lancée par lui, choix de l'autre caché jusqu'à la fin de la manche) ; 409 avec un message si l'action est refusée. Les défis en cours reviennent dans la réponse de `POST /borne/promenade` (`duels`). Aucun texte libre ; un défi sans nouvelle est oublié en 90 s |
| POST | `/access/presences/{vehicleId}/release` | Oui (exploitation) | Libère un véhicule présent, désigné par son identifiant pseudonymisé : place rendue à Parking, présence « sorti », demande de sortie tracée (« Sortie forcée par l'exploitation »), événement `VEHICLE_EXITED` avec `forced: true`, rien de facturé ; réponse `vehicleId`, `requestId`, `placeId`, `placeFreed` ; 404 si le véhicule n'est pas présent |
| POST | `/borne/pmr-validation` | Code agent (`agentCode`) | Validation PMR par un agent après « confirmation requise » : `{"licensePlate", "country", "agentCode"}` ; justificatif enregistré chez Vehicles (`PUT`), puis entrée rejouée ; réponse identique à `/borne/passages` (entrée PMR autorisée même si Vehicles refuse l'enregistrement) ; 403 code faux |
| POST | `/borne/passages` | Non (borne publique) | Passage d'un véhicule depuis la borne : `{"licensePlate", "type", "vehicleType"}` (`vehicleType` facultatif, entrée seulement : `STANDARD`, `ELECTRIC`, `XL`, `HANDICAPPED`, `TWO_WHEELS`) ; date imposée par le serveur, 10/min par adresse, réponse sans identifiants ; 403 si `BORNE_PUBLIC=false` |
| GET | `/access/borne/key` | Oui (clé API seulement) | Clé des bornes client, pour leur mise en service depuis le dashboard ; 404 si `BORNE_API_KEY` n'est pas définie. Refusée (401) avec la clé borne |
| GET | `/access/parking` | Oui (clé API) | Occupation par catégorie vue par Parking (libellé, prises, mises de côté, capacité) et catégories utilisées par Access mais absentes chez Parking ; `available: false` si Parking ne répond pas |
| POST | `/access/vehicles/known` | Oui | Vérifie si une plaque (`{"licensePlate": …}`) est connue de Vehicles, sans la créer ni rien persister |
| GET | `/access/events` | Oui | Liste les événements publiés (outbox, démo/observabilité) |
| GET | `/health` | Non | Healthcheck (API + DB) + moteur de base, version et SHA du commit déployé |
| GET | `/metrics` | Oui (clé API ou jeton `METRICS_TOKEN`) | Métriques Prometheus, pour le Prometheus qui supervise Access (`X-API-Key` ou `Authorization: Bearer`) : `http_requests_total` (méthode, gabarit de route, classe de statut), `parking_operations_total` (opération, résultat), latences, métriques métier et d'intégration. Uniquement des agrégats, aucune plaque ni identifiant ; hors limitation de débit ; ne compte pas ses propres lectures |

Documentation interactive complète (schémas, exemples, codes d'erreur) sur
`/docs`. Toutes les réponses portent l'en-tête `X-Correlation-ID` (voir
[section 9](#logs-exploitables)).

### Exemple — `POST /access/requests` (entrée)

```json
{
  "licensePlate": "AB-123-CD",
  "type": 1,
  "date": "2026-09-02T10:15:00Z",
  "source": 3,
  "photoBase64": null
}
```

Réponse — `vehicleId` est le `pseudoId` renvoyé par Vehicles :

```json
{
  "requestId": "b3a1f7b0-...-uuid",
  "vehicleId": "301b7c98-3634-4842-8ff5-baf503c53302",
  "type": 1,
  "status": 2,
  "authorization": {
    "result": 1,
    "reason": "Accès autorisé",
    "vehicleTypeCheckOk": true,
    "disabilityCheckOk": null
  }
}
```

---

## 12. Borne et journal de bord (dashboard)

Une petite page statique (`src/interfaces/api/static/dashboard.html`) est
servie **par Access lui-même** — pas de port supplémentaire, pas de serveur
front séparé, elle appelle `GET /api/v1/access/events` en same-origin (donc
aucun souci CORS). Accessible sur http://localhost:8000/ (redirige
automatiquement) ou http://localhost:8000/static/dashboard.html.

Renseignez votre `X-API-Key` dans le champ prévu (stockée uniquement dans le
`localStorage` de votre navigateur). Cinq onglets :

- **Borne** (par défaut) : simule une borne d'entrée/sortie. On saisit la
  plaque lue par la borne, on choisit l'heure
  de passage, puis **Entrée** ou **Sortie** : la décision d'Access s'affiche
  en direct (barrière ouverte / fermée / intervention requise, motif,
  véhicule pseudonymisé, montant, identifiant du paiement réel). Pendant une
  sortie, un compteur montre l'attente de Pricing puis Payment (~15-30 s).
  L'heure de passage « Dans 2 h 30 » simule une durée de stationnement :
  sans elle, une sortie juste après l'entrée tombe dans la 1re heure
  gratuite (0 €, aucun paiement). L'historique de la session n'affiche
  que le `vehicleId` pseudonymisé.
- **État du parking** : ce que voit Access à l'instant — santé, version et
  commit du service (`/health`), nombre de véhicules présents, décisions
  récentes (autorisées / refusées / confirmation requise), liste des
  **véhicules présents** (place attribuée, réservation, heure et durée de
  présence) et des **dernières demandes** avec leur motif et montant. Un
  clic ouvre le détail. Chaque véhicule présent a un bouton **« Libérer »**
  (et le panneau un bouton « Tout libérer ») : sortie forcée par
  l'exploitation, sans plaque ni paiement, pour un véhicule parti sans
  passer par la borne ou un véhicule de test ; une confirmation est
  demandée, et le dashboard signale si Parking n'a pas rendu la place. Panneau **Occupation vue par Parking** : par
  catégorie, libellé de Parking, taux d'occupation (vert, orange au-delà de
  70 %, rouge au-delà de 90 %), places prises et mises de côté, capacité ;
  alerte si une catégorie utilisée par Access manque chez Parking, ou si
  Parking ne répond pas (redemandé toutes les 30 s seulement, Parking étant
  sur l'offre gratuite de Render). Rappel des opérations disponibles (borne,
  recherche, journal, `/docs`, `/metrics`). Rafraîchi automatiquement.
- **Plan 3D** : le parking en trois dimensions (three.js), construit à
  partir de l'occupation renvoyée par Parking (`GET /access/parking`). Une
  zone par catégorie (PMR, recharge électrique, deux-roues, standard, grand
  gabarit), une place dessinée par place réelle, **un véhicule par place
  prise**, du bon type : citadine, berline, SUV, électrique, utilitaire,
  camping-car, moto, scooter. Quand l'occupation change, les véhicules
  **entrent par la barrière et vont se garer**, ou reculent et sortent ; une
  place mise de côté (hold de 30 s) clignote en ambre ; chaque place a son
  capteur (vert libre, rouge prise) ; un **« R » bleu** flotte au-dessus
  des véhicules entrés avec une réservation Booking (nombre rappelé dans la
  légende). Décor complet : portique « ENTRÉE /
  SORTIE », barrières levantes, bornes Access, guérite, bornes de recharge,
  panneaux PMR, lampadaires, arbres, route avec circulation. **Jour en
  thème clair, nuit en thème sombre** (lampadaires, phares). Caméra libre
  (glisser pour tourner, molette pour zoomer, Maj ou clic droit pour
  déplacer, flèches du clavier), rotation automatique, plein écran, clic
  sur une zone de la légende pour zoomer. Au survol : type de véhicule,
  zone, et pour un véhicule entré par Access son identifiant pseudonymisé
  et son heure d'entrée ; un clic ouvre sa demande. Sans clé, ou si Parking
  ne répond pas, le plan passe en **démonstration** et l'affiche. Au-delà
  de 260 places, une place affichée en représente plusieurs (indiqué).
  **Mode « Promenade »** : un bouton fait incarner un personnage vu de
  dos, suivi de son chihuahua, pour parcourir le parking comme dans un jeu
  (ZQSD ou flèches pour marcher, Maj pour courir, souris pour regarder,
  E pour interagir, F pour appeler son compagnon, Espace pour sauter,
  1 à 4 pour saluer, Échap pour quitter ; manette tactile sur écran tactile). On contourne les véhicules garés, les
  haies et le mobilier ; la zone où l'on se trouve s'affiche avec son
  occupation. Une **borne de réservation** est posée sur un parvis près de
  l'entrée : elle indique, zone par zone, les places encore réservables
  chez Booking pour l'heure en cours et les véhicules entrés avec une
  réservation. Sur la borne publique, s'approcher de la borne d'entrée ou
  de sortie du décor et appuyer sur E lance le vrai parcours. La borne de
  réservation affiche en tête le **nombre de places libres** à l'instant
  et les atouts du parking.
  **Un agent du parking** (gilet jaune) fait sa ronde tout seul : il
  inspecte les véhicules garés, va au-devant d'une arrivée, salue le
  promeneur. **Six véhicules en libre-service** (camping-car, berline,
  scooter, 4x4, citadine électrique, moto) se conduisent ; les barrières se lèvent devant eux et le
  compagnon monte à bord.
  **Bonneplace, le village du parking**, se rejoint par la route, à pied
  ou au volant. Le promeneur démarre toujours sur le parvis du parking.
  Le village est aux couleurs de **KingPar**, la marque du parking (logo :
  une couronne en trace de pneu, `static/kingpar-logo.svg`) : grande arche d'entrée, statue de
  la mascotte, rue commerçante, belvédère au sommet d'un escalier sous
  cinq arches (une par zone du parking), Tour KingPar à cinq étages, étang
  et passerelle, place de la fête, champs de fleurs, lettres KINGPAR sur
  la colline. Trois boutiques servent vraiment, et **tout y est offert** :
  Boutique KingPar (carnation, huit tenues : T-shirt, pull, chemise,
  veste, sweat à capuche, salopette, robe, maillot ; pantalon, short ou
  jupe ; lunettes, écharpe ; casquette, chapeau, bonnet, béret, et une
  couronne qui se mérite avec neuf succès), Coiffure
  Le Créneau (treize coupes, onze couleurs, quatre regards dont un « manga », vue de près), Animalerie du
  Copilote (dix compagnons : chihuahua, chat, shiba, lapin, renard, cochon,
  panda, mouton, tortue, canard). Le personnage a un vrai visage et des
  formes rondes, dans un style doux : grosse tête, petit corps, visage
  peint (grands yeux qui clignent, joues roses, sourire). Le décor suit
  le même style : arbres en boules, collines rondes, fleurs.
  **Quêtes** : six habitants de Bonneplace ont un « ! » au-dessus de la
  tête et un petit service à demander (retrouver un chat, cueillir des
  fleurs, livrer un colis…) ; « ? » quand c'est en cours, puis on revient
  les voir. Les dialogues s'affichent dans une bulle, en bas de l'écran.
  **Station KingPar**, sur la route du village : auvent, pompes, borne de
  recharge, boutique, place d'entraînement du « créneau parfait » (on se
  gare, on est noté sur 100), et un **grand panneau qui affiche en direct
  les places libres du parking**.
  **KingPar Tuning**, en face de la station : un atelier avec son podium
  tournant. On y vient au volant (touche E sur l'aire) ou à pied (Jo, le
  mécano, sort le véhicule choisi). Chacun des six véhicules se
  personnalise, et **tout est offert** : quatorze peintures et quatre
  finitions (brillante, mate, métallisée, nacrée), quatre modèles de
  jantes en huit couleurs, quatre types de pneus (route, flancs blancs,
  sport, tout-terrain), huit autocollants (couronne KingPar, numéro 7,
  flamme, éclair, cœur, patte de Ticket, étoile, damier), bandes de
  course, vitres teintées, aileron, galerie de toit ou fanion KingPar,
  néon sous la caisse en six couleurs, quatre klaxons (touche H). Un
  bouton « Surprise ! » tire un style au hasard, un autre remet le
  véhicule d'origine. Le réglage de chaque véhicule est gardé sur
  l'appareil, et les autres promeneurs voient la voiture telle qu'elle a
  été préparée.
  **Le gros bouton rouge**, sur un îlot au milieu de la route, devant le
  parking (« Ne pas appuyer ») : il lance une **publicité KingPar** de
  trente-cinq secondes, tournée dans le décor. Six plans (le parking vu
  d'en haut, le panneau des places libres, l'agent qui salue, Jo et une
  voiture sur le podium, le village en fête, le carton final), des bandes
  de cinéma, des sous-titres et un bouton « Passer la pub ». Les voix des
  acteurs sont **enregistrées** (six répliques, synthèse vocale libre,
  voix sous licence CC BY 4.0, dans `static/sons/pub/`) ; en secours, la
  synthèse vocale de l'appareil, puis la voix chantonnée des habitants.
  **Douze mini-jeux** (souris, doigt ou clavier) : course de canards au spa, jeu des paires au café,
  passage piéton au bistrot, chasse aux olives à la pizzeria, « Feu
  vert ! » chez le glacier, éclate-ballons à la fête, pêche aux canards, crêpes,
  frites et barbe à papa aux stands de la fête, grosse caisse au kiosque,
  « plein pile » à la pompe. Records gardés sur l'appareil, meilleurs
  scores partagés entre promeneurs.
  **Carnet** (touche C), en trois onglets : seize **tampons** à
  découvrir, cinquante-huit **succès**, dont sept secrets (au volant, aux mini-jeux, en
  rencontrant d'autres promeneurs, en revenant un autre jour) avec un rang
  qui monte, et les scores. Un **ticket d'or** est caché chaque jour à un
  endroit différent. Une **photo souvenir** (touche P) s'enregistre depuis
  la page.
  **Défis amicaux** : près d'un autre promeneur, la touche E ouvre une
  roulette : morpion, pierre-feuille-ciseaux ou pile ou face. L'autre
  accepte ou non ; le serveur arbitre la partie.
  **Kingfarm**, au sud des champs : un potager de citrouilles à cueillir,
  un verger à abattre à coups de poing, une grotte de pierre (portail en
  bois, rails, wagonnet) où extraire des minerais : sa voûte s'efface
  quand on y entre. En promenade, le monde est **courbé** comme une petite
  planète (effet de dessin : le plan vu de haut reste à plat). **Sons** :
  gestes (dix sons enregistrés, packs Kenney en licence CC0, dans
  `static/sons/`, avec repli synthétisé), voix des habitants et musique
  de promenade synthétisées par le navigateur ; la roue ⚙ règle le volume et coupe la musique. Tout repousse au bout d'un moment.
  Les animaux et le décor suivent le style doux des personnages : maisons
  aux murs crème à poutres de bois, toits à deux pans en tuiles arrondies
  avec pignons et faîtière, portes arrondies, haies, boîtes aux lettres,
  chemins de terre,
  clôtures en bois, arbres touffus à pommes, prairie dessinée.
  **Accueil** : à la première visite sur un appareil, une fenêtre explique
  ce monde en 3D (voir le parking en direct, mais aussi s'amuser) ; le
  bouton « ? » la rouvre. **Ballons KingPar** offerts à la fête : le
  personnage le tient à la main, saute plus haut et retombe doucement.
  **Multijoueur** : en promenade, on voit les autres visiteurs, leur
  compagnon et leur véhicule, avec le pseudo qu'Access leur attribue
  (« Renard Malin 76 ») et leur nombre de succès. Vu de haut (et dans le
  dashboard), on les regarde se promener. Pas de pseudo saisi ni de
  discussion libre : quatre saluts au choix (se saluer à deux fait pleuvoir
  des cœurs). On peut **monter dans la voiture d'un autre promeneur** et
  se laisser conduire. Tenue, compagnon, tuning des véhicules, carnet et
  jeton du promeneur sont gardés dans le navigateur de l'appareil ; le plan
  n'appelle que les routes `/borne/promenade`, sans clé ni cookie. Le
  carnet est un jeu : il ne donne droit à aucun tarif.
  Occupation redemandée toutes les 10 s tant que l'onglet est ouvert, rendu
  3D arrêté dès qu'on le quitte. Aucune plaque : le plan ne connaît que des
  compteurs et des identifiants pseudonymisés.
- **Journal** : la liste des événements se rafraîchit automatiquement
  (intervalle configurable), avec un badge coloré par type d'événement et le
  détail JSON dépliable.
- **Recherche** : une demande par `requestId`, l'historique d'un
  `vehicleId`, ou d'une plaque (résolue d'abord en `vehicleId` auprès de
  Vehicles, sans la créer).

**Design** : thème [Catppuccin](https://catppuccin.com) — **Latte** (clair)
par défaut, **Mocha** (sombre) en un clic, choix mémorisé dans le navigateur ;
police **MesloLGS NF** embarquée (`static/fonts/`, sous-ensemble latin de
15 Ko par graisse, licence Apache 2.0) ; surfaces en verre dépoli
(`backdrop-filter`) sur des halos aux couleurs du thème. La borne affiche une
barrière animée (levée, fermée, en attente), le journal se filtre par type
d'événement, les listes ne se redessinent que si les données changent, et le
rafraîchissement se met en pause quand l'onglet du navigateur est en
arrière-plan. Aucune ressource externe : three.js (0.160.0, licence MIT)
est une copie figée servie par Access (`static/vendor/`, empreinte
SHA-256 contrôlée par les tests), jamais un CDN, puisque la page détient
la clé d'exploitation ; animations désactivées avec
`prefers-reduced-motion`.

Testé dans Chrome (clair, sombre, mobile 390 px) : entrée puis sortie payée
de bout en bout avec Pricing et Payment réels. L'onglet « État du parking »
a été vérifié en local (bureau et mobile 375 px, sans défilement
horizontal). L'onglet « Plan 3D » a été vérifié dans le navigateur (bureau
1280 px et mobile 375 px, jour et nuit) : construction du parking, entrée
d'un véhicule par la barrière, sortie, place mise de côté, survol et clic
sur un véhicule, passage des données de démonstration aux données réelles.

### Borne client (écran public)

Le dashboard est l'outil de l'exploitant. La borne client
(`src/interfaces/api/static/borne.html`, servie directement sur
**[`/borne`](https://access-api-a1u7.onrender.com/borne)** : l'adresse reste
courte, sans `.html` ; l'ancienne adresse `/static/borne.html` redirige vers
`/borne`) est l'écran
que voit le conducteur à l'entrée ou à la sortie du parking :

1. **Accueil** : « Entrer » ou « Sortir ». Une borne installée à un endroit
   précis saute ce choix (`/borne?mode=entree` ou `/borne?mode=sortie`).
2. **Votre véhicule** (entrée seulement) : cinq grandes tuiles avec icône —
   Voiture, Électrique (place avec recharge), Grand gabarit (utilitaire,
   fourgon, camping-car), Mobilité réduite (place PMR), Deux-roues (moto,
   scooter). Le choix est envoyé à Access (`vehicleType`) :
   - pour un véhicule **inconnu**, Vehicles le crée avec ces caractéristiques
     (électrique, XL, deux-roues) ; pour un véhicule **connu**, sa fiche
     Vehicles fait foi (vérifié : `identify` ne modifie jamais un véhicule
     existant) ;
   - **Mobilité réduite** : si Vehicles connaît le véhicule comme PMR, entrée
     normale ; sinon une place PMR est demandée mais **un agent vérifie la
     carte** avant d'ouvrir (« Un agent arrive »). PMR n'est jamais
     enregistré chez Vehicles sur simple déclaration ;
   - une réservation Booking impose son propre type de place.

   L'écran suivant rappelle le type choisi, avec « Modifier ».
3. **Plaque** : saisie libre au clavier à l'écran (ou au clavier
   physique) : lettres, chiffres et espace, 2 à 10 caractères. **Pays** :
   France par défaut, bouton « Changer de pays » (Italie, Espagne,
   Allemagne, Belgique, Suisse, Royaume-Uni, Pays-Bas, Luxembourg,
   Portugal, autre pays). Le bandeau bleu de la plaque affiche la lettre du
   pays (F, I, E, D…), l'exemple s'adapte, et une plaque qui ne correspond
   pas au format du pays est signalée avant l'envoi. À l'entrée comme à la
   sortie : un véhicule italien sort en choisissant l'Italie.
4. **Traitement** : étapes affichées (identification, place ou montant,
   paiement ; jusqu'à ~40 s pour un paiement).
5. **Résultat** :
   - entrée autorisée : « La barrière s'ouvre », type de place en français
     (place standard, avec recharge, grand gabarit, PMR, deux-roues : les
     libellés techniques de Parking ne sont jamais affichés au client),
     réservation reconnue ;
   - sortie autorisée : ticket avec heure d'entrée, heure de sortie, durée et
     montant payé (« Gratuit » pendant la première heure) ;
   - refus : message clair pour le client (parking complet, véhicule déjà
     présent, paiement refusé…), jamais le motif technique, avec
     « Réessayer » quand c'est utile ;
   - véhicule non identifié : « Un agent arrive » ;
   - **PMR déclaré, justificatif inconnu de Vehicles** : « Un agent arrive »,
     avec un bouton **« Validation agent »**. L'agent vérifie la carte
     mobilité inclusion et tape son code (`AGENT_CODE`, `123` par défaut) :
     Access enregistre le justificatif chez Vehicles et le véhicule entre
     sur une place PMR. Aux passages suivants, plus besoin d'agent (si
     Vehicles refuse l'enregistrement, l'entrée PMR passe quand même pour
     ce passage, sans mémorisation). Sans
     carte : « Pas de carte : place standard ». La plaque n'est gardée qu'en
     mémoire de la page, le temps de la validation (90 s sans action →
     accueil).

   Retour automatique à l'accueil après quelques secondes.

**Dock et parking en direct** : sur le côté de la borne (en bas sur mobile),
un dock à deux boutons, à la manière du Dock de macOS. La maison ramène à la
borne (entrer, sortir) ; la voiture ouvre **« Le parking en direct »** : le
[plan 3D](#12-borne-et-journal-de-bord-dashboard) en plein écran,
visible par tout le monde, sans clé. C'est le même module que l'onglet
« Plan 3D » du dashboard, alimenté par la route publique
`GET /borne/parking` : des compteurs par catégorie seulement (capacité,
places prises, mises de côté, véhicules entrés avec une réservation),
aucun véhicule ni identifiant, donc pas de
détail au survol sur l'origine d'un véhicule. Toujours de jour à
l'arrivée (bouton « Nuit » disponible), avec le mode « Promenade », le
village de Bonneplace et la borne de réservation décrits plus haut. Le dock disparaît pendant l'envoi d'un passage et dans les
réglages ; quitter le plan arrête son rendu.

**Mise en service : aucune.** Le lien
[`/borne`](https://access-api-a1u7.onrender.com/borne) (ou
`/borne?mode=entree`, `/borne?mode=sortie`) marche tel quel, pour tout le
monde, sur n'importe quel appareil : la borne demande à Access si la borne
publique est ouverte (`GET /borne/status`) et passe alors par la route
publique `POST /borne/passages` (voir [section 10](#10-sécurité)).

**Avec la clé borne (si `BORNE_PUBLIC=false`)**, depuis le dashboard : onglet
« Borne » du dashboard, panneau **Borne client** (affiché seulement une fois
la clé d'exploitation validée) : choisir l'emplacement (entrée et sortie,
entrée, sortie) puis **Ouvrir la borne client**. Le dashboard demande la clé
borne à Access (`GET /access/borne/key`, clé d'exploitation exigée), la
range dans le navigateur à l'endroit où la borne la lit (même site, même
stockage) et ouvre `/borne` dans un nouvel onglet : aucune saisie. La clé
d'exploitation, elle, n'est jamais transmise à la borne.

**Mise en service manuelle** (appareil sans dashboard) : appui long (3 s)
sur le logo, ou `/borne?config`. On y saisit la **clé borne**
(`BORNE_API_KEY`, voir [section 10](#10-sécurité)) et l'emplacement ;
« Tester la clé » la vérifie sans rien enregistrer côté Access. Dans les deux
cas, la borne s'en souvient ensuite (à refaire seulement sur un autre
appareil ou navigateur, en navigation privée, ou si les données du site sont
effacées). Une borne configurée avec sa clé utilise `POST /access/requests`
(si la clé a changé dans Render, elle repasse d'elle-même par la route
publique). Sans clé et avec `BORNE_PUBLIC=false`, la borne affiche « Borne
hors service ».

**Données** : la borne ne garde que sa clé et son emplacement (stockage du
navigateur). La plaque n'est conservée nulle part : elle disparaît de
l'écran dès l'envoi et n'est jamais réaffichée ; l'identifiant interne du
véhicule n'est jamais montré au client. Thème clair ou sombre selon le
réglage de l'appareil, utilisable sur mobile, sans ressource externe.

Vérifiée dans le navigateur : réglages (clé refusée puis acceptée), saisie
guidée, Vehicles injoignable (« Un agent arrive »), entrée autorisée, ticket
de sortie, refus « parking complet » ; bureau sombre et mobile 375 px clair.

---

## 13. Postman

> ⚠️ Le dossier `postman/` est **exclu du dépôt** (`.gitignore`) : les
> collections ci-dessous restent sur le poste du développeur. La vérification
> reproductible **versionnée** est [`scripts/smoke_test.sh`](scripts/smoke_test.sh)
> ([section 9](#vérifier-une-instance-déployée-smoke-test)).

Un dossier `postman/` (local) contient :

- `Access-Microservice.postman_collection.json` — toutes les routes,
  organisées par dossier (Health / Access — Entry / Access — Exit / Access —
  Lookup / Events / **Errors — edge cases**), avec des exemples prêts à
  l'emploi pour chaque scénario métier (entrée
  simple, réservation, accessibilité, véhicule inconnu, sortie payée,
  paiement refusé...).
- `Access-Microservice.postman_environment.json` — variables `baseUrl` et
  `apiKey` à ajuster selon votre `.env`, pour tester en **local**.
- `Access-Render.postman_collection.json` + `Access-Render.postman_environment.json`
  — strictement les mêmes requêtes, prêtes à pointer vers le **déploiement
  public Render** (section 14) plutôt que `localhost` : pratique pour que
  toute l'équipe teste la même instance sans rien installer.

Le dossier **"Payment — Direct Verification"** prouve l'intégration Payment
côté Payment lui-même : après une sortie payée, `GET /access/events` capture
le `paymentId`, puis on consulte ce paiement chez Payment (`ACCEPTED`,
`source_service=access`, rattaché au stationnement) et on **rejoue la même
demande** : Payment répond `200` avec le même `payment_id`, preuve qu'une
sortie rejouée ne débite jamais deux fois. Ces requêtes utilisent la variable
d'environnement `paymentApiKey` (clé fournie par l'équipe Payment), jamais la
clé Access. ⏱️ Une sortie prend désormais ~15-30 s : Access attend le statut
final du paiement (polling), c'est normal.

Le dossier **"Errors — edge cases"** contient volontairement des requêtes
invalides (pas de clé API, plaque invalide, type invalide, champ manquant,
`photoBase64` corrompu, id inexistant, rate limit) — chacune avec un script
de test Postman qui vérifie le code HTTP attendu, pour voir concrètement à
quoi ressemblent les erreurs de l'API.

**Import** : Postman → *Import* → sélectionnez les fichiers voulus (locaux
et/ou Render) → choisissez l'environnement correspondant ("Access — Local"
ou "Access — Render") en haut à droite. La requête "Entry — standard
vehicle" capture automatiquement `requestId`/`vehicleId` dans des variables
de collection, réutilisées par les requêtes suivantes (sortie, détail par
id).

---

## 14. Déploiement sur Render

Un [`render.yaml`](render.yaml) (Render Blueprint) décrit **un seul service**
(pas de service RabbitMQ Render, cf. ci-dessous) :

- **`access-api`** — le microservice Access (FastAPI), public, plan Free,
  publication d'événements en mode **`rabbitmq`** (cf. section 6) vers le
  bus d'événements partagé de l'équipe (CloudAMQP, exchange
  `microservice-event-bus`) — **pas** vers un service RabbitMQ hébergé par
  Render : zéro coût supplémentaire côté Render.

**`RABBITMQ_URL` n'est PAS renseigné automatiquement** — contrairement à
`API_KEY` (que Render peut générer lui-même), l'URL du broker CloudAMQP est
un secret externe fourni par l'équipe, que Render ne peut pas deviner. Le
blueprint la déclare avec `sync: false`, ce qui veut juste dire "cette
variable existe, mais Render ne mettra jamais sa valeur dans le fichier
versionné" — **il faut la coller soi-même dans le dashboard Render** une
fois le service créé (voir étape 2bis ci-dessous). Tant qu'elle est vide,
le reste de l'API fonctionne normalement (best-effort : la publication
échoue silencieusement, loggée, sans bloquer les décisions d'accès).

### Marche à suivre

1. Sur [render.com](https://render.com), **New +** → **Blueprint** → connectez
   le repo GitHub `DenisDMU/access-parking` → Render détecte `render.yaml` et
   propose de créer `access-api` → **Apply**.
2. Une fois déployé, allez dans **access-api → Environment** et récupérez la
   valeur générée automatiquement pour `API_KEY` (Render la génère au
   premier déploiement, `generateValue: true` dans le blueprint) — c'est
   cette clé qu'il faut mettre dans Postman/`.env`, pas `change-me`.
2bis. **Toujours dans Environment**, trouvez `RABBITMQ_URL` (probablement
   affiché vide/"à définir" à cause de `sync: false`) et collez-y l'URL
   CloudAMQP du bus partagé de l'équipe (`amqps://...`) — sans ça, Access ne
   publiera aucun événement (le reste marche quand même).
2ter. Toujours dans Environment : vérifiez que `PAYMENT_SERVICE_URL` vaut
   `https://payment-xp8n.onrender.com` et collez dans `PAYMENT_API_KEY` la
   clé transmise **en privé** par l'équipe Payment (`sync: false` dans le
   blueprint, comme `RABBITMQ_URL`). Tant que Payment n'a pas activé son
   authentification, la variable peut rester vide sans rien casser.
2quater. **`PARKING_API_KEY` (obligatoire)** : Parking exige l'en-tête
   `X-API-Key` sur toutes ses routes depuis le 18/11/2026. Demandez la clé à
   l'équipe Parking et collez-la ici — sans elle, toute entrée est refusée
   avec « Service Parking indisponible, réessayez plus tard ».
   `PRICING_API_KEY` et `VEHICLES_API_KEY` existent sur le même principe,
   pour le jour où ces services activeront leur authentification.
2quater bis. **`METRICS_TOKEN`** (lecture de `/metrics`) : généré par Render
   (`generateValue: true`) ; sinon, ajoutez-le à la main (au moins 16
   caractères, différent des deux clés, par exemple `openssl rand -hex 24`).
   Sa valeur se lit dans **access-api → Environment → `METRICS_TOKEN`**
   (icône œil) : c'est elle que `tp/prometheus/demarrer.sh` demande. Sans
   cette variable, seule `API_KEY` lit les métriques.
2quinquies. **`BORNE_API_KEY`** (bornes client) : générée par Render
   (`generateValue: true`) ; sinon, ajoutez-la à la main avec une valeur
   d'au moins 16 caractères, différente d'`API_KEY` (par exemple
   `openssl rand -hex 24`). Sa valeur se lit dans **access-api →
   Environment → `BORNE_API_KEY`** (icône œil). Inutile de la recopier :
   le bouton « Ouvrir la borne client » du dashboard la récupère tout seul
   (section 12) ; `/borne?config` reste possible sur un appareil sans
   dashboard.
3. Récupérez l'URL publique du service (en haut de la page `access-api`,
   type `https://access-api-xxxx.onrender.com`).
2quinquies. **`DATABASE_URL`** : collez l'URL de connexion de la base
   **Postgres Neon** (`postgresql://…?sslmode=require`). Sans elle, Access
   utilise un fichier SQLite effacé à chaque redémarrage du plan Free (voir
   ci-dessous). Access crée ses tables tout seul au démarrage.
4. Vérifiez `GET /health` : `version` attendue, `databaseEngine: postgresql`.
5. Lancez `scripts/smoke_test.sh` (section 9) avec la clé de l'étape 2 et un
   plaque de test (section 3) — ou le workflow GitHub
   « Smoke test ». La collection Postman locale (section 13) reste utilisable.

### ⚠️ Points d'attention et limites connues

- **Base de données : Postgres Neon en production.** Le disque du plan Free
  est éphémère : un fichier SQLite y est **effacé à chaque redéploiement et
  à chaque réveil** du service. Or Access doit se souvenir des véhicules
  présents et de leur heure d'entrée (règles 1 et 2.4) : sans persistance, un
  véhicule garé pendant une mise en veille ne pourrait plus sortir. En
  production, `DATABASE_URL` pointe donc vers une base **Postgres Neon**
  gratuite (qui ne supprime pas les données en cas d'inactivité) ; Access
  crée ses tables tout seul au démarrage. `/health` indique le moteur utilisé
  (`databaseEngine`). SQLite reste utilisé en local et dans les tests, avec
  les clés étrangères activées pour se comporter comme Postgres. Pour lancer
  toute la suite de tests contre une vraie base Postgres (dans un schéma
  jetable, sans toucher aux tables de production) :
  `ACCESS_TEST_DATABASE_URL=<url> pytest tests/integration`.
- **Mise en veille (plan Free)** : `access-api` s'endort après ~15 min
  d'inactivité ; le premier appel suivant peut prendre 30-60s (cold start) —
  normal, pas un bug. Les services de l'équipe (Parking, Pricing...) sont
  logés pareil : un appel sortant d'Access vers l'un d'eux peut donc aussi
  déclencher son réveil. Les clients HTTP réels utilisent un timeout de
  **20s** (`infrastructure/external/http_*_client.py`) pour l'encaisser, et
  toute erreur (429/5xx/timeout/connexion refusée) est traitée comme un
  refus métier propre plutôt qu'un crash — voir l'exemple en
  [section 4](#4-architecture-hexagonale).
- **CORS** : `CORS_ALLOWED_ORIGINS` est limité à l'URL du service lui-même
  dans le blueprint (le dashboard est same-origin). Si un front d'équipe
  doit appeler Access depuis un navigateur, ajoutez son origine (séparée
  par une virgule).
- **`RABBITMQ_URL` vide ou incorrect** : si les logs `access-api` affichent
  `Échec de publication RabbitMQ pour l'événement ...`, vérifier d'abord que
  la variable est bien renseignée dans Environment (étape 2bis),
  et que l'URL CloudAMQP est toujours valide (pas de rotation de mot de
  passe côté CloudAMQP entre-temps).
- **Ancienne option abandonnée** : un service RabbitMQ auto-hébergé sur
  Render (privé, payant) reste en commentaire tout en bas de `render.yaml`
  au cas où le broker CloudAMQP externe serait un jour abandonné — pas
  utilisé actuellement.

---

## 15. Rejoindre l'équipe : brancher vos microservices

Access étant déployé sur Render, les autres équipes peuvent l'appeler
directement sans rien installer — c'est tout l'intérêt d'un déploiement
public partagé :

- **Ils veulent qu'Access les appelle (Vehicles, Booking, Parking, Pricing,
  Payment)** : il suffit de m'envoyer l'URL publique de leur service et
  leur contrat d'API. Les 5 services sont déjà branchés en réel ; un
  changement de contrat se traite dans le client HTTP correspondant
  (`infrastructure/external/http_*_client.py`), sans toucher aux autres
  couches.
- **Ils veulent recevoir les événements d'Access** (`VEHICLE_ENTERED` /
  `VEHICLE_EXITED` / `ACCESS_REFUSED`) : c'est déjà fait pour tout le monde
  qui écoute le bus partagé de l'équipe — Access publie sur l'exchange
  **`microservice-event-bus`** (CloudAMQP) avec les routing keys
  `access.entry` / `access.exit` / `access.refused` / `access.other`
  (section 6). N'importe quel camarade déclare sa propre queue et la lie à
  `access.#` (tout recevoir) ou une clé précise, avec les mêmes identifiants
  CloudAMQP que le reste de l'équipe — rien à me redemander. L'alternative
  webhook (`EVENT_SUBSCRIBERS_URLS`, `EVENT_PUBLISHER=webhook`) reste
  disponible pour quelqu'un qui préfère une route HTTP dédiée plutôt que le
  bus commun.

---

## 16. Écarts assumés par rapport à la spec

Pour rester fidèle au modèle de données figé (section 6 de la spec) tout en
répondant aux besoins fonctionnels du use case "Sortie" (retrouver la place
et son type à partir de la seule présence), quelques extensions **minimes et
non intrusives** ont été ajoutées :

- `VehiclePresenceRepositoryPort.list_present` et le use case
  `ListPresentVehicles` : lecture seule, pour la vue « État du parking »
  (`GET /access/presences`) ; `ListAccessRequests` renvoie chaque demande
  avec sa décision, et `AccessFilters` a gagné un `limit`.
- `AccessRepositoryPort.get_authorization_by_request`,
  `get_event_by_request` et `list_events` : lecture supplémentaire, aucune
  règle métier ajoutée. Le `placeId`/type de place attribué à l'entrée est
  retrouvé via le `payload` JSON de l'événement `VEHICLE_ENTERED` associé
  (le schéma SQL officiel ne prévoit pas de colonne dédiée — le payload
  d'événement est explicitement documenté comme pouvant contenir "la place",
  section 6).
- `VehiclePresenceRepositoryPort.get_current_request_id` : complète
  `get_status` (dont la signature spec est inchangée) pour exposer
  `current_request_id`, nécessaire à l'étape 4 du workflow "Sortie".
- `Reservation.place_id` (optionnel) : toujours absent avec le vrai Booking
  (aucune place nominative) ; le use case demande alors la place à Parking,
  avec le **type réservé**, dans le quota « booking ».
- **Réservation payée d'avance** (Booking encaisse au moment de réserver) :
  à la sortie, rien n'est facturé dans le créneau ; au-delà de la fin du
  créneau, seul le dépassement est facturé, au tarif sans réservation
  (Booking ne prévoit aucune tolérance). La fin du créneau est gardée dans
  l'événement d'entrée (`reservationId`, `reservationEnd`, champs ajoutés).
  Hypothèse à valider avec les équipes Booking et Pricing.
- `ParkingServicePort.request_place`/`mark_place_occupied`/`mark_place_free`
  ont gagné un paramètre `is_reservation` (même principe que
  `PricingServicePort`, section 5) : le vrai service Parking sépare sa
  capacité en deux pools ("walkin"/"booking") par catégorie. Par ailleurs,
  Parking **ne gère aucun identifiant de place individuel** (juste des
  compteurs par catégorie, conforme aux consignes projet section 2.1) : le
  `place_id` qu'Access manipule en interne est donc **synthétique**
  (`"CATEGORIE:walkin"` ou `"CATEGORIE:booking"`), fabriqué par
  `http_parking_client.py` pour que le reste du code (qui a besoin d'un
  identifiant pour "quelle place libérer" à la sortie) continue de
  fonctionner sans changement.
- `PlaceAssignment.hold_id` et `ParkingServicePort.mark_place_occupied(...,
  hold_id)` : depuis le 18/11, Parking met une place de côté 30 s au `hold`
  et exige son `hold_id` pour `confirm_entry` (409 si expiré ou déjà
  utilisé). Si la confirmation échoue, **l'entrée est refusée** (« Place non
  confirmée par Parking, réessayez ») : un véhicule ne doit jamais entrer
  sans être compté par Parking.
- `ParkingServicePort.request_place` lève `ParkingUnavailableError` quand
  Parking ne répond pas (panne, délai, clé API refusée) au lieu de renvoyer
  `None` : l'entrée est refusée avec « Service Parking indisponible,
  réessayez plus tard », distinct de « Aucune place disponible » (parking
  réellement complet) — dans la réponse, les logs et les métriques.
- Durée envoyée à Pricing (`http_pricing_client._duration_minutes`) :
  arrondie à la minute supérieure (« tout quart d'heure entamé est dû »,
  règle 2.5), au moins 1 minute (Pricing refuse 0) et **plafonnée à 7 jours**
  (règle 2.4 ; Pricing refuse au-delà). Une sortie juste après l'entrée est
  donc gratuite au lieu d'être bloquée, et un véhicule resté plus de 7 jours
  peut toujours sortir.
- `PricingServicePort.calculate_price` renvoie désormais `Decimal | None`
  (au lieu de toujours `Decimal`) : `None` signale que Pricing est
  indisponible (429/5xx/timeout), traité par `ProcessExitRequest` comme un
  refus propre de la sortie (jamais un montant inventé, jamais de paiement
  tenté). Même principe déjà en place pour `ParkingServicePort.request_place`
  côté entrée — voir l'exemple commenté en [section 4](#4-architecture-hexagonale).
- `PaymentServicePort.request_payment(stay_id, amount)` (au lieu de
  `(vehicle_id, amount)`) renvoie `PaymentResult | None` : conformément au
  workflow "Sortie" des consignes ("une demande de paiement est envoyée avec
  l'identifiant du stationnement concerné"), Access transmet l'identifiant
  du **stationnement** — l'id de la demande d'entrée, stable — qui fonde la
  clé d'idempotence côté Payment. `None` = résultat indéterminé (Payment
  injoignable, ou paiement encore `PENDING` après 40 s) : la sortie est
  refusée avec "réessayez", ce qui est sans risque puisque rejouer la sortie
  renvoie le même paiement (jamais de double encaissement). Un stationnement
  à 0 € ne déclenche aucun paiement (Payment refuse un montant nul).
- `VehiclesServicePort.get_vehicle_info(plate)` / `identify_vehicle(plate)` :
  depuis sa mise à jour du 24/11, Vehicles ne connaît plus de `code` et
  identifie les véhicules par leur plaque (`GET /api/vehicles/{plaque}`, 404
  si inconnue ; `POST /api/vehicles/identify` retrouve ou crée). Access reçoit
  donc de nouveau la plaque (`licensePlate` dans `POST /access/requests`,
  `POST /access/vehicles/known` au lieu de `GET /access/vehicles/{code}/known`)
  et la transmet à Vehicles sans la conserver. Changement de contrat de l'API
  Access, d'où la version `4.0.0`. Le `pseudoId` renvoyé devient le
  `vehicleId`. À l'entrée, une plaque inconnue est créée chez Vehicles comme
  un 4 roues standard (Access ne connaît pas ses caractéristiques) ; à la
  sortie, elle ne l'est jamais.
  Vehicles n'expose pas de justificatif PMR distinct : `isHandicaped` (`handicaped` puis `disabled` avant le 24/11) sert à la
  fois de type de véhicule (`is_handicap`) et de justificatif
  (`disability_permit`), donc un véhicule PMR est toujours autorisé sur une
  place PMR (plus de `CONFIRMATION_REQUIRED` pour justificatif manquant avec
  le vrai service). Une panne de Vehicles (erreur réseau, 5xx, réponse
  hors contrat) n'entraîne jamais de création : elle est traitée comme
  « véhicule non identifié » (procédure alternative), jamais comme un
  plantage d'Access.

**Nommage anglais vs. contenu français** : tous les identifiants de code
(classes d'entités, champs, colonnes SQL, clés JSON) sont en anglais — la
spec d'origine (rédigée en français) est donc traduite dans le code, avec la
correspondance rappelée dans chaque docstring et dans la
[section 8](#8-enums-tables-de-correspondance). En revanche, le contenu des
messages métier renvoyés (`reason`, ex. "Accès autorisé", "Véhicule déjà
présent dans le parking") reste en français, volontairement : Access sert
des conducteurs et exploitants francophones, et ces chaînes sont du contenu
utilisateur, pas des identifiants de code — les traduire n'apporterait rien
et un choix inverse serait trivial à faire évoluer plus tard (elles sont
toutes centralisées dans les deux use cases `Process*Request`).

Toutes ces extensions sont documentées dans le code (docstrings des ports
concernés) et n'affaiblissent aucune des garanties de la spec — notamment la
règle RGPD de non-circulation de la plaque brute, qu'Access transmet à Vehicles sans jamais la conserver.

## 17. TP Splunk (à côté du service)

À lire d'abord : [`SPLUNK.md`](SPLUNK.md), le pas-à-pas. Le dossier [`tp/splunk`](tp/splunk/README.md) contient le TP « Installer Splunk
en local avec Docker » : Dockerfile, scripts de démarrage et d'arrêt, notice.
Il ne fait pas partie du service Access et n'est pas déployé sur Render.

## 18. TP Prometheus (supervision des microservices)

À lire d'abord : [`PROMETHEUS.md`](PROMETHEUS.md), le pas-à-pas. Le dossier
[`tp/prometheus`](tp/prometheus/README.md) contient le TP « Observabilité
avec Prometheus » : le `Dockerfile` du sujet, `prometheus.yml` (Access en
ligne, les cinq autres microservices, un Access local pour simuler une
panne), les scripts de démarrage et d'arrêt, et en bonus un Grafana avec sa
source de données et son tableau de bord provisionnés. Côté service, le TP
s'appuie sur `GET /metrics` ([section 9](#métriques-prometheus)). Prometheus
et Grafana tournent sur l'ordinateur de qui fait la démonstration : ils ne
sont pas déployés sur Render.
