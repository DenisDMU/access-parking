#!/usr/bin/env bash
# TP Prometheus — construit l'image `tp-prometheus`, puis démarre le conteneur.
#
#   ./demarrer.sh             Prometheus seul       → http://localhost:9090/
#   ./demarrer.sh --grafana   Prometheus + Grafana  → http://localhost:3000/
#
# Aucun mot de passe : Prometheus n'en a pas, et Grafana s'ouvre en lecture
# seule sans connexion (le mot de passe de son compte admin est tiré au hasard
# à la création du conteneur, jamais affiché ni écrit dans un fichier). Les
# deux interfaces ne sont ouvertes que sur cet ordinateur (127.0.0.1).
set -euo pipefail
cd "$(dirname "$0")"

IMAGE=tp-prometheus
NAME=tp-prometheus
VOLUME=tp-prometheus-data
NETWORK=tp-prometheus
GRAFANA_NAME=tp-grafana
GRAFANA_IMAGE=docker.io/grafana/grafana:latest

WITH_GRAFANA=false
case "${1:-}" in
  "") ;;
  --grafana) WITH_GRAFANA=true ;;
  *) echo "Usage : ./demarrer.sh [--grafana]" >&2; exit 2 ;;
esac

if ! docker info >/dev/null 2>&1; then
  echo "Docker ne répond pas : démarrez Docker Desktop, puis relancez ce script." >&2
  exit 1
fi

wait_for() { # wait_for <url> <essais de 2 s>
  for _ in $(seq 1 "$2"); do
    if curl -fsS -o /dev/null "$1" 2>/dev/null; then return 0; fi
    sleep 2
  done
  return 1
}

# Réseau commun : Grafana y joint Prometheus par son nom (http://tp-prometheus:9090).
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

# L'image est reconstruite à chaque fois (une seconde quand rien n'a changé) :
# prometheus.yml y est copié, une modification doit donc repasser par là.
echo "Construction de l'image $IMAGE…"
docker build -q -t "$IMAGE" . >/dev/null
WANTED="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
CURRENT="$(docker inspect -f '{{.Image}}' "$NAME" 2>/dev/null || true)"

if [ -n "$CURRENT" ] && [ "$CURRENT" != "$WANTED" ]; then
  echo "prometheus.yml a changé : le conteneur est recréé (les mesures sont conservées)."
  docker rm -f "$NAME" >/dev/null
  CURRENT=""
fi
if [ -n "$CURRENT" ]; then
  docker start "$NAME" >/dev/null
else
  # --add-host : rend `host.docker.internal` disponible aussi sous Linux
  # (cible `access-local`, l'Access lancé sur cet ordinateur).
  docker run -d --name "$NAME" --network "$NETWORK" \
    --add-host=host.docker.internal:host-gateway \
    -p 127.0.0.1:9090:9090 -v "$VOLUME":/prometheus "$IMAGE" >/dev/null
fi

if ! wait_for http://127.0.0.1:9090/-/ready 30; then
  echo "Prometheus n'a pas répondu. Regardez : docker logs $NAME" >&2
  exit 1
fi
echo "Prometheus est prêt : http://localhost:9090/targets (état des services)"

if [ "$WITH_GRAFANA" = true ]; then
  if docker ps -a --format '{{.Names}}' | grep -qx "$GRAFANA_NAME"; then
    docker start "$GRAFANA_NAME" >/dev/null
  else
    echo "Démarrage de Grafana (le premier téléchargement est long)…"
    # Lu dans l'environnement par `-e NOM` (sans valeur) : le mot de passe
    # n'apparaît ni dans la ligne de commande ni dans un fichier.
    GF_SECURITY_ADMIN_PASSWORD="$(openssl rand -base64 24)"
    export GF_SECURITY_ADMIN_PASSWORD
    docker run -d --name "$GRAFANA_NAME" --network "$NETWORK" \
      -p 127.0.0.1:3000:3000 \
      -e GF_SECURITY_ADMIN_PASSWORD \
      -e GF_AUTH_ANONYMOUS_ENABLED=true \
      -e GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
      -e GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/var/lib/grafana/dashboards/parking-management.json \
      -v "$PWD/grafana/provisioning":/etc/grafana/provisioning:ro \
      -v "$PWD/grafana/dashboards":/var/lib/grafana/dashboards:ro \
      "$GRAFANA_IMAGE" >/dev/null
    unset GF_SECURITY_ADMIN_PASSWORD
  fi
  if ! wait_for http://127.0.0.1:3000/api/health 60; then
    echo "Grafana n'a pas répondu. Regardez : docker logs $GRAFANA_NAME" >&2
    exit 1
  fi
  echo "Grafana est prêt : http://localhost:3000/ (tableau de bord « Parking Management »)"
fi
