# Splunk en local — quoi faire, pas à pas

TP « Installer Splunk en local avec Docker ». Tout est dans
[`tp/splunk`](tp/splunk) ; cette page est le résumé à suivre.

## Où on en est

- Docker est installé et l'image **`tp-splunk` est déjà construite** sur ce Mac.
- Il reste **une chose à faire vous-même** : démarrer le conteneur en
  choisissant votre mot de passe. Personne d'autre ne doit le connaître, et
  il n'est écrit nulle part.

## Les 3 gestes

**1. Ouvrir Docker Desktop** et attendre que l'icône de la baleine soit fixe.

**2. Démarrer Splunk** (le script demande le mot de passe au clavier, 8
caractères au moins) :

```bash
cd tp/splunk && ./demarrer.sh
```

Le premier démarrage prend plusieurs minutes (sur un Mac Apple Silicon,
l'image tourne par émulation). Le script affiche « Prêt » quand c'est bon.

**3. Ouvrir <http://localhost:8000/>** et se connecter :

- identifiant : `admin`
- mot de passe : celui que vous venez de choisir

Pour arrêter (le conteneur et sa configuration sont conservés) :

```bash
cd tp/splunk && ./arreter.sh
```

Pour relancer plus tard : de nouveau `./demarrer.sh`.

## Ce qu'il faut savoir expliquer

**1. À quoi sert le Dockerfile ?** Il décrit l'image à construire :

| Ligne | Ce qu'elle fait |
|---|---|
| `FROM splunk/splunk:latest` | Part de l'image officielle de Splunk : rien à installer à la main. |
| `ENV SPLUNK_START_ARGS=--accept-license` | Accepte la licence, sans quoi Splunk refuse de démarrer. |
| `ENV SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com` | Accepte les conditions générales, exigées par les versions récentes. |
| `ENV SPLUNK_LICENSE_URI=Free` | Utilise la licence gratuite. |
| `EXPOSE 8000` | Documente le port de l'interface web (il ne l'ouvre pas : c'est `-p` au lancement). |

Le mot de passe n'y est pas : une variable `ENV` resterait lisible dans
l'image. Il est donné au lancement du conteneur.

**2. Construire l'image :**

```bash
docker build --platform linux/amd64 -t tp-splunk tp/splunk
```

**3. Démarrer et arrêter le conteneur** (sans le script) :

```bash
docker run -d --platform linux/amd64 --name tp-splunk -p 127.0.0.1:8000:8000 -e 'SPLUNK_PASSWORD=<votre-mot-de-passe>' tp-splunk
```

```bash
docker stop tp-splunk
```

```bash
docker start tp-splunk
```

`-p 127.0.0.1:8000:8000` : l'interface n'est joignable que depuis cet
ordinateur. Ne faites pas `docker rm tp-splunk` si vous voulez garder la
configuration : le TP n'utilise pas de volume.

**4. Se connecter :** <http://localhost:8000/>, compte `admin`.

## Si ça coince

| Ce que vous voyez | Quoi faire |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop n'est pas démarré : le lancer et recommencer. |
| `port is already allocated` | Le port 8000 est pris : arrêter l'autre programme, ou remplacer `8000:8000` par `8001:8000` et ouvrir <http://localhost:8001/>. |
| `The container name "/tp-splunk" is already in use` | Il existe déjà : `docker start tp-splunk`. |
| La page ne s'ouvre pas | Splunk démarre encore : `docker logs -f tp-splunk` pour suivre. |
| Le conteneur s'arrête tout de suite | Mot de passe trop court : `docker rm tp-splunk`, puis relancer `./demarrer.sh`. |

La notice complète, option par option : [`tp/splunk/README.md`](tp/splunk/README.md).
