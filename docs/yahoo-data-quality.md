# Yahoo historical data gate

Captured 2026-10-03 at 12:58:30 UTC for SPY, QQQ and GLD. All six maximum-history
hourly/daily chart requests succeeded. Original responses and SHA-256 manifests
are preserved under `data/yahoo/20261003T125830Z-5c0cf912`.
The authoritative prepared exports are in its `prepared-77c833b4` directory.
Earlier preparation failures remain archived; use this directory's quality reports.

Hourly regular-session coverage: 2024-10-03 through 2026-10-02.
Each asset has 3,492 expected calendar slots, with no absent timestamps.
SPY and GLD each have 15 null OHLCV bars (0.430%); QQQ has 14 (0.401%).
All three hourly exports fail validation and must not enter a backtest.

| Session date | SPY null bars | QQQ null bars | GLD null bars |
|---|---:|---:|---:|
| 2024-11-29 | 1 | 1 | 1 |
| 2024-12-24 | 1 | 1 | 1 |
| 2025-07-03 | 1 | 1 | 1 |
| 2025-11-28 | 1 | 1 | 1 |
| 2025-12-24 | 1 | 1 | 1 |
| 2026-01-30 | 6 | 5 | 6 |
| 2026-02-02 | 4 | 4 | 4 |

Five null bars are the legitimate final half-hour on early-close sessions.
Yahoo also returned five records after those sessions closed and one flat,
zero-volume closing quote. These six outside-session records are explicitly
audited exclusions, not replacements for missing prices. No eligible bars were
dropped or filled. The raw payload establishes the nulls; their upstream cause
is unknown.

Daily exports pass independent calendar, timestamp and OHLCV validation:
SPY has 8,477 bars from 1993-01-29; QQQ has 6,935 from 1999-03-10;
GLD has 5,502 from 2004-11-18. All end on 2026-10-02. Daily bars become
available at actual session close, including holidays, DST and early closes.

Source OHLC is retained without auto-adjustment, back-adjustment or repair;
Adj Close is unused and corporate-action events remain in raw files.
Dividend accounting and split treatment remain research decisions.

Decision required: retain hourly decisions and obtain another source, explicitly
change the contract to daily decisions, or approve a documented reduced-sample
policy. Do not silently omit the affected sessions. Capital, trading costs,
strategy parameters, evaluation windows and holdout remain unset.
No historical benchmark, LLM call, holdout evaluation or live trading was run.

Verification: project virtualenv pytest suite, 89 passed in 19.18 seconds.
Coverage includes anti-lookahead, deterministic benchmarks and Yahoo timestamp,
session-close, raw preservation and rejection tests. Stats-only vs Stats+LLM
remains a mandatory pending research gate.
