# Phase 4: GPT-4o mini decision layer

Status: approved by the user on 2026-10-04; implementation has not started.

## Approved scope

Implement the original contract's Phase 4 provider-neutral LLM interface,
versioned prompts, strict validation, cache and audit, using OpenAI GPT-4o mini.
The initial paid experiments share one $10 maximum API budget across SPY and
GLD. QQQ stays blocked by unresolved dividend payment dates and is not removed
from the overall research scope. Development remains 2005-2014; walk-forward
2015-2023 and untouched holdout 2024-2025 remain later sequential gates.
No broker or live execution adapter is included.

## Approved experimental settings

- Model ID `gpt-4o-mini`, temperature 0, maximum output 512 tokens, 30-second
  timeout, and no automatic paid retries. Temperature 0 is not a guarantee of
  deterministic model generation; immutable responses support exact replay.
- Primary E2 variant uses the existing complete statistical snapshot without
  a journal first. Support an explicit journal variant with the last 20 past
  decisions only, and E1 normalized market context without engineered features.
  These are distinct experiment IDs and must not be pooled as one result.
- Returned fields are action, confidence, nullable horizon_bars and concise
  reason. Confidence is audited but does not alter sizing. Under the approved
  no-time-stop setup, horizon_bars must be null; non-null values are invalid.
- Store exact requests, responses and audit records locally in immutable run
  artifacts; use a project-local exact-request cache under data/cache/llm.
  API keys never enter cache keys, logs or artifacts.
- First paid pilot: at most 20 daily decisions per asset, at the beginning of
  the approved development period, after offline tests pass. Its results are
  labelled pilot-only. Inspect usage and failure rate before a full paid pass.

## Architecture

Use a small provider interface returning raw response, parsed structured output,
usage and latency. Implement an OpenAI HTTPS adapter with strict JSON-schema
output and explicit key lookup through OPENAI_API_KEY. An LLM strategy adapts
validated decisions into the existing Decision contract. Code supplies the
approved 3% stop; the model never selects shares, leverage, stops or capital.
Existing engine/risk/portfolio code stays authoritative for next-open execution,
long-only rejection, exits, costs, dividends and kill switches.

Use versioned prompt files under prompts. Every request is constructed from
an allowlist, not from serialization of the raw Context. Only completed causal
features, normalized price context, relative account measures and bounded past
decision records may be shown. Hide asset/date/exchange/raw price/share count,
and source metadata. Account measures use fractions/returns; the journal cannot
carry raw identifying fields or future events. Null features remain null.
Complete Phase 5 leakage tests before any paid pilot, although Phase 4 interface
implementation comes first. Blindfolding reduces memorization risk but cannot
prove a pretrained model has no knowledge of historical return patterns.

## Validation and failure behavior

Reject unknown fields, malformed JSON, duplicate keys, nonfinite values, invalid
actions, confidence outside [0,1], oversized reasons and disallowed horizons.
API refusal, malformed output, timeout or provider failure yields an audited
HOLD for that decision. HOLD preserves any open position; deterministic stops
and risk exits still operate. Authentication/configuration errors abort before
a scored experiment; an interrupted or budget-limited run is incomplete and
must not appear as a completed primary comparison.

## Budget and cache

Track spending in a persistent project-local ledger shared across the initial
experiments. Serialize ledger reservations to prevent concurrent overspending.
Before sending, reserve a conservative maximum input/output charge at the
configured official standard rates ($0.15/$0.60 per million tokens). Input
reservation must be a documented upper bound including request overhead;
output reservation uses the 512-token cap. Settle using reported token usage;
retain the reservation on uncertain failures. Stop before a request whose
reservation would exceed the remaining $10 budget. No unrequested automatic
budget reset, paid retry or full-pass launch.

Cache identity includes exact model parameters, prompt/schema versions and
complete sanitized request. Different account states or cost scenarios cannot
reuse responses merely because the date/features match. Verify cached bytes
and preserve original usage; report historical generation cost separately from
new spend (a local cache hit adds no API charge).

## Audit and integration

Archive request, feature/account context actually shown, prompt hashes, model
ID and returned model identifier, parameters, raw response, validated output,
confidence, errors, cache disposition, latency, usage and estimated charges.
Link these to engine decision IDs. Replaying a saved run must use archived
responses and make zero network calls. Fingerprint prompts and LLM settings
alongside existing source/data/configuration fingerprints.

Expose separate explicitly selected E1/E2/journal runs through the CLI, with
offline replay as the default for archived artifacts. Paid execution requires
explicit selection and configured credentials; ordinary baselines remain offline.
Preserve identical feature, risk, execution and scoring boundaries for B4/E2.
Later Phase 7 implements the complete paired comparison and uncertainty analysis;
the initial pilot does not satisfy that gate.

## Required verification

Offline fake-provider tests cover structured validation, refusal/failure handling,
budget reservation and recovery, shared-ledger concurrency, exact cache identity,
artifact hashes and no-network replay. Causal tests perturb future bars and
journal records, check incomplete higher bars, and reject identifying fields.
Engine integration proves next-open execution, deterministic sizing and short
rejection. Existing mandatory anti-lookahead and 100-agent benchmark tests must
remain passing. No success/alpha claim follows from a synthetically mocked test.

## Source

Official model documentation: https://developers.openai.com/api/docs/models/gpt-4o-mini
Contract: ../../../LLM_TRADING_AGENT_BACKTEST_SPEC.md
