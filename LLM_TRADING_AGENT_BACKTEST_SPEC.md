# LLM Trading Agent Backtest Specification

**File:** `LLM_TRADING_AGENT_BACKTEST_SPEC.md`  
**Purpose:** Codex-ready research and implementation specification  
**Version:** 1.0  
**Primary Mode:** Historical backtest first; paper/live trading explicitly out of scope until validation gates pass.

---

## 1. Objective

Build a reproducible Python research framework to test whether an LLM decision layer adds measurable, repeatable trading value on top of statistical market features.

The project is **not** intended to prove that an LLM can generate plausible trading explanations. It must determine whether the LLM produces incremental out-of-sample performance versus deterministic strategies using the same information.

### Primary research question

> Does a blindfolded LLM, supplied with scale-free statistical market features, improve out-of-sample risk-adjusted performance relative to deterministic statistical baselines after realistic transaction costs?

### Primary comparison

`Statistical Strategy Only` **vs.** `Same Statistical Features + LLM Decision Layer`

Both branches must use the same:

- market data;
- timestamps;
- feature calculations;
- risk engine;
- execution simulator;
- commission model;
- spread/slippage assumptions; and
- evaluation periods.

The LLM is the principal experimental variable.

---

## 2. Core Principles

1. **No look-ahead bias.** Only information available at decision time may be used.
2. **Next-bar execution.** Decisions based on bar `T` cannot fill on bar `T`; default fill is the next eligible bar.
3. **Blindfold the LLM.** Hide ticker, asset identity, calendar dates, absolute price level and unnecessary identifying information.
4. **Statistical features first.** Avoid making generic technical indicators the primary source of information.
5. **Deterministic risk.** The LLM proposes a direction/action; code controls exposure and risk.
6. **Same-engine comparisons.** Every benchmark must run through the same execution/cost framework.
7. **Out-of-sample evidence matters most.** In-sample optimization is not evidence of alpha.
8. **Full auditability.** Every LLM input, output, risk decision, order, fill and P&L result must be reproducible and logged.
9. **No live execution in the initial implementation.** Historical backtesting must be completed first.

---

## 3. Initial Research Universe

Architecture must support arbitrary liquid instruments through adapters.

Initial candidates:

- QQQ
- SPY
- GLD
- BTC/USD
- EUR/USD

Do **not** assume all instruments share identical trading hours, spread behavior, fees or data schemas.

### Timeframes

Default configuration:

- Decision timeframe: `1h`
- Higher-timeframe context: `1d`
- Optional additional research timeframes: `15m`, `4h`

All timeframes must be configurable.

---

## 4. Data Requirements

Minimum OHLCV schema:

```text
timestamp
open
high
low
close
volume
```

Volume may be null/unsupported for instruments where meaningful centralized volume is unavailable. Feature code must handle this explicitly rather than silently substituting fabricated values.

### Data integrity checks

Before a run:

- timestamps sorted and unique;
- duplicate bars detected;
- missing bars reported;
- timezone normalized;
- invalid OHLC relationships detected;
- NaN/inf values reported;
- corporate-action handling documented for equities/ETFs;
- session/calendar rules applied per instrument;
- data source and dataset fingerprint recorded.

A run with material unresolved data-quality errors must fail rather than silently continue.

---

## 5. Anti-Lookahead Rules

These requirements are mandatory and require unit tests.

At decision timestamp `T`:

- only fully completed bars through `T` are visible;
- an incomplete higher-timeframe candle must not be included;
- every feature must be calculated only from observations available through `T`;
- rolling normalization must use past/current observations only;
- regime models must not be fitted using future observations;
- model selection/parameter optimization must not use the final test period;
- LLM memory/journal may contain only decisions/events known by `T`.

### Execution timing

Default:

```text
Observe completed bar T
        ↓
Calculate features
        ↓
LLM / strategy decision
        ↓
Risk validation
        ↓
Execute at next eligible bar T+1 open
        ↓
Apply spread + slippage + commission
```

No strategy may receive the `T+1` open before its decision is finalized.

---

## 6. LLM Blindfolding

The LLM must not receive:

- ticker symbol;
- asset/company name;
- exchange name unless operationally necessary;
- real calendar date;
- absolute raw price;
- future information;
- textual news identifying the historical period in the initial experiment.

### Price normalization

Represent price history using a scale-free index or returns.

Example:

```text
Start of visible context = 100.00
Current indexed price     = 103.42
1-bar return              = -0.42%
20-bar return             = +2.15%
```

### Time normalization

Instead of real dates:

```text
T-24h
T-20h
...
T
```

The system should preserve useful market/session information only if deliberately included as an experimental feature.

---

## 7. Feature Engine

Features must be generated in Python, not calculated by the LLM.

Every feature must have:

- documented mathematical definition;
- lookback/window;
- minimum observations;
- NaN policy;
- normalization rule;
- anti-leakage test.

### 7.1 Return and distribution features

Candidate features:

- 1/2/4/8/24-bar returns;
- rolling return z-score;
- cumulative return over configurable horizons;
- realized volatility;
- realized-volatility percentile;
- downside volatility;
- upside/downside volatility ratio;
- rolling skewness;
- rolling kurtosis;
- return percentile/rank.

### 7.2 Trend features

Prefer statistical measurements such as:

- regression slope normalized by volatility;
- regression `t` statistic;
- R-squared of rolling trend;
- multi-horizon trend agreement;
- momentum acceleration/deceleration;
- distance from rolling mean normalized by realized volatility.

### 7.3 Mean-reversion features

Candidate features:

- rolling z-score;
- deviation from VWAP/rolling mean normalized by volatility;
- short-lag autocorrelation;
- variance ratio;
- estimated half-life where statistically meaningful;
- reversal magnitude after extreme returns.

### 7.4 Volatility/regime features

Candidate features:

- realized-vol percentile;
- short-vol / long-vol ratio;
- volatility expansion/contraction;
- range percentile;
- trend-vs-chop score;
- regime classification/probabilities.

Initial regimes can include:

```text
LOW_VOL_TREND
HIGH_VOL_TREND
LOW_VOL_RANGE
HIGH_VOL_RANGE
TRANSITION
```

Do not use future data to label the current regime.

### 7.5 Volume/liquidity features

Where reliable data exists:

- relative volume;
- volume z-score;
- price/volume divergence;
- volume acceleration;
- range-to-volume anomaly.

### 7.6 Optional technical-control features

RSI, EMA distances and ATR may be implemented as **control features** for comparison, but they must not be the only feature set.

---

## 8. Experimental Strategy Variants

At minimum implement:

### B0 — Buy & Hold
Passive benchmark where meaningful.

### B1 — Random Agents
At least 100 seeded random agents using the same engine/cost/risk assumptions.

Purpose: estimate the performance distribution obtainable by chance under the simulator.

### B2 — Deterministic Momentum
Simple, documented trend/momentum baseline.

### B3 — Deterministic Mean Reversion
Simple, documented statistical mean-reversion baseline.

### B4 — Statistical Regime Strategy
Rule-based strategy using the same statistical features supplied to the LLM.

### E1 — LLM Only
Blindfolded LLM with normalized market context but minimal engineered statistical information.

### E2 — Statistical Features + LLM
**Primary experimental strategy.**

The LLM receives the statistical snapshot and returns a bounded trading decision.

### E3+ — Ablation variants
Support experiments such as:

- stats + LLM without journal;
- stats + LLM with journal;
- without regime features;
- without volume features;
- different feature subsets;
- different prompts;
- different models;
- different reasoning budgets/configurations.

---

## 9. LLM Decision Contract

The LLM must return strict structured output validated against a schema.

Example:

```json
{
  "action": "LONG",
  "confidence": 0.72,
  "horizon_bars": 4,
  "reason": "Extreme negative deviation within a statistically positive trend; volatility is elevated but not in transition."
}
```

Allowed actions:

```text
LONG
SHORT
HOLD
CLOSE
```

### Important restriction

The LLM does **not** have unrestricted authority to specify leverage, contracts or capital allocation.

Position sizing is determined by the deterministic risk engine.

Confidence must initially be treated as an experimental feature, not assumed to be calibrated probability.

---

## 10. LLM Prompt Requirements

Store prompts as version-controlled files under `/prompts`.

The system prompt must instruct the model to:

- reason only from supplied information;
- not identify/guess the asset or historical period;
- obey the structured output contract;
- avoid inventing missing data;
- choose HOLD when evidence is insufficient;
- distinguish trend, mean-reversion and regime conditions;
- avoid changing risk constraints;
- provide concise reasoning.

Every decision record must store:

- prompt version/hash;
- model identifier;
- model parameters;
- feature snapshot;
- account/trade context shown;
- raw model output;
- parsed output;
- validation errors/retries;
- token usage if available;
- latency;
- estimated API cost if available.

---

## 11. Deterministic Risk Engine

The risk engine is authoritative and can reject or resize an LLM request.

Configurable controls:

```yaml
max_risk_per_trade_pct: 0.50
max_daily_loss_pct: 1.50
max_portfolio_drawdown_pct: 10.00
max_gross_exposure_pct: 100.00
max_positions: 1
allow_short: true
```

These are initial research defaults, not claims of optimal values.

### Risk responsibilities

- calculate allowed position size;
- enforce max exposure;
- validate long/short permissions;
- enforce stop rules where applicable;
- enforce daily loss limits;
- enforce portfolio drawdown kill switch;
- prevent invalid/repeated orders;
- reject trades with insufficient data;
- log every rejection and reason.

### Stop/exit experiments

Support configurable modes:

- volatility/ATR-based stop;
- fixed risk multiple;
- statistical invalidation;
- time stop;
- model CLOSE decision;
- trailing stop;
- combinations of the above.

Risk/exit methods must be compared rather than optimized on the final test set.

---

## 12. Execution Simulator

The simulator must model realistic execution and remain identical across strategy variants.

### Default fill model

Market decision at completed bar `T` → simulated fill at next eligible bar `T+1` open.

### Costs

Support:

```yaml
commission_bps_per_side: 5
slippage_bps_per_side: 2
spread_bps: configurable
```

These values are placeholders/configuration defaults and must be replaced with instrument-appropriate assumptions during research.

### Required capabilities

- commissions;
- bid/ask spread approximation;
- slippage;
- minimum tick/quantity where relevant;
- long/short accounting;
- stop/target handling;
- gaps through stops;
- partial-fill abstraction if later enabled;
- trading-session rules;
- mark-to-market accounting.

The simulator must not assume a stop always fills exactly at the stop price.

---

## 13. Portfolio/Account State

Track at minimum:

```text
cash
equity
realized_pnl
unrealized_pnl
position
entry_price
position_size
exposure
peak_equity
drawdown
daily_pnl
transaction_costs
```

The LLM should receive only the account information intentionally allowed by the experiment.

---

## 14. Walk-Forward Evaluation

A single 50-day test is insufficient.

The framework must support multi-year, rolling walk-forward tests.

Example only:

```text
Development     Validation      Test
2018-2021       2022            2023
2019-2022       2023            2024
2020-2023       2024            2025
```

Exact windows depend on data availability and instrument history.

### Final untouched holdout

Reserve a final period that is never used for:

- feature selection;
- prompt tuning;
- threshold tuning;
- strategy selection;
- risk-parameter optimization.

Do not inspect the final holdout repeatedly during development.

---

## 15. Statistical Validation

Performance must not be judged solely by final P&L.

Required analysis:

- bootstrap confidence intervals where appropriate;
- distribution of random-agent outcomes;
- performance by instrument;
- performance by year;
- performance by regime;
- performance by volatility bucket;
- sensitivity to transaction costs;
- sensitivity to slippage;
- sensitivity to prompt/model configuration;
- stability across walk-forward windows.

Where practical, include tests for whether apparent performance differences could reasonably arise from sampling variation. Clearly label statistical assumptions and limitations.

---

## 16. Performance Metrics

Calculate consistently for all strategies:

### Return/risk

- total return;
- CAGR/annualized return where appropriate;
- annualized volatility;
- Sharpe ratio;
- Sortino ratio;
- maximum drawdown;
- Calmar ratio.

### Trade statistics

- number of trades;
- win rate;
- average win;
- average loss;
- payoff ratio;
- profit factor;
- expectancy per trade;
- average holding period;
- turnover;
- market exposure.

### Cost statistics

- commissions;
- spread cost;
- slippage cost;
- total transaction cost;
- gross vs net performance.

### LLM statistics

- number of calls;
- action distribution;
- HOLD rate;
- confidence distribution;
- API/token cost;
- average latency;
- invalid-output/retry rate;
- performance by confidence bucket (research only).

---

## 17. Primary Alpha Test

For each instrument and walk-forward window, compare:

```text
Statistical Strategy
        VS
Same Features + LLM
```

Produce a paired comparison containing:

```text
Net Return
Sharpe
Sortino
Max Drawdown
Calmar
Profit Factor
Turnover
Trade Count
Transaction Costs
```

The report must explicitly answer:

1. Did the LLM improve risk-adjusted returns?
2. Was improvement consistent across periods/assets or concentrated in one sample?
3. Did the LLM reduce or increase drawdown?
4. Did it increase turnover/costs?
5. Does performance remain after higher slippage assumptions?
6. Is it clearly separated from the random-agent distribution?
7. Does the incremental performance survive the untouched holdout?

---

## 18. Ablation Framework

Implement experiment configuration so features/components can be toggled without code changes.

Example matrix:

| Experiment | Statistical Features | Regime | Journal | LLM |
|---|---:|---:|---:|---:|
| A | Yes | Yes | No | No |
| B | No | No | No | Yes |
| C | Yes | No | No | Yes |
| D | Yes | Yes | No | Yes |
| E | Yes | Yes | Yes | Yes |

This should help identify whether performance comes from:

- the statistical signal;
- regime classification;
- LLM reasoning;
- memory/journal context; or
- an interaction among components.

---

## 19. Reproducibility

Every run must have a unique `run_id` and immutable configuration snapshot.

Record:

```text
run_id
git_commit
created_at
dataset_fingerprint
asset
timeframe
period
feature_config
strategy_config
risk_config
execution_config
prompt_hash
model_id
model_parameters
random_seed
```

Random-agent and any stochastic experiment must use explicit seeds.

LLM responses should be cached by a deterministic request hash when permitted so reports can be regenerated without unnecessarily re-calling the model.

---

## 20. Storage and Audit Trail

Suggested output structure:

```text
runs/<run_id>/
├── config.json
├── metadata.json
├── features.parquet
├── decisions.jsonl
├── orders.csv
├── trades.csv
├── equity_curve.csv
├── metrics.json
├── regime_metrics.csv
├── llm_usage.csv
└── report.html
```

### Decision record

Each LLM decision should include:

```text
decision_id
decision_timestamp
visible_data_end
feature_snapshot
account_snapshot
prompt_hash
model_id
raw_response
parsed_action
confidence
reason
risk_result
risk_rejection_reason
intended_order
```

### Trade record

```text
trade_id
signal_timestamp
entry_timestamp
entry_price
side
size
stop
target
exit_timestamp
exit_price
exit_reason
gross_pnl
commission
spread_cost
slippage
net_pnl
```

---

## 21. Reporting

Generate a self-contained HTML report plus machine-readable files.

Report sections:

1. run configuration;
2. data-quality summary;
3. equity curves;
4. drawdown curves;
5. benchmark comparison;
6. walk-forward results;
7. performance by asset;
8. performance by regime;
9. transaction-cost analysis;
10. random-agent distribution;
11. LLM action/confidence analysis;
12. ablation results;
13. statistical uncertainty;
14. major failure cases;
15. conclusion limited to evidence from the run.

Avoid conclusions such as "LLM works" from a single period.

---

## 22. Suggested Project Structure

```text
llm-trading-agent/
├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── base.yaml
│   ├── assets.yaml
│   ├── risk.yaml
│   └── experiments/
├── data/
│   ├── adapters/
│   ├── validation.py
│   └── cache/
├── features/
│   ├── returns.py
│   ├── trend.py
│   ├── mean_reversion.py
│   ├── volatility.py
│   ├── volume.py
│   └── regimes.py
├── agents/
│   ├── base.py
│   ├── llm_agent.py
│   ├── random_agent.py
│   └── cache.py
├── prompts/
│   ├── system_v1.txt
│   └── snapshot_v1.txt
├── strategies/
│   ├── base.py
│   ├── buy_hold.py
│   ├── momentum.py
│   ├── mean_reversion.py
│   ├── statistical_regime.py
│   └── llm_strategy.py
├── risk/
│   └── risk_engine.py
├── execution/
│   ├── simulator.py
│   └── cost_model.py
├── backtest/
│   ├── engine.py
│   ├── walk_forward.py
│   └── experiment_runner.py
├── evaluation/
│   ├── metrics.py
│   ├── bootstrap.py
│   ├── comparisons.py
│   └── ablation.py
├── reporting/
│   └── html_report.py
├── paper/
│   └── adapter_interface.py
├── tests/
│   ├── test_no_lookahead.py
│   ├── test_features.py
│   ├── test_execution.py
│   ├── test_risk.py
│   ├── test_metrics.py
│   └── test_reproducibility.py
├── runs/
└── main.py
```

---

## 23. Configuration Example

```yaml
experiment:
  name: stats_plus_llm_v1
  seed: 42

asset:
  symbol: QQQ
  decision_timeframe: 1h
  context_timeframe: 1d

features:
  returns: true
  trend_tstat: true
  autocorrelation: true
  variance_ratio: true
  realized_vol_percentile: true
  skew: true
  kurtosis: true
  volume_anomaly: true
  regime: true
  technical_controls: false

llm:
  enabled: true
  blindfold: true
  model: configurable
  temperature: configurable
  max_reason_words: 80
  allowed_actions: [LONG, SHORT, HOLD, CLOSE]

risk:
  max_risk_per_trade_pct: 0.50
  max_daily_loss_pct: 1.50
  max_portfolio_drawdown_pct: 10.0
  max_positions: 1

execution:
  fill: next_bar_open
  commission_bps_per_side: 5
  slippage_bps_per_side: 2
  spread_bps: configurable

reporting:
  html: true
  csv: true
  json: true
```

---

## 24. Testing Requirements

Before trusting any P&L output, tests must cover:

### Anti-leakage

- feature at `T` unchanged if future bars are modified;
- incomplete daily bar unavailable to an intraday decision;
- next-bar open inaccessible before decision;
- rolling scalers do not fit on future data.

### Execution

- correct long/short P&L;
- commission charged on correct sides;
- slippage direction correct;
- gap-through-stop behavior correct;
- no same-bar impossible fills.

### Risk

- position sizing obeys limits;
- daily loss kill switch works;
- max-drawdown kill switch works;
- invalid LLM action rejected;
- exposure limit enforced.

### Reproducibility

Given identical cached LLM responses, data, configuration and seed, the backtest must reproduce identical trades and metrics.

---

## 25. Implementation Phases for Codex

### Phase 1 — Deterministic core

Build:

- data schema/validation;
- backtest event loop;
- portfolio accounting;
- execution/cost model;
- risk engine;
- metrics;
- tests.

No LLM dependency yet.

### Phase 2 — Statistical feature engine

Implement features with anti-leakage unit tests.

### Phase 3 — Baselines

Implement:

- buy & hold;
- random agents;
- momentum;
- mean reversion;
- statistical regime strategy.

Establish benchmark reports before introducing the LLM.

### Phase 4 — LLM integration

Implement:

- provider-neutral agent interface;
- strict output schema;
- prompt versioning;
- response caching;
- usage/cost logging;
- graceful failure/retry policy.

### Phase 5 — Blindfolding

Implement normalization, date/ticker removal and tests proving identifying raw fields are not sent to the model.

### Phase 6 — Walk-forward runner

Implement multiple windows and untouched holdout support.

### Phase 7 — Statistical validation and ablations

Implement paired comparisons, random distributions, bootstrap analysis and feature/component toggles.

### Phase 8 — Reporting

Generate HTML + machine-readable outputs.

### Phase 9 — Paper trading (only after research gates)

Add an adapter interface for real-time market data and paper broker execution. Keep strategy/risk logic shared with the backtester to minimize research/live divergence.

Do not implement live-money execution by default.

---

## 26. Research Acceptance Gates

Do **not** declare success based on a fixed arbitrary Sharpe threshold or one profitable period.

The LLM layer should advance to paper trading only if evidence shows, after realistic costs:

1. incremental performance versus the deterministic statistical baseline;
2. improvement across multiple walk-forward windows rather than one isolated sample;
3. acceptable drawdown relative to the baseline;
4. no dependence on a single asset/regime;
5. reasonable stability under worse slippage/cost assumptions;
6. separation from the random-agent distribution that is not obviously attributable to one lucky path;
7. positive evidence on the untouched holdout;
8. reproducible results and a complete audit trail.

Failure of these gates is a valid research outcome.

---

## 27. Paper-Trading Gate

Only after the research acceptance gates pass:

```text
Live Market Data
      ↓
Same Feature Engine
      ↓
Same LLM Decision Contract
      ↓
Same Deterministic Risk Engine
      ↓
Paper Broker Adapter
      ↓
Actual Paper Fills
      ↓
Reconciliation + Drift Analysis
```

Paper trading must compare:

- expected simulated fill vs paper fill;
- expected vs actual slippage;
- latency;
- rejected orders;
- data discrepancies;
- signal timing drift;
- realized paper P&L vs shadow backtest.

Only a separate future specification should authorize live-money trading.

---

## 28. Optional Laya / Orchestration Integration

Keep orchestration separate from alpha logic.

If Laya or another agent/orchestration framework is used, it may coordinate:

- experiment generation;
- batch backtests;
- model/prompt variants;
- result collection;
- report generation;
- experiment metadata.

It must **not** bypass the deterministic risk engine or alter historical data/execution rules between strategies.

The core backtester must remain runnable directly from Python without requiring an orchestration framework.

---

## 29. Codex Build Instructions

When implementing this specification:

1. Build in phases; do not start with broker integration.
2. Do not fabricate unavailable market data.
3. Prefer simple, testable components over a large agent framework.
4. Keep data, feature, strategy, risk and execution layers independent.
5. Write tests before trusting performance output.
6. Never calculate features using future observations.
7. Never execute a decision using a price that was unavailable when the decision was made.
8. Keep LLM calls behind an interface so models/providers can be changed.
9. Make all material assumptions configurable.
10. Cache LLM decisions for reproducible research.
11. Generate an experiment manifest for every run.
12. Make deterministic baselines fully operational before evaluating the LLM.
13. Do not optimize against the final holdout.
14. Surface errors rather than silently repairing data or model output.
15. Update `README.md` with exact commands to install, test and run each phase.

---

## 30. Minimum CLI

Target commands:

```bash
# Validate data
python main.py validate-data --config config/base.yaml

# Run deterministic baselines
python main.py backtest --experiment baselines

# Run one LLM experiment
python main.py backtest --experiment stats_plus_llm_v1

# Run walk-forward evaluation
python main.py walk-forward --experiment stats_plus_llm_v1

# Run ablations
python main.py ablation --config config/experiments/ablation_v1.yaml

# Build report from an existing run
python main.py report --run-id <RUN_ID>

# Run test suite
pytest -q
```

CLI syntax may be refined during implementation, but equivalent functionality is required.

---

## 31. Definition of Done — V1 Backtest

V1 is complete when:

- deterministic backtest engine passes tests;
- no-lookahead tests pass;
- statistical features are documented and tested;
- all required baselines run;
- blindfolded LLM agent runs using strict structured output;
- identical risk/execution engines are used across comparisons;
- 100+ seeded random-agent runs are supported;
- walk-forward experiments run end-to-end;
- final holdout is protected from tuning workflow;
- transaction costs/slippage are included;
- all decisions/trades are auditable;
- metrics and HTML report are generated;
- stats-only vs stats+LLM comparison is automatically produced;
- results can be reproduced from saved run metadata and cached LLM responses.

---

## 32. Final Research Output

The final report must end with evidence-based answers to:

> **Does the LLM add incremental alpha over the statistical strategy?**

> **Does any improvement survive realistic costs, walk-forward testing and an untouched holdout?**

> **What happens to Sharpe, Calmar and maximum drawdown when the LLM is added?**

> **Is the result stable across assets and regimes?**

> **Is the LLM contribution worth its additional complexity, latency and API cost?**

If the evidence is weak or inconsistent, the correct conclusion is that the LLM has **not yet demonstrated incremental trading value**.

