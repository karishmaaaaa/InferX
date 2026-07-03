# InferX Live Failover Demo Runbook

Goal: show a provider failing, its adaptive score dropping, and the next request transparently routing to the highest-scoring healthy provider while metrics, scores, and logs update.

## One-Time Setup

Start the local stack:

```bash
docker compose up --build
```

Use the local premium demo key:

```bash
export INFERX_KEY=inferx-premium-local
```

## Interview Layout

Open one browser tab and four terminal panes:

1. **Browser:** `http://localhost:8000/dashboard`.
2. **Terminal A:** API logs.
3. **Terminal B:** provider/circuit state.
4. **Terminal C:** Prometheus metrics.
5. **Terminal D:** request driver.

## Terminal A: Logs

```bash
docker compose logs -f api | grep -E "demo provider|failover|circuit|demo stream|provider scored|provider score"
```

Say:

> This is the API gateway log stream. I’m filtering to the operational events I’d expect an infra engineer to care about: provider health, adaptive score changes, score-ordered routing, failover, and circuit state.

## Terminal B: Provider State

```bash
watch -n 1 "curl -s -H \"X-API-Key: $INFERX_KEY\" http://localhost:8000/v1/demo/providers | python -m json.tool"
```

Expected initial state:

```json
{
  "providers": {
    "dev_echo": {"provider": "dev_echo", "forced_down": false},
    "dev_backup": {"provider": "dev_backup", "forced_down": false}
  },
  "circuits": {
    "dev_echo": "closed",
    "dev_backup": "closed"
  }
}
```

Say:

> The adaptive router scores healthy providers from recent latency, errors, and known cost. With no recent failures, both dev providers score well and the configured priority breaks the tie, so traffic starts on dev_echo.

## Terminal C: Metrics

```bash
watch -n 1 "curl -s http://localhost:8000/metrics | grep -E 'inferx_provider_requests_total|inferx_provider_score|inferx_failovers_total|inferx_provider_circuit_state|inferx_active_streaming_sessions'"
```

Say:

> These are Prometheus-native metrics, not printed demo counters. The provider score, failover count, circuit gauge, and streaming-session gauge are the production-grade signals behind the dashboard.

Circuit state values:

- `0`: closed
- `1`: open
- `2`: half-open

## Terminal D: Happy-Path Streaming Request

```bash
curl -N -X POST http://localhost:8000/v1/demo/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INFERX_KEY" \
  -d '{"prompt":"stream a short status update about provider routing","model":"demo-stream"}'
```

Expected first event:

```text
event: route
data: {"provider": "dev_echo", "attempted_chain": ["dev_echo"]}
```

Say:

> This is a streaming response. The first server-sent event tells us which provider accepted the stream. Because dev_echo is healthy and wins the current score ordering, it serves the request.

## Kill The Current Provider

Run:

```bash
curl -s -X POST http://localhost:8000/v1/demo/kill-provider \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INFERX_KEY" \
  -d '{"provider":"dev_echo"}' | python -m json.tool
```

Say:

> I’m simulating a provider outage by flipping a runtime flag in the dev adapter. The control endpoint triggers an immediate score refresh, so the router can stop sending new traffic to the failed provider without waiting for the next 60-second scoring tick.

Expected response includes:

```json
{
  "provider": "dev_echo",
  "forced_down": true
}
```

## Send Another Streaming Request

Run:

```bash
curl -N -X POST http://localhost:8000/v1/demo/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INFERX_KEY" \
  -d '{"prompt":"stream another status update after the primary outage","model":"demo-stream"}'
```

Expected first event:

```text
event: route
data: {"provider": "dev_backup", "attempted_chain": ["dev_backup"]}
```

Say:

> The client still gets a normal stream. Internally, dev_echo’s health score dropped to zero, so the score-ordered router selected dev_backup before spending a timeout on the killed provider.

Point to Terminal A:

```text
provider score changed provider=dev_echo score=0.00 ...
provider scored route order provider_order=['dev_backup', 'dev_echo'] scores={'dev_backup': 100.0, 'dev_echo': 0.0}
demo stream opened provider=dev_backup attempted_chain=['dev_backup']
```

Point to Terminal C:

```text
inferx_provider_score{provider="dev_echo"} 0.0
inferx_provider_score{provider="dev_backup"} 100.0
inferx_provider_circuit_state{provider="dev_echo"} 0.0
```

## Show Score-Based Short-Circuiting

Immediately run the same streaming request again:

```bash
curl -N -X POST http://localhost:8000/v1/demo/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INFERX_KEY" \
  -d '{"prompt":"stream one more request while the circuit is open","model":"demo-stream"}'
```

Expected first event:

```text
event: route
data: {"provider": "dev_backup", "attempted_chain": ["dev_backup"]}
```

Say:

> The adaptive score prevents wasting a timeout on dev_echo. The router skips straight to dev_backup, which is why the attempted chain only contains the backup provider. The circuit breaker is still there for unexpected runtime failures; the score lets the gateway avoid known-bad providers proactively.

## Restore The Provider

Run:

```bash
curl -s -X POST http://localhost:8000/v1/demo/restore-provider \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INFERX_KEY" \
  -d '{"provider":"dev_echo"}' | python -m json.tool
```

Say:

> Restoring the provider flips the adapter back to healthy and triggers another score refresh. If a circuit had opened from runtime failures, the background health probe would close it after cooldown once health_check passes.

Watch Terminal A for:

```text
provider score changed provider=dev_echo score=100.00 ...
```

Then run:

```bash
curl -N -X POST http://localhost:8000/v1/demo/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INFERX_KEY" \
  -d '{"prompt":"stream after provider recovery","model":"demo-stream"}'
```

Expected first event:

```text
event: route
data: {"provider": "dev_echo", "attempted_chain": ["dev_echo"]}
```

Say:

> The provider recovered, the circuit closed, the provider score recovered, and traffic returned to the highest-scoring provider automatically.

## Close

Say:

> The important design point is that provider adapters own provider-specific behavior, while the router only depends on the shared Provider interface. Scoring, failover, circuit breaking, logs, and Prometheus metrics are gateway-level concerns, so adding Sarvam, OpenAI, or Gemini does not change the gateway control flow.
