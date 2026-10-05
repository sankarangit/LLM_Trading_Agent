# GPT-4o mini historical pilot

The Phase 4 integration supports llm_only, stats_llm and stats_llm_journal.
Primary stats_llm has no journal. Risk/execution/corporate-action accounting
are shared with deterministic baselines. Initial commands are pilot-only;
walk-forward, final holdout and the complete paired comparison remain pending.

## Set the key privately in the invoking PowerShell

```powershell
Set-Location 'D:\ICICI-NRI-AC\AQ100\LLM_Trading_Agent'
$tradingApiSecret = Read-Host 'OpenAI API key' -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $tradingApiSecret).Password
Remove-Variable tradingApiSecret
```

The hidden prompt keeps the key out of PowerShell history. Do not paste the key
into chat or configuration files. This sets it only in the current process
environment inherited by Python. API access/billing must be enabled separately.

## Run the initial paired-instrument pilot

```powershell
.\.venv\Scripts\python.exe .\main.py backtest --config .\config\research-SPY.json --experiment stats_llm --allow-api --pilot-decisions 20
.\.venv\Scripts\python.exe .\main.py backtest --config .\config\research-GLD.json --experiment stats_llm --allow-api --pilot-decisions 20
.\.venv\Scripts\python.exe .\main.py llm-budget
Remove-Item Env:\OPENAI_API_KEY
```

Each command has 20 decisions beginning at the approved 2005 development
boundary plus the next session for pending fills. Additional end-session
strategy calls produce HOLD without API requests. Up to 50 preceding sessions
are warmup only. QQQ remains blocked. No holdout performance is read or scored.
Ordinary baseline commands do not use the key, provider or ledger.

The model uses temperature 0, a 512-token output ceiling and a 30-second timeout.
Confidence is logged, not used for sizing. The model's horizon must be null.
Invalid/refused/truncated output or transient request failure gives HOLD;
authentication/configuration and missing/invalid usage abort an incomplete run.
There are no automatic paid retries. An explicit rerun may retry an uncached
failure and consumes further budget; it does not reset the original ledger.
Initial paid scope checks require the approved daily SPY/GLD 2005-2014
development settings before resolving credentials. Synthetic test providers
are injected explicitly by tests and cannot redirect the shared paid ledger.

## Spending and reproducibility

Both assets share data/cache/llm-budget.sqlite and a $10 cap. Reserving a full
128,000-token input ceiling plus 512 output tokens costs $0.0195072 at configured
rates; successful responses settle to reported usage. Failed uncertain calls
retain that maximum reservation, so the remaining ledger budget is conservative.
This is a local spending guard at recorded rates, not an account-wide billing
limit; external calls or provider price changes are outside its accounting.
No automatic budget reset or full-pass launch exists.

Exact-request cache hits have zero additional API spend. Model settings,
prompt/schema, features and account state form the cache key. Different cost
scenarios reuse responses only when the complete sanitized request is identical.
Initial successful run paths contain llm_audit.jsonl, prompt.txt, launch.json,
incremental request_audit, engine artifacts and hashed metadata. Interrupted
runs keep INCOMPLETE, prearchived configuration/data/source/prompt and raw
request evidence. Received HTTP bodies are retained as base64 audit fields,
including malformed UTF-8/JSON bodies. Metadata marks pilot_only.

Use the returned run path:

```powershell
.\.venv\Scripts\python.exe .\main.py report --run-path '<returned run path>'
.\.venv\Scripts\python.exe .\main.py replay --run-path '<returned run path>'
Start-Process '<returned run path>\report.html'
```

Replay uses archived responses only; it never resolves a key or sends network
requests. Source and prompt fingerprints must match. After later code changes,
restore the archived source.zip to a separate directory for exact replay.
Inspect pilot usage/failures before selecting a full paid development pass.
Pilot P&L is not proof of incremental trading value.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use injected fake providers and synthetic fixtures. They do not make
paid API requests. They include strict output, prefix/future perturbation,
scale-invariance, journal isolation, concurrent budget reservations, local
cache integrity, next-open execution and archived replay checks.

Official API references:
https://developers.openai.com/api/docs/models/gpt-4o-mini
https://developers.openai.com/api/docs/guides/structured-outputs
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
