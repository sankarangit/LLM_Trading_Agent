# Daily development benchmarks

Development sessions: 2005-2014. Capital: $100,000 per ETF, separately.
Long-only, whole shares; fixed 3% stop and approved shared risk controls.
Each cost level uses four deterministic controls and 100 seeded random agents.
2024-2025 holdout is excluded. Walk-forward and Stats+LLM remain pending.

| Asset | Cost multiplier | Stats-only total net return | Random median net return |
|---|---:|---:|---:|
| SPY | 1x | -0.75% | -7.50% |
| SPY | 2x | -1.94% | -9.57% |
| SPY | 3x | -3.09% | -10.03% |
| GLD | 1x | 2.40% | 1.94% |
| GLD | 2x | 0.99% | -2.95% |
| GLD | 3x | -0.08% | -6.85% |

Stats-only means the statistical-regime baseline. These are total returns
over the entire development interval, not annual returns or LLM results.
These comparisons do not establish alpha or statistical significance.
The buy-and-hold control is constrained by the same stops and risk rules;
it is not a fully invested unconstrained ETF total-return index.

## Reports

- [SPY 1x costs](D:/ICICI-NRI-AC/AQ100/LLM_Trading_Agent/runs/benchmarks-20261003T135016Z-629c5d3d9581/report.html)
- [SPY 2x costs](D:/ICICI-NRI-AC/AQ100/LLM_Trading_Agent/runs/benchmarks-20261003T135704Z-f033998245ff/report.html)
- [SPY 3x costs](D:/ICICI-NRI-AC/AQ100/LLM_Trading_Agent/runs/benchmarks-20261003T140015Z-1d5e105c3340/report.html)
- [GLD 1x costs](D:/ICICI-NRI-AC/AQ100/LLM_Trading_Agent/runs/benchmarks-20261003T140327Z-a0fa34433725/report.html)
- [GLD 2x costs](D:/ICICI-NRI-AC/AQ100/LLM_Trading_Agent/runs/benchmarks-20261003T140617Z-8cb622bdfa57/report.html)
- [GLD 3x costs](D:/ICICI-NRI-AC/AQ100/LLM_Trading_Agent/runs/benchmarks-20261003T140904Z-59afdacd5be0/report.html)

## Blocked and pending

QQQ has valid daily OHLCV but incomplete distribution payment-date evidence.
Its Yahoo events on 2010-06-25 and 2011-12-27 are unresolved; no QQQ run was made.
See [distribution-source gate](dividend-source-quality.md).
The full three-asset Phase 3 research gate remains open until QQQ is resolved
or the user explicitly changes experiment scope. No Phase 4 LLM integration
or primary Stats-only versus Stats+LLM evaluation has been performed.

## Verification

Code tests: 105 passed in 19.25s. Fresh accounting review passed after provenance fix.
Saved SPY 1x statistical replay using its archived source is identical.
Saved SPY 2x statistical/random and GLD 1x statistical replays are identical.
The first SPY report was recovered from its saved comparison after a tested
datetime serializer fix; no simulation inputs, decisions or scores were changed.

All six batches are complete: 624 simulations. Batch seed counts, archived development boundaries and completion markers were checked.
