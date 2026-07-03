import time
from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


@dataclass
class CircuitSnapshot:
    provider: str
    state: CircuitState
    failure_count: int
    opened_at: float | None


class CircuitBreaker:
    def __init__(self, provider: str, failure_threshold: int, cooldown_seconds: float) -> None:
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = CircuitState.closed
        self.failure_count = 0
        self.opened_at: float | None = None

    def allow_request(self) -> bool:
        if self.state == CircuitState.closed:
            return True

        if self.state == CircuitState.half_open:
            return True

        if self.opened_at is None:
            return False

        if time.monotonic() - self.opened_at >= self.cooldown_seconds:
            self.state = CircuitState.half_open
            return True

        return False

    def record_success(self) -> None:
        self.state = CircuitState.closed
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.state == CircuitState.half_open or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.open
            self.opened_at = time.monotonic()

    def mark_open(self) -> None:
        self.state = CircuitState.open
        self.opened_at = time.monotonic()

    def snapshot(self) -> CircuitSnapshot:
        return CircuitSnapshot(
            provider=self.provider,
            state=self.state,
            failure_count=self.failure_count,
            opened_at=self.opened_at,
        )
