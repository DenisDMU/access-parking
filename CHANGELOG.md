# Changelog — Access

Version exposée par `GET /health` (`version` + `commit` déployé) et dans `/docs`.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
sémantique (majeure = contrat d'API cassé).

## [4.29.3] — 2026-11-27 — Aucun secret dans une adresse ni dans le journal

### Sécurité
- Un appel sortant qui échoue (Parking, Payment, abonnés aux événements, bus
  RabbitMQ) n'écrit plus dans le journal que le code HTTP reçu ou le type de
  l'erreur. Le message d'erreur complet recopiait l'adresse appelée, donc
  tout identifiant ou jeton qui s'y serait trouvé. Pour un abonné, seul son
  hôte est écrit.
- En production, Access refuse aussi de démarrer si :
  - l'adresse d'un service ou d'un abonné contient des identifiants
    (`https://utilisateur:motdepasse@hôte`) ;
  - `RABBITMQ_URL` vise un bus distant sans TLS (`amqp://`) : son mot de
    passe partirait en clair. Nouvelle variable `RABBITMQ_ALLOW_PLAINTEXT`
    (`false` par défaut) pour un bus du réseau privé de Render ;
  - `VEHICLES_IDENTIFY_PATH` ou `VEHICLES_LOOKUP_PATH` n'est pas un simple
    chemin (même filtre que pour les routes lues dans le Swagger de
    Vehicles).
  En local, ce sont de simples avertissements.
- `scripts/tests_en_ligne.py` n'envoie `VEHICLES_API_KEY` qu'en https ;
  `scripts/bilan_journal.py` et `scripts/smoke_test.sh` n'envoient la clé
  d'exploitation qu'en https ou vers la machine locale (hôte comparé en
  entier, aucune adresse avec identifiants).

### Corrigé
- Une adresse de bus mal formée ou un hôte de bus introuvable faisait
  échouer le passage en cours (500), et le message d'erreur pouvait recopier
  un morceau du mot de passe : l'échec est maintenant traité comme les
  autres pannes du bus (une ligne dans le journal, le passage continue).
- `VEHICLES_IDENTIFY_PATH` ou `VEHICLES_LOOKUP_PATH` définie mais vide
  reprend sa valeur par défaut. Un chemin terminé par un saut de ligne est
  refusé par le filtre.

## [4.29.2] — 2026-11-27 — Une clé de service ne part jamais sans https

### Sécurité
- La clé d'un service de l'équipe suit l'adresse de ce service. En
  production, Access **refuse de démarrer** si une clé (`VEHICLES_API_KEY`,
  `BOOKING_API_KEY`, `PARKING_API_KEY`, `PRICING_API_KEY`,
  `PAYMENT_API_KEY`) est renseignée alors que l'adresse du service
  (`…_SERVICE_URL`) n'est pas en `https://` : une faute de frappe dans
  Render aurait envoyé la clé en clair à chaque appel. En local, simple
  avertissement. Sans clé renseignée, l'adresse n'est pas contrôlée.

### Documentation
- La vérification d'une plaque (`POST /access/vehicles/known`) et la sortie
  n'interrogent pas Vehicles « sans créer » le véhicule, comme la doc le
  disait : depuis le 24/11, Vehicles n'offre plus de consultation par plaque
  sans création, une plaque jamais vue y est donc enregistrée, et `known`
  vaut `true` dès que Vehicles répond. README, description de la route dans
  `/docs`, aide du dashboard et commentaires du code corrigés (aucun
  changement de comportement).
- La présentation de l'API dans `/docs` disait encore qu'Access « ne reçoit
  jamais la plaque » : il la reçoit depuis la 4.0.0, la transmet à Vehicles
  et ne la conserve jamais. Texte corrigé.
- README, section 16 : le paragraphe Vehicles décrit le contrat actuel
  (`POST /api/vehicle/create`, `GET /api/vehicle/{pseudoId}`) et la
  validation PMR par un agent, au lieu du premier contrat du 24/11.

## [4.29.1] — 2026-11-27 — Booking 2.5.0 : nouvelles routes et clé

### Corrigé
- Booking est passé en 2.5.0 : ses routes sont désormais sous `/v2/booking`,
  `/reservations/active` s'appelle `/reservations/valid` (mêmes paramètres,
  même réponse) et toutes exigent `X-API-Key`. Access appelait l'ancienne
  adresse (404) : plus aucune réservation n'était reconnue, les véhicules
  entraient comme des clients sans réservation. Access appelle maintenant
  `GET /v2/booking/reservations/valid` et `GET /v2/booking/availability`
  avec la clé `BOOKING_API_KEY`.
- Une clé refusée par Booking (401 ou 403) s'écrit en erreur dans le journal
  (« Booking refuse la clé d'Access ») au lieu de passer pour une panne.
- Le réveil de Booking (au démarrage d'Access et à l'ouverture de la borne)
  visait encore `/health`, qui répond 404 depuis Booking 2.x : il appelle
  maintenant `/v2/booking/health`.

### Modifié
- `BOOKING_API_KEY` devient obligatoire en production : déclarée dans
  `render.yaml` (`sync: false`, à saisir dans Render > Environment), décrite
  dans `.env.example` et dans la procédure de déploiement du README.

## [4.29.0] — 2026-11-27 — Le passage d'un véhicule exige une clé

### Sécurité
- Jalon 15 : un endpoint métier ne doit pas être accessible librement. Le
  passage d'un véhicule sans clé (`POST /borne/passages`) est **fermé par
  défaut** (403) : seule une borne mise en service avec sa clé fait entrer
  ou sortir un véhicule (`POST /access/requests`). Nouvelle variable
  `BORNE_PASSAGES_PUBLIC` (`false` par défaut, `false` dans `render.yaml`)
  pour le rouvrir lors d'une démonstration.
- `POST /borne/pmr-validation` exige aussi la clé de la borne (`X-API-Key`,
  401 sinon) tant que le passage sans clé est fermé. Une borne mise en
  service valide désormais ses PMR même si `BORNE_PUBLIC=false`.

### Modifié
- `BORNE_PUBLIC` ne gouverne plus que le plan 3D et la promenade, qui
  restent publics (lecture seulement).
- `GET /borne/status` renvoie aussi `publicPassages` (ajout, aucun champ
  retiré).
- Borne sans clé : écran « Borne hors service », avec le parking en 3D
  toujours accessible depuis le dock. La borne envoie sa clé pour la
  validation PMR.
- `scripts/tests_en_ligne.py` fait ses passages avec la clé de la borne
  (`BORNE_API_KEY`) et vérifie que le passage sans clé est refusé.

## [4.28.0] — 2026-11-25 — Le gros bouton rouge et sa pub

### Ajouté
- Un **gros bouton rouge** sur un îlot au milieu de la route, devant le
  parking, sous une étiquette « Ne pas appuyer ».
- Il lance une **publicité KingPar** tournée dans le décor : six plans de
  caméra, bandes de cinéma, sous-titres, feux d'artifice, carton final avec
  le logo, bouton « Passer la pub ». L'agent et Jo, le mécano, saluent la
  caméra ; une voiture tourne sur le podium du tuning.
- **Voix enregistrées** pour les acteurs (six répliques, `static/sons/pub/`,
  environ 200 Ko) : synthèse vocale libre Piper, voix françaises sous
  licence CC BY 4.0 (mention dans `LICENCE.txt`). En secours : la synthèse
  vocale de l'appareil (voix locale seulement), puis la voix chantonnée.
- Un succès secret de plus (cinquante-huit en tout, sept secrets).

### Modifié
- Les fichiers `.m4a` sont servis avec le type `audio/mp4`.

## [4.27.2] — 2026-11-25 — `/metrics` de nouveau protégé

### Sécurité
- `GET /metrics` n'est plus lisible sans clé (il l'était depuis la 4.26.0).
  Il exige la clé d'exploitation ou un **jeton de lecture** `METRICS_TOKEN`
  (généré par Render), dans `X-API-Key` ou `Authorization: Bearer` ; sinon
  401. Le jeton ne lit que cette route ; la clé borne ne la lit pas ; un
  jeton trop court ou égal à une clé empêche le démarrage en production.
- Prometheus (`tp/prometheus`) lit le jeton dans un fichier que
  `./demarrer.sh` fait saisir sans l'afficher, rangé dans un dossier ignoré
  par Git et monté en lecture seule : rien de secret dans `prometheus.yml`.
- Scripts de vérification en ligne et agent `securite` : `/metrics` sans clé
  doit répondre 401.

## [4.27.1] — 2026-11-25 — Finition nacrée

### Corrigé
- KingPar Tuning : la finition nacrée décalait trop la teinte (un bleu
  nacré tirait sur le violet). Le reflet est maintenant à peine décalé :
  la couleur choisie reste la même.

## [4.27.0] — 2026-11-25 — KingPar Tuning

### Ajouté
- **KingPar Tuning**, un atelier en face de la station : bâtiment, podium
  tournant, mâts de projecteurs, piles de pneus, pots de peinture et Jo, le
  mécano. On y entre au volant (touche E sur l'aire) ou à pied (le
  véhicule choisi est sorti sur le podium).
- Personnalisation des six véhicules, tout offert : quatorze peintures,
  quatre finitions, quatre modèles de jantes en huit couleurs, quatre types
  de pneus (dont tout-terrain, garde au sol relevée), huit autocollants
  dessinés par la page (portières et capot), bandes de course, vitres
  teintées, aileron, galerie de toit, fanion KingPar, néon sous la caisse,
  quatre klaxons. Boutons « Surprise ! » et « Remettre d'origine ».
- Le réglage de chaque véhicule est gardé sur l'appareil
  (`access.plan3d.garage`) et relu avec prudence. En multijoueur, le tuning
  du véhicule conduit voyage avec la position (`tune`, couleurs `#rrggbb`
  et mots courts, tout autre champ refusé) : les autres promeneurs voient
  la voiture telle qu'elle a été préparée.
- Un tampon (seize en tout) et quatre succès, dont un secret
  (cinquante-sept en tout, six secrets).

### Modifié
- La voiture d'un autre promeneur prend la peinture de son tuning ; sans
  tuning (page restée sur l'ancienne version), elle garde la couleur de son
  haut, comme avant.
## [4.26.0] — 2026-11-25 — TP Prometheus : supervision des microservices

### Ajouté
- Compteur métier `parking_operations_total{operation,result}` : entrées,
  sorties et sorties forcées par l'exploitation, autorisées, refusées ou en
  attente de confirmation. Les séries existent à zéro dès le démarrage.
- Dossier `tp/prometheus` : le `Dockerfile` du sujet, `prometheus.yml`
  (Access en ligne, Parking, Vehicles, Booking, Pricing, Payment, un Access
  local pour simuler une panne), `demarrer.sh` et `arreter.sh`. Interface
  sur `127.0.0.1:9090`, mesures gardées dans un volume.
- Bonus Grafana (`./demarrer.sh --grafana`) : source Prometheus et tableau de
  bord « Parking Management — supervision » provisionnés, lecture seule sans
  connexion, aucun mot de passe dans le dépôt.
- Guide `PROMETHEUS.md` : quoi lancer, les trois requêtes PromQL
  (disponibilité, requêtes par seconde, erreurs et opérations métier), la
  démonstration UP/DOWN, quoi montrer au rendu.
- Captures pour le rendu dans `tp/prometheus/captures` : page des cibles,
  les trois graphiques, les opérations métier, le tableau de bord Grafana.

### Modifié
- `GET /metrics` se lit désormais **sans clé**, pour que le Prometheus de
  chaque équipe puisse superviser Access. La route ne livre que des
  agrégats : aucune plaque, aucun identifiant, routes comptées par gabarit.
  Elle est servie directement par `prometheus_client` (version figée),
  hors limitation de débit, hors du log d'accès courant, et ne compte pas
  ses propres lectures.
- Scripts de vérification en ligne et agent `securite` alignés sur ce choix
  (`/metrics` n'est plus attendu en 401).

### Retiré
- `monitoring/prometheus.yml` (lecture avec clé), remplacé par
  `tp/prometheus/prometheus.yml`.

## [4.24.0] — 2026-11-25 — Sons enregistrés

### Ajouté
- Dix sons enregistrés pour les gestes (panneau, tampon, salut, saut, porte,
  pas, coup de poing, pioche, cloche, succès), tirés de trois packs de
  Kenney en licence CC0 et rangés dans `static/sons/` avec leur note de
  licence. Si le navigateur ne lit pas ce format, les sons synthétisés
  restent utilisés. La musique et les voix restent synthétisées.

## [4.23.0] — 2026-11-25 — Succès secrets, course de canards

### Ajouté
- Cinq succès secrets, affichés « ??? » tant qu'ils ne sont pas trouvés, et
  un succès pour le nouveau jeu : cinquante-trois en tout.
- Douzième mini-jeu : la course de canards, au Spa du Point Mort.
- Des papillons au-dessus des fleurs du village.

## [4.22.0] — 2026-11-25 — Kingfarm, monde courbé, sons

### Ajouté
- Monde courbé en promenade : le sol s'arrondit vers l'horizon, comme sur
  une petite planète. Effet de dessin seulement : collisions, ombres et plan
  vu de haut restent à plat.
- Sons synthétisés : gestes (saut, pas, panneau, tampon, succès, salut,
  portière, klaxon avec H), voix des habitants, musique de promenade.
  Réglages ⚙ : volume par paliers, musique oui ou non, gardés sur l'appareil.
- Défis : pièce qui tourne, mains qui se secouent avant de se montrer, ligne
  gagnante du morpion en jaune.

### Modifié
- La ferme s'appelle la Kingfarm : potager agrandi de quinze citrouilles
  derrière sa clôture, pompe à eau, verger de neuf arbres à pommes.
- La mine devient une grotte de pierre fermée (voûte, portail, rails,
  wagonnet) ; la voûte s'efface quand on entre.
- Maisons du village plus petites. Sol découpé en carreaux plus grands et
  affichage moins dense sur écran tactile, pour les téléphones.

## [4.21.0] — 2026-11-25 — Décor de village

### Modifié
- Maisons refaites : deux pans de toit épais en tuiles arrondies qui
  débordent des murs, pignons crème avec œil-de-bœuf, faîtière, cheminée,
  portes arrondies avec leur couronne, haies rondes, boîte aux lettres
  devant chaque commerce. Les toits ronds de la 4.20.0 disparaissent.
- Arbres plus touffus (couronnes à plusieurs bosses), rochers ronds semés
  dans le village.

## [4.20.0] — 2026-11-25 — Défis entre promeneurs, Suppositofarm

### Ajouté
- Défis amicaux entre deux promeneurs : près d'un autre joueur, E ouvre une
  roulette (morpion, pierre-feuille-ciseaux, pile ou face). Route publique
  `POST /borne/promenade/defi` ; le serveur valide les coups, lance la
  pièce et cache le choix de l'autre jusqu'à la fin. Champ `duels` dans la
  réponse de `POST /borne/promenade`.
- La Suppositofarm, au sud des champs : carottes à ramasser, arbres à
  abattre à coups de poing (nouveau geste du personnage), mini-grotte à
  minerais ; les ressources repoussent.
- Six succès (défis, récoltes) et un tampon de plus : quarante-sept succès,
  quinze tampons.

### Modifié
- Animaux dans le style des personnages (grosse tête, grands yeux, joues).
- Décor de village : murs crème à poutres de bois, toits à deux pans qui
  débordent, chemins de terre, clôture en bois à la ferme, arbres touffus
  à pommes, prairie dessinée.

## [4.19.0] — 2026-11-25 — Style doux, quêtes, onze mini-jeux

### Ajouté
- Quêtes : six habitants de Bonneplace demandent un service (« ! » au-dessus
  de la tête, « ? » en cours, ♥ une fois rendu), avec des dialogues dans
  une bulle. Onglet « Quêtes » dans le carnet, trois succès.
- Cinq mini-jeux de plus, dans les commerces et à la fête : jeu des paires,
  passage piéton, chasse aux olives, « Feu vert ! », éclate-ballons (onze en
  tout, plus le créneau).
- Cinq coupes de cheveux (au bol, banane, tresses, en piques, bouclée),
  quatre regards au choix (ronds, manga, malins, étoilés), des couleurs en
  plus pour les hauts, les pantalons, les cheveux et les ballons (dont le
  violet).
- Trois véhicules en libre-service de plus : 4x4, citadine électrique, moto.
- Quarante et un succès au total (mini-jeux, véhicules, marche, saluts,
  quêtes).

### Modifié
- Personnages refaits dans un style doux : grosse tête ronde, petit corps en
  cloche, **visage peint** (grands yeux qui clignent, joues, petit nez,
  sourire), démarche qui se dandine. Les autres promeneurs et les habitants
  utilisent le même modèle.
- Décor dans le même style : arbres et buissons en boules avec leur reflet,
  nuages et collines ronds, fleurs semées dans le village.
- Interface du plan refaite dans le même esprit : cartes crème aux coins
  ronds, police arrondie, boutons en pastille ; le panneau des places reste.
  Les pseudos des autres promeneurs s'affichent sans fond, et seulement de
  près quand on se promène.
- `look.eyes` (facultatif) dans `POST /borne/promenade` ; cinq jeux de plus
  acceptés par `POST /borne/promenade/scores`.

## [4.18.0] — 2026-11-25 — KingPar : la marque, les personnages, le covoiturage

### Ajouté
- La marque du parking s'appelle **KingPar**. Logo (une couronne en trace
  de pneu) : `static/kingpar-logo.svg`, dessiné aussi dans Figma. Il est sur
  la Tour KingPar, le panneau des places libres, les ballons et l'accueil ;
  la boutique, la station et les lettres de la colline portent le nom.
- Fenêtre d'accueil à la première visite (et bouton « ? ») : ce monde en 3D
  montre le parking en direct, et on y vient aussi pour s'amuser.
- Boutique KingPar : huit tenues (T-shirt, pull, chemise, veste, sweat à
  capuche, salopette, robe, maillot), pantalon, short ou jupe, lunettes,
  écharpe, bonnet, béret, et une couronne à mériter (neuf succès).
- Ballons KingPar à la fête : tenus à la main, ils font sauter plus haut et
  retomber doucement.
- Monter dans la voiture d'un autre promeneur (champ `ride`), cœurs quand
  deux promeneurs se saluent, six succès de plus (trente au total).
- `tp/splunk` : TP « Installer Splunk en local avec Docker » (Dockerfile,
  scripts `demarrer.sh` et `arreter.sh`, notice). Le mot de passe est saisi
  au lancement, jamais dans l'image ; l'interface n'écoute que sur
  `127.0.0.1:8000`. Sans effet sur le service Access. Pas-à-pas :
  `SPLUNK.md`.

### Modifié
- Personnages refaits dans un style doux (grosse tête, grands yeux, joues
  roses, sourire) ; la tête bouge à l'arrêt. Mini-jeux redessinés (ciels en
  dégradé, ombres, canards et tambours plus soignés). Interface : panneaux,
  invites et messages plus lisibles et animés.
- `POST /borne/promenade` accepte `look.outfit`, `look.bottom`,
  `look.extra`, `look.balloon` et `ride`, tous facultatifs et bornés.

## [4.17.0] — 2026-11-25 — Promenade multijoueur, mini-jeux et succès

### Ajouté
- Promenade multijoueur : on voit les autres visiteurs se promener (tenue,
  compagnon, véhicule), avec un pseudo attribué par Access et leur nombre
  de succès ; quatre saluts au choix (touches 1 à 4). Vu de haut et dans le
  dashboard, on les regarde. Routes publiques `POST` et `GET
  /borne/promenade`, `GET` et `POST /borne/promenade/scores` ; réglages
  `PROMENADE_MULTI`, `PROMENADE_CAPACITY`, `RATE_LIMIT_PROMENADE`.
- Six mini-jeux (`promenade-jeux.js`) : pêche aux canards, crêpes, frites,
  barbe à papa, grosse caisse, « plein pile ». Records sur l'appareil,
  meilleurs scores partagés.
- Station Access sur la route du village : pompes, recharge, boutique,
  place d'entraînement du « créneau parfait », et un grand panneau des
  places libres du parking, en direct.
- Vingt-quatre succès et un rang ; carnet à trois onglets (tampons, succès,
  scores) ; un ticket d'or caché chaque jour à un endroit différent.
- Cinq compagnons de plus : cochon, panda, mouton, tortue, canard.

### Modifié
- Personnage refait : formes arrondies, visage (yeux, sourcils, nez,
  sourire, oreilles), mains, chaussures, carnation au choix ; les huit
  coupes de cheveux se reconnaissent de face comme de dos, et la caméra
  s'approche dans les boutiques. Compagnons arrondis eux aussi.
- Les stands de la fête et la grosse caisse lancent un vrai jeu.
- Le plan n'appelle que les routes `/borne/promenade` données par la page,
  sans clé ni cookie ; ces appels ne sont pas journalisés un par un.

## [4.16.0] — 2026-11-25 — Bonneplace, le village du parking

### Ajouté
- Plan 3D, mode « Promenade » : le personnage saute (Espace) ; trois
  véhicules en libre-service se conduisent (camping-car, berline, scooter),
  avec compteur de vitesse, collisions et barrières qui se lèvent ; le
  compagnon monte à bord.
- Un agent du parking fait sa ronde tout seul : il inspecte les véhicules
  garés, va au-devant d'une arrivée, fait une pause à la guérite, salue le
  promeneur.
- Bonneplace, le village du parking, au bout de la route : arche d'entrée,
  statue de la mascotte, rue de huit commerces, belvédère et sa cloche en
  haut d'un escalier sous cinq arches (une par zone), Tour Access, étang et
  passerelle, place de la fête, champs de fleurs, fermes, lettres ACCESS
  sur la colline. Fenêtres, bornes lumineuses et guirlandes s'allument la
  nuit.
- Trois boutiques où tout est offert : Boutique Access (tenue), Coiffure
  Le Créneau (huit coupes, huit couleurs), Animalerie du Copilote (cinq
  compagnons : chihuahua, chat, shiba, lapin, renard).
- Carnet de tampons (touche C) : treize choses à découvrir, du parking au
  village ; feu d'artifice au dernier tampon. Tickets chance au belvédère,
  grosse caisse et stands à la fête, distributeur de boissons.
- Photo souvenir (touche P), à enregistrer depuis la page.
- Borne de réservation du décor : nombre de places libres à l'instant et
  atouts du parking, avant le détail par zone.

### Modifié
- Le promeneur démarre toujours sur le parvis du parking. Tenue, compagnon
  et carnet sont gardés dans le navigateur de l'appareil (`localStorage`) ;
  le module n'envoie rien. Le carnet est un jeu, sans avantage tarifaire.
- « F » appelle le compagnon choisi (il n'aboie plus forcément).

## [4.15.0] — 2026-11-25 — Libérer un véhicule présent

### Ajouté
- `POST /access/presences/{vehicleId}/release` (clé d'exploitation) : sortie
  forcée d'un véhicule présent, désigné par son identifiant pseudonymisé
  (Access ne garde aucune plaque). Place rendue à Parking, présence
  « sorti », demande de sortie tracée avec un motif explicite, événement
  `VEHICLE_EXITED` avec `forced: true`. Rien n'est facturé. 404 si le
  véhicule n'est pas présent.
- Dashboard, onglet « État du parking » : bouton « Libérer » sur chaque
  véhicule présent et « Tout libérer », avec confirmation ; le bilan
  signale les places que Parking n'a pas rendues.

## [4.14.0] — 2026-11-25 — Promenade dans le plan 3D

### Ajouté
- Plan 3D : mode « Promenade ». On incarne un personnage vu de dos, suivi
  de son chihuahua, et on parcourt le parking comme dans un jeu : ZQSD ou
  flèches, Maj pour courir, souris pour regarder, E pour interagir, F pour
  faire aboyer le chien, Échap pour quitter ; manette tactile sur écran
  tactile. Les véhicules garés, les haies et le mobilier arrêtent le
  personnage ; la zone traversée s'affiche avec son occupation.
- Borne de réservation dans le décor, sur un parvis près de l'entrée :
  places encore réservables chez Booking pour l'heure en cours et véhicules
  entrés avec une réservation, zone par zone.
- Borne publique : en promenade, la borne d'entrée ou de sortie du décor
  lance le vrai parcours (touche E).
- `GET /borne/parking` : champ `reservable` par catégorie (Booking,
  `GET /availability` sur l'heure en cours ; gardé 60 s ; `null` si Booking
  ne répond pas).

### Modifié
- Borne publique : le plan s'ouvre toujours de jour, quel que soit le thème
  de l'appareil (le bouton « Nuit » reste disponible).

## [4.13.1] — 2026-11-25 — Revue de sécurité

### Corrigé
- Borne publique : au plus 8 passages traités en même temps
  (`BORNE_MAX_CONCURRENT`) ; au-delà, 503 et « réessayez ». Un service
  endormi faisait attendre chaque passage jusqu'à 45 s : quelques visiteurs
  pouvaient occuper tous les threads d'Access.
- Validation PMR par l'agent : acceptée seulement pour un véhicule mis en
  attente de vérification PMR à l'entrée dans les 5 dernières minutes
  (409 sinon). Le code agent ne permet plus de faire enregistrer n'importe
  quelle plaque comme PMR chez Vehicles. Exemple Swagger neutre (`0000`).
- Découverte des routes Vehicles : seuls des chemins simples (`/api/…`)
  sont acceptés depuis son Swagger, jamais un autre hôte.
- Test anti-fuite de plaque étendu à toute la borne publique.

## [4.13.0] — 2026-11-24 — Réservations dans le plan 3D

### Ajouté
- Plan 3D (dashboard et borne) : un « R » bleu flotte au-dessus des
  véhicules entrés avec une réservation Booking ; leur nombre est rappelé
  dans la légende, zone par zone.
- `GET /borne/parking` : champ `reserved` par catégorie (véhicules entrés
  avec une réservation, compte d'Access ; aucun identifiant).

## [4.12.1] — 2026-11-24 — Parking complet et services réveillés d'avance

### Corrigé
- Catégorie pleine chez Parking (constaté : XL 12/12, deux-roues 10/10) :
  la borne affichait « Service Parking indisponible » au lieu de « Le
  parking est complet ». Quand Parking refuse une place, Access lui demande
  s'il en reste dans cette catégorie avant de conclure à une panne.
- « Service Parking indisponible, réessayez plus tard » au premier passage
  après une pause : les services de l'équipe (offre gratuite de Render)
  dorment après 15 min et mettent 30 à 60 s à se réveiller. Access les
  réveille maintenant d'avance (`GET /health` aux cinq services, en
  parallèle) à son démarrage et à l'ouverture de la borne ou du dashboard,
  et les attend 45 s au lieu de 20. `WARM_UP_SERVICES=false` pour couper.

## [4.12.0] — 2026-11-24 — Plan 3D sur la borne publique

### Ajouté
- Borne : dock sur le côté (en bas sur mobile), comme celui de macOS. La
  maison ramène à la borne (entrer, sortir), la voiture ouvre « Le parking
  en direct » : le plan 3D en plein écran, pour tout le monde, sans clé.
- `GET /borne/parking` (publique) : occupation par catégorie pour ce plan
  (`totalCapacity`, `spotTaken`, `spotHeld`, libellé). Aucun véhicule ni
  identifiant. Réponse de Parking gardée 10 s (`BORNE_PARKING_CACHE_S`),
  30 demandes par minute et par adresse (`RATE_LIMIT_BORNE_PARKING`), 403
  si `BORNE_PUBLIC=false`.

## [4.11.0] — 2026-11-24 — Plan 3D du parking

### Ajouté
- Dashboard : onglet « Plan 3D ». Le parking en trois dimensions, construit
  à partir de l'occupation renvoyée par Parking : une zone par catégorie,
  un véhicule du bon type par place prise (citadine, berline, SUV,
  électrique, utilitaire, camping-car, moto, scooter). Les véhicules
  entrent par la barrière et se garent, ou sortent, quand l'occupation
  change ; les places mises de côté clignotent ; jour en thème clair, nuit
  en thème sombre. Caméra libre, zoom sur une zone, plein écran, survol et
  clic sur un véhicule (ouvre sa demande d'entrée).
- Sans clé ou si Parking ne répond pas : plan de démonstration, signalé
  comme tel.
- three.js 0.160.0 (MIT) servi par Access (`static/vendor/`), empreinte
  contrôlée par les tests : toujours aucune ressource externe.

### Compatibilité
- Aucune route d'API ajoutée ni modifiée ; l'occupation de Parking est
  redemandée toutes les 10 s seulement quand l'onglet « Plan 3D » est
  ouvert (30 s sinon).

## [4.10.2] — 2026-11-24 — Création Vehicles en 201

### Corrigé
- Vehicles a annoncé qu'il renverrait `201 Created` à la création d'un
  véhicule : Access accepte désormais 200 et 201 (il n'acceptait que 200,
  toute entrée serait repartie en « Un agent arrive »). L'enregistrement
  PMR accepte 200 et 204.

## [4.10.1] — 2026-11-24 — Vehicles protège PUT et DELETE

### Corrigé
- Vehicles exige désormais une authentification pour `PUT` (et `DELETE`) :
  la validation PMR par l'agent n'est plus bloquée pour autant. La carte
  vérifiée vaut pour ce passage (entrée sur place PMR) ; seule la
  mémorisation chez Vehicles est perdue tant qu'Access n'a pas sa clé
  (`VEHICLES_API_KEY`).
- Délai d'attente de Vehicles porté de 20 à 45 s : la première entrée après
  une pause (Vehicles endormi par Render) ne finit plus en « Un agent
  arrive ».

## [4.10.0] — 2026-11-24 — Validation PMR par un agent

### Ajouté
- Borne : sur « Un agent arrive » pour un PMR déclaré sans justificatif
  connu, bouton « Validation agent ». L'agent vérifie la carte mobilité
  inclusion et tape son code : entrée sur une place PMR. « Pas de carte :
  place standard » fait entrer le véhicule sur une place standard.
- `POST /borne/pmr-validation` (`licensePlate`, `country`, `agentCode`) :
  code agent `AGENT_CODE` (`123` par défaut), justificatif enregistré chez
  Vehicles (`PUT` avec `isHandicaped`), puis entrée rejouée avec toutes ses
  règles. Aux passages suivants, le véhicule entre directement en PMR.
  403 si le code est faux, 503 si Vehicles n'enregistre pas.

## [4.9.2] — 2026-11-24 — Champs Vehicles renommés

### Corrigé
- Vehicles a renommé les champs de sa réponse (`electric` → `isElectric`,
  `xl` → `isXl`, `twoWheels` → `isTwoWheels`, `handicaped` →
  `isHandicaped`) : tout véhicule était lu comme une voiture standard.
  Chaque caractéristique est désormais lue sous tous ses noms connus.

## [4.9.1] — 2026-11-24 — Zone PMR de Pricing

### Corrigé
- Pricing a renommé sa zone PMR `disabled` → `handicapped` (grille v2 du
  24/11) : chaque sortie d'un véhicule PMR était refusée (« service de
  tarification indisponible »). Access envoie `handicapped` et réessaie
  l'ancien nom sur un `ZONE_NOT_FOUND`.
- Une réponse de Pricing sans montant exploitable donne un refus propre
  (jamais une erreur 500).

## [4.9.0] — 2026-11-24 — Routes Vehicles retrouvées automatiquement

### Ajouté
- Découverte automatique des routes Vehicles : si la création ou la
  consultation répond 404 (route renommée), Access lit le Swagger de
  Vehicles (`/v3/api-docs`), y retrouve la route POST qui reçoit
  `licensePlate` et la route GET dont la réponse contient `pseudoId` (jamais
  celle qui renvoie la plaque), réessaie aussitôt et garde ces routes pour
  les passages suivants. Avertissement dans les logs avec les routes
  trouvées ; au plus une lecture du Swagger par minute.

### Corrigé
- 5ᵉ renommage Vehicles : `/api/vehicles/...` → `/api/vehicle/...`
  (singulier). La borne renvoyait de nouveau « Un agent va arriver » à
  chaque entrée. Nouvelles routes par défaut.

## [4.8.1] — 2026-11-24 — 4ᵉ contrat Vehicles

### Corrigé
- Vehicles a renommé ses routes (4ᵉ fois le 24/11) : `POST /api/identify`
  → `POST /api/vehicles/create`, `GET /api/getvehicles/{id}` →
  `GET /api/vehicles/{id}`. L'ancienne route répondait 404 : chaque entrée
  à la borne finissait en « Un agent va arriver » et aucun véhicule n'était
  créé. Nouvelles routes par défaut (`VEHICLES_IDENTIFY_PATH`,
  `VEHICLES_LOOKUP_PATH` toujours réglables).
- Champ PMR renommé `disabled` → `handicaped` : les deux noms sont lus.

## [4.8.0] — 2026-11-24 — Pays de la plaque

### Ajouté
- `country` (facultatif) sur `POST /access/requests`, `POST /borne/passages`
  et `POST /access/vehicles/known` : FR, IT, ES, DE, BE, CH, GB, NL, LU, PT,
  XX (autre). Une plaque non française est envoyée à Vehicles sous la forme
  `<ISO>:<plaque>` : une italienne `AB 123 CD` n'est plus jamais confondue
  avec la française `AB-123-CD`. Les plaques françaises gardent leur forme.
- Format vérifié selon le pays (France SIV/FNI, Italie, Espagne, Allemagne,
  Belgique, Suisse, Royaume-Uni ; générique ailleurs) ; 422 sans recopier
  la plaque.
- Borne : « Changer de pays » sous la plaque (France par défaut), bandeau
  de la plaque à la lettre du pays, exemple adapté, format vérifié avant
  l'envoi ; à l'entrée comme à la sortie.

### Compatibilité
- Sans `country`, comportement inchangé (plaque traitée comme française).

## [4.7.0] — 2026-11-24 — Type de véhicule à la borne

### Ajouté
- Borne, à l'entrée : écran « Votre véhicule » avant la plaque, cinq tuiles
  avec icône (Voiture, Électrique, Grand gabarit, Mobilité réduite,
  Deux-roues) ; rappel du choix sur l'écran de la plaque, avec « Modifier ».
  La sortie va directement à la plaque.
- `vehicleType` (facultatif, entrée seulement) sur `POST /access/requests`
  et `POST /borne/passages` : `STANDARD`, `ELECTRIC`, `XL`, `HANDICAPPED`,
  `TWO_WHEELS`. Transmis à Vehicles pour créer un véhicule inconnu avec ses
  caractéristiques ; un véhicule connu garde sa fiche (vérifié en réel).
- Mobilité réduite déclarée sur un véhicule que Vehicles ne connaît pas
  comme PMR : place PMR demandée, carte vérifiée par un agent
  (confirmation requise) ; PMR jamais enregistré sur simple déclaration.

### Modifié
- Borne : libellés de place toujours en français (« Place avec recharge »,
  « Place PMR »…), jamais le libellé technique de Parking.

## [4.6.1] — 2026-11-24 — Vehicles : identification puis consultation par identifiant

### Corrigé
- Vehicles a encore changé son contrat : `GET /api/getvehicles/{…}` attend
  l'identifiant du véhicule (UUID), plus la plaque (400). Aucune nouvelle
  plaque n'était identifiée à la borne (« Un agent arrive »). Nouveau
  parcours : plaque → `POST /api/identify` (retrouve ou crée, sans réécrire
  un véhicule connu) → `GET /api/getvehicles/{pseudoId}`. Vérifié contre le
  vrai service.

### Modifié
- `VEHICLES_LOOKUP_PATH` par défaut : `/api/getvehicles/{vehicleId}` ; une
  route contenant `{plate}` rétablit l'ancien mode « par plaque ».
- Vehicles n'offrant plus de consultation sans création, une plaque inconnue
  à la sortie est enregistrée chez Vehicles (refus « non présent » côté
  Access, comme avant).

## [4.6.0] — 2026-11-24 — Booking réel

### Ajouté
- Booking branché en réel : à l'entrée, `GET /reservations/active` à
  l'instant du passage (réservation confirmée qui couvre l'instant). Si
  elle existe : place du **type réservé**, prise dans le quota « booking »
  de Parking ; « Réservation reconnue » sur la borne. Panne de Booking :
  entrée sans réservation, jamais d'erreur.
- `GET /health` indique `"booking": "réel"` ou `"simulé"`.
- Événement d'entrée : `reservationId` et `reservationEnd` (champs ajoutés).

### Modifié
- Sortie d'un véhicule avec réservation : le créneau est déjà payé à
  Booking, rien n'est facturé dedans ; seul le dépassement après la fin du
  créneau est facturé, au tarif sans réservation (avant : nouveau prix
  « réservé », soit un double paiement). Borne : « Réservation déjà réglée ».
- Booking réel par défaut (`BOOKING_USE_MOCK=true` pour le simuler) ;
  `USE_MOCKS` n'a plus d'effet ; sur Render, une ancienne URL `localhost`
  est ignorée au profit de `https://booking-api-vhy5.onrender.com`.

## [4.5.1] — 2026-11-24 — Nouvelles routes Vehicles

### Corrigé
- Vehicles a renommé ses routes : `GET /api/getvehicles/{plaque}` et
  `POST /api/identify` (au lieu de `/api/vehicles/{plaque}` et
  `/api/vehicles/identify`). Access appelait les anciennes : toutes les
  plaques passaient « inconnues » et aucune n'était créée à l'entrée
  (« Un agent arrive »). Testé contre le vrai service.

### Ajouté
- Routes de Vehicles réglables sans toucher au code
  (`VEHICLES_LOOKUP_PATH`, `VEHICLES_IDENTIFY_PATH`).
- Un 404 sur `identify` (route disparue) est loggé en ERREUR avec la route
  appelée, pour repérer tout de suite un nouveau changement de contrat.

## [4.5.0] — 2026-11-24 — Borne publique, sans réglage

### Ajouté
- Le lien `/borne` marche pour tout le monde, sans saisir de clé : la
  borne sans clé passe par `POST /api/v1/borne/passages`, route publique
  réduite au passage d'un véhicule (mêmes règles métier) ; date imposée
  par le serveur, source « borne », réponse sans identifiant de demande
  ni de véhicule, 10 passages/min par adresse (`RATE_LIMIT_BORNE`,
  adresse réelle derrière le proxy de Render).
- `GET /api/v1/borne/status` : la borne sait si l'accès public est ouvert.
- `BORNE_PUBLIC` (true par défaut) : `false` ferme la route publique
  (403) ; la borne exige alors sa clé, comme en 4.4.

### Modifié
- Une borne configurée avec une clé devenue invalide repasse d'elle-même
  par la route publique au lieu d'afficher « hors service ».
- Tout le reste de l'API (y compris `POST /access/requests`) garde sa clé.

## [4.4.1] — 2026-11-24 — Adresse courte de la borne

### Modifié
- La borne client est servie directement sur `/borne` (plus de redirection
  vers `/static/borne.html`) : l'adresse affichée reste courte, `?mode=…`
  compris. L'ancienne adresse redirige (301) vers `/borne` en gardant ses
  paramètres : les bornes déjà ouvertes continuent de fonctionner.

## [4.4.0] — 2026-11-24 — Mise en service de la borne depuis le dashboard

### Ajouté
- Dashboard, onglet « Borne » : panneau « Borne client » (visible seulement
  avec une clé d'exploitation valide). Choix de l'emplacement puis « Ouvrir
  la borne client » : la borne de ce navigateur reçoit sa clé et s'ouvre,
  sans passer par `/borne?config`.
- `GET /access/borne/key` (clé d'exploitation seulement, 401 avec la clé
  borne, 404 si `BORNE_API_KEY` n'est pas définie) ; valeur jamais loggée.

## [4.3.0] — 2026-11-24 — Plaques de tous pays

### Modifié
- Toutes les plaques sont acceptées : françaises SIV ou ancien format
  (FNI), étrangères. 2 à 10 lettres ou chiffres, espaces, tirets et points
  acceptés comme séparateurs. La plaque SIV garde sa forme `AB-123-CD`
  (véhicules déjà enregistrés chez Vehicles retrouvés) ; les autres sont
  envoyées sans séparateurs (`B-MW 1234` → `BMW1234`), pour qu'une même
  plaque saisie autrement donne le même véhicule. Aucune plaque acceptée
  avant n'est refusée maintenant.
- Borne client : saisie libre (toutes les touches actives, touche Espace),
  bandeau « F » seulement pour une plaque SIV ; borne de test et recherche
  du dashboard alignées ; smoke test mis à jour.

## [4.2.0] — 2026-11-24 — Catégories et occupation Parking

Parking 1.5.0 a ajouté `GET /parking/categories`, un `label` dans ses
réponses et `spot_held` dans l'occupation (rien de retiré). Aucun champ
d'Access modifié ni retiré.

### Ajouté
- Avant chaque `hold`, la catégorie demandée est comparée à la liste de
  Parking (cache 5 min). Absente, ou 404 sur `hold` : entrée refusée avec
  « Catégorie de place X inconnue du service Parking » (au lieu de
  « Service Parking indisponible »). Liste indisponible ou vide :
  vérification sautée, l'entrée n'est jamais bloquée par elle ;
  comparaison sans tenir compte de la casse.
- `GET /access/parking` (clé d'exploitation) : occupation par catégorie vue
  par Parking (libellé, prises, mises de côté, capacité, taux) et
  catégories utilisées par Access mais absentes chez Parking ;
  `available: false` si Parking ne répond pas.
- Dashboard, onglet « État du parking » : panneau « Occupation vue par
  Parking » (barres colorées, alerte catégorie manquante ou Parking muet,
  rafraîchi toutes les 30 s) ; présences et borne de test affichent les
  libellés de Parking.
- `placeLabel` dans la réponse d'une entrée autorisée ; la borne client
  l'affiche en priorité.

## [4.1.0] — 2026-11-24 — Borne client

Aucun champ existant modifié ni retiré : les autres services et la borne du
dashboard fonctionnent comme avant.

### Ajouté
- Borne client `/borne` (écran public, entrée et sortie) : saisie guidée de
  la plaque (clavier à l'écran ou physique), étapes du traitement, place
  attribuée, ticket de sortie (entrée, sortie, durée, montant), messages
  clairs en cas de refus, « Un agent arrive » si besoin, retour automatique
  à l'accueil. `?mode=entree|sortie` pour une borne fixe, réglages par appui
  long sur le logo ou `?config`. Thème clair/sombre, mobile, aucune
  ressource externe ; la plaque n'est conservée nulle part.
- Clé borne `BORNE_API_KEY` : n'autorise que `POST /access/requests` (401
  sur toutes les autres routes). Access refuse de démarrer en production si
  elle fait moins de 16 caractères ou vaut `API_KEY`. Générée par Render.
- Réponse de `POST /access/requests` quand le passage est autorisé :
  `placeType` et `reservation` (entrée), `enteredAt` et `durationMinutes`
  (sortie). `null` sinon.

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
