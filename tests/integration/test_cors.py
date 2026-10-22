"""Test d'intégration — CORS restreint à la liste blanche."""


def test_cors_origine_non_autorisee(client):
    response = client.get("/health", headers={"Origin": "https://site-malveillant.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_origine_autorisee(client):
    # Origine fixée dans tests/integration/conftest.py
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
