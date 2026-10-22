# Access — microservice de gestion des accès parking

> Décide si un véhicule peut **entrer** ou **sortir** du parking et coordonne les
> échanges nécessaires avec les services **Vehicles**, **Booking**, **Parking**,
> **Pricing** et **Payment**. Fait partie du projet fil rouge "Gestion d'un
> parking" (voir `.claude/access-microservice-spec.md` pour la spécification
> complète, et `.claude/consignes.md` pour le contexte du projet global).

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
| **Version actuelle** | `2.0.0` |
| **URL du service déployé** | https://access-api-a1u7.onrender.com |
| **Documentation Swagger/OpenAPI** | https://access-api-a1u7.onrender.com/docs (ReDoc : `/redoc`, spec brute : `/openapi.json`) |
| **Dépendances (services appelés)** | Vehicles *(mocké)*, Booking *(mocké)*, **Parking** *(réel)*, **Pricing** *(réel)*, Payment *(mocké)* |
| **Tester le service** | Collection Postman `postman/Access-Render.postman_collection.json` + environnement `Access — Render` (clé dans l'en-tête `X-API-Key`) — voir [section 13](#13-postman). Sans clé : `GET /health`. |

### Fonctionnalités

- [x] Résoudre une plaque en identifiant pseudonymisé, sans jamais la stocker/logger/renvoyer.
- [x] Autoriser l'entrée d'un véhicule sans réservation (place attribuée automatiquement).
- [x] Autoriser l'entrée d'un véhicule avec réservation active.
- [x] Refuser l'entrée d'un véhicule déjà présent.
- [x] Refuser l'entrée en cas d'incompatibilité véhicule/place.
- [x] Demander une confirmation (pas un refus direct) si le justificatif PMR manque.
- [x] Calculer et faire payer une sortie (montant réel, paiement mocké).
- [x] Refuser une sortie en cas de paiement refusé ou de véhicule non présent.
- [x] Publier un événement (webhook ou RabbitMQ) à chaque entrée/sortie/refus.
- [x] Lister/consulter l'historique des demandes et des événements publiés (audit).
- [x] Protéger toutes les routes (sauf `/health`) par clé API.
- [x] Résoudre un véhicule via le vrai service **Vehicles**.
- [ ] Vérifier une réservation via le vrai service **Booking**.
- [x] Attribuer/occuper/libérer une place via le vrai service **Parking**.
- [x] Calculer un prix via le vrai service **Pricing**.
- [ ] Exécuter un paiement via le vrai service **Payment**.

> Une case n'est cochée que si le comportement est réellement vérifié —
> montants Pricing et compteurs Parking réels confirmés dans `JOURNAL.md`
> et `reponse.md`.

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
9. [Tests](#9-tests)
10. [Sécurité](#10-sécurité)
11. [Endpoints](#11-endpoints)
12. [Journal de bord (dashboard)](#12-journal-de-bord-dashboard)
13. [Postman](#13-postman)
14. [Déploiement sur Render](#14-déploiement-sur-render)
15. [Rejoindre l'équipe : brancher vos microservices](#15-rejoindre-léquipe--brancher-vos-microservices)
16. [Écarts assumés par rapport à la spec](#16-écarts-assumés-par-rapport-à-la-spec)

---

## 1. Présentation

Access est le **point central** du workflow d'entrée/sortie du parking. Il ne
possède **aucune donnée métier des autres services** (identité véhicule,
réservations, disponibilité des places, tarifs, transactions) : il les
interroge via 5 ports dédiés (mockés pour ce MVP) et ne conserve en propre
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

    V->>A: Entrée (plaque brute)
    A->>Ve: get_vehicle_info(plate)
    Ve-->>A: vehicleId (pseudonymisé) + attributs
    A->>B: get_reservation(vehicleId)
    alt pas de réservation
        A->>P: request_place(vehicleType)
    end
    A-->>V: Autorisation (AUTHORIZED / REFUSED / CONFIRMATION_REQUIRED)
    A--)A: Publie VEHICLE_ENTERED / ACCESS_REFUSED

    V->>A: Sortie (plaque brute)
    A->>Ve: get_vehicle_info(plate)
    A->>Pr: calculate_price(...)
    Pr-->>A: amount
    A->>Pa: request_payment(vehicleId, amount)
    Pa-->>A: succès / échec
    A-->>V: Autorisation de sortie
    A--)A: Publie VEHICLE_EXITED / ACCESS_REFUSED
```

**Règle absolue (RGPD) : la plaque brute n'est utilisée qu'à un seul endroit**
de toute la codebase — l'appel `VehiclesServicePort.get_vehicle_info(plate)`
depuis les use cases `ProcessEntryRequest` / `ProcessExitRequest` /
`CheckPlateKnown`. Elle n'est **jamais** persistée, publiée dans un événement,
renvoyée par l'API, ni écrite dans un log (un filtre de logging redonde même
cette garantie en profondeur, voir [section 10](#10-sécurité)).

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

Un registre de plaques de démonstration est câblé dans le mock Vehicles pour
exercer chaque cas manuellement — détail dans
[`mock_vehicles_client.py`](src/infrastructure/external/mock_vehicles_client.py) :

| Plaque       | vehicleId              | Profil                                                       |
|--------------|--------------------------|---------------------------------------------------------------|
| `AA-111-AA`  | `v_standard_4wheeler`    | 4 roues standard                                               |
| `BB-222-BB`  | `v_2wheeler`             | 2 roues                                                        |
| `CC-333-CC`  | `v_xl`                   | 4 roues XL                                                     |
| `DD-444-DD`  | `v_electric`             | 4 roues électrique                                             |
| `EE-555-EE`  | `v_disabled_ok`          | 4 roues handicapé, **avec** justificatif d'accessibilité       |
| `FF-666-FF`  | `v_disabled_no_permit`   | 4 roues handicapé, **sans** justificatif (→ confirmation)      |
| `GG-777-GG`  | `v_with_reservation`     | 4 roues standard, **a une réservation active** (Booking)       |
| `HH-888-HH`  | `v_payment_fail`         | 4 roues standard, **paiement toujours refusé** à la sortie     |
| toute autre  | —                        | inconnue de Vehicles (→ rejet)                                 |

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
│   ├── db/              # SQLAlchemy : modèles, session, repositories SQLite
│   ├── external/        # Mocks + squelettes HTTP (5 services) + OutboxEventPublisher/
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
   `SqliteAccessRepository` écrit en base, `RabbitMQEventPublisher` publie
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

Chaque service externe a sa **propre bascule mock/réel**
(`VEHICLES_USE_MOCK`, `BOOKING_USE_MOCK`, `PARKING_USE_MOCK`,
`PRICING_USE_MOCK`, `PAYMENT_USE_MOCK`) — `USE_MOCKS` reste la valeur par
défaut globale tant qu'aucune bascule individuelle n'est définie. **C'est
volontaire** : vos camarades finissent leur service chacun à son rythme, pas
question d'attendre que les 5 soient prêts pour en brancher un premier. Les
5 squelettes HTTP existent déjà (`infrastructure/external/http_*_client.py`),
chacun avec des `TODO` explicites listant ce qui reste à confirmer avec
l'équipe du service concerné (route exacte, méthode HTTP, noms de champs
JSON, codes d'erreur). Pour finaliser Vehicles par exemple :

1. Ouvrez `src/infrastructure/external/http_vehicles_client.py` et traitez
   chaque `TODO[VEHICLES-*]` avec la vraie spec de l'équipe Vehicles (route,
   méthode, champs de réponse, code "inconnu").
2. Renseignez `VEHICLES_SERVICE_URL` (son URL réelle) et ajoutez
   `VEHICLES_USE_MOCK=false` — dans `.env` en local, ou dans **Render →
   access-api → Environment** pour la version déployée.
3. C'est tout — `deps.py::get_vehicles_port()` bascule automatiquement sur
   `HttpVehiclesClient` dès que `VEHICLES_USE_MOCK=false`, **sans toucher au
   `USE_MOCKS` global** ni aux 4 autres services qui restent mockés en
   attendant.

> ⚠️ **CORS n'a rien à voir avec ce branchement.** `CORS_ALLOWED_ORIGINS`
> ne concerne que du JavaScript exécuté **dans un navigateur** qui
> appellerait l'API Access depuis un autre domaine — pas les appels
> serveur-à-serveur (Access → Vehicles via `httpx`, ou l'inverse). Rien à
> configurer côté CORS pour brancher un microservice de l'équipe.

**Aucune autre couche à toucher** : ni `domain`, ni `application`, ni les
routers, ni les schémas — c'est toute la promesse de l'architecture
hexagonale. Le même principe s'applique identiquement à Booking, Parking,
Pricing et Payment (`get_booking_port`, `get_parking_port`, etc., dans le
même fichier `deps.py`) — chaque squelette liste ses propres `TODO` :

| Service  | Fichier squelette                      | Points ouverts principaux |
|----------|------------------------------------------|----------------------------|
| Vehicles | `http_vehicles_client.py`  | Route/méthode, code "inconnu", noms de champs |
| Booking  | `http_booking_client.py`   | Route/méthode, code "pas de réservation", `placeId` déjà assigné ou non |
| **Parking** | `http_parking_client.py` | **✅ Branché** (`hold`/`confirm_entry`/`free`, catégories STANDARD/XL/ELECTRIC/HANDICAPPED/TWO_WHEELS) — pas de `placeId` réel, encodage synthétique `"CATEGORIE:walkin\|booking"`, voir section 16 |
| **Pricing** | `http_pricing_client.py` | **✅ Branché** (`PRICING_USE_MOCK=false`) contre le vrai service (`POST /quote`) — mapping `PlaceType → zone` et arrondi de durée pour les réservations restent des hypothèses documentées dans le fichier, voir aussi section 16 |
| Payment  | `http_payment_client.py`   | Route/méthode, clé d'idempotence (consignes 2.6), statuts intermédiaires |

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
  faudra déclarer l'exchange toi-même (`durable=True`, pas seulement
  `passive=True`) puisqu'il n'existera pas encore localement ; voir
  l'historique git de `rabbitmq_event_publisher.py` pour un exemple de
  déclaration active si besoin.

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
au cas "véhicule inconnu de Vehicles")

**AuthorizationResult** — `1=AUTHORIZED` · `2=REFUSED` · `3=CONFIRMATION_REQUIRED`

**EventType** — `1=VEHICLE_ENTERED` · `2=VEHICLE_EXITED` · `3=ACCESS_REFUSED` · `4=OTHER`

**DetectionSource** — `1=CAMERA` · `2=TERMINAL` · `3=LPR` · `4=MOBILE_APP`
(pour une sortie, `TERMINAL` et `MOBILE_APP` sont tous deux valides)

**PresenceStatus** *(technique)* — `1=IN` · `2=OUT`

**VehicleCategory** *(technique, véhicule ET place)* — `1=TWO_WHEELER` · `2=FOUR_WHEELER`

---

## 9. Tests

```bash
source .venv/bin/activate
pytest              # unitaires + intégration
pytest tests/unit           # règles métier + use cases (ports mockés)
pytest tests/integration    # endpoints via TestClient FastAPI (SQLite en mémoire)
pytest -v            # détail de chaque cas
```

Couverture (91 tests) :

- **Unitaires** — matrice complète de la règle de compatibilité
  véhicule/place, règle de présence, règle d'accessibilité ; chaque use case
  (`ProcessEntryRequest`, `ProcessExitRequest`) avec tous les ports mockés ;
  comportement best-effort de `RabbitMQEventPublisher` (broker injoignable).
- **Intégration** — entrée autorisée (sans/avec réservation), entrée refusée
  (déjà présent, type incompatible), entrée en confirmation requise
  (accessibilité), entrée rejetée (véhicule inconnu), sortie autorisée,
  sortie refusée (paiement échoué, véhicule non présent), `/health`,
  `/access/plates/.../known`, et un **test dédié** qui rejoue plusieurs
  scénarios puis inspecte directement chaque table SQLite pour garantir
  qu'aucune valeur au format plaque française n'y apparaît
  (`tests/integration/test_no_plate_leak.py`).

### Intégration continue (CI/CD)

Chaque push sur `main` et chaque pull request déclenche le pipeline
GitHub Actions [`.github/workflows/ci.yml`](.github/workflows/ci.yml), composé
de 5 jobs indépendants qui doivent **tous** passer :

| Job | Outil | Ce qu'il vérifie |
|---|---|---|
| Lint | `ruff` | Erreurs, imports, bugs probables, règles de sécurité (config : `ruff.toml`) |
| Tests | `pytest` | Les 91 tests unitaires + intégration, sans aucun secret |
| Sécurité du code | `bandit` | Analyse statique (SAST) : injections, appels dangereux, secrets en dur… |
| Dépendances | `pip-audit` | Vulnérabilités connues (CVE) dans `requirements.txt` |
| Secrets | `gitleaks` | Aucun secret (clé API, URL CloudAMQP…) dans tout l'historique git |

Render est configuré en **Auto-Deploy : After CI Checks Pass** : un commit
sur `main` n'est déployé que si le pipeline est entièrement vert. En
complément, **Dependabot** ([`.github/dependabot.yml`](.github/dependabot.yml))
ouvre chaque semaine une PR de mise à jour des dépendances Python et des
actions GitHub, elle-même validée par la CI.

Reproduire la CI en local :

```bash
pip install -r requirements-dev.txt
ruff check src tests && pytest && bandit -r src -q && pip-audit -r requirements.txt
```

---

## 10. Sécurité

- **Authentification** : clé API (`X-API-Key`) sur toutes les routes sauf
  `/health` (`src/infrastructure/security/api_key_auth.py`). Jamais loggée.
- **Validation stricte** : Pydantic, y compris le format de plaque française
  (`^[A-Z]{2}-\d{3}-[A-Z]{2}$`) sur la requête d'entrée et sur le path param
  de `/access/plates/{plate}/known`.
- **CORS restrictif** : liste blanche configurable (`CORS_ALLOWED_ORIGINS`).
- **Rate limiting** : `POST /access/requests` limité (`RATE_LIMIT_ACCESS_REQUESTS`,
  `20/minute` par défaut) via `slowapi`.
- **Gestion d'erreurs centralisée** : `main.py` intercepte `HTTPException`,
  les erreurs de validation et toute exception non prévue — **aucune stack
  trace n'est jamais renvoyée au client** (500 générique, détail loggé côté
  serveur uniquement).
- **RGPD / minimisation des données** : voir la règle absolue en
  [section 1](#1-présentation). En complément de la discipline de code, un
  `logging.Filter` (`RedactPlateFilter`) masque toute sous-chaîne au format
  plaque dans les logs, en défense en profondeur.

---

## 11. Endpoints

Préfixe `/api/v1` (sauf `/health`).

| Méthode | Route | Auth | Description |
|---|---|---|---|
| POST | `/access/requests` | Oui | Crée et traite une demande d'accès (entrée ou sortie) |
| GET | `/access/requests/{id}` | Oui | Détail d'une demande + décision |
| GET | `/access/requests?vehicleId=&type=&from=&to=` | Oui | Liste/filtre (audit) |
| GET | `/access/plates/{plate}/known` | Oui | Vérifie si une plaque est connue, sans rien persister |
| GET | `/access/events` | Oui | Liste les événements publiés (outbox, démo/observabilité) |
| GET | `/health` | Non | Healthcheck (API + DB) |

Documentation interactive complète (schémas, exemples, codes d'erreur) sur
`/docs`.

### Exemple — `POST /access/requests` (entrée)

```json
{
  "plate": "AA-111-AA",
  "type": 1,
  "date": "2026-09-02T10:15:00Z",
  "source": 3,
  "photoBase64": null
}
```

Réponse — ne contient jamais la plaque :

```json
{
  "requestId": "b3a1f7b0-...-uuid",
  "vehicleId": "v_standard_4wheeler",
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

## 12. Journal de bord (dashboard)

Une petite page statique (`src/interfaces/api/static/dashboard.html`) est
servie **par Access lui-même** — pas de port supplémentaire, pas de serveur
front séparé, elle appelle `GET /api/v1/access/events` en same-origin (donc
aucun souci CORS). Accessible sur http://localhost:8000/ (redirige
automatiquement) ou http://localhost:8000/static/dashboard.html.

Renseignez votre `X-API-Key` dans le champ prévu (stockée uniquement dans le
`localStorage` de votre navigateur) : la liste des événements se rafraîchit
automatiquement (intervalle configurable), avec un badge coloré par type
d'événement et le détail JSON dépliable.

---

## 13. Postman

Un dossier [`postman/`](postman/) contient :

- `Access-Microservice.postman_collection.json` — toutes les routes,
  organisées par dossier (Health / Access — Entry / Access — Exit / Access —
  Lookup / Events / **Errors — edge cases**), avec des exemples prêts à
  l'emploi pour chaque scénario du tableau de plaques de démo (entrée
  simple, réservation, accessibilité, véhicule inconnu, sortie payée,
  paiement refusé...).
- `Access-Microservice.postman_environment.json` — variables `baseUrl` et
  `apiKey` à ajuster selon votre `.env`, pour tester en **local**.
- `Access-Render.postman_collection.json` + `Access-Render.postman_environment.json`
  — strictement les mêmes requêtes, prêtes à pointer vers le **déploiement
  public Render** (section 14) plutôt que `localhost` : pratique pour que
  toute l'équipe teste la même instance sans rien installer.

Le dossier **"Errors — edge cases"** contient volontairement des requêtes
invalides (pas de clé API, plaque mal formée, type invalide, champ manquant,
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
versionné" — **il faut la coller toi-même dans le dashboard Render** une
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
3. Récupérez l'URL publique du service (en haut de la page `access-api`,
   type `https://access-api-xxxx.onrender.com`).
4. Ouvrez `postman/Access-Render.postman_environment.json` dans Postman et
   renseignez `baseUrl` (l'URL de l'étape 3) et `apiKey` (la clé de l'étape 2) —
   ou envoyez-moi l'URL, je peux mettre à jour le fichier directement.
5. Vérifiez `GET /health` puis un scénario complet (voir tableau de plaques
   de démo, section 3) avec la collection **"Access — Render"**.

### ⚠️ Points à vérifier / limites connues

Je n'ai pas d'accès direct à ton compte Render pour tester ce blueprint en
conditions réelles — voici ce qui mérite une vérification de ta part au
premier déploiement :

- **Disque éphémère (plan Free)** : le fichier SQLite (`access.db`) est
  réinitialisé à chaque redéploiement/redémarrage du service `access-api`
  sur le plan Free (pas de disque persistant sans upgrade). Acceptable pour
  une démo/tests d'intégration entre camarades, mais les données ne
  survivent pas dans la durée. Si besoin de persistance, il faudra un plan
  payant avec un **Disk** Render monté (ex. `/var/data`) et
  `DATABASE_URL=sqlite:////var/data/access.db`.
- **Mise en veille (plan Free)** : `access-api` s'endort après ~15 min
  d'inactivité ; le premier appel suivant peut prendre 30-60s (cold start) —
  normal, pas un bug. Les services de l'équipe (Parking, Pricing...) sont
  logés pareil : un appel sortant d'Access vers l'un d'eux peut donc aussi
  déclencher son réveil. Les clients HTTP réels utilisent un timeout de
  **20s** (`infrastructure/external/http_*_client.py`) pour l'encaisser, et
  toute erreur (429/5xx/timeout/connexion refusée) est traitée comme un
  refus métier propre plutôt qu'un crash — voir l'exemple en
  [section 4](#4-architecture-hexagonale).
- **CORS** : `CORS_ALLOWED_ORIGINS=*` par défaut dans le blueprint (démo
  publique/équipe) — à restreindre à vos vraies origines une fois un front
  ou un domaine d'équipe fixé.
- **`RABBITMQ_URL` vide ou incorrect** : si tu vois `Échec de publication
  RabbitMQ pour l'événement ...` dans les logs `access-api`, vérifie
  d'abord que la variable est bien renseignée dans Environment (étape 2bis),
  et que l'URL CloudAMQP est toujours valide (pas de rotation de mot de
  passe côté CloudAMQP entre-temps).
- **Ancienne option abandonnée** : un service RabbitMQ auto-hébergé sur
  Render (privé, payant) reste en commentaire tout en bas de `render.yaml`
  au cas où le broker CloudAMQP externe serait un jour abandonné — pas
  utilisé actuellement.

---

## 15. Rejoindre l'équipe : brancher vos microservices

Une fois Access déployé sur Render, tes camarades peuvent l'appeler
directement sans rien installer — c'est tout l'intérêt d'un déploiement
public partagé :

- **Ils veulent qu'Access les appelle (Vehicles, Booking, Parking, Pricing,
  Payment)** : une fois leur propre service déployé (Render ou ailleurs),
  donne-moi son URL publique → je mets à jour `VEHICLES_SERVICE_URL` (etc.)
  dans les variables d'environnement Render de `access-api`, je complète le
  squelette HTTP correspondant (`infrastructure/external/http_*_client.py`,
  déjà prêt avec des `TODO` précis, section 5) avec leur vrai contrat
  d'API, puis bascule la variable **de ce service uniquement**
  (`VEHICLES_USE_MOCK=false`, `BOOKING_USE_MOCK=false`, etc.) — les autres
  restent mockés tant que leurs équipes ne sont pas prêtes, aucune autre
  couche à toucher.
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
- `Reservation.place_id` (optionnel) : Booking (mocké) peut indiquer
  directement la place réservée ; si absent (cas réel désormais, cf.
  ci-dessous), le use case retombe sur `ParkingServicePort.request_place`.
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
- `PricingServicePort.calculate_price` renvoie désormais `Decimal | None`
  (au lieu de toujours `Decimal`) : `None` signale que Pricing est
  indisponible (429/5xx/timeout), traité par `ProcessExitRequest` comme un
  refus propre de la sortie (jamais un montant inventé, jamais de paiement
  tenté). Même principe déjà en place pour `ParkingServicePort.request_place`
  côté entrée — voir l'exemple commenté en [section 4](#4-architecture-hexagonale).

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
règle RGPD de non-circulation de la plaque brute, vérifiée par un test dédié.
