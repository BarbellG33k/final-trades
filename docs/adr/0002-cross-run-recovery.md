# ADR-0002: Cross-run recovery instead of retries

Date: 2026-10-25 · Status: accepted · Refs: DECISIONS D-008

## Context

Sources are third-party sites that fail transiently (bot walls, outages,
markup changes) and historical gaps are inevitable. Naive fixes (retry
loops, rerun buttons, queues with DLQs) add cost, complexity, and abuse
surface (public trigger endpoints).

## Decision

Failures are **recorded, never retried in-run**. One bounded attempt per
(source, date) unit per scheduled run. Durable state
(`date_processing_status` + URL-keyed `issues`) forms the backlog; every
subsequent scheduled run reserves capacity for current-day work and spends
the remainder oldest-first on the backlog. No public or UI-initiated
re-execution exists; operators have a CLI/dispatch backfill.

## Consequences

- Predictable cost and source load (bounded fetches/run, ≥2s politeness).
- The backlog table IS the queue — no broker, no DLQ, nothing to lose state.
- Failure history is a first-class product feature (attempt counts,
  first/last occurrence, resolution timestamps).
- Trade-off: recovery latency = next schedule slot (hours), not seconds.
  Accepted: the data is historical by nature.
- Cloud Run Jobs `maxRetries: 0` and workflow `continue-on-error` encode
  this at the infrastructure level too.

## Alternatives rejected

In-run exponential retries (retry storms against bot walls; hides systemic
blocks); task queue (Celery/SQS — infra cost & complexity at $0 budget);
public "retry" button (abuse vector + violates read-only requirement).
