from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_app_status(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "InferX Test")
    monkeypatch.setenv("ENVIRONMENT", "test")

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "InferX Test",
        "environment": "test",
    }


def test_provider_health_endpoint_reports_no_configured_providers_in_phase_1() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/v1/providers/health")

    assert response.status_code == 200
    assert response.json() == {
        "providers": {},
        "circuits": {},
        "configured_count": 0,
    }
