# Daily Research Accounting Implementation Plan

> Execute inline using superpowers:executing-plans; follow TDD and final review.

**Goal:** Run approved daily development benchmarks with causal dividend
accounting and a protected final holdout.

**Architecture:** Immutable dividend events are input alongside bars, with
ex-date entitlement before opening trades and payment transferred from
receivable to cash at the payment session close. Research configuration slices
data before simulation and supplies earlier causal warmup without trading.
Archive event inputs and window configuration so replay checks accounting too.

**Tech Stack:** Python standard library core, pytest; optional data tooling for
public-source capture and extraction.

**Spec:** ../../approved-research-settings.md and ../../../LLM_TRADING_AGENT_BACKTEST_SPEC.md.

## Global constraints

- Historical only; no broker connection or live trading.
- Preserve source bytes and hashes; do not infer missing payment dates.
- 2005-2014 development; 2015-2023 walk-forward; 2024-2025 holdout excluded.
- Shared costs/risk; 100 seeded random agents; LLM comparison remains mandatory.
- $0.01 simulated tick approved; long-only research; no dividend reinvestment.

## Review focus

- Ex-date opening buys receive no dividend; opening sells retain entitlement.
- Receivables cannot fund entries or create duplicate income on payment.
- Warmup and holdout cannot trade, score or initialize risk peaks.
- Closed-trade dividend P&L and outstanding receivables reconcile to equity.
- Source event coverage gaps block runs rather than omit distributions.

## Tasks

- [ ] Capture and reconcile development payment dates with every Yahoo event;
  preserve disagreements and refuse incomplete event coverage.
- [x] Write failing accounting tests for entitlement, settlement, closed-trade
  attribution, shorts, duplicate/invalid events and future-event invisibility.
  Add dividend contracts and portfolio/engine processing, then run tests.
- [x] Write failing tests for 24-session momentum and long-only negative-signal
  exits. Implement explicit strategy configuration, preserving older defaults.
- [x] Write failing tests for scored-window start, warmup and holdout rejection.
  Add a research-window boundary and CLI integration; archive/replay events.
- [x] Verify full suite and fresh-context review. Correct material findings.
- [x] Run development benchmarks for each fully validated asset at approved
  costs and stress multipliers. Preserve incomplete assets as blocked.

## Ledger

Initial source inspection: Yahoo development dividends SPY 40 and QQQ 41.
Two public payment tables together cover SPY 40, but QQQ 39: events dated
2010-06-25 and 2011-12-27 require further source evidence. Neither is omitted.
The attempted State Street historical PDF was DIA-only and is not SPY evidence.

Subsequently captured issuer workbook matching all 40 SPY development dates,
with full precision amounts and payment dates. GLD has no distributions or
scored-period splits. QQQ remains source-blocked. RED/GREEN accounting/window
tests completed; full suite 104 passed in 24.18s. Fresh review found missing
research/source provenance in archives; fixed with exact input-byte archives
and assertions. Reviewer verified fix; no Important/Critical issue remains.
SPY/GLD six development benchmark batches completed: 624 simulations. Final
batch count/seed/archived date/completion checks passed; GLD statistical replay
also identical. Consolidated results in ../../development-benchmarks.md.
The source-reconciliation task remains open specifically for QQQ.
