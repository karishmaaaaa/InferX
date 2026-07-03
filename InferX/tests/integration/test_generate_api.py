from fastapi.testclient import TestClient

from app.api.v1.inference import get_request_queue
from app.main import create_app
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.auth import AuthenticatedAccount, require_api_key


class FakeQueue:
    async def submit(
        self,
        request: InferenceRequest,
        account: AuthenticatedAccount,
    ) -> InferenceResponse:
        return InferenceResponse(
            provider="test",
            model=request.model,
            output=f"{account.tier}:{request.prompt}",
        )


def test_generate_endpoint_uses_authenticated_priority_queue() -> None:
    app = create_app()
    app.dependency_overrides[require_api_key] = lambda: AuthenticatedAccount(
        user_id="user-id",
        api_key_id="key-id",
        tier="premium",
        key_prefix="test",
    )
    app.dependency_overrides[get_request_queue] = lambda: FakeQueue()

    with TestClient(app) as client:
        response = client.post(
            "/v1/generate",
            headers={"X-API-Key": "unused-by-override"},
            json={"prompt": "hello", "model": "unit-test-model"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "test",
        "model": "unit-test-model",
        "output": "premium:hello",
    }
