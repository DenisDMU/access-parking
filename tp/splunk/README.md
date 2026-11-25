# TP — Installer Splunk en local avec Docker

Une instance locale de **Splunk Enterprise** dans un conteneur Docker, avec
son interface web sur `http://localhost:8000/`. Ce TP s'arrête à
l'installation et au démarrage ; la collecte et l'analyse de logs viendront
dans un exercice suivant.

## En deux commandes

```bash
cd tp/splunk
```

```bash
./demarrer.sh
```

Le script construit l'image `tp-splunk` si elle n'existe pas, **demande le
mot de passe du compte `admin` au clavier**, démarre le conteneur et attend
que l'interface réponde. Ensuite : ouvrir <http://localhost:8000/>,
identifiant `admin`, mot de passe choisi.

Pour arrêter :

```bash
./arreter.sh
```

## 1. À quoi sert le Dockerfile

```dockerfile
FROM splunk/splunk:latest

ENV SPLUNK_START_ARGS=--accept-license
ENV SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com
ENV SPLUNK_LICENSE_URI=Free

EXPOSE 8000
```

| Ligne | Rôle |
|---|---|
| `FROM splunk/splunk:latest` | Part de l'image officielle de Splunk : rien à installer à la main. |
| `SPLUNK_START_ARGS=--accept-license` | Accepte la licence de Splunk, sans quoi le service refuse de démarrer. |
| `SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com` | Accepte les conditions générales de Splunk, exigées par les versions récentes. |
| `SPLUNK_LICENSE_URI=Free` | Utilise la licence gratuite (pas de fichier de licence à fournir). |
| `EXPOSE 8000` | Documente le port de l'interface web. Il ne l'ouvre pas : c'est `-p` qui le fait au lancement. |

**Le mot de passe n'est pas dans le Dockerfile.** Une variable `ENV` reste
lisible dans l'image (`docker history`, `docker inspect`) par quiconque la
récupère. Il est donc donné au lancement du conteneur.

## 2. Construire l'image

```bash
docker build --platform linux/amd64 -t tp-splunk .
```

`--platform linux/amd64` : l'image officielle n'existe que pour cette
architecture. Sur un Mac Apple Silicon, Docker l'exécute par émulation ;
sur un PC, l'option ne change rien.

## 3. Démarrer et arrêter le conteneur

Démarrer, en choisissant son propre mot de passe (8 caractères au moins) :

```bash
docker run -d \
  --platform linux/amd64 \
  --name tp-splunk \
  -p 127.0.0.1:8000:8000 \
  -e 'SPLUNK_PASSWORD=<votre-mot-de-passe>' \
  tp-splunk
```

- `-d` : en arrière-plan.
- `--name tp-splunk` : un nom pour le retrouver.
- `-p 127.0.0.1:8000:8000` : le port 8000 n'est joignable **que depuis cet
  ordinateur** (sans `127.0.0.1:`, il le serait depuis tout le réseau).
- `-e SPLUNK_PASSWORD=…` : le mot de passe du compte `admin`.

Le premier démarrage prend plusieurs minutes. Pour le suivre :

```bash
docker logs -f tp-splunk
```

Arrêter, puis relancer plus tard **le même** conteneur :

```bash
docker stop tp-splunk
```

```bash
docker start tp-splunk
```

Ne supprimez pas le conteneur (`docker rm`) si vous voulez garder sa
configuration : ce TP ne configure aucun volume de persistance.

## 4. Ouvrir l'interface web

<http://localhost:8000/> — identifiant `admin`, mot de passe choisi à
l'étape 3.

## En cas de souci

| Symptôme | Cause probable | Quoi faire |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop n'est pas démarré | Le lancer, attendre l'icône stable, recommencer |
| `port is already allocated` | Le port 8000 est pris (par exemple Access lancé en local sur 8000) | Arrêter l'autre service, ou publier Splunk ailleurs : `-p 127.0.0.1:8001:8000` |
| `The container name "/tp-splunk" is already in use` | Le conteneur existe déjà | `docker start tp-splunk` |
| La page ne répond pas | Splunk démarre encore | Attendre, suivre `docker logs -f tp-splunk` |
| Le conteneur s'arrête tout de suite | Mot de passe refusé (trop court) | `docker logs tp-splunk`, puis `docker rm tp-splunk` et relancer avec un mot de passe plus long |

Documentation : *Splunk — Déploiement dans Docker* (dépôt `splunk/docker-splunk`,
`docs/SETUP.md`).
