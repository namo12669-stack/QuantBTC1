# Changelog

## 1.2.0 - 2026-09-10

A new research/conditional trade-plan pipeline, not a patch declaring the old spot
model profitable.

### Research and plans

- Binance USD-M BTCUSDT perpetual for both historical research and live observations.
- Official price, mark-price and funding archives; independent historical/live checks.
- 26 declared candidates, BTC-only benchmarks, ETH/SOL context, fixed chronological
  selection and a frozen later holdout. No externally reported win rate imported.
- Trend-pullback adaptation added; no gold factor forced from the uploaded Thai-gold
  thesis. Source findings and implementation hypotheses are documented separately.
- Conditional limit entry, structural/ATR stop, one TP, activation/expiry/time stop,
  quantity, USDT risk, margin and 1-3x isolated leverage in Telegram plans.
- Default account 500 USDT, risk 2% (<=10 USDT initially), hard ceiling 50 USDT;
  leverage and allocation constraints can reduce risk further.
- Fee/slippage/funding reserves, actual historical funding, stop-first and trade-through
  fill rules, conservative gap/margin sensitivities, no entry-bar target profit.
- Aggregate-dollar profit factor, side-specific historical lower bounds and net
  expectancy checks; NO next-trade probability claim or prevalidated model.

### Operational safeguards

- Binance live HTTP 451 still requires an authorized accessible environment. No
  Coinbase fallback, proxy or assumption that a code patch fixes provider policy.
- Optional `BOT2_LIVE_RUNNER` variable for an authorized self-hosted runner.
- New Account Settings workflow: current equity and explicit flat confirmation.
- Active-plan lock, conservative notification-risk reservation, stale account/evidence
  gates and no blind duplicate after a delivery timeout.
- State uses `btc-bot2-v12-state`; old venue/schema/fingerprint cannot carry approval.
- Immutable GitHub SHA for state branch creation retained; no unsafe default_branch
  assumption. Same workflow filenames and existing Bot2 Telegram secrets retained.
- Correct `.github/workflows` files plus text copies and a local PowerShell path helper.
- Pinned dependencies, offline tests and a build-status record. Real-market downloading
  could not complete in the build environment; no real-market backtest is bundled.

### Remaining limitations

1h OHLC is not order-book replay. Funding valuation within an hour is approximate.
Exchange historical filters, user fee tier, account liquidation brackets, ADL and
actual fills are not reconstructed. Current quote filters and conservative live
risk reservations are additional restrictions, not a separately validated account
track record. Paper mode is manually invoked and clearly unvalidated.
