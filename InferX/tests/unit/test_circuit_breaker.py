from app.routing.circuit_breaker import CircuitBreaker, CircuitState


def test_circuit_opens_after_failure_threshold() -> None:
    circuit = CircuitBreaker(provider="test", failure_threshold=2, cooldown_seconds=60)

    circuit.record_failure()
    assert circuit.snapshot().state == CircuitState.closed

    circuit.record_failure()
    assert circuit.snapshot().state == CircuitState.open
    assert circuit.allow_request() is False


def test_circuit_half_opens_after_cooldown(monkeypatch) -> None:
    circuit = CircuitBreaker(provider="test", failure_threshold=1, cooldown_seconds=10)
    monkeypatch.setattr("app.routing.circuit_breaker.time.monotonic", lambda: 100.0)
    circuit.record_failure()

    monkeypatch.setattr("app.routing.circuit_breaker.time.monotonic", lambda: 111.0)

    assert circuit.allow_request() is True
    assert circuit.snapshot().state == CircuitState.half_open


def test_circuit_closes_on_success() -> None:
    circuit = CircuitBreaker(provider="test", failure_threshold=1, cooldown_seconds=60)
    circuit.record_failure()

    circuit.record_success()

    assert circuit.snapshot().state == CircuitState.closed
    assert circuit.snapshot().failure_count == 0
