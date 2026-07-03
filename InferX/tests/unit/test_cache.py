import pytest

from app.cache.embedding import HashingEmbedder, cosine_similarity
from app.cache.redis_cache import SemanticCache
from app.core.config import Settings
from app.schemas.inference import InferenceRequest, InferenceResponse


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        _ = ex
        self.values[key] = value

    async def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])
        return values[start : end + 1]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    async def expire(self, key: str, seconds: int) -> None:
        _ = key, seconds


def test_hashing_embedder_cosine_similarity_for_identical_text() -> None:
    embedder = HashingEmbedder(dimensions=64)
    vector = embedder.embed("cache hit rate")

    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


async def test_semantic_cache_returns_exact_hit() -> None:
    cache = SemanticCache(
        redis=FakeRedis(),
        settings=Settings(
            semantic_cache_threshold=0.5,
            semantic_embedding_dimensions=64,
        ),
    )
    request = InferenceRequest(prompt="explain cache hit rate", model="test-model")
    response = InferenceResponse(provider="test", model="test-model", output="cached")

    await cache.set(request, response)
    hit = await cache.get(request)

    assert hit is not None
    assert hit.tier == "exact"
    assert hit.response == response


async def test_semantic_cache_returns_similarity_hit() -> None:
    cache = SemanticCache(
        redis=FakeRedis(),
        settings=Settings(
            semantic_cache_threshold=0.35,
            semantic_embedding_dimensions=64,
        ),
    )
    response = InferenceResponse(provider="test", model="test-model", output="cached")
    await cache.set(
        InferenceRequest(prompt="summarize provider latency", model="test-model"),
        response,
    )

    hit = await cache.get(
        InferenceRequest(prompt="summarize provider latency please", model="test-model")
    )

    assert hit is not None
    assert hit.tier == "semantic"
    assert hit.response == response
