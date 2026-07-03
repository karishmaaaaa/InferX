from fastapi.testclient import TestClient

from app.main import create_app


def test_dashboard_page_contains_live_polling_targets() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "InferX Live Ops" in response.text
    assert "fetch('/v1/analytics?window_seconds=300'" in response.text
    assert "fetch('/metrics'" in response.text
