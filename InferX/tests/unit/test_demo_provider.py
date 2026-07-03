import asyncio

import pytest

from app.providers.adapters.dev import DevEchoProvider
from app.schemas.inference import InferenceRequest
from app.schemas.providers import ProviderStatus


@pytest.mark.asyncio
async def test_dev_provider_forced_down_reports_unhealthy_and_times_out() -> None:
    provider = DevEchoProvider(name="dev_demo")
    provider.set_forced_down(True)

    health = await provider.health_check()

    assert health.status == ProviderStatus.unhealthy
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            provider.generate(InferenceRequest(prompt="hello", model="demo")),
            timeout=0.01,
        )


@pytest.mark.asyncio
async def test_dev_provider_streams_word_chunks_when_healthy() -> None:
    provider = DevEchoProvider(name="dev_demo", stream_chunk_delay_ms=0)

    stream = await provider.stream(InferenceRequest(prompt="hello world", model="demo"))
    chunks = [chunk async for chunk in stream]

    assert chunks[0].provider == "dev_demo"
    assert chunks[0].delta == "[dev_demo] "
    assert chunks[-1].done is True
