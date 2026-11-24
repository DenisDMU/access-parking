#!/usr/bin/env bash
# Vérification reproductible d'une instance Access (locale ou Render).
#
#   BASE_URL=http://localhost:8000 API_KEY=change-me ./scripts/smoke_test.sh
#   BASE_URL=https://access-api-a1u7.onrender.com API_KEY=... VEHICLE_PLATE=AB-123-CD ./scripts/smoke_test.sh
#
# Sans VEHICLE_PLATE : contrôles sans effet de bord (santé, authentification,
# validation des entrées, métriques). Avec VEHICLE_PLATE (une plaque de test,
# créée chez Vehicles si elle est inconnue) : workflow complet entrée →
# présence → sortie payée, qui appelle RÉELLEMENT Vehicles, Parking, Pricing
# et Payment.
#
# Toutes les requêtes portent le même X-Correlation-ID (affiché au début) :
# un `grep` de cette valeur dans les logs d'Access retrouve tout le passage.
set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-change-me}"
VEHICLE_PLATE="${VEHICLE_PLATE:-}"
# Si défini (ex. par la CI) : vérifie que l'instance sert bien CETTE version.
EXPECTED_VERSION="${EXPECTED_VERSION:-}"
CID="smoke-$(date +%Y%m%d%H%M%S)"
FAILS=0
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "Access smoke test — $BASE_URL — X-Correlation-ID: $CID"

# call METHOD PATH [BODY] [KEY]  → code HTTP sur stdout, corps dans $TMP
call() {
  local method="$1" path="$2" body="${3:-}" key="${4-$API_KEY}"
  local args=(-s -o "$TMP" -w "%{http_code}" -X "$method" --max-time 90
    -H "X-Correlation-ID: $CID" -H "Content-Type: application/json")
  [ -n "$key" ] && args+=(-H "X-API-Key: $key")
  [ -n "$body" ] && args+=(--data "$body")
  curl "${args[@]}" "$BASE_URL$path"
}

# json EXPR → évalue EXPR (Python) sur le corps de la dernière réponse (`d`)
json() { python3 -c "import json,sys; d=json.load(open('$TMP')); print($1)" 2>/dev/null; }

check() { # check LIBELLÉ ATTENDU OBTENU
  if [ "$2" = "$3" ]; then echo "  PASS  $1"; else echo "  FAIL  $1 (attendu $2, obtenu $3)"; FAILS=$((FAILS + 1)); fi
}

# body PLAQUE TYPE DATE SOURCE [CHAMPS_JSON_EN_PLUS] → corps de POST /access/requests
body() { printf '{"licensePlate":"%s","type":%s,"date":"%s","source":%s%s}' "$1" "$2" "$3" "$4" "${5:+,$5}"; }

iso_in() { python3 -c "from datetime import datetime,timedelta,timezone as t; print((datetime.now(t.utc)+timedelta(minutes=$1)).strftime('%Y-%m-%dT%H:%M:%SZ'))"; }

echo "1. Santé et version"
check "GET /health sans clé → 200" 200 "$(call GET /health '' '')"
echo "        version $(json "d['version']") · commit $(json "d['commit'][:7]") · base $(json "d['database']")"
[ -n "$EXPECTED_VERSION" ] && check "version déployée = $EXPECTED_VERSION" "$EXPECTED_VERSION" "$(json "d['version']")"

echo "2. Authentification"
check "sans clé API → 401" 401 "$(call GET /api/v1/access/requests '' '')"
check "mauvaise clé API → 401" 401 "$(call GET /api/v1/access/requests '' 'mauvaise-cle')"

echo "3. Validation des entrées"
NOW="$(iso_in 0)"
check "corps vide → 422" 422 "$(call POST /api/v1/access/requests '{}')"
B="$(body AB-123-CD 3 "$NOW" 3)"
check "type inconnu → 422" 422 "$(call POST /api/v1/access/requests "$B")"
B="$(body 'AB#123' 1 "$NOW" 3)"
check "plaque mal formée → 422" 422 "$(call POST /api/v1/access/requests "$B")"
check "erreur 422 sans la plaque reçue" False "$(grep -q 'AB#123' "$TMP" && echo True || echo False)"
B="$(body AB-123-CD 1 "$NOW" 3 '"photoBase64":"%%%"')"
check "photoBase64 corrompue → 400" 400 "$(call POST /api/v1/access/requests "$B")"
check "période from > to → 422" 422 "$(call GET '/api/v1/access/requests?from=2026-12-02T00:00:00Z&to=2026-12-01T00:00:00Z')"
check "demande inexistante → 404" 404 "$(call GET /api/v1/access/requests/inexistante)"

echo "4. Observabilité"
check "GET /metrics avec clé → 200" 200 "$(call GET /metrics)"
check "/metrics expose les métriques métier" True "$(call GET /metrics >/dev/null; grep -q '^# HELP access_decisions_total' "$TMP" && echo True || echo False)"
check "en-tête X-Correlation-ID renvoyé" "$CID" "$(curl -s -o /dev/null -D - -H "X-Correlation-ID: $CID" "$BASE_URL/health" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-correlation-id"{print $2}')"
check "GET /access/presences → 200" 200 "$(call GET /api/v1/access/presences)"
echo "        $(json "len(d)") véhicule(s) actuellement présent(s)"

if [ -n "$VEHICLE_PLATE" ]; then
  echo "5. Workflow réel entrée → sortie (plaque de test fournie)"
  B="$(body "$VEHICLE_PLATE" 1 "$NOW" 3)"
  check "entrée → 200" 200 "$(call POST /api/v1/access/requests "$B")"
  RESULT="$(json "d['authorization']['result']")"
  VEHICLE_ID="$(json "d['vehicleId']")"
  echo "        décision $RESULT ($(json "d['authorization']['reason']")) · vehicleId $VEHICLE_ID"
  check "entrée autorisée (result=1)" 1 "$RESULT"
  call GET /api/v1/access/presences >/dev/null
  check "véhicule listé dans les présences" True "$(json "any(v['vehicleId'] == '$VEHICLE_ID' for v in d)")"
  echo "        sortie dans 2 h 30 (Pricing puis Payment, ~15-30 s)…"
  B="$(body "$VEHICLE_PLATE" 2 "$(iso_in 150)" 2)"
  check "sortie → 200" 200 "$(call POST /api/v1/access/requests "$B")"
  echo "        décision $(json "d['authorization']['result']") ($(json "d['authorization']['reason']")) · montant $(json "d['authorization']['paymentAmount']") €"
  check "sortie autorisée (result=1)" 1 "$(json "d['authorization']['result']")"
else
  echo "5. Workflow réel : ignoré (définir VEHICLE_PLATE pour l'exécuter)"
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "OK — tous les contrôles sont passés"; else echo "ÉCHEC — $FAILS contrôle(s) en erreur"; fi
exit "$FAILS"
