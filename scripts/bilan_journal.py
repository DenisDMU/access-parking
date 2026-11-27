"""Bilan du journal d'Access après un test (en local, avec la clé d'exploitation).

    API_KEY=... python3 scripts/bilan_journal.py
    API_KEY=... python3 scripts/bilan_journal.py --depuis 2026-11-24T14:00:00Z
    API_KEY=... ACCESS_URL=http://localhost:8000 python3 scripts/bilan_journal.py

Lit les dernières demandes (`GET /api/v1/access/requests`, 500 au plus) et
les véhicules encore présents (`GET /api/v1/access/presences`), puis affiche :
- les décisions (autorisées, refusées, à confirmer), entrées et sorties ;
- les motifs de refus et de confirmation, du plus fréquent au plus rare ;
- l'activité minute par minute (pour repérer un pic ou une panne) ;
- les véhicules restés dans le parking, et depuis combien de temps.

Aucune plaque : Access ne la stocke jamais. Les véhicules ne sont désignés
que par le début de leur identifiant pseudonymisé. La clé n'est jamais
affichée ; elle reste sur votre machine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime

RESULT = {1: "autorisée", 2: "refusée", 3: "à confirmer"}
TYPE = {1: "entrée", 2: "sortie"}


def get(base: str, path: str, key: str):
    # La clé d'exploitation ne part qu'en https, ou vers cette machine.
    if not base.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise SystemExit("ACCESS_URL doit être en https:// (http:// accepté pour localhost)")
    req = urllib.request.Request(f"{base}{path}", headers={"X-API-Key": key})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 (http(s) vérifié)
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        if err.code == 401:
            raise SystemExit("Clé refusée (401) : vérifiez API_KEY.") from None
        raise SystemExit(f"{path} : HTTP {err.code}") from None


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bar(n: int, top: int, width: int = 30) -> str:
    return "█" * max(1, round(n / top * width)) if n else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--depuis", help="date ISO 8601 (UTC), ex. 2026-11-24T14:00:00Z")
    args = parser.parse_args()
    key = os.getenv("API_KEY", "")
    if not key:
        print("Renseignez la clé d'exploitation : API_KEY=... python3 scripts/bilan_journal.py")
        return 2
    base = os.getenv("ACCESS_URL", "https://access-api-a1u7.onrender.com").rstrip("/")
    query = "?limit=500" + (f"&from={args.depuis}" if args.depuis else "")
    requests = get(base, f"/api/v1/access/requests{query}", key)
    presences = get(base, "/api/v1/access/presences", key)
    now = datetime.now(UTC)

    if not requests:
        print("Aucune demande sur la période.")
    else:
        dates = sorted(parse(r["date"]) for r in requests)
        print(
            f"{len(requests)} demandes du {dates[0]:%d/%m %H:%M} au {dates[-1]:%d/%m %H:%M} (UTC)"
        )
        if len(requests) == 500:
            print("  (limite de 500 atteinte : resserrez la période avec --depuis)")

        print("\nDécisions")
        decisions = Counter(
            (TYPE.get(r["type"], "?"), RESULT.get(r["result"], "en cours")) for r in requests
        )
        for (kind, result), n in sorted(decisions.items()):
            print(f"  {kind:7} {result:12} {n:5}")

        print("\nMotifs des refus et des confirmations")
        reasons = Counter(r["reason"] or "(sans motif)" for r in requests if r["result"] in (2, 3))
        top = max(reasons.values(), default=1)
        for reason, n in reasons.most_common():
            print(f"  {n:5}  {bar(n, top, 20):20}  {reason}")
        if not reasons:
            print("  aucun")

        print("\nActivité par minute (█ autorisée · ░ refusée ou à confirmer)")
        per_minute: dict[str, Counter] = {}
        for r in requests:
            minute = parse(r["date"]).strftime("%H:%M")
            per_minute.setdefault(minute, Counter())["ok" if r["result"] == 1 else "ko"] += 1
        for minute in sorted(per_minute):
            c = per_minute[minute]
            print(f"  {minute}  {'█' * c['ok']}{'░' * c['ko']}  {c['ok']} ok, {c['ko']} non")

    print(f"\nVéhicules encore présents : {len(presences)}")
    if presences:
        by_place = Counter((p.get("placeId") or "?").split(":")[0] for p in presences)
        print("  par catégorie : " + ", ".join(f"{k} {v}" for k, v in by_place.most_common()))
        oldest = sorted(presences, key=lambda p: p.get("enteredAt") or "")[:10]
        print("  les plus anciens :")
        for p in oldest:
            since = ""
            if p.get("enteredAt"):
                minutes = int((now - parse(p["enteredAt"])).total_seconds() // 60)
                since = f"depuis {minutes // 60} h {minutes % 60:02d}"
            resa = " · réservation" if p.get("reservation") else ""
            print(f"    {str(p['vehicleId'])[:8]}…  {p.get('placeId') or '?':18} {since}{resa}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
