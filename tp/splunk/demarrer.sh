#!/usr/bin/env bash
# TP Splunk — construit l'image `tp-splunk` si besoin, puis démarre le conteneur.
#
#   ./demarrer.sh
#
# Le mot de passe du compte `admin` est demandé au clavier : il n'est écrit
# nulle part (ni dans l'image, ni dans un fichier, ni dans l'historique du
# terminal). L'interface n'est ouverte que sur cet ordinateur (127.0.0.1).
set -euo pipefail
cd "$(dirname "$0")"

IMAGE=tp-splunk
NAME=tp-splunk
# L'image officielle de Splunk n'existe qu'en amd64 : sur un Mac Apple Silicon,
# Docker l'exécute par émulation (plus lent au premier démarrage).
PLATFORM=linux/amd64

if ! docker info >/dev/null 2>&1; then
  echo "Docker ne répond pas : démarrez Docker Desktop, puis relancez ce script." >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "Le conteneur $NAME existe déjà : on le redémarre (sa configuration est conservée)."
  docker start "$NAME" >/dev/null
else
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Construction de l'image $IMAGE (le premier téléchargement est long)…"
    docker build --platform "$PLATFORM" -t "$IMAGE" .
  fi
  read -r -s -p "Mot de passe du compte admin (8 caractères au moins) : " SPLUNK_PASSWORD
  echo
  if [ "${#SPLUNK_PASSWORD}" -lt 8 ]; then
    echo "Mot de passe trop court : Splunk en exige au moins 8 caractères." >&2
    exit 1
  fi
  export SPLUNK_PASSWORD
  # `-e SPLUNK_PASSWORD` sans valeur : Docker la lit dans l'environnement, elle
  # n'apparaît donc pas dans la ligne de commande.
  docker run -d --platform "$PLATFORM" --name "$NAME" \
    -p 127.0.0.1:8000:8000 -e SPLUNK_PASSWORD "$IMAGE" >/dev/null
  unset SPLUNK_PASSWORD
fi

echo "Splunk démarre (plusieurs minutes la première fois)…"
for _ in $(seq 1 90); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/en-US/account/login 2>/dev/null; then
    echo "Prêt : http://localhost:8000/ (identifiant : admin)"
    exit 0
  fi
  sleep 5
done
echo "Splunk n'a pas encore répondu. Suivez le démarrage avec : docker logs -f $NAME" >&2
exit 1
