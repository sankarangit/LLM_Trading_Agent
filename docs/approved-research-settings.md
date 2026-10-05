# Approved daily research settings

User approved the proposed setup on 2026-10-03. SPY, QQQ and GLD are separate
$100,000 simulations, long-only, whole-share, without leverage. Decisions use
completed daily sessions and fills use the next eligible session open.

Commission is 1 bp per side, slippage 2 bp per side and full spread 2 bp.
Repeat evaluation at 2x and 3x these costs. These are simulated cost assumptions.
Risk limits remain 0.5% per trade, 1.5% daily loss and 10% drawdown.
Stops are fixed 3%, ambiguous bars stop-first. Features use 24-session and
8-session short windows. Approved momentum horizon is 24 sessions with 1%
threshold. Mean reversion enters at z-score +/-2 and exits within +/-0.5.
No time stop, target or trailing stop. Annualization is 252 sessions.

Development: 2005-2014. Annual walk-forward evaluation: 2015-2023.
Final untouched holdout: 2024-2025. Earlier rows provide causal warmup only;
2026 is excluded. No holdout performance has been inspected.
Deterministic controls and 100 seeded random agents remain mandatory, as does
the paired Stats-only / Stats+LLM comparison using identical conditions.

User subsequently approved obtaining dividend payment dates and a $0.01
simulated execution increment. Entitlement is recognized before trades at
ex-date open; payment transfers the receivable to cash at payment-session close.
Daily dates do not establish intraday payment availability, so cash is available
for next-session entries. There is no automatic reinvestment.

Implemented signed dividend accounting, archived payment inputs and ledger,
causal warmup, holdout exclusion, 24-session momentum and long-only exits.
Scored sessions are 2005-2014; up to 50 preceding sessions supply warmup without
trading, scoring or risk initialization. GLD has only 30 preceding sessions
after listing; undefined features retain their normal null warmup.
Neither SPY nor GLD has a split in the scored period. Source-native
split-consistent OHLC is retained; no dividend-adjusted-price shortcut is used.

State Street's archived historical workbook supplies all 40 SPY development
distributions, with full-precision amounts and payment dates. GLD's captured
source has no distributions. QQQ remains blocked: two of its 41 Yahoo events
(2010-06-25 and 2011-12-27) have no reliable matching payment dates. The other
39 dates do not establish that these two can be discarded. No QQQ scores
are produced pending source reconciliation.

Exact dividend input bytes, source hashes, research configuration, data,
decisions, orders, trades, dividend ledger and code are archived per run.
Replay checks event/accounting equivalence.

On 2026-10-04 the user selected OpenAI GPT-4o mini (`gpt-4o-mini`) for
the Phase 4 LLM decision layer. DeepSeek is not selected. This records the
model choice only; no API calls or credentials have been configured.
The user subsequently approved a $10 maximum API budget for the initial
experiments and proceeding with SPY/GLD first while QQQ remains blocked.
This does not discard QQQ from the original research scope. The cap covers
all initial experiment requests together, not $10 per asset or run.
The user approved the Phase 4 design: temperature 0, maximum output 512 tokens,
30-second timeout, no automatic paid retries, local exact-request cache and
immutable audit logs. Primary E2 starts without a journal; the optional journal
variant has the last 20 past decisions. Confidence does not affect sizing and
horizon_bars must be null under the approved no-time-stop policy. The initial
paid pilot is limited to 20 daily decisions per asset after offline tests.
No credentials or API calls have been configured.
