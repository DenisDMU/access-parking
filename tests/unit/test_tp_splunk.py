"""TP Splunk (`tp/splunk`) — l'image ne doit contenir aucun mot de passe, et
l'interface ne doit s'ouvrir que sur l'ordinateur local."""

from __future__ import annotations

from pathlib import Path

TP = Path(__file__).resolve().parents[2] / "tp" / "splunk"


def test_dockerfile_du_tp_sans_mot_de_passe():
    lines = [line.strip() for line in (TP / "Dockerfile").read_text().splitlines() if line.strip()]
    assert lines == [
        "FROM splunk/splunk:latest",
        "ENV SPLUNK_START_ARGS=--accept-license",
        "ENV SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com",
        "ENV SPLUNK_LICENSE_URI=Free",
        "EXPOSE 8000",
    ]
    assert "PASSWORD" not in (TP / "Dockerfile").read_text().upper()


def test_demarrage_local_et_mot_de_passe_saisi():
    script = (TP / "demarrer.sh").read_text()
    assert "-p 127.0.0.1:8000:8000" in script  # jamais ouvert sur le réseau
    assert "read -r -s" in script  # saisi au clavier, sans écho
    assert "-e SPLUNK_PASSWORD " in script  # lu dans l'environnement, pas en clair
    assert "SPLUNK_PASSWORD=" not in script.replace("SPLUNK_PASSWORD=<", "")
    for doc in (TP / "README.md", TP / "demarrer.sh", TP / "arreter.sh"):
        assert "MotDePasse" not in doc.read_text()
