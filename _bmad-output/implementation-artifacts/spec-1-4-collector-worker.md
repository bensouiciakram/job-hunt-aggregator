---
title: 'Story 1.4: Collector worker'
type: 'feature'
created: '2026-08-18'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-3-collection-pipeline.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The collection pipeline exists but nothing runs it on a schedule — a manual `collect_source` call is the only way to gather postings, and the 24-hour freshness window is silently missed whenever the machine was off.

**Approach:** Ship a collector worker process (`uv run python manage.py run_collector`) using APScheduler 3.x (pinned <4) with a 30-minute interval job that polls every registered Source through `collect_source`, runs an initial catch-up pass at startup (backfill after downtime, AD-7), and derives the 24-hour freshness marker from `published_at` (no schema change). Runs as a separate process from the Django server (two-process envelope, AD-2).

## Boundaries & Constraints

**Always:**
- APScheduler 3.x, pinned `<4` (4.0 still alpha per spine).
- Separate process: a management command, started independently of `runserver`; graceful Ctrl+C shutdown.
- Initial pass at startup (backfill semantics): everything the 30-min cadence would have collected while the worker was down is collected on boot; a FetchLog row (stage `'backfill'`, ok=True, error contains the count of stale listings found) records the catch-up. After the startup pass, the 30-minute interval takes over.
- Freshness marker (AD-7) is DERIVED: a Listing is fresh while `published_at >= now - 24h`; the worker logs the stale count at backfill. No schema change — if a persisted marker is ever needed, that is a separate decision.
- Downtime detection: `needs_backfill(last_pass_at, now)` — pure function; backfill when the gap since the last successful pass exceeds the 30-min interval by a factor (>= 2×, i.e. 60 min) OR it is the first-ever pass.
- Per-source failure isolation: `collect_source` already never raises; the worker loop must not abort on any single source (AD-6).
- The worker job logs one `pass` FetchLog (ok=True) per completed cycle, and writes FetchLog rows for failures via `collect_source`'s own logging.
- Test the LOGIC (job function, backfill detection, freshness, isolation), not the scheduler loop itself.

**Ask First:** (none)

**Never:**
- No schema migration, no new models, no real adapters (1.5–1.7), no webhooks/emails/dashboard.
- No double-run guard/locking (document "one worker only" in README instead) — personal single-user tool.
- No changes to `collect_source` or the pipeline.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| POLL_ALL | 3 Sources: 2 stub-OK, 1 fetch-failing | all 3 attempted; 2 collect cleanly; 1 leaves a FetchLog ok=False; job completes without raising | AD-6 per-source isolation |
| FIRST_PASS | no prior pass FetchLog exists | backfill triggered; startup pass runs immediately | n/a |
| GAP_OVERDUE | last pass 3h ago | `needs_backfill` True; backfill pass runs | n/a |
| GAP_FRESH | last pass 10 min ago | `needs_backfill` False; normal interval job | n/a |
| FRESHNESS_CUTOFF | listing published_at = now-2h vs now-30h | fresh vs stale by the 24h cutoff | n/a |
| GRACEFUL_STOP | Ctrl+C in the worker process | scheduler shuts down, process exits 0 | no zombie process |
| INTERVAL_JOB | scheduler running | exactly one 30-min interval job registered | n/a |

</frozen-after-approval>

## Code Map

- `backend/collector/collect.py` -- `collect_source(source)` never raises; the worker's per-source loop is a thin wrapper.
- `backend/listings/models.py` -- `FetchLog {source, stage, ok, error, created_at}`; the pass/backfill bookkeeping lives here.
- `backend/collector/registry.py` -- `get_adapter` (not needed by the worker directly; collect_source handles it).
- `backend/job_hunt_aggregator/settings.py` -- worker reads settings via Django; no new settings unless a schedule constant helps (keep `COLLECTOR_INTERVAL_MINUTES = 30` here as the single source of truth).
- Story 1.3 continuity: `collect_source` signature, FetchLog conventions, stub-adapter test patterns (registry `clear()` in setUp).
- Structural Seed: `backend/collector/worker.py` is the designated home.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/collector/worker.py` -- `needs_backfill(last_pass_at, now)`, `find_stale_count(cutoff)` query helper, `poll_all()` job function (all Sources, per-source isolation, pass FetchLog), `last_pass_at()` (latest ok=True pass FetchLog), `run()` (BlockingScheduler, IntervalTrigger(minutes=COLLECTOR_INTERVAL_MINUTES), startup pass + backfill decision, graceful shutdown) -- AD-7 cadence + AD-2 process envelope
- [ ] `backend/collector/management/__init__.py` + `backend/collector/management/commands/__init__.py` + `backend/collector/management/commands/run_collector.py` -- manage.py command invoking `worker.run()` -- the separate-process entry point
- [ ] `backend/job_hunt_aggregator/settings.py` -- `COLLECTOR_INTERVAL_MINUTES = 30` (single source of truth) -- cadence pin
- [ ] `backend/README.md` -- document starting the worker (`uv run python manage.py run_collector`), the two-process envelope, and "run exactly one worker" -- operator handoff
- [ ] `backend/collector/tests.py` (extend) -- POLL_ALL isolation, FIRST_PASS, GAP_OVERDUE/GAP_FRESH, FRESHNESS_CUTOFF, interval-job registration (scheduler introspection), backfill FetchLog row written with stale count -- matrix audit

**Acceptance Criteria:**
- Given registered Sources, when the collector worker runs (APScheduler 3.x, 30-minute interval), then all Sources are polled with the Keyword Set.
- And after downtime, the next pass backfills missed polls.
- And Listings older than 24 hours at backfill carry a freshness marker (derived from published_at; stale count logged).
- And the worker runs as a separate process from the Django server (two-process envelope, AD-2).

## Spec Change Log

(Append-only; empty until first review loopback.)

## Suggested Review Order

**Lifecycle correctness** — run() startup/backfill/interrupt paths
- Ctrl+C guard (`scheduler.running`), misfire_grace_time, pass/backfill row bookkeeping
  [`worker.py:1`](../../backend/collector/worker.py#L1)

**Dependency manifest** — AD-7 pin enforceable
- [`requirements.txt:1`](../../backend/requirements.txt#L1)

**Tests** — real-scheduler wiring, interrupt-during-startup, GAP_OVERDUE integration, two-cycle sequencing, exact cutoff
  [`tests.py:1`](../../backend/collector/tests.py#L1)

## Design Notes

- **Why BlockingScheduler:** the worker is a dedicated process with one job; BlockingScheduler keeps it alive and handles signals; `wait()` + `shutdown(wait=False)` on KeyboardInterrupt gives clean exits.
- **Backfill = startup pass, not catch-up windowing:** per-source fetches are stateless; re-polling everything on boot IS the backfill. `needs_backfill` decides whether the startup pass also logs a `backfill` row (first pass or gap ≥ 2× interval) vs a plain `pass` row.
- **Freshness derived, not stored:** `published_at >= now - 24h` is the marker; it will surface in Story 1.8's UI. Logging the stale count at backfill keeps the AD-7 intent visible without schema churn.
- **Interval as a setting:** `COLLECTOR_INTERVAL_MINUTES` in settings.py is the single knob; tests import it rather than hardcoding 30.

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: 0 issues
- `uv run python manage.py test` -- expected: all pass
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected"
- Worker smoke: `uv run python manage.py run_collector` for ~10 seconds against a dev DB with a stub-OK source → one pass FetchLog ok=True appears; Ctrl+C exits cleanly (exit 0)
- `uv run python manage.py help run_collector` -- expected: command listed

**Manual checks (if no CLI):**
- `backend/collector/worker.py` contains no `scheduler.start()` at import time (only inside `run()`) — importing the module must never start a scheduler.