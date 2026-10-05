# Sequential backtest implementation plan

**Contract:** ../LLM_TRADING_AGENT_BACKTEST_SPEC.md (all 32 sections).
**Goal:** Test incremental LLM performance against identical statistical, risk,
execution and cost inputs, using historical data only.
**Architecture:** Independent standard-library Python components for validated
bars, causal snapshots, strategies, deterministic risk, fills, accounting,
evaluation, storage and reporting. No broker adapters or network calls.
**Execution:** Implement in the user-specified empty project directory, sequentially.
No Git repository exists; no worktree or commits are applicable yet.

## Approved decisions (2026-10-03)
- Require explicit open_time and close_time for each bar; timestamp means close_time.
- A decision can fill at the next bar open, including an open equal to the preceding close.
- Stop-first if both stop and target touch within one OHLC bar.
- Every entry requires a positive stop distance. Risk limits may reject it.

## Implementation boundaries
- Explicit timezone-aware timestamps; normalize to UTC without sorting/repairing data.
- An explicit expected-bar schedule defines eligibility and completeness per instrument.
  Calendar adapters may later construct it; do not infer holiday/session rules.
- Costs, tick, quantity increment, daily timezone and annualization require configuration.
- One instrument/position per run in V1; portfolio comparison aggregates separate runs.
- Long/short positions use signed quantities and mark-to-market cash accounting.
- Risk percentages use percent units (0.50 means 0.5%, not 50%).
- HOLD preserves position, CLOSE exits; repeat entry rejected; reverse requires CLOSE first.
- Stops/targets are resting simulated orders, with gaps filled at open plus adverse costs.
- Close-observed kill switches liquidate at the next eligible open, never retroactively.
- Open positions remain marked at final close; final signals expire, never invent a fill.
- Annualized metrics need supplied sampling rate; undefined metrics are null, never infinity.
- All sample bars live in tests and are explicitly synthetic; no research dataset is created.

## Tasks / phase gates
1. [x] Data schema/validation, expected schedule, dataset fingerprint.
   Test bad OHLC, duplicates, naive/overlapping intervals, missing bars, null volume,
   timezone normalization, metadata and fingerprint changes before implementation.
2. [x] Portfolio, adverse costs/tick rounding, risk and event loop.
   Test long/short round trips, next-open isolation, gaps, simultaneous stop/target,
   exposure/risk/cash limits, repeated/invalid actions, daily/DD kill switches,
   horizon exit and outstanding end-of-data positions.
3. [x] Metrics, immutable run artifacts and Phase 1 CLI.
   Test hand-calculated drawdown/return/cost/P&L and reproducibility; no P&L accepted
   until Phase 1 tests pass.
4. [x] Phase 2 causal statistical features with mathematical feature catalogue.
   Test prefix/future-perturbation invariance, unavailable daily bars, zero variance,
   missing volume and warmup explicitly.
5. [x] Phase 3 implementation: B0-B4 and >=100 independently seeded random agents, same engine.
   Test deterministic decisions, identical seeds, benchmark consistency and artifacts.
   Historical benchmark reports are a required gate before LLM evaluation.
   **Historical gate pending user data/calendar/cost choices; tests use fixtures only.**
6. [ ] Phase 4 provider-neutral strict LLM interface, prompts, cache and audit.
7. [ ] Phase 5 blindfolding and identifying-field leakage tests.
8. [ ] Phase 6 walk-forward and protected holdout.
9. [ ] Phase 7 paired Stats-only vs Stats+LLM comparison, uncertainty and ablations.
10. [ ] Phase 8 HTML + machine-readable reports.
11. [ ] Phase 9 deferred: paper only after evidence gates and separate authorization.

## Decisions still reserved for the user
Historical source/datasets and corporate actions; instruments and session calendars;
research periods/final holdout; realistic per-instrument costs/short financing;
LLM provider/model/parameters/budget/retry policy and permitted cache storage.
Stop when a phase depends on these decisions. Do not present fixture tests as alpha.

## Verification
Run `python -m pytest -q` after each task gate. CLI integration uses test-owned
synthetic CSVs, checks immutable artifacts and reproduces trades/metrics.
Track evidence and outstanding contract requirements in progress.md.
