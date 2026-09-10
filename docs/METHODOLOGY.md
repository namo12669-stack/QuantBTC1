# Declared research and execution protocol - v1.2

## Scope and evidence status

This implementation studies BTCUSDT USD-M perpetual plans on Binance. BTC is the
only proposed position. ETHUSDT or SOLUSDT can supply context, not a second hedge
order. The paper/spot results of other authors are never imported as this bot's
performance. No claim of an optimal pair or an 80% next-trade probability is made.
See `RESEARCH_ADJUSTMENTS.md` for what each supplied paper actually supports.

No actual market backtest was completed in the build environment. The repository
contains code and synthetic software checks, not a pre-approved model. The GitHub
research workflow must acquire and verify real observations before a model exists.

## Data and clocks

- Trade-price candles: official Binance USD-M monthly 1h klines for BTC/ETH/SOL.
- BTC mark-price candles: official monthly 1h markPriceKlines.
- BTC funding events: official monthly fundingRate archives, including declared
  interval hours when supplied. No invented zero-funding events.
- Declared range: 2022-01-01 through 2026-09-01 exclusive, all UTC.
- Live inputs: public Binance Futures endpoints only. Never substitute spot prices
  or another exchange when access fails. No order/account endpoints are called.
- Each original ZIP must match the publisher's SHA256 checksum. Normalized CSV
  hashes and data-quality diagnostics are retained in the manifest. Cached original
  checksum files preserve the retrieved version; they are not a continuous check
  for a later publisher correction. Clear that raw cache to refresh a revision.
- UTC candle open times remain on a complete hourly grid. Missing hours are NaN.
  Indicators and models restart on continuous observed segments, not compressed time.
  Missing fraction above 0.5% or a run longer than 24h stops the affected dataset.
- Coincident peer timestamps are required; price levels are never forward-filled.

A sample availability check is not verification of an entire historical dataset.
The complete download stage validates every requested archive and the funding clock.
An archive correction, code edit or changed configuration requires a new research run.

## Fixed candidates and statistical split

The default list contains 26 candidates:

| Family | Context choices | Gross TP/SL multiples | Count |
|---|---|---|---:|
| Trend pullback | BTC-only, ETH, SOL | 1.5, 2.0 | 6 |
| Breakout/volume | BTC-only, ETH, SOL | 1.5, 2.0 | 6 |
| Confirmed RSI divergence | BTC-only, ETH, SOL | 1.5, 2.0 | 6 |
| Pair-spread re-entry | ETH, SOL | 1.5, 2.0 | 4 |
| Lead-lag setup | ETH, SOL | 1.5, 2.0 | 4 |

2022 supplies initial history. Candidate selection uses 2023-01-01 to 2025-06-01
exclusive. ONE candidate is frozen for the holdout 2025-06-01 to 2026-09-01 exclusive.
The holdout begins after the end of the Lancaster proposal's reported sample.
This is source-informed development, not an independently preregistered trial.

Selection is based on net daily Sharpe (365-day annualization), subject to positive
net expectancy, minimum 40 trades, profit factor >=1.05, at least half positive
months, positive double-cost sensitivity and no unobserved trade/margin-stress cases.
For the first three families, a peer variant must improve the matching BTC-only
selection Sharpe. Pair-only families must beat the best declared BTC-only benchmark;
that comparison is not an identical-model ablation. Lead-lag also tests its peer
forecast against a BTC-only forecast in its inner historical window.

If nothing passes selection, the best relative candidate may be shown for diagnosis
and manually invoked PAPER mode. It cannot be strict-approved even if its diagnostic
holdout happens to look good. Holdout results never select a replacement runner-up.
Repeatedly changing parameters after seeing the same holdout consumes its independence.
New data and a versioned forward/paper trial are still needed.

## Signal definitions

These are explicit implementation hypotheses, not rules certified by the papers.

**Trend pullback.** EMA 27/125, Wilder ADX 90 >=14 and ATR14; EMA separation >=0.2 ATR;
price crosses back over the fast EMA in the prevailing EMA direction. At least 500
continuous hours are needed. Peer variants require same-direction 6h return and
168h return correlation >=0.30.

**Breakout/volume.** Prior 48-hour range (excluding the signal bar), volume relative
to its past history >=1.5, directional finish, volatility and optional peer confirmation.

**Divergence.** Confirmed local pivots with three bars on each side, separated by
6-72 hours. Minimum price difference 0.2% and RSI difference 5 points. The second
pivot is only available after its three confirming bars. Prefix/causality tests ensure
future data cannot retroactively create earlier signals.

**Pair spread.** Rolling 720h log-price formation sample, return correlation >=0.30,
cointegration test p<0.01 and estimated half-life 2-120h; re-entry after a spread
extreme beyond 2.25 standard deviations. It is a hypothesis about BTC direction,
not a self-financing two-leg statistical-arbitrage result. Correlation, a p-value
and a spread z-score are not next-trade success probabilities.

**Lead-lag.** Rolling 2160h sample, 360h inner chronological validation, past return
features, ridge forecasts and matured 6h target labels; refits every 168h. Require
at least 2% inner MSE improvement over a BTC-only model, positive information
coefficient above 0.05, and a forecast exceeding declared cost/noise thresholds.
A 6h forecast triggers a setup; realized success is measured using the same
conditional-entry and bracket rules below, not by simply counting forecast signs.

Pair/lead-lag coefficients can refit causally inside a frozen candidate. The candidate
family, peer, settings and TP/SL variant do not change based on holdout results.

## Entry, SL, TP and order expiry

A signal candle opening at T closes at T+1h. Its plan may be alerted shortly after
that close, but the earliest permitted activation is T+2h. Backtests never fill at
the close price before the notification could exist.

The limit entry is close minus direction times 0.2 ATR. The initial stop distance is
the largest of 1.5 ATR, a 12h structural extreme with a 0.25 ATR buffer, and 0.3% of
entry. For divergence the confirmed pivot is also respected. A stop wider than
4 ATR or 3% of entry is rejected; it is not moved closer just to fit a desired size.

TP is 1.5 or 2.0 times the stop distance as declared by the frozen candidate. Both
prices and quantity are rounded against conservative tick/step constraints. Net
reward/risk must remain >=1.10 after the explicit cost and funding reserve.
One fixed SL, one fixed TP and a 24h maximum holding time are used. There is no
partial-profit, breakeven, trailing-stop or martingale rule hidden in the code.

Unfilled entries expire two hours after activation. The user must cancel the order;
the bot does not send a cancellation to Binance. Invalidation of SL or TP before
activation cancels the setup. Do not place early or chase a missed entry.

## Fill and path simulation

- Require at least one tick of trade-through for a limit fill; a mere touch is not
  assumed to fill a queue. Fill price is the stated limit, not a better hindsight price.
- If both SL and TP are reachable in a candle, SL takes precedence.
- No target profit is awarded on the entry candle; the high/low may predate the fill.
- A later adverse opening gap while the order is already working can fill then stop
  at the worse opening price. It is not retroactively cancelled using that gap.
- Contract/Last Price triggers the simulated stop; a gap pays the adverse opening
  price. TP requires a trade-through. Time exits use the open after the hold period.
- Funding uses the actual historical rate multiplied by mark price at the opening
  of its hour. That valuation is an approximation, not the exact settlement mark.
  In an ambiguous entry hour, adverse funding is charged and beneficial funding is
  not credited. Direction is respected, and the stress run charges absolute funding.
- Fees and slippage are cash debits on entry and exit notionals. Defaults are 6bps
  fee plus 4bps slippage per side; they are study assumptions, not the user's fee tier.
- The double-cost sensitivity keeps the same fills and sizes and doubles trading
  costs plus absolute funding. It is NOT a fully rebalanced high-cost counterfactual.
- Gaps in a possible fill/held path remain as explicitly unobserved adverse margin-loss
  sensitivity cases. They are not invented observed liquidations, and they block
  strict approval. They are never silently dropped to improve the win rate.

One pending/held plan at a time is simulated, with a six-hour cooldown. Boundary
signals without a complete predetermined exit horizon are excluded by the period
cutoff rule, not by whether they later win or lose.

## Position sizing and margin

The account starts at 500 USDT. Default planned risk is min(2% of current equity,
50 USDT). Quantity equals risk divided by stop distance plus fee/slippage/funding
reserve per BTC, rounded down. A 10bps funding reserve is included for plan sizing;
real historical events determine backtest cash flow.

Among leverage settings 1, 2 and 3, the planner maximizes admissible risk-sized quantity
and chooses the smallest leverage able to support that quantity. Initial margin plus
cost reserve must be <=60% of equity; absolute notional cap is 1500 USDT. Margin caps
can reduce actual risk below 10 USDT. Risk is never increased to spend the full 50 ceiling.

An assumed 1% maintenance allowance and 1% liquidation-fee buffer create a conservative
MARGIN STRESS PRICE. Its distance must exceed three stop distances. It is **not** the
Binance liquidation formula or a verified liquidation price. A simulated stress hit
is retained and blocks approval. Account-specific brackets, fee tier, auto-add-margin,
ADL and detailed liquidation execution are not reconstructed. The user must check
actual liquidation on Binance and place exchange-side protection after a real fill.
The stop-loss amount is a plan, not a guaranteed maximum realized loss.

Historical exchange filters are not reconstructed. `research_rules` is a clearly
labeled set of assumptions. Fresh live `exchangeInfo` must match those fields before
a live plan is sent. A mismatch stops the plan and requires review and a new research run.

## Evidence gate

Both the overall result and the proposed direction must pass. Defaults include:
150 holdout trades total, 60 in the proposed side, 12 calendar months, 24 active weeks
overall /12 per side, profit factor >=1.2, at least 58% positive months, conservative
intrabar drawdown <=25%, positive double-cost result, and no unobserved/margin-stress
cases. A side cannot borrow the other side's win rate.

The historical win-rate lower bound is the smaller of one-sided Wilson and a
four-calendar-week circular block-bootstrap bound. The declared family alpha 0.05
is divided by six checks. Bootstrap expectancy in net R must have a positive lower
bound. A historical win lower bound must be STRICTLY above 80%.

Block methods do not prove stationarity, independence from model development or
future profitability. Six-check adjustment is a declared diagnostic policy, not a
claim that every possible data-snooping risk has been eliminated. No calibrated
next-trade probability is supplied. Zero valid candidates is a legitimate result.

## Live policies that are not broker execution

Hourly live gates additionally reject stale quotes, wide bid/ask spread, excessive
Mark/Last basis, adverse funding, expired signals, changed filters and invalidated
levels. Those current quote gates are NOT reconstructed over full historical books;
therefore the displayed historical frequency is for the declared candidate/side,
not a calibrated frequency for the exact extra-filtered live subset.

Actual balance/fills/orders are not read. Before strict plans, equity/flat status
must be manually confirmed within 24h. One strict plan reserves its planned risk and
locks further plans until the user confirms that real orders/positions are flat.
Daily/weekly notification budgets reserve all sent risk (4%/10%), plus reported losses.
Backtests use realized simulated loss budgets (4%/10%). The live reservation policy is
intentionally stricter and can skip historically simulated trades. Treat historical
performance as candidate evidence, not the actual alert user's account track record.

A 20% drawdown from the manually tracked account peak pauses new plans. Changes in
reported equity are not an account audit; deposits/withdrawals require separate
manual interpretation. Telegram/network ambiguity never justifies a blind duplicate
entry. A reserved plan may remain locked even if delivery failed: review it manually.

The source, schema, code/config fingerprint and evidence age must match. Evidence
expires 45 days after its test end. Demo never creates evidence or an active lock.
Manual PAPER mode can show unvalidated plans; scheduled runs are always STRICT.
