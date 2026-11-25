#!/usr/bin/env bash
# TP Splunk — arrête le conteneur sans le supprimer (sa configuration reste).
# Pour le relancer : ./demarrer.sh (ou `docker start tp-splunk`).
set -euo pipefail
docker stop tp-splunk
echo "Conteneur arrêté. Il n'est pas supprimé : ./demarrer.sh le relance tel quel."
