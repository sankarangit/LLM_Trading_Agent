# LLM Trading Agent — historical research

Implementation contract: [LLM_TRADING_AGENT_BACKTEST_SPEC.md](LLM_TRADING_AGENT_BACKTEST_SPEC.md).
This directory implements the deterministic core, causal statistical features,
and required benchmark runner (Phases 1-3). No network client, broker connection,
LLM evaluation or paper/live execution exists.

Historical benchmark validation is pending user-selected data/calendars/costs.
Phases 4-8, including the **Stats-only vs Stats+LLM paired comparison**, are still
required before V1 is complete. A profitable synthetic test proves nothing about alpha.

## Setup and verification

Use Python 3.11 or newer. On Windows, installation includes `tzdata` for named
timezones; the market-data/backtest components otherwise use the standard library.
In PowerShell:

```powershell
Set-Location 'D:\ICICI-NRI-AC\AQ100\LLM_Trading_Agent'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest -q
```

For the existing environment with pytest installed:

```powershell
python -m pytest -q
python main.py --help
```

The suite contains synthetic, test-owned bars only. It runs all deterministic
variants, 100 independently seeded random agents, CLI integration and exact
replay. Tests cover future-price perturbation, rolling scalers, incomplete daily
bars, inaccessible next-bar opens, costs, long/short accounting, gaps, both exit
touches, trailing stops, loss limits and immutable run artifacts.

Tests create a fresh `.test-tmp/session-<UUID>` inside the project on every run.
This avoids permissions inherited from an OS temp directory created by another
Windows account (including Codex's sandbox account). Explicit `--basetemp` is
honored. Pytest's shared cache is disabled; old test artifacts are retained for
diagnostics and can be removed from `.test-tmp` when no tests are running.

If the virtualenv was installed before the Windows dependency fix, refresh it:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest -q
```

## Configure an actual historical run

Copy `config/base.json` to a new JSON configuration. `null` fields that need
research choices deliberately cause failure. Relative file paths resolve from
the configuration's directory. No market data is downloaded or invented.

Required OHLCV CSV columns:

```text
open_time,close_time,open,high,low,close,volume
```

All times must include a UTC offset, for example `2020-01-02T09:30:00-05:00`.
An optional `timestamp` column must equal `close_time`. Volume is blank/null only
when `volume_supported` is explicitly false. No forward fill, sorting, duplicate
removal or volume substitution is performed.

A second, independently supplied schedule CSV requires:

```text
open_time,close_time
```

The schedule must reflect the chosen instrument's actual eligible historical
bars: sessions, holidays, early closes and outages. Do not derive it from the
observed data: that would hide missing bars. Expected and observed intervals
must match exactly. Session irregularities are represented explicitly in this
schedule rather than assuming all instruments trade 24/7.

Document the source and corporate-action treatment, e.g. how adjusted OHLC and
volume relate to splits/dividends. This implementation records the policy; it
does not itself adjust raw data or book dividends. Research cannot proceed on
an undocumented equity/ETF adjustment policy. Declare currency-consistent data,
capital and fees per single-instrument run; no FX conversion is performed.

`higher_data` can be a second object with the same fields as `data`, using actual
daily bar open/close times and its own calendar. It must have the same asset.
The engine exposes only higher bars whose `close_time <= decision_timestamp`.
Higher context is unavailable unless that dataset is explicitly supplied.

Choose initial cash, annualization periods, daily-loss timezone, realistic
commission/slippage/spread, tick and quantity increments, and baseline entry/exit
thresholds. Feature presets are configurable engineering defaults, not optimized
or validated choices. Commission/slippage values from the contract are placeholders;
this template requires actual assumptions instead of quietly using them.
Short borrow charges, financing, dividends and multi-currency valuation require
explicit research treatment before results can be considered realistic.

## Phase 1: validate data and run the core

```powershell
python main.py validate-data --config config/research.json
python main.py backtest --config config/research.json --experiment buy_hold
python main.py replay --run-path runs/<RUN_ID>
python main.py report --run-path runs/<RUN_ID>
```

Run/report paths are printed as JSON. Errors have nonzero exit status and are
written to stderr. `report` creates a derived `report.html` once; it verifies the
run's saved artifact hashes before reading them. Use a fresh output filename
through the Python reporting API if another rendering is needed.

## Phase 2: causal features

`llm_trading.features.snapshot(completed_bars, completed_higher_bars, FeatureConfig)`
returns scale-free features: multi-horizon returns, z-scores/ranks, realized and
downside volatility, skew/kurtosis, OLS trend statistics, trend agreement,
acceleration, autocorrelation, variance ratio, half-life diagnostic, liquidity
features and a deterministic causal regime. All features are Python-calculated.

Each definition, minimum observations, window, normalization and null policy is
in `FEATURE_CATALOGUE` and is exported with benchmark runs. Full windows are
required. Undefined denominators yield `null`, never fabricated zero/inf. The
half-life estimate is a diagnostic, not proof of stationarity. Regime thresholds
are configurable and never fit using future bars. `volume`, `regime` and an
`enabled` feature-name subset support feature toggles.

## Phase 3: deterministic benchmark gate

```powershell
python main.py backtest --config config/research.json --experiment baselines
python main.py backtest --config config/research.json --experiment momentum
python main.py backtest --config config/research.json --experiment mean_reversion
python main.py backtest --config config/research.json --experiment statistical_regime
python main.py backtest --config config/research.json --experiment random
```

`baselines` runs B0, B2, B3, B4 and at least 100 B1 agents using distinct recorded
seeds and identical validated bars, snapshots, risk, costs and execution.

- **B0:** one initial LONG request, then HOLD. Stops and shared risk limits apply;
  this is risk-constrained passive exposure, not a separate full-capital return.
- **B1:** uniform LONG/SHORT/HOLD/CLOSE requests from an independent `random.Random`
  instance per seed. Invalid/repeated actions are risk-rejected and logged.
- **B2:** 8-bar return above/below configured momentum threshold; otherwise flat.
- **B3:** log-price z-score beyond configured entry threshold, exiting around
  zero or on statistical invalidation.
- **B4:** momentum in trend regimes, reversion in range regimes, flat in transition.
  This is the Stats-only branch reserved for the primary LLM comparison.

Reversal requires CLOSE before another entry. Missing required features yield HOLD.
Entries support `stop_mode: "fixed_pct"` and `"realized_volatility"`. The latter
requires an explicit positive `volatility_stop_multiple` and uses
`100 * current causal per-bar log-return volatility * multiple` as stop percent.
No volatility estimate means HOLD; no fallback stop is invented. Targets use
`target_r_multiple`; statistical invalidation, time stops and trailing stops can
be combined. These are research controls, not optimized exit recommendations.
The batch writes `comparison.json`, `comparison.csv`, `feature_catalogue.json`,
`report.html` and full run artifacts for every agent. The random distribution is
empirical; confidence intervals and significance analysis remain Phase 7 work.
Reports explicitly show that Stats+LLM has not been run.

## Execution and accounting rules

Decisions use completed bar T; fills occur at next eligible bar open, even when
that timestamp equals T's close. Strategies receive frozen account snapshots,
completed bars and completed higher bars only. Fill-time risk revalidates sizing
after a gap; it cannot change the already finalized strategy decision.

Entry sizing takes the lesser of stop-based loss budget (including modeled
roundtrip costs), gross exposure and commission-inclusive cash availability,
rounded down to the quantity increment. Percent units are literal percentages:
`0.50` means 0.5%. A stop cannot bound losses through unexpected future gaps.

Market fills pay half spread plus slippage in the adverse direction, adverse
tick rounding and commission on actual fill notional. Costs are separately
logged. Short proceeds are signed cash; exposure limits still apply. Realized
P&L contains closed-trade net P&L; open entry commission remains reflected in
cash and equity until the trade closes. Unrealized P&L uses actual entry fills.

Resting stop gaps fill at the open, with adverse costs; target gaps use the open.
Stop-first resolves bars touching both exits. `ambiguity_policy: "reject"` instead
requires finer data. Intrabar exits are stamped at bar close as an availability
bound, not a claim that the precise fill time is known. Friction-crossed entry
stops close at the entry open, with both sides' costs. Trailing levels calculated
from a close become effective only afterward. Horizon exits fill at the next
open after the configured held-bar count is completed.

Daily loss latches until the next configured local day. Portfolio drawdown
latches for the rest of the run. Close-observed limit crossings liquidate at
the next available open; no retroactive close fills. At the last bar, open
positions remain marked to market and unfilled decisions expire.

Metrics include initial capital and completed-bar close returns. Risk can also
observe opening marks, so its peak equity can differ from close-sampled report
drawdowns. Sharpe uses zero risk-free rate and sample return standard deviation;
Sortino uses zero-target downside deviation. Annualized return scales by supplied
periods/year; CAGR uses elapsed calendar time. Undefined/overflow ratios are null.
Turnover is reference-price traded notional divided by initial capital. Market
exposure is the fraction of bars touched by a position (an OHLC time upper bound).
Open trades are excluded from win rate/trade statistics and are reported separately.

## Audit and remaining gates

## Yahoo historical ingestion

Install optional download dependencies with the project interpreter:
`.venv\Scripts\python.exe -m pip install -e ".[data,test]"`.
Download with `.venv\Scripts\python.exe main.py download-yahoo --assets SPY QQQ GLD --output-root data/yahoo`.
The adapter preserves raw chart responses, creates independent regular-session
calendars and saves per-asset research configurations without inventing costs.
For offline reprocessing, use `main.py prepare-yahoo --batch-path <captured-batch>`.

The captured October 3 batch has valid daily exports but invalid hourly exports:
15 null bars in SPY/GLD and 14 in QQQ. See `docs/yahoo-data-quality.md`.
Do not run research until the data policy and remaining parameters are decided.
The ingestion client accesses historical Yahoo data only; core backtests remain offline.

The user subsequently approved daily decisions for SPY, QQQ and GLD.
Use `config/research-SPY.json`, `config/research-QQQ.json` and
`config/research-GLD.json`. `config/research.json` points to SPY for the original
validation command. All three daily datasets pass validation; archived hourly
configs still fail. Daily availability remains session close and execution the
next eligible session open. Approved capital, costs and evaluation dates are
recorded in `docs/approved-research-settings.md`. Research runs use 2005-2014,
with causal warmup and the 2024-2025 holdout excluded. SPY dividends use the
issuer's payment dates; GLD has no distributions. QQQ research remains blocked
by two unmatched Yahoo dividend events despite valid OHLCV.

Development benchmark command: `python main.py backtest --config config/research-SPY.json --experiment baselines`.
Use `research-GLD.json` for GLD. Stress configurations are
`config/development-SPY-2x.json`, `development-SPY-3x.json` and their GLD
counterparts. Each batch contains four deterministic controls and 100 seeded
random agents under identical conditions. This is a development evaluation;
walk-forward and the Stats-only vs Stats+LLM comparison remain mandatory.

## Run audit

Each create-once run stores `config.json`, `metadata.json`, `data_quality.json`,
`data.csv`, optional `higher_data.csv`, `features.json`, `decisions.jsonl`,
`orders.csv`, `trades.csv`, `equity_curve.csv`, `corporate_actions.json`, and
`metrics.json`. Research runs also archive exact `dividend_input.json` bytes
and the approved window/configuration/source hashes inside `config.json`.
Metadata records unique run ID, timestamps, source/dataset fingerprint, seed,
configuration hash and artifact hashes. The Git commit is null while this project
is not a Git repository. Each run archives `source.zip` and a source fingerprint;
replay rejects changed code until the archived source is restored in a separate
directory. An `INCOMPLETE` marker blocks partially written runs.
Saved core artifacts are checked for tampering on load and are never overwritten.

Required next decisions: QQQ event-source reconciliation; LLM model/provider,
parameters, budget and permitted caching. Phase 4 starts only
after the historical deterministic benchmark gate is established. Phases 4-8 must
add strict/cached/audited LLM decisions, blindfolding, walk-forward/holdout protection,
paired Stats-only vs Stats+LLM analysis, bootstrap/ablations and the full research report.
No live-money execution is authorized by this contract.
