"""TP Prometheus (`tp/prometheus`) — le Dockerfile est celui du sujet, la
collecte vise Access et les autres microservices sans aucun secret, les
interfaces ne s'ouvrent que sur l'ordinateur local, et Prometheus reste un
détail d'infrastructure (ni le domaine ni les cas d'usage ne l'importent)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yaml

from src.infrastructure import metrics
from src.interfaces.api.middleware import _access_log_level

ROOT = Path(__file__).resolve().parents[2]
TP = ROOT / "tp" / "prometheus"
SECRET_WORDS = ("password", "passwd", "api-key", "api_key", "authorization", "bearer", "token")


def _scrape_configs() -> dict[str, dict]:
    config = yaml.safe_load((TP / "prometheus.yml").read_text())
    return {job["job_name"]: job for job in config["scrape_configs"]}


def _targets(job: dict) -> list[str]:
    return [target for group in job["static_configs"] for target in group["targets"]]


def test_dockerfile_du_sujet_tel_quel():
    assert (TP / "Dockerfile").read_text() == (
        "# Image officielle Prometheus\n"
        "FROM docker.io/prom/prometheus:latest\n"
        "\n"
        "# Configuration de la collecte (à créer dans le même dossier)\n"
        "COPY prometheus.yml /etc/prometheus/prometheus.yml\n"
    )


def test_prometheus_supervise_access_et_les_autres_microservices():
    jobs = _scrape_configs()

    assert jobs["access"]["scheme"] == "https"
    assert _targets(jobs["access"]) == ["access-api-a1u7.onrender.com"]
    assert jobs["access"].get("metrics_path", "/metrics") == "/metrics"
    others = {"parking", "vehicles", "booking", "pricing", "payment"} & set(jobs)
    assert len(others) >= 2  # le sujet : le nôtre et au moins deux autres
    for name in others:
        assert jobs[name]["scheme"] == "https"
        assert all(target.endswith(".onrender.com") for target in _targets(jobs[name]))
    # Une cible par service : pas deux fois le même hôte sous deux noms.
    all_targets = [target for job in jobs.values() for target in _targets(job)]
    assert len(all_targets) == len(set(all_targets))


def test_cible_locale_pour_simuler_une_indisponibilite():
    local = _scrape_configs()["access-local"]

    assert local["scheme"] == "http"
    assert _targets(local) == ["host.docker.internal:8010"]
    # Le guide donne la commande qui démarre cette cible, sur le même port.
    assert "--port 8010" in (ROOT / "PROMETHEUS.md").read_text()


def test_collecte_sans_aucun_secret():
    text = (TP / "prometheus.yml").read_text().lower()
    for word in SECRET_WORDS + ("http_headers", "basic_auth", "credentials"):
        assert word not in text


def test_demarrage_local_sans_mot_de_passe_ecrit():
    script = (TP / "demarrer.sh").read_text()

    assert "-p 127.0.0.1:9090:9090" in script  # Prometheus : jamais ouvert sur le réseau
    assert "-p 127.0.0.1:3000:3000" in script  # Grafana non plus
    # Mot de passe admin de Grafana : tiré au hasard, passé par l'environnement.
    assert 'GF_SECURITY_ADMIN_PASSWORD="$(openssl rand' in script
    assert "-e GF_SECURITY_ADMIN_PASSWORD \\" in script
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer" in script  # lecture seule sans connexion
    for line in script.splitlines():
        assert not re.search(r"PASSWORD=[A-Za-z0-9]", line), line
    assert "tp-prometheus" in (TP / "arreter.sh").read_text()


def test_grafana_provisionne_la_source_et_le_tableau_de_bord():
    grafana = TP / "grafana"
    source = yaml.safe_load((grafana / "provisioning/datasources/prometheus.yml").read_text())
    provider = yaml.safe_load((grafana / "provisioning/dashboards/dashboards.yml").read_text())
    dashboard = json.loads((grafana / "dashboards/parking-management.json").read_text())

    datasource = source["datasources"][0]
    assert datasource["type"] == "prometheus"
    assert datasource["url"] == "http://tp-prometheus:9090"
    assert not any(word in json.dumps(source).lower() for word in SECRET_WORDS)
    assert provider["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"
    queries = " ".join(t["expr"] for panel in dashboard["panels"] for t in panel["targets"])
    for needle in ("up", "rate(http_requests_total", '"4xx|5xx"', "parking_operations_total"):
        assert needle in queries
    for panel in dashboard["panels"]:
        assert panel["datasource"]["uid"] == datasource["uid"]


def test_guide_donne_les_trois_requetes_promql():
    guide = (ROOT / "PROMETHEUS.md").read_text()

    assert "http://localhost:9090/targets" in guide
    for query in (
        "sum by (job) (rate(http_requests_total[2m]))",
        'http_requests_total{status=~"4xx|5xx"}',
        "parking_operations_total",
    ):
        assert query in guide
    assert "\nup\n" in guide


def test_domaine_et_cas_d_usage_ignorent_prometheus():
    for layer in ("domain", "application"):
        for source in (ROOT / "src" / layer).rglob("*.py"):
            text = source.read_text()
            assert "prometheus" not in text.lower(), source
            assert "infrastructure.metrics" not in text, source


def test_compteur_metier_par_operation_et_resultat():
    def value(operation: str, result: str) -> float:
        return metrics.PARKING_OPERATIONS.labels(operation=operation, result=result)._value.get()

    entry_ok = value("entry", "authorized")
    exit_refused = value("exit", "refused")
    forced_ok, forced_missed = value("forced_exit", "authorized"), value("forced_exit", "refused")

    metrics.record_decision(1, 1, "Accès autorisé")
    metrics.record_decision(2, 2, "Paiement refusé")
    metrics.record_forced_exit(released=True)
    metrics.record_forced_exit(released=False)

    assert value("entry", "authorized") == entry_ok + 1
    assert value("exit", "refused") == exit_refused + 1
    assert value("forced_exit", "authorized") == forced_ok + 1
    assert value("forced_exit", "refused") == forced_missed + 1


def test_lectures_de_metrics_hors_du_journal_courant():
    assert _access_log_level("GET", "/metrics", 200) == logging.DEBUG
    assert _access_log_level("GET", "/metrics", 500) == logging.WARNING
