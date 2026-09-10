# No real-market backtest is bundled

The build environment could not complete external price/archive requests (DNS/network
resolution failure). The 161 passing tests use synthetic observations and mocked
service responses. They establish software behavior, NOT a profitable trading edge.

There is no real-market best pair, win rate, return, trade ledger or approved model in
this ZIP. Run **Bot2 - Research Backtest** after the archive check on your GitHub runner.
Only that run can generate `BACKTEST_REPORT.md`, `holdout_trades.csv`, `model.json`
and the other actual research outputs. A negative evidence result is legitimate.

Current Binance HTTP 451 restrictions on a runner are a separate access issue. This
build does not claim to remove them. Historical archive research is independent from
live API access. For live plans use only an authorized environment that can reach the
required Binance endpoints. The repository has no mixed-venue price fallback.
