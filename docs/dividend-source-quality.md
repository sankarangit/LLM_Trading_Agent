# Development distribution-source gate

Source captures: `data/dividends/20261003T133059Z`.
All original public responses are retained with SHA-256 metadata.
Only distribution events in 2005-2014 are prepared for scoring.

SPY: State Street's `spdr-etf-historical-distributions.xlsx` contains all
40 ex-dates found in the captured Yahoo development history. Extracted dates,
full-precision dividend plus capital-gain cash amounts, and payable dates are
in `spy-issuer-development.csv`; the normalized, immutable accounting input
is `SPY-development.json`. Primary source:
https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx
The independent public payment tables agree on overlapping payable dates.
The first downloaded historical PDF was DIA-only; it is not SPY evidence.

GLD: zero source distribution events and no scored-period split events.
`GLD-development.json` is a complete empty distribution input, not missing data.

QQQ: Yahoo contains 41 development distribution events. The downloaded
DividendHistory and Slickcharts tables together have payment dates for 39.
The unmatched events are 2010-06-25 ($0.089/share) and 2011-12-27
($0.049/share). Other public tables show blank dates or inconsistent dates
for these events. Their cause is not established. The issuer's old product
URL now redirects to a current page without the required historical table.
Search-index snippets are not a complete archived replacement dataset.

`QQQ-development.json` explicitly has `complete: false` and records the errors.
The CLI refuses QQQ research before calling the engine. No two events are
deleted, merged with neighboring distributions, or assigned guessed dates.

Daily timestamps identify a payment date, not intraday fund availability.
Normalized cash settlement uses that session's actual close; the receivable
is included in equity from ex-date open, but excluded from spendable cash
until settlement. Sales on ex-date retain entitlement; buys on ex-date do not.
Unpaid entitlements remain receivables when the scored window ends, so no
future price bars are needed to value them. Taxes and cash interest are absent
from this approved simulated capital/cost model.

Resolution still required for QQQ: reliable complete corporate-action history
that explains both unmatched events. Any removal or replacement requires an
explicit, documented source-policy decision; the adapter cannot invent it.
