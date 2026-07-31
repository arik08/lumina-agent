# Lumina Backend Harness

This task bank turns existing deterministic backend contracts into a repeatable
regression gate for harness changes. It keeps seven failure taxonomies separate:
prompt caching, provider resilience, worker recovery, context efficiency, and
event-loop isolation, plus capacity/streaming and storage efficiency behavior.

Run all suites three times:

```powershell
uv run --project apps/server python devtools/run_backend_harness.py
```

Run one taxonomy while iterating:

```powershell
uv run --project apps/server python devtools/run_backend_harness.py --suite cache-contract --trials 1
```

Compare a candidate with a previously saved report:

```powershell
uv run --project apps/server python devtools/run_backend_harness.py --baseline .lumina-harness/backend-harness-BASELINE.json
```

The command fails when any trial fails. With `--baseline`, it also fails when a
suite's median wall time grows by more than 30% and at least 0.5 seconds. Runtime
reports are local evidence and are intentionally ignored by Git. A single trial
is terminated after 180 seconds by default; use `--trial-timeout-seconds` only
for a deliberately longer scenario.

## Measurement contract

- Reliability is a 100% pass rate across every selected deterministic case and
  trial. A timeout, skip, empty JUnit result, process error, or assertion failure
  fails the suite.
- Harness latency is reported as median and p95 wall time per taxonomy. Compare
  performance only on equivalent OS, Python, and hardware profiles; every report
  records those fields. The default regression gate requires both a greater than
  30% median increase and at least 0.5 seconds, which filters startup noise. A
  changed case set or execution environment is reported as comparison-skipped
  instead of being mislabeled as a performance regression.
- Queue capacity is guarded by a 5,000-Run identical-timestamp claim case with a
  two-second ceiling. Event-loop isolation uses heartbeat probes while report
  validation and Python calculation perform blocking work.
- Cache efficiency is measured separately for first and subsequent model calls:
  cache-read, cache-write, uncached-input, system-prompt, tool-schema, and total
  static-prefix tokens. Do not claim a cost win from cache-read ratio alone.
- Model latency uses first-call and subsequent-call Provider TTFT, first visible
  text, and full-turn duration p50/p95. Keep Provider/network measurements
  separate from deterministic harness wall time.
- Runtime resource safety is guarded by bounded broker state, durable streaming
  checkpoints, control-poll caching, bounded MCP connections, and a
  hardware-adaptive 1-4 slot limit for heavy render/validation/calculation and
  Python subprocess work.
- Storage efficiency verifies SQLite and PostgreSQL migration contracts while
  retaining composite lookup coverage and removing duplicate write indexes.
- Reports include the Git revision, dirty-state flag, and a SHA-256 fingerprint
  of relevant tracked diffs and untracked source. This identifies the exact
  candidate without copying source code or secrets into the report.

These deterministic gates catch regressions; they do not replace a sealed live
model task bank. Model-quality, real Provider TTFT, token cost, and end-to-end
task success must be compared on held-out tasks before prompt or tool-surface
changes are promoted.
