"""Batterie de tests en ligne d'Access.

Fait de vrais passages (Vehicles, Booking, Parking, Pricing, Payment réels),
toujours dans la première heure (0 €, aucun paiement), puis supprime les
véhicules de test chez Vehicles.

    BORNE_API_KEY=... python3 scripts/tests_en_ligne.py
    ACCESS_URL=https://... BORNE_API_KEY=... VEHICLES_API_KEY=... python3 scripts/tests_en_ligne.py

- `ACCESS_URL` : instance testée (par défaut, celle de Render). La version
  attendue est lue dans `src/__init__.py`.
- `BORNE_API_KEY` : clé des bornes (jamais la clé d'exploitation), lue dans
  Render > Environment ; `ACCESS_URL` doit alors être en https. Depuis la 4.29.0, un passage exige une borne mise en service
  avec sa clé : les passages passent par `POST /access/requests`, comme la
  borne. Sans cette clé, les sections de passages sont sautées (signalé,
  sans compter comme un échec).
- Nettoyage chez Vehicles : `DELETE` est protégé depuis le 24/11. Sans
  `VEHICLES_API_KEY`, les véhicules de test (plaques ZZ-9xx-ZZ) restent chez
  Vehicles ; c'est signalé, sans compter comme un échec.
- Environ 2 minutes : `POST /access/requests` limite à 20 passages par minute.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

A = os.getenv("ACCESS_URL", "https://access-api-a1u7.onrender.com").rstrip("/")
V = os.getenv("VEHICLES_URL", "https://parking-vehicles.onrender.com").rstrip("/")
VEHICLES_KEY = os.getenv("VEHICLES_API_KEY", "")
# Clé des bornes seulement : jamais la clé d'exploitation pour faire des passages.
PASSAGE_KEY = os.getenv("BORNE_API_KEY", "")
if PASSAGE_KEY and not A.startswith("https://"):
    sys.exit("ACCESS_URL doit être en https:// quand BORNE_API_KEY est fournie")
KEY_HEADERS = {"X-API-Key": PASSAGE_KEY}
_INIT = os.path.join(os.path.dirname(__file__), "..", "src", "__init__.py")
VERSION = re.search(r'__version__ = "([^"]+)"', open(_INIT, encoding="utf-8").read()).group(1)
results = []


def call(method, url, body=None, timeout=90, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL http(s) attendue")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})  # noqa: S310
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (http(s) vérifié)
            raw = resp.read().decode()
            return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(), dict(err.headers)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def status_no_redirect(url):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(url, timeout=60)
        return resp.status, None
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Location")


def check(label, ok, detail=""):
    results.append((label, ok))
    print(("  OK   " if ok else "  ÉCHEC ") + label + (f"  ({detail})" if detail else ""))


def keyed(body):
    """Passage comme la borne mise en service : clé borne, date et source fixées."""

    body = {"date": datetime.now(UTC).isoformat(), "source": 2, **body}
    return call("POST", f"{A}/api/v1/access/requests", body, headers=KEY_HEADERS)


def passage(plate, type_, vehicle_type=None, country=None):
    body = {"licensePlate": plate, "type": type_}
    if vehicle_type:
        body["vehicleType"] = vehicle_type
    if country:
        body["country"] = country
    code, raw, _ = keyed(body)
    time.sleep(3.5)  # limite : 20 passages / minute
    try:
        data = json.loads(raw)
    except ValueError:
        return code, raw
    if not isinstance(data, dict) or "authorization" not in data:
        return code, data
    # Même forme que la réponse affichée par la borne.
    auth = data["authorization"]
    return code, {
        "result": auth.get("result"),
        "reason": auth.get("reason"),
        "paymentAmount": auth.get("paymentAmount"),
        "vehicleIdentified": bool(data.get("vehicleId")),
        "placeType": data.get("placeType"),
    }


print("1. Santé")
code, raw, _ = call("GET", f"{A}/health")
h = json.loads(raw)
check("GET /health 200", code == 200)
check(f"version {VERSION}", h.get("version") == VERSION, h.get("version"))
check(
    "base Postgres connectée",
    h.get("database") == "connected" and h.get("databaseEngine") == "postgresql",
)
check("Booking réel", h.get("booking") == "réel", h.get("booking"))

print("2. Pages")
check("/borne 200 (sans .html)", status_no_redirect(f"{A}/borne")[0] == 200)
code, loc = status_no_redirect(f"{A}/static/borne.html?mode=entree")
check("ancien lien → /borne (301)", code == 301 and loc == "/borne?mode=entree", f"{code} {loc}")
check("dashboard 200", call("GET", f"{A}/static/dashboard.html")[0] == 200)
check("/docs 200", call("GET", f"{A}/docs")[0] == 200)
code, raw, _ = call("GET", f"{A}/openapi.json")
check(f"OpenAPI en {VERSION}", json.loads(raw)["info"]["version"] == VERSION)
code, raw, _ = call("GET", f"{A}/borne")
check(
    "écrans « Votre véhicule » et « Pays » servis",
    'id="screen-type"' in raw and 'id="screen-country"' in raw,
)

print("3. Sécurité (sans clé → 401)")
for method, path in [
    ("GET", "/api/v1/access/requests"),
    ("GET", "/api/v1/access/presences"),
    ("GET", "/api/v1/access/events"),
    ("GET", "/api/v1/access/parking"),
    ("GET", "/api/v1/access/borne/key"),
    ("POST", "/api/v1/access/requests"),
    ("POST", "/api/v1/access/vehicles/known"),
    ("GET", "/metrics"),
]:
    code = call(method, f"{A}{path}", {} if method == "POST" else None)[0]
    check(f"{method} {path} → 401", code == 401, code)
code, raw, headers = call("GET", f"{A}/api/v1/borne/status")
check(
    "plan 3D public, passage sans clé fermé",
    json.loads(raw) == {"publicAccess": True, "publicPassages": False},
    raw,
)
code = call("POST", f"{A}/api/v1/borne/passages", {"licensePlate": "ZZ-920-ZZ", "type": 1})[0]
check("POST /api/v1/borne/passages sans clé → 403", code == 403, code)
code = call(
    "POST", f"{A}/api/v1/borne/pmr-validation", {"licensePlate": "ZZ-920-ZZ", "agentCode": "0"}
)[0]
check("POST /api/v1/borne/pmr-validation sans clé → 401", code == 401, code)
check(
    "plan 3D public (GET /api/v1/borne/parking)", call("GET", f"{A}/api/v1/borne/parking")[0] == 200
)
low = {k.lower(): v for k, v in headers.items()}
check(
    "en-têtes de sécurité",
    low.get("x-frame-options") == "DENY"
    and low.get("x-content-type-options") == "nosniff"
    and low.get("referrer-policy") == "no-referrer",
)

if not PASSAGE_KEY:
    print("\n  (sans BORNE_API_KEY : passages réels sautés, voir l'en-tête de ce script)")
    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} contrôles OK")
    for label in failed:
        print("  échec :", label)
    sys.exit(1 if failed else 0)

print("4. Erreurs de saisie (borne avec sa clé)")
code, raw, _ = keyed({"licensePlate": "AB#123", "type": 1})
check("plaque invalide → 422 sans la plaque", code == 422 and "AB#123" not in raw, code)
code, _, _ = keyed({"licensePlate": "AB-123-CD", "type": 3})
check("sens invalide → 422", code == 422, code)
code, _, _ = keyed({"licensePlate": "AB-123-CD", "type": 1, "vehicleType": "TANK"})
check("type de véhicule invalide → 422", code == 422, code)

print("5. Passages réels, un par type de véhicule")
cases = [
    (
        "ZZ-921-ZZ",
        "zz 921 zz",
        "STANDARD",
        "FR",
        lambda p: not (p["isXl"] or p["isElectric"] or p["isHandicap"]) and p["category"] == 2,
    ),
    ("B-ZZ 921", "BZZ921", "ELECTRIC", "DE", lambda p: p["isElectric"]),
    ("921 ZZZ 75", "921ZZZ75", "XL", "FR", lambda p: p["isXl"]),
    ("ZZ-922-ZZ", "ZZ922ZZ", "TWO_WHEELS", None, lambda p: p["category"] == 1),
]
for plate_in, plate_out, vtype, country, place_ok in cases:
    code, body = passage(plate_in, 1, vtype, country)
    ok = code == 200 and isinstance(body, dict) and body.get("result") == 1
    check(f"entrée {vtype} ({plate_in}) autorisée", ok, body if not ok else "")
    if ok:
        check(
            f"  place adaptée ({vtype})",
            bool(body.get("placeType")) and place_ok(body["placeType"]),
            body.get("placeType"),
        )
    code, body = passage(plate_out, 2, None, country)
    ok = code == 200 and isinstance(body, dict) and body.get("result") == 1
    check(
        f"sortie {vtype} ({plate_out}, {country or 'sans pays'}) autorisée, 0 €",
        ok and body.get("paymentAmount") in (0, 0.0, None),
        body,
    )

code, body = passage("ZZ-923-ZZ", 1, "HANDICAPPED")
check(
    "PMR déclaré, inconnu de Vehicles → agent",
    code == 200 and body.get("result") == 3 and body.get("vehicleIdentified") is True,
    body,
)

print("6. Refus attendus")
code, body = passage("ZZ-924-ZZ", 1, "STANDARD")
check("entrée ZZ-924-ZZ", code == 200 and body.get("result") == 1, body)
code, body = passage("ZZ-924-ZZ", 1, "STANDARD")
check(
    "2e entrée → refus « déjà présent »",
    code == 200 and body.get("result") == 2 and "déjà présent" in (body.get("reason") or ""),
    body,
)
code, body = passage("ZZ-924-ZZ", 2)
check("sortie ZZ-924-ZZ", code == 200 and body.get("result") == 1, body)
code, body = passage("ZZ-925-ZZ", 2)
check(
    "sortie sans entrée → refus « non présent »",
    code == 200 and body.get("result") == 2 and "non présent" in (body.get("reason") or ""),
    body,
)

print("7. Pays de la plaque : France et Italie, même plaque")
code, body = passage("ZZ-932-ZZ", 1, "STANDARD", "FR")
check("entrée française ZZ-932-ZZ", code == 200 and body.get("result") == 1, body)
code, body = passage("ZZ 932 ZZ", 1, "STANDARD", "IT")
check(
    "entrée italienne ZZ 932 ZZ : autre véhicule (pas « déjà présent »)",
    code == 200 and body.get("result") == 1,
    body,
)
code, body = passage("ZZ932ZZ", 2, None, "IT")
check("sortie italienne", code == 200 and body.get("result") == 1, body)
code, body = passage("ZZ-932-ZZ", 2, None, "FR")
check("sortie française", code == 200 and body.get("result") == 1, body)
code, raw, _ = keyed({"licensePlate": "B-MW 1234", "type": 1, "country": "FR"})
check(
    "plaque allemande déclarée française → 422 sans la plaque",
    code == 422 and "BMW1234" not in raw and "B-MW" not in raw,
    code,
)
code, _, _ = keyed({"licensePlate": "AB-123-CD", "type": 1, "country": "US"})
check("pays inconnu → 422", code == 422, code)

print("8. Nettoyage chez Vehicles")
if not VEHICLES_KEY:
    print("  (sans VEHICLES_API_KEY : DELETE protégé chez Vehicles, véhicules de test laissés)")
for plate in [
    "ZZ-921-ZZ",
    "DE:BZZ921",
    "921ZZZ75",
    "ZZ-922-ZZ",
    "ZZ-923-ZZ",
    "ZZ-924-ZZ",
    "ZZ-925-ZZ",
    "ZZ-932-ZZ",
    "IT:ZZ932ZZ",
]:
    code, raw, _ = call("POST", f"{V}/api/vehicle/create", {"licensePlate": plate})
    vid = json.loads(raw) if code == 200 else None
    if not VEHICLES_KEY:
        continue
    auth = {"X-API-Key": VEHICLES_KEY}
    dcode = call("DELETE", f"{V}/api/vehicle/{vid}", headers=auth)[0] if vid else None
    check(f"véhicule de test {plate} supprimé", dcode == 200, dcode)

failed = [label for label, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} contrôles OK")
for label in failed:
    print("  échec :", label)
sys.exit(1 if failed else 0)
