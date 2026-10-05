# Sequential implementation ledger

Contract read completely. User approved explicit open/close timestamps,
stop-first ambiguity policy and required stop distance on 2026-10-03.
Existing directory was empty and is not a Git repository.
Python 3.13.5 and pytest 9.1.1 available. Global pandas cannot import due to
missing pytz; use standard library for the historical deterministic core.

Phase 1 core gate: 43 tests passed (`python -m pytest -q`). Covers validation,
event sequencing, signed cash accounting, costs, stops/gaps, risk limits,
kill switches, horizons, close-sampled metrics and immutable run artifacts.
The future-perturbation test compares finalized inputs; execution-time sizing
is intentionally revalidated after a gap and logged separately.
Phase 2 causal statistical engine gate: 51 tests passed after implementing
the feature catalogue, future-perturbation/scale-invariance tests and completed
daily-bar isolation. No future fit/normalization is performed.

Phase 3 implementation gate: 57 tests passed including the full B0-B4 suite,
100 independent random seeds with 104 individually audited runs, CLI validation,
replay and report generation. All use synthetic test fixtures, not market data.

Independent read-only review (requesting-code-review skill) found four issues:
entry costs could cross stops and cause unattainable prices; open exits overstated
held bars; rejected NaN decision fields could not be serialized; higher context
could have the wrong asset. Regression tests reproduced all four before fixes.
Final fixes add immediate open stop fills with both-side friction-aware sizing,
correct held-bar/elapsed-time accounting, explicit NONFINITE audit evidence and
asset consistency. Daily resets, trailing timing, short costs and future-modified
regime decisions have additional tests.

Source archives and fingerprints supplement the null Git commit; replay detects
changed code. Volatility-derived deterministic stop sizing is configurable and
waits for causal warmup; fixed/target/horizon/trailing/statistical exits remain
combinable. Research parameters are explicit rather than selected as optimal.

Phase 3 historical benchmark gate is blocked pending the user's selected source,
instrument, calendar/schedule, adjustment/financing policy, costs, capital and
research thresholds. Phase 4 has not started. Stats-only vs Stats+LLM, blindfolding,
walk-forward/holdout, bootstrap/ablations and full research reporting are pending
and mandatory. No alpha claim, holdout inspection, network call or trading connection.

Final verification: `python -m pytest -q` — 71 passed in 14.51 seconds.
CLI help works. Unconfigured base.json fails explicitly with `configure 'source'
explicitly`; it cannot generate a research result using invented inputs.
The project copy of the contract matches the downloaded original SHA-256:
BFB776546853F1AE8374747A96F5FD708A38F216B1D7B46AC5EFAF40FD95F636.

## Windows virtualenv/test permissions fix

User reported 37 failures, 27 passes and 7 permission errors. Reproduced the
virtualenv failure: tzdata was absent, so Windows ZoneInfo could not resolve UTC
or America/New_York. The original successful verification had used the global
Conda interpreter, which already included timezone data. Also inspected the
shared OS pytest temp root: owner CodexSandboxOffline, with only OWNER RIGHTS,
SYSTEM and Administrators access. The normal Acer account could not use it.

Added a Windows-specific tzdata runtime dependency and refreshed the existing
project virtualenv. Added tests/conftest.py to create the ordinary-permission
project-local .test-tmp parent and choose a unique session UUID as basetemp.
Explicit caller basetemp is preserved. Disabled pytest's shared cache so its
old sandbox-owned cache cannot cause normal-account write warnings. No ACL
changes, deletion of shared temp directories, trading changes or skipped
financial tests. Regression tests covered named-local-day resets and project-
local writable temp paths; both failed before their respective setup fixes.

Verification under normal Windows Acer account using .venv/Scripts/python.exe:
`-m pytest -q` — 73 passed in 16.59 seconds, no warnings.
`-m pip check` — No broken requirements found.
The .test-tmp parent inherits project permissions for Acer and sandbox users;
session UUIDs avoid reusing either account's private test directories.
No research data, broker connection or LLM API calls authorized/configured.

## Approved Yahoo ingestion

User selected SPY/QQQ/GLD and approved maximum hourly history plus daily context.
Added optional historical Yahoo ingestion with exact raw-response capture,
hash manifests, independent session calendars, completed-bar availability and
create-only exports. Downloaded all six source datasets; no broker connection.
Daily data validates. Hourly has 15 null bars for SPY/GLD and 14 for QQQ;
validation blocks all three. See yahoo-data-quality.md for observed evidence
and the required user decision. No imputation or silent sample reduction.
Per-asset research configs preserve unset costs/capital/strategy inputs.
Full virtualenv verification: 89 passed in 19.18 seconds.
Historical deterministic research and Stats-only vs Stats+LLM remain pending.

## Approved daily decision timeframe

User approved switching SPY, QQQ and GLD from hourly to daily decisions.
Created config/research-SPY.json, research-QQQ.json and research-GLD.json
against the preserved validated daily exports. config/research.json is the SPY
entry point so the user's existing command works. No higher timeframe is
configured: the former daily context is now the decision dataset.
Raw captures and earlier hourly configurations remain archived unchanged.
Fresh CLI validation passed for all three: SPY 8477, QQQ 6935, GLD 5502 bars,
with zero errors, missing bars or unexpected bars. Daily decisions retain the
completed-session-close / next-session-open execution contract.
Capital, costs, annualization, corporate-action accounting, strategy thresholds,
research windows and final holdout require decisions before benchmark execution.
No benchmark scores or LLM comparison results have been produced.

## Approved research assumptions, accounting decision pending

Recorded user-approved scalar assumptions in all four daily research configs;
see approved-research-settings.md for exact values and protected date ranges.
Inspection found dividend records lack payment dates. Recognition/cash timing
cannot be invented. Minimum tick also was absent from the proposal and remains
unset. No benchmark execution, accounting change or holdout scoring occurred.

## Approved dividend timing and daily development implementation

User approved obtaining payment dates and a $0.01 simulated tick. Implemented
ex-date entitlement before fills, signed receivables in equity, payment-date
close cash settlement, closed-trade dividend attribution and archived event
ledger/input bytes. No automatic reinvestment. Up to 50 earlier sessions supply
features only; no warmup trade/score/risk initialization. Research datasets are
sliced through 2014 before engine execution, with a holdout boundary check.
This is the development boundary, not the complete Phase 6 walk-forward runner.
Implemented approved 24-session momentum and explicit long-only strategy exits.

State Street's archived issuer workbook verifies all 40 SPY development
distribution dates. GLD has none; neither has a scored-period split. QQQ has
two unresolved Yahoo events, 2010-06-25 and 2011-12-27, and is blocked before
engine invocation. See dividend-source-quality.md; no event was discarded.

Fresh-context review found missing research/source provenance in stored runs.
Fixed by archiving complete research config, source hashes/coverage and exact
dividend input bytes; regression checked hashes and replay. Reviewer confirmed.
The first SPY benchmark finished all simulations but hit datetime JSON report
serialization. Reproduced with a failing test and fixed the renderer. Recovered
its report from saved comparisons after checking all 104 immutable run hashes.
Replayed its statistical run using archived source (current reporting code had
changed); identical. Replayed 2x-cost statistical and random runs; identical.

Final code suite: 105 passed in 19.25s. SPY's three 104-agent development batches
are complete. GLD's three batches are running. QQQ and Phase 4 LLM configuration
remain blocked/pending. No walk-forward, holdout or Stats+LLM scores produced.

Final batch verification: all six SPY/GLD cost batches complete, 624 simulations
including 600 seeded random runs. Each batch has four deterministic controls,
100 distinct random seeds, 104 immutable run metadata files, an HTML report,
no INCOMPLETE marker and an archived scoring end in 2014. GLD 1x statistical
replay is identical too. Consolidated results: development-benchmarks.md.
QQQ remains blocked, so the full three-asset historical gate is not complete.
No Phase 4-8 research gate or primary LLM comparison is marked achieved.

## Phase 4 model selection (2026-10-04)

User selected OpenAI GPT-4o mini (`gpt-4o-mini`). Recorded in the approved
research settings; provider integration remains unimplemented. No paid API
requests or live trading connections occurred. The user subsequently approved
the $10 initial experiment API cap and SPY/GLD first while QQQ stays blocked.
Prepared a reviewable Phase 4 design; integration and paid execution remain
pending its remaining experimental settings. No research gate is marked passed.

## Phase 4 offline integration gate (2026-10-04)

User approved the design and native implementation plan. Implemented strict
provider-neutral decisions, GPT-4o mini HTTPS adapter, versioned allowlisted
blindfolded prompts, primary/journal/E1 variants, shared persistent $10 ledger,
exact-request cache, immutable paid-request audit and offline response replay.
Inputs/config/source/prompt are archived before the first paid call. Invalid
outputs produce HOLD; authentication/quota and budget/usage errors stop an
incomplete run. Fixed 3% stop and null horizon are enforced by code.

Phase 5 payload leakage coverage includes identity/string allowlisting,
scale-invariance, future perturbation, incomplete higher bars and future journal
rejection. Existing core anti-lookahead and >=100 seeded benchmark tests passed.
Read-only fresh review found important malformed-output, stop, quota, ledger-path,
interruption and scope issues; all were reproduced and fixed with regressions.
Final suite: 152 passed in 24.79 seconds, no warnings. See phase4-execution-ledger.md.

SPY/GLD full data validation still passes. Offline fake-provider historical
journal integration exercised 20 decisions plus one pending-execution session
for each asset, January 2005, with no network requests. Initial real pilots
require the explicit CLI flag and a locally configured OPENAI_API_KEY.
Actual OpenAI compatibility/access/usage remains unverified by paid calls.
The real project ledger is untouched: $0 spent/reserved, $10 available.

No real LLM performance, full paired Stats-only/Stats+LLM comparison, annual
walk-forward or final holdout result is claimed. Those sequential research gates
remain mandatory. QQQ remains blocked and no live trading adapter exists.
