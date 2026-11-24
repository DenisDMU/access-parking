# Access — dossier de revue de code et d'intégration (jalons 10 et 11)

Support de la revue du 24 novembre. Chaque point renvoie au code ou au
README. Les écarts constatés en conditions réelles sont listés en fin de
document, avec leur statut (corrigé / documenté / à traiter avec l'équipe).

---

## 1. Revue de code

### Organisation et séparation des responsabilités

Architecture hexagonale (README [section 4](../README.md#4-architecture-hexagonale)) :

| Couche | Rôle | Dépend de |
|---|---|---|
| `src/domain/` | Entités, règles métier pures, ports (`Protocol`) | rien |
| `src/application/use_cases/` | Orchestration des workflows | `domain` uniquement |
| `src/infrastructure/` | Clients HTTP, SQLite, RabbitMQ, logs, métriques, sécurité | `domain` |
| `src/interfaces/api/` | FastAPI : routes, schémas, middlewares, composition (`deps.py`) | tout |

Vérifiable : aucun `import` de `infrastructure`/`interfaces` dans `domain` ni
`application` (`grep -rn "infrastructure\|interfaces" src/domain src/application`).

### Cohérence code ↔ règles métier

| Règle (document « Règles métier ») | Code | Tests |
|---|---|---|
| Un véhicule déjà présent ne peut pas entrer | `domain/rules/presence_rule.py::can_enter` | `test_presence_rule.py`, `test_access_entry.py` |
| Un véhicule absent ne peut pas sortir | `presence_rule.py::can_exit` | `test_process_exit_request.py` |
| Compatibilité véhicule / place (2 roues, XL, électrique, PMR) | `vehicle_place_compatibility_rule.py` | matrice complète `test_vehicle_place_compatibility_rule.py` |
| Place PMR sans justificatif → confirmation, pas refus | `disability_rule.py` | `test_disability_rule.py` |
| Réservation → place du pool « booking », sinon « walkin » | `ProcessEntryRequest` | `test_process_entry_request.py` |
| Sortie : prix (Pricing) puis paiement (Payment) du stationnement | `ProcessExitRequest` | `test_process_exit_request.py`, `test_http_payment_client.py` |
| Sortie datée avant l'entrée refusée | `stay_rule.py` | `test_stay_rule.py`, `test_quality.py` |
| Durée plafonnée à 7 jours, tout quart d'heure entamé dû (règles 2.4 et 2.5) | `http_pricing_client.py::_duration_minutes` (minute supérieure, 1 min à 7 jours ; le calcul par quart d'heure est fait par Pricing) | `test_http_pricing_client.py` |
| La plaque ne fait que traverser Access (RGPD) | transmise à Vehicles puis oubliée ; seul le `pseudoId` est stocké, publié, renvoyé ; erreurs 422 sans la valeur reçue | `test_no_plate_leak.py` (réponses, base, événements, logs), `test_http_vehicles_client.py` |

### Gestion des erreurs

- Entrées : validation Pydantic → 422 (400 pour une photo non décodable), rien
  n'est persisté ni appelé.
- Services appelés : toute panne (timeout, connexion refusée, 4xx/5xx,
  réponse inattendue) devient une **décision métier propre** (refus motivé
  ou « véhicule inconnu »), jamais une 500 — un seul client y échappait
  (Booking), corrigé en 3.2.0.
- Erreur imprévue : 500 générique sans détail technique, avec `correlationId`
  pour retrouver la stack trace dans les logs.

### Logs, tests, dépendances

- Logs : README [section 9](../README.md#logs-exploitables) — correlation ID,
  une ligne par décision, log d'accès, avertissements des appels sortants.
- Tests : 246 (unitaires + intégration ; clés étrangères appliquées en SQLite comme en Postgres ; suite d'intégration validée aussi contre la base Neon de production, dans un schéma jetable), aucun réseau ; CI en 5 étapes.
- Dépendances (`requirements.txt`) : FastAPI, SQLAlchemy, Pydantic, httpx
  (appels sortants), pika (RabbitMQ), slowapi (rate limiting),
  prometheus-fastapi-instrumentator (métriques). Surveillées par Dependabot et
  `pip-audit` en CI.

### Choix réalisés avec ou sans assistance de l'IA

> À compléter personnellement avant la revue : quelles parties ont été
> conçues seul, lesquelles avec un assistant IA, et ce qui a été vérifié /
> réécrit / refusé dans ses propositions. L'enseignant attend surtout que
> chaque choix ci-dessous puisse être expliqué.

Principaux choix techniques à savoir justifier :

- Architecture hexagonale plutôt qu'un CRUD FastAPI direct (règles testables
  sans réseau, services réels branchés un par un sans toucher au métier).
- Postgres (Neon) en production depuis 3.6.0, SQLite en local et dans les
  tests : le disque de Render est éphémère, la base effaçait tout à chaque
  redémarrage.
- Publication d'événements **best-effort** après persistance (outbox) : une
  panne du bus ne bloque jamais une barrière.
- Paiement idempotent (clé `access:{stationnement}:exit`) + polling borné.
- Clé API simple plutôt qu'OAuth2 (périmètre du jalon 15), avec une **clé
  borne séparée** (4.1.0) : la borne client est un écran public, sa clé
  n'ouvre que le passage d'un véhicule (401 partout ailleurs), jamais
  l'historique ni les présences.
- La plaque ne fait que traverser Access (4.0.0) : transmise à Vehicles puis
  oubliée, jamais stockée, publiée, renvoyée ni loggée (test dédié).
- Borne client (`/borne`) servie par Access lui-même : pas de front séparé à
  déployer, pas de CORS ; champs de ticket ajoutés à la réponse sans en
  modifier aucun (aucun consommateur cassé).

---

## 2. Revue d'intégration

### Contrats d'API consommés (appels synchrones REST)

Tous les appels passent par `infrastructure/external/outgoing_http.py` :
timeout 20 s, en-tête `X-Correlation-ID`, métriques par service.

| Service | Appel | Données envoyées | Données utilisées | Erreur → comportement d'Access |
|---|---|---|---|---|
| **Vehicles** | `GET /api/vehicles/{plaque}` ; à l'entrée, sur un 404 : `POST /api/vehicles/identify` puis nouveau `GET` | plaque (normalisée `AB-123-CD`) | `pseudoId`, `twoWheels`, `xl`, `electric`, `disabled` | 404 à l'entrée → véhicule créé (4 roues standard) ; 404 à la sortie, 5xx ou réseau → « véhicule non identifié » (confirmation requise), jamais de création sur une panne |
| **Booking** *(mocké)* | `GET /bookings/active?vehicleId=` *(supposé)* | `vehicleId` pseudonymisé | `id`, `reservedPlaceType`, dates, `placeId` | 404 → pas de réservation ; panne → entrée sans réservation |
| **Parking** (1.5.0) | `GET /parking/categories` (en cache 5 min) puis `POST /parking/hold` → `POST /parking/confirm_entry` (avec `hold_id`) ; sortie : `POST /parking/free` ; exploitation : `GET /parking/occupation` — en-tête `X-API-Key` exigé | `category_name`, `commercial_type` (`walkin`/`booking`), `hold_id` | `success`, `hold_id` (place mise de côté 30 s), `label` ; occupation : `spot_taken`, `spot_held`, `total_capacity` | catégorie absente de la liste ou 404 sur `hold` → « Catégorie de place X inconnue du service Parking » ; liste indisponible → vérification sautée (n'empêche jamais une entrée) ; `success: false` → « Aucune place disponible » ; panne ou clé refusée → « Service Parking indisponible » ; confirmation refusée (409 expiré/déjà utilisé, 422) → entrée refusée « Place non confirmée par Parking » ; `free` en échec loggé |
| **Pricing** | `POST /quote` | `zone`, `mode`, `duration_min` | `amount_eur` | panne → sortie refusée « tarification indisponible » |
| **Payment** | `POST /payments` puis `GET /payments/{id}` | montant en centimes, clé d'idempotence, référence du stationnement | `payment_id`, `status` | `REFUSED` → refus ; panne / `PENDING` > 40 s → refus « réessayez » (rejouable sans double débit) |

Mappings à valider en revue avec les équipes concernées :

- Catégorie Parking / zone Pricing, même priorité dans les deux clients :
  PMR > 2 roues > électrique > XL > standard.
- Pricing en mode réservation : durée arrondie à l'heure supérieure (≥ 60 min).

### Échanges asynchrones (publiés par Access)

Exchange **`microservice-event-bus`** (CloudAMQP, administré par l'équipe,
déclaré en passif par Access).

| Routing key | Quand | Corps (`payload`) |
|---|---|---|
| `access.entry` | entrée autorisée | `vehicleId`, `placeId`, `placeType`, `reservation` |
| `access.exit` | sortie autorisée | `vehicleId`, `placeId`, `amount`, `paymentId`, `enteredAt` (heure d'entrée, UTC), `durationMinutes` (durée réelle, minutes entamées) |
| `access.refused` | refus ou véhicule inconnu | `vehicleId` (ou `null`), `reason` |
| `access.other` | confirmation PMR requise | `vehicleId`, `reason`, place |

Enveloppe commune : `id`, `type` (1 à 4), `requestId`, `payload`,
`createdAt`, `correlationId`. Le correlation ID est aussi dans la propriété
AMQP `correlation_id` et l'en-tête `X-Correlation-ID`. Événements de test :
`scripts/simulate_bus_events.py` (marqués `simulated: true`).

### Workflows réels et correlation ID

```mermaid
sequenceDiagram
    participant B as Borne / client
    participant A as Access
    participant Ve as Vehicles
    participant P as Parking
    participant Bus as Bus d'événements
    B->>A: POST /access/requests (X-Correlation-ID: c1, ou généré)
    A->>Ve: GET /api/vehicles/{plaque} (X-Correlation-ID: c1)
    A->>P: POST /parking/hold (X-Correlation-ID: c1)
    A->>P: POST /parking/confirm_entry (X-Correlation-ID: c1)
    A--)Bus: access.entry (correlation_id: c1)
    A-->>B: décision (X-Correlation-ID: c1)
```

Toutes les lignes de log d'Access pour ce passage portent `[cid=c1]`. Pour la
démonstration collective, il suffit que chaque service reprenne l'en-tête
reçu dans ses propres logs.

### Dépendances entre services

Access dépend **en synchrone** de Vehicles (entrée et sortie), Parking
(entrée, et libération à la sortie), Pricing et Payment (sortie). Aucun
service ne dépend d'Access en synchrone : les autres consomment ses
événements. Une panne de l'un d'eux bloque donc le passage concerné, mais
toujours avec un refus explicite et loggé, jamais un plantage.

---

## 3. Écarts constatés et statut

| # | Constat | Statut |
|---|---|---|
| 1 | Booking toujours mocké : contrat (route, codes, champs) non confirmé | 📌 à traiter avec l'équipe Booking — `TODO[BOOKING-*]` dans `http_booking_client.py` |
| 2 | Une panne de Booking (réel) aurait donné une 500 | ✅ corrigé en 3.2.0 (entrée traitée sans réservation) + tests |
| 3 | Vehicles renvoyait **500** (et non 404) pour un code inconnu | ✅ corrigé par Vehicles (24/11) : 404 pour une plaque inconnue, qu'Access distingue désormais d'une panne |
| 4 | Vehicles n'a pas de justificatif PMR distinct : `disabled` sert de type et de justificatif → la confirmation PMR n'arrive jamais avec le vrai service | 📄 documenté (README section 16) — responsabilité à clarifier |
| 5 | Parking ne gère pas d'identifiant de place : `placeId` synthétique `CATEGORIE:walkin\|booking` | 📄 documenté, conforme aux consignes (places comptées par catégorie) |
| 6 | 18/11 : service Parking injoignable (aucune réponse en 75 s) → toutes les entrées refusées « Aucune place disponible », motif trompeur | ✅ corrigé en 3.4.0 : motif distinct « Service Parking indisponible, réessayez plus tard » |
| 7 | 18/11 : variables du `render.yaml` non appliquées par un déploiement automatique (Access appelait `localhost` pour Vehicles) | ✅ résolu par redéploiement ; détectable désormais par le smoke test |
| 8 | Payment n'active pas encore son authentification (`auth_enabled: false`) | 📄 Access envoie déjà `X-API-Key` si `PAYMENT_API_KEY` est renseignée |
| 10 | 18/11 : Parking a activé son authentification (`X-API-Key`) sans prévenir → appels d'Access refusés | ✅ Access envoie `PARKING_API_KEY` (3.4.0) ; clé obtenue et saisie dans Render |
| 11 | 18/11 : `confirm_entry` exige le `hold_id` du `hold` (place mise de côté 30 s) | ✅ géré en 3.5.0 ; entrée refusée si la confirmation échoue |
| 12 | **Sécurité Parking** : la clé API de Parking était écrite en clair dans sa page publique `/dashboard` | ✅ vérifié le 24/11 : la page demande désormais la clé à l'utilisateur (`prompt`, gardée en `sessionStorage`), plus aucune clé dans le code source |
| 13 | La doc de Parking indique qu'il **consomme aussi les événements RabbitMQ** pour les confirmations d'entrée/sortie : si Parking confirme à partir de `access.entry` en plus de l'appel `confirm_entry` d'Access, une entrée pourrait être comptée deux fois | 📌 à clarifier avec l'équipe Parking (un seul des deux mécanismes) |
| 14 | **Vehicles ne respectait pas la règle 3.2** (« Vehicles *recherche ou crée* l'identifiant pseudonymisé ») : `identify` exigeait un code fourni par l'appelant et renvoyait 500 pour une plaque connue | ✅ corrigé par Vehicles (24/11) : `identify` retrouve ou crée (même `pseudoId` pour une même plaque, vérifié par appels réels) ; Access l'appelle à l'entrée pour une plaque inconnue (4.0.0) |
| 15 | Durée envoyée à Pricing : 0 min (sortie juste après l'entrée) et plus de 7 jours refusés par Pricing (422) → sortie bloquée ; règle 2.4 (« durée plafonnée à sept jours ») non appliquée | ✅ corrigé en 3.5.1 : durée arrondie à la minute supérieure, bornée entre 1 min et 7 jours |
| 16 | Le cas « véhicule inconnu → intervention d'un agent » vient de la spec d'Access, pas des règles métier, qui mettent le « traitement manuel des erreurs » hors périmètre (section 5) | 📄 depuis 4.0.0, ne reste possible qu'en cas de panne de Vehicles (entrée) ou de plaque jamais entrée (sortie) : refus sûr, barrière fermée |
| 17 | 18/11 : SQLite sur le disque éphémère de Render → base effacée à chaque redéploiement ou réveil (constaté : 4 passages perdus en quelques minutes). Un véhicule garé pendant une mise en veille ne pouvait plus sortir | ✅ 3.6.0 : Postgres Neon en production (`DATABASE_URL`), tables créées au démarrage. Corrigé au passage : la présence était enregistrée avant la demande d'entrée qu'elle référence (clé étrangère), ce qui aurait fait échouer chaque entrée sous Postgres |
| 18 | 24/11 : **nouveau contrat Vehicles**, sans prévenir : plus de `code`, consultation par plaque (`GET /api/vehicles/{plaque}`). Access envoyait un code → tous les véhicules auraient été « inconnus » | ✅ 4.0.0 : Access reçoit la plaque (`licensePlate`), la transmet à Vehicles sans la conserver, vérification déplacée en `POST /access/vehicles/known` (plaque hors des URL) ; testé contre le vrai service. 📌 à signaler à Vehicles : la plaque figure dans l'URL de `GET /api/vehicles/{plaque}`, donc dans les journaux de leur hébergeur |
| 19 | 24/11 : **Parking 1.5.0** : `GET /parking/categories`, `label` dans ses réponses, `spot_held` dans l'occupation (champs uniquement ajoutés, rien de cassé) | ✅ 4.2.0 : catégories vérifiées avant chaque `hold` (motif précis si Parking renomme une catégorie), libellés affichés (borne, dashboard), occupation par catégorie dans le dashboard (`GET /access/parking`). Contrat lu sur le Swagger de Parking : leurs routes exigent la clé Parking, non disponible en local, donc à revérifier en ligne après déploiement |
| 9 | Propagation du correlation ID par les autres services | 📌 à vérifier en revue d'intégration (Access le transmet partout) |
