import asyncio
from collections.abc import AsyncIterator

from app.providers.base import Provider
from app.schemas.inference import InferenceRequest, InferenceResponse, StreamChunk, StreamResult
from app.schemas.providers import ProviderHealth, ProviderStatus


class DevEchoProvider(Provider):
    def __init__(
        self,
        name: str = "dev_echo",
        latency_ms: int = 0,
        stream_chunk_delay_ms: int = 250,
    ) -> None:
        self.name = name
        self.latency_ms = latency_ms
        self.stream_chunk_delay_ms = stream_chunk_delay_ms
        self._forced_down = False

    def set_forced_down(self, forced_down: bool) -> None:
        self._forced_down = forced_down

    def demo_state(self) -> dict[str, bool | str]:
        return {"provider": self.name, "forced_down": self._forced_down}

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        await self._raise_timeout_if_forced_down()
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)
        return InferenceResponse(
            provider=self.name,
            model=request.model,
            output=f"[{self.name}] {request.prompt}",
        )

    async def stream(self, request: InferenceRequest) -> StreamResult:
        await self._raise_timeout_if_forced_down()

        async def chunks() -> AsyncIterator[StreamChunk]:
            words = f"[{self.name}] {request.prompt}".split()
            for word in words:
                if self.stream_chunk_delay_ms:
                    await asyncio.sleep(self.stream_chunk_delay_ms / 1000)
                yield StreamChunk(
                    provider=self.name,
                    model=request.model,
                    delta=f"{word} ",
                    done=False,
                )
            yield StreamChunk(
                provider=self.name,
                model=request.model,
                delta="",
                done=True,
            )

        return chunks()

    async def health_check(self) -> ProviderHealth:
        if self._forced_down:
            return ProviderHealth(
                name=self.name,
                status=ProviderStatus.unhealthy,
                detail="forced down by demo control endpoint",
            )
        return ProviderHealth(name=self.name, status=ProviderStatus.healthy)

    async def _raise_timeout_if_forced_down(self) -> None:
        if not self._forced_down:
            return
        await asyncio.sleep(3600)
