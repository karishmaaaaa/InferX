from collections.abc import AsyncIterator

import httpx

from app.providers.base import Provider
from app.schemas.inference import InferenceRequest, InferenceResponse, StreamChunk, StreamResult
from app.schemas.providers import ProviderHealth, ProviderStatus


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        payload = {
            "model": request.model,
            "prompt": request.prompt,
            "stream": False,
        }
        if request.temperature is not None or request.max_tokens is not None:
            payload["options"] = {}
            if request.temperature is not None:
                payload["options"]["temperature"] = request.temperature
            if request.max_tokens is not None:
                payload["options"]["num_predict"] = request.max_tokens

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

        return InferenceResponse(
            provider=self.name,
            model=request.model,
            output=data.get("response", ""),
        )

    async def stream(self, request: InferenceRequest) -> StreamResult:
        async def chunks() -> AsyncIterator[StreamChunk]:
            response = await self.generate(request)
            yield StreamChunk(
                provider=self.name,
                model=request.model,
                delta=response.output,
                done=True,
            )

        return chunks()

    async def health_check(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
        except Exception as exc:
            return ProviderHealth(
                name=self.name,
                status=ProviderStatus.unhealthy,
                detail=str(exc),
            )

        return ProviderHealth(name=self.name, status=ProviderStatus.healthy)
