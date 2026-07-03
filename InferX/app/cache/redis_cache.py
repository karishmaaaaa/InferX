import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.cache.embedding import HashingEmbedder, cosine_similarity
from app.core.config import Settings
from app.schemas.inference import InferenceRequest, InferenceResponse


def create_redis_client(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=True)


@dataclass(frozen=True)
class CacheHit:
    response: InferenceResponse
    tier: str
    similarity: float | None = None


class SemanticCache:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.enabled = settings.semantic_cache_enabled
        self.threshold = settings.semantic_cache_threshold
        self.ttl_seconds = settings.semantic_cache_ttl_seconds
        self.max_entries = settings.semantic_cache_max_entries
        self.embedder = HashingEmbedder(settings.semantic_embedding_dimensions)

    async def get(self, request: InferenceRequest) -> CacheHit | None:
        if not self.enabled:
            return None

        exact_payload = await self.redis.get(self._exact_key(request))
        if exact_payload:
            response = InferenceResponse.model_validate_json(exact_payload)
            return CacheHit(response=response, tier="exact", similarity=1.0)

        embedding = self.embedder.embed(request.prompt)
        best_payload: dict[str, Any] | None = None
        best_similarity = -1.0
        entries = await self.redis.lrange(
            self._semantic_index_key(request),
            0,
            self.max_entries - 1,
        )
        for raw_entry in entries:
            entry = json.loads(raw_entry)
            similarity = cosine_similarity(embedding, entry["embedding"])
            if similarity > best_similarity:
                best_similarity = similarity
                best_payload = entry

        if best_payload is None or best_similarity < self.threshold:
            return None

        response = InferenceResponse.model_validate(best_payload["response"])
        return CacheHit(response=response, tier="semantic", similarity=best_similarity)

    async def set(self, request: InferenceRequest, response: InferenceResponse) -> None:
        if not self.enabled:
            return

        serialized_response = response.model_dump_json()
        await self.redis.set(self._exact_key(request), serialized_response, ex=self.ttl_seconds)

        entry = {
            "created_at": time.time(),
            "request_hash": self._request_hash(request),
            "prompt": request.prompt,
            "embedding": self.embedder.embed(request.prompt),
            "response": response.model_dump(mode="json"),
        }
        await self.redis.lpush(self._semantic_index_key(request), json.dumps(entry))
        await self.redis.ltrim(self._semantic_index_key(request), 0, self.max_entries - 1)
        await self.redis.expire(self._semantic_index_key(request), self.ttl_seconds)

    def _exact_key(self, request: InferenceRequest) -> str:
        return f"inferx:cache:exact:{self._request_hash(request)}"

    def _semantic_index_key(self, request: InferenceRequest) -> str:
        provider = request.provider or "any"
        return f"inferx:cache:semantic:{provider}:{request.model}"

    def _request_hash(self, request: InferenceRequest) -> str:
        payload = {
            "prompt": request.prompt,
            "model": request.model,
            "provider": request.provider,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
