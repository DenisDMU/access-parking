#!/usr/bin/env bash
# TP Prometheus — arrête les conteneurs sans les supprimer (les mesures déjà
# collectées restent dans le volume `tp-prometheus-data`).
# Pour relancer : ./demarrer.sh (ou ./demarrer.sh --grafana).
set -euo pipefail
for name in tp-grafana tp-prometheus; do
  if docker ps --format '{{.Names}}' | grep -qx "$name"; then
    docker stop "$name" >/dev/null
    echo "Conteneur $name arrêté."
  fi
done
echo "Rien n'est supprimé : ./demarrer.sh relance le tout tel quel."
