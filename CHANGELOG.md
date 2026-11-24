# Changelog — Access

Version exposée par `GET /health` (`version` + `commit` déployé) et dans `/docs`.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
sémantique (majeure = contrat d'API cassé).

## [4.0.0] — 2026-11-24 — Vehicles par plaque

Vehicles a changé de contrat le 24/11 : plus de `code`, les véhicules sont
identifiés par leur plaque. Sans cette version, tous les véhicules étaient
« inconnus ».

### Modifié (rupture de contrat)
- `POST /access/requests` reçoit `licensePlate` (format `AB-123-CD`,
  minuscules et espaces acceptés, normalisée) au lieu de `vehicleCode`.
- `POST /access/vehicles/known` (plaque dans le corps) remplace
  `GET /access/vehicles/{vehicle_code}/known` : la plaque ne passe jamais
  dans une URL.
- Smoke test : `VEHICLE_PLATE` remplace `VEHICLE_CODE`.

### Ajouté
- Entrée : une plaque inconnue de Vehicles (404) est créée via
  `POST /api/vehicles/identify` (règle 3.2), comme un 4 roues standard, et
  l'entrée continue. Une panne de Vehicles ne crée jamais rien : agent requis.
- Sortie et vérification : consultation seule, jamais de création.
- Test anti-fuite rétabli : aucune plaque dans les réponses, la base, les
  événements ni les logs.

### Sécurité
- La plaque est transmise à Vehicles puis oubliée : jamais stockée,
  publiée, renvoyée ni loggée (le client Vehicles ne logge que le type
  d'erreur, jamais l'URL appelée).
- Les erreurs 422 ne recopient plus la valeur reçue (`input` retiré).

### Corrigé
- Client Vehicles : une réponse JSON qui n'est pas un objet ne fait plus
  planter la demande (traitée comme Vehicles indisponible).
- Simulateur (`scripts/simulate_bus_events.py`) : une erreur réseau (DNS
  indisponible, connexion coupée) n'arrête plus la simulation ; la
  publication est retentée au cycle suivant.

### Modifié
- Dépendances mises à jour en un seul passage de CI (reprend les PR
  Dependabot #31 à #35) : `fastapi>=0.163.1`, `pydantic>=2.14.3`,
  `psycopg[binary]>=3.3.9`, `httpx>=0.28.1`, `certifi>=2026.10.23`.
  191 tests au vert ; suite d'intégration validée aussi contre la base Neon.
- Dashboard : borne et recherche par plaque.

## [3.6.2] — 2026-11-18 — Événement de sortie enrichi

### Ajouté
- `access.exit` contient `enteredAt` (heure d'entrée, UTC) et
  `durationMinutes` (durée réelle, minutes entamées), pour le ticket de
  sortie du service Messages. Champs ajoutés, aucun champ modifié.
- Simulateur : mêmes champs, stationnements de 20 min à 5 h et montant
  indicatif calculé comme Pricing (1re heure gratuite, 0,75 € le quart
  d'heure).

## [3.6.1] — 2026-11-18 — Nettoyage avant l'oral

### Modifié
- Repositories renommés `Sql…Repository` (au lieu de `Sqlite…`) : ils
  fonctionnent avec SQLite en local et Postgres en production.
- `ProcessEntryRequest` : attribution de la place et analyse de la photo
  extraites en méthodes dédiées (plus aucune fonction signalée comme trop
  complexe par l'analyse statique).
- Commentaires et README remis à jour (authentification Parking/Pricing,
  bascule mock limitée à Booking, procédure de déploiement avec Neon et
  smoke test).

## [3.6.0] — 2026-11-18 — Données persistantes (Postgres)

### Ajouté
- Support de Postgres (Neon) en production via `DATABASE_URL` : les données
  survivent aux redémarrages de Render. Pilote psycopg 3, connexions
  revérifiées après la mise en pause de la base.
- `/health` indique le moteur de base (`databaseEngine`).
- Tests d'intégration exécutables contre une vraie base Postgres
  (`ACCESS_TEST_DATABASE_URL`, schéma jetable).

### Corrigé
- La présence d'un véhicule était enregistrée avant sa demande d'entrée,
  qu'elle référence : sous Postgres (clés étrangères), chaque entrée aurait
  échoué. SQLite applique désormais aussi les clés étrangères.
- `render.yaml` n'impose plus `DATABASE_URL` : la valeur saisie dans Render
  n'est plus écrasée par le blueprint.

## [3.5.1] — 2026-11-18 — Durée de stationnement (règles 2.4 et 2.5)

### Corrigé
- Sortie juste après l'entrée : la durée de 0 minute était refusée par
  Pricing (422) et la sortie bloquée ; elle compte désormais pour 1 minute
  (gratuite).
- Stationnement de plus de 7 jours : la durée est plafonnée à 7 jours
  (règle 2.4) au lieu d'être refusée par Pricing, ce qui bloquait la sortie.
- La durée est arrondie à la minute supérieure (« tout quart d'heure entamé
  est dû », règle 2.5) et non plus à la minute la plus proche.

## [3.5.0] — 2026-11-18 — Nouveau contrat Parking (hold_id)

### Modifié
- Entrée : le `hold_id` renvoyé par `POST /parking/hold` est transmis à
  `POST /parking/confirm_entry` (exigé par Parking depuis le 18/11 ; la place
  est mise de côté 30 s).
- Si Parking refuse la confirmation (409 : hold expiré ou déjà utilisé ;
  422), l'entrée est refusée : « Place non confirmée par Parking, réessayez ».

## [3.4.0] — 2026-11-18 — Clés API des services appelés

### Ajouté
- `PARKING_API_KEY`, `PRICING_API_KEY`, `VEHICLES_API_KEY` : clé envoyée dans
  `X-API-Key` si elle est renseignée (Parking l'exige depuis le 18/11).

### Modifié
- Parking injoignable (panne, délai, clé refusée) : l'entrée est refusée avec
  « Service Parking indisponible, réessayez plus tard », et non plus
  « Aucune place disponible », réservé à un parking réellement complet.
- Un `confirm_entry` ou `free` refusé par Parking est loggé en avertissement.

## [3.3.0] — 2026-11-18 — Refonte du dashboard

### Modifié
- Dashboard redessiné : thème Catppuccin (Latte par défaut, Mocha au choix),
  police MesloLGS NF embarquée, surfaces en verre dépoli, mise en page mobile.
- Borne : barrière animée selon la décision, heure de passage en un clic.
- Journal : filtre par type d'événement ; libellés en français partout.
- Rafraîchissement automatique : listes redessinées seulement si les données
  changent, en pause quand l'onglet est en arrière-plan.

## [3.2.0] — 2026-11-18 — Traçabilité, observabilité, sécurité (jalons 10 à 15)

### Ajouté
- Propagation du correlation ID (`X-Correlation-ID`) à tous les services
  appelés (Vehicles, Booking, Parking, Pricing, Payment, webhooks) et dans les
  événements RabbitMQ (propriété AMQP `correlation_id`, en-tête, champ
  `correlationId` du corps).
- Métriques métier Prometheus : `access_decisions_total`,
  `access_refusals_total`, `access_payments_total`,
  `access_payment_amount_euros_total`, `access_vehicles_present`,
  `access_outgoing_requests_total`, `access_outgoing_request_duration_seconds`,
  `access_events_published_total`.
- Configuration Prometheus prête à l'emploi (`monitoring/`).
- En-têtes de sécurité HTTP (`nosniff`, `DENY`, `no-referrer`, `no-store`,
  HSTS derrière HTTPS) ; comparaison de la clé API en temps constant ; refus
  de démarrer en production avec une clé API par défaut ou trop courte.
- Workflow « Smoke test » de l'instance déployée (manuel + quotidien),
  vérifiant aussi que la version en ligne est celle du dépôt.
- Dossier de revue de code et d'intégration (`docs/REVUE.md`).

### Corrigé
- Une panne du service Booking (réel) provoquait une erreur 500 : elle est
  désormais traitée comme une entrée sans réservation.

## [3.1.0] — 2026-11-18 — UI d'exploitation, qualité (jalons 8 et 9)

### Ajouté
- Dashboard : onglet « État du parking » ; `GET /access/presences`.
- `GET /access/requests` renvoie la décision, `limit`, contrôle `from` ≤ `to`.
- Logs avec correlation ID, une ligne par décision métier, log d'accès.
- Refus d'une sortie datée avant l'entrée ; validation renforcée.
- `scripts/smoke_test.sh`, `scripts/simulate_bus_events.py`.

## [3.0.0] — 2026-10-28 — Vehicles réel (jalon 7)

### Modifié (rupture de contrat)
- `POST /access/requests` reçoit `vehicleCode` (code Vehicles) au lieu d'une
  plaque ; `/access/vehicles/{vehicle_code}/known` remplace
  `/access/plates/{plate}/known`. Access ne reçoit plus jamais de plaque.

## [2.2.0] — 2026-10-22 — Payment réel

### Ajouté
- Paiement réel (idempotent, polling jusqu'au statut final) ; borne simulée
  dans le dashboard ; CI enchaînée et formatage vérifié.

## [2.1.0] — 2026-10-22

### Ajouté
- Version et commit exposés par `/health`, `/metrics` protégé, CORS restreint,
  pipeline CI (lint, tests, SAST, CVE, secrets) et Dependabot.

## [2.0.0] — 2026-09-02 / 03 — MVP et premières intégrations (jalons 6 et 7)

Version affichée dans `/docs` (pas encore dans `/health`). MVP hexagonal (entrée, sortie,
règles métier, API documentée, `/health`), Pricing et Parking branchés en
réel, publication des événements sur le bus CloudAMQP de l'équipe,
dashboard (journal, recherche), déploiement Render.
