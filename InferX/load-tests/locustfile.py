import os
import random

from locust import HttpUser, between, task

FREE_API_KEY = os.getenv("INFERX_FREE_API_KEY", "inferx-free-local")
PREMIUM_API_KEY = os.getenv("INFERX_PREMIUM_API_KEY", "inferx-premium-local")

PROMPTS = [
    "Summarize the latest invoice payment status for account alpha.",
    "Classify this support ticket as billing, outage, or product feedback.",
    "Draft a concise incident update for a delayed inference provider.",
    "Extract action items from a short customer success call transcript.",
    "Rewrite this notification in a professional support tone.",
    "Generate a one paragraph explanation of cache hit rate.",
    "Identify likely root causes for elevated P99 latency.",
    "Create a short response for a rate limit exceeded error.",
]


class InferXUser(HttpUser):
    wait_time = between(0.01, 0.05)

    @task(7)
    def free_tier_generate(self) -> None:
        self._generate(FREE_API_KEY)

    @task(3)
    def premium_tier_generate(self) -> None:
        self._generate(PREMIUM_API_KEY)

    def _generate(self, api_key: str) -> None:
        prompt = random.choice(PROMPTS)
        self.client.post(
            "/v1/generate",
            headers={"X-API-Key": api_key},
            json={
                "prompt": prompt,
                "model": "dev-gateway-benchmark",
                "temperature": 0.2,
                "max_tokens": 80,
            },
            name="/v1/generate",
        )
