# InferX Roadmap

This document captures the next engineering steps without claiming they are implemented in the current repository.

## Kafka or Redis Streams for Usage Events

Current state: usage records are written by an in-process async writer into PostgreSQL.

Next design:

- emit usage events to Kafka or Redis Streams before analytical persistence;
- acknowledge request completion independently from downstream analytics writes;
- batch inserts into PostgreSQL or ClickHouse;
- support replay after schema changes;
- include idempotency keys so retried writes do not duplicate billable events.

Why it matters: the gateway should not lose usage data under database backpressure, and request latency should not depend on analytical write availability.

## ClickHouse for Analytics

Current state: dashboard and cost analytics read from PostgreSQL `usage_records`.

Next design:

- keep PostgreSQL as the transactional source for users, keys, and recent usage;
- stream usage events into ClickHouse for high-cardinality provider/model/cache analytics;
- pre-aggregate dashboard windows by provider, model, account tier, and cache tier;
- retain raw events for audit windows and downsample older data.

Why it matters: cost, latency, cache, and provider-split dashboards become expensive in PostgreSQL as request volume grows.

## Kubernetes Deployment Model

Current state: Docker Compose runs one API container, Redis, PostgreSQL, Prometheus, and an optional Locust profile.

Next design:

- deploy multiple API replicas behind a service/load balancer;
- run Redis and PostgreSQL as managed services or StatefulSets depending on environment;
- add readiness probes for provider registry and database connectivity;
- scale API replicas on queue depth, request latency, and CPU;
- expose Prometheus metrics with service discovery;
- roll configuration changes through ConfigMaps/Secrets with safe restarts.

Why it matters: the current benchmark saturates one API container at high concurrency; production traffic needs horizontal scaling.

## Predictive Routing

Current state: providers are scored from recent latency, error rate, health, circuit state, and known cost.

Next design:

- add per-provider adaptive concurrency limits;
- incorporate score trends, not only current-window observations;
- detect increasing tail latency before failures begin;
- support hedged requests for latency-sensitive premium traffic;
- separate cost-sensitive and latency-sensitive routing policies.

Why it matters: reactive scoring avoids known-bad providers; predictive routing should reduce exposure before a provider becomes unhealthy.

## Multi-Region Routing

Current state: provider scoring is process-local and region-unaware.

Next design:

- track provider health per deployment region;
- route by customer region, provider latency, data residency rules, and availability;
- replicate score snapshots through a control plane or metrics pipeline;
- keep local fallback behavior when cross-region control data is stale.

Why it matters: provider availability and latency vary by region, and some customers cannot route prompts across every geography.

## Typed Client SDK

Current state: callers use raw HTTP.

Next design:

- ship Python and TypeScript clients;
- include typed request/response models matching `app/schemas`;
- provide helpers for streaming SSE responses;
- expose request IDs and retry-safe errors;
- keep auth handling explicit through API-key configuration.

Why it matters: an SDK reduces copy-pasted HTTP code and makes gateway semantics easier to adopt without hiding operational errors.
