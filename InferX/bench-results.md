# InferX Phase 2 Benchmark Results

Date: 2026-07-02

## Setup

- Command path: Docker Compose stack with API, Redis, PostgreSQL, Prometheus, and Locust.
- Endpoint: `POST /v1/generate`
- Provider: `dev_echo`, enabled only for local gateway benchmarking.
- Provider latency setting: `DEV_PROVIDER_LATENCY_MS=2`
- API container settings:
  - `REQUEST_QUEUE_WORKERS=16`
  - `REQUEST_QUEUE_MAX_SIZE=2000`
  - `USAGE_WRITER_WORKERS=8`
  - `DATABASE_POOL_SIZE=40`
  - `DATABASE_MAX_OVERFLOW=80`
- Load profile: Locust burst stages at 100, 500, and 1000 concurrent users.
- Run time: 20 seconds per stage.
- Prompt mix: 8 repeated operational prompts from `load-tests/locustfile.py`.
- API keys: local free and premium keys bootstrapped by Compose for benchmark only.

This benchmark measures gateway overhead and queue/cache behavior, not real LLM provider latency or output quality.

## Results

| Concurrent users | Requests | Failures | Req/s | P50 | P95 | P99 | Max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 12,675 | 0 | 666.01 | 100 ms | 180 ms | 260 ms | 870 ms |
| 500 | 10,164 | 0 | 533.80 | 1000 ms | 1600 ms | 2800 ms | 4200 ms |
| 1000 | 8,093 | 0 | 410.95 | 1800 ms | 6300 ms | 10000 ms | 12000 ms |

Source files:

- `load-tests/results/inferx_100_stats.csv`
- `load-tests/results/inferx_500_stats.csv`
- `load-tests/results/inferx_1000_stats.csv`

## Cache And Usage

Post-benchmark usage rows persisted in PostgreSQL:

| Cache tier | Rows |
|---|---:|
| exact | 33,576 |
| miss | 16 |

Prometheus scrape status for `inferx-api`: `up == 1`.

## Observations

- The gateway has no request failures through 1000 concurrent users after moving usage writes off the request path.
- P99 rises sharply once concurrency exceeds available queue workers and one API container becomes saturated.
- The benchmark prompt set is intentionally repetitive, so exact cache hit rate is high.
- The local `dev_echo` provider avoids external network and model latency; real providers would dominate tail latency.

## P99 Improvements For Production

- Run multiple API replicas behind a load balancer and scale on queue depth plus P95/P99 latency.
- Batch usage inserts or push usage events to Kafka/Redis Streams before PostgreSQL persistence.
- Cache API-key auth in Redis with short TTL and revoke-list checks to avoid per-request database pressure.
- Split priority queues by tier with reserved premium worker capacity, not just priority ordering in one queue.
- Add adaptive concurrency limits per provider so one slow provider cannot fill all gateway workers.
- Use hedged requests for latency-sensitive premium traffic after a configurable provider latency percentile.
