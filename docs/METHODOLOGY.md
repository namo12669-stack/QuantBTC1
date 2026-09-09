# Methodology and reproducibility

## 1. Target and instrument definitions

BTCUSDT USDT-margined linear perpetual is the target. Five explicitly named perpetual companions are considered. The set was chosen as a manageable research starting universe, not because any has been demonstrated superior. It has selection/survivorship bias: these are currently familiar surviving instruments, not a historical exhaustive universe including delisted contracts.

Signals arise on UTC hourly bars that have completed. One signal's direction is +1 (BUY/open long BTC) or -1 (SELL/open short BTC). A "win" means the **whole modeled trade's net return after fees, slippage and funding is greater than zero**. For a pair, both legs combined determine the result. Merely reaching a higher price at some future point is not a win label.

## 2. Data acceptance

Download monthly price/funding ZIP files from the official public archive. Verify their SHA256 CHECKSUM documents, validate schema and OHLC, parse seconds/milliseconds/microseconds explicitly, require aligned hourly grids and complete funding coverage. Do not forward-fill missing prices, invent zero funding or combine venues. Missing or denied data produces failure, not an artificial no-op backtest. Archive and processed-file hashes are retained.

Monthly archives can be revised by the publisher. The first validated cached version is preserved until its cache is deliberately removed. Retain the manifest with each experiment. Local files with a source label alone cannot pass the normal loading path: processed checksums and exact configured dates must agree.

Funding schedules may change. The archive's interval field is used when present; otherwise the validator assumes an eight-hour maximum spacing. Unsupported coverage or interval ambiguities stop rather than fabricate settlements.

## 3. Four hypotheses, fixed before the code's historical comparison

### A. Pair spread re-entry

Every 168 hours, regress the last 720 completed closes:

`log(BTC) = alpha + beta * log(peer) + residual`

Require beta in (0.1,5), residual AR(1) coefficient between 0 and 1, half-life between 2 and 120 hours, hourly-return correlation >=0.30, and Engle-Granger no-cointegration-null p<0.01 (constant, one lag, no automatic lag search). Price levels' I(1) assumption and structural stability remain limitations; the cointegration screen is not a proof or a multiplicity-adjusted economic result.

Freeze alpha/beta/residual mean and standard deviation until the next weekly refit. A signal occurs when |z| previously >=2.25 moves back inside 2.25 but remains >1, with the same sign. Positive spread: SELL BTC / BUY peer. Negative spread: BUY BTC / SELL peer. A re-entry requirement avoids immediately fighting a still-expanding extreme.

Dollar weights are `BTC=1/(1+beta)`, `peer=beta/(1+beta)`. Their signs are opposite. Gross notional sums to one; beta is a log-price elasticity, NOT a ratio of coin counts. These weights are not guaranteed dollar-neutral or market-beta-neutral.

Exit after a completed hourly close shows |z|<=0.30 or convergence across zero; risk exit if |z|>=3.75 or gross pair loss>=2%; time cap 48 completed holding hours. Execute at the scheduled next hourly open one full hour after the trigger close. Parameters remain the entry-vintage parameters while a trade is open. A close-based loss limit is not a maximum guaranteed loss.

### B. Companion lead-lag, BTC-only execution

Features: BTC and companion log returns over 1,3,6,24 hours, BTC realized volatility over 24 hours and BTC price relative to a 48-hour exponential average. Ridge regression uses standardized training features with regularization 1.0. Forecast the BTC open-to-open return over six holding hours, starting at the delayed executable entry, not the already-past signal close.

Every 168 hours use a 2160-hour rolling formation window, its last 360 hours as an inner chronological evaluation window, and an eight-hour purge to ensure labels mature before subsequent partitions/refits. All target prices used in fitting are known before the refit observation. Require improvement of inner-test MSE >=2% versus BTC-only features and rank IC>=0.05. Refit on all matured labels in the window.

Only signal if absolute predicted log return exceeds the larger of 3x assumed round-trip trading friction and 0.5x inner-test residual RMSE. Sign determines BTC direction. The peer is context, not an order. Stop/target 1.5/2 ATR; time cap six hours. This is predictive association, not causal identification or an estimate of win probability.

### C. Confirmed RSI divergence, BTC-only execution

RSI uses alpha=1/14 exponential smoothing with an EWM seed, not a claim of byte-identical platform-specific Wilder initialization. A unique price swing uses three bars on both left and right. No signal can be timestamped before the three right bars complete.

Compare consecutive same-type price swings separated by 6-72 bars. Bullish: new low at least 0.2% lower while RSI is >=5 points higher. Bearish is symmetric. At the observable confirmation bar require the latest BTC close to move in the signal direction and companion six-hour return to be non-opposing. Require finite ATR with ATR/price<3%. Stop/target 1.5/2 ATR; maximum 24 hours.

This exact rule is a testable engineering hypothesis, not an academically established 90% predictor.

### D. Breakout with companion confirmation

BTC completed close must exceed the previous 48-bar high/low (current bar excluded); completed-bar base-asset volume divided by the previous 24-bar median >=1.5; price on the corresponding side of EMA20; companion six-hour return non-opposing. ATR/price<3%. Stop/target 2/3 ATR, maximum 24 hours.

Crypto volume has intraday/weekend effects. The initial simple 24-bar median is not a fully deseasonalized activity model. It is explicitly tested after costs, not called institutional accumulation.

## 4. Chronology and selection

2021-2023 supplies formation history. Calendar 2024 is validation for comparing 5 peers x4 fixed families. BTC-only breakout and divergence are baselines. Select one candidate with the highest daily-net-return Sharpe (365-day annualization) among candidates with >=60 validation trades, positive mean net and double-cost returns, profit factor>=1.05, >=50% positive validation months and Sharpe above both zero and the strongest BTC-only baseline.

Do not replace a failed holdout candidate with the runner-up. If none passes validation, inspect the highest-ranked candidate as research-only and mark validation admission false; it cannot be approved. Only one chosen candidate is tested from 2025-01-01 to 2026-09-01 exclusive. Rolling refits in this holdout use only earlier observations and matured labels, as a live learner could.

These are chronological development/test partitions, not a claim that researchers were ignorant of all historical prices or later research. New prospective paper data should be collected independently before reliance. No Deflated Sharpe, PBO calculation or nested outer cross-validation is implemented; do not claim those from the bibliography. The held-out choice and conservative gate reduce, not eliminate, selection bias.

## 5. Event-driven execution

A signal candle at index i opens at T and closes T+1h. A scheduled alert around T+1h+7min plans entry at the open of i+2, T+2h. Closed-bar pair exits use the same additional delay. Directional native TP/SL can trigger during each holding bar; if both hit, assume stop first. Gaps beyond a stop receive the worse open. Profit targets receive the target, not favorable gap improvement.

Native orders are only a simulation assumption. The bot sends a plan, not orders. Actual stops/targets should be interpreted relative to actual fills; the backtest uses raw candle opens, then subtracts a slippage haircut. It does not replay fills, intrabar ordering, bid/ask, stop order types, spreads or target shifts caused by slippage. This mismatch is a material limitation, not execution-precision proof.

One position/pair at a time; gross exposure 1.0; six-bar cooldown after modeled exit before a new signal is eligible. Reinvest remaining equity after resolved trades. End-of-split entries require room for the entire maximum holding period plus exit delay: no unresolved losers are silently excluded at the boundary. Equity is marked at hourly closes with fees/funding accrued. Intrabar drawdown could be worse.

## 6. Costs and funding

Fees 6bp + slippage 4bp each way by traded gross notional. One bp=0.01%. A roughly unchanged full-notional trade costs about 0.20% round trip before funding; this is an assumption, not an exchange fee quotation. For pairs, BTC and peer entry notional add to one; exits are charged on each leg's exit notional. Stress doubles both costs; it does not model worst-case gaps or liquidity crises.

Positive funding rates charge signed long quantity and pay signed short quantity. Include settlements strictly after the modeled entry and at/before exit. Funding amount uses hourly open at the settlement hour as a proxy for unavailable exact historical mark price. Settlements a few milliseconds after the hour and unknown intrabar stop times create timing ambiguity; execution and funding results remain approximate.

No liquidation, margin collateral haircut, depeg, venue default, borrow availability, account fee tier, tax or size-dependent impact model. Gross exposure=1 limits modeled leverage, but short/futures losses are not guaranteed capped at posted capital or at the signal stop.

## 7. The >90% gate

Do NOT read a score, coint p-value, z-score, or correlation as probability of winning.

For overall trades and separately BUY and SELL subsets, compute:
- one-sided Wilson lower bound on historical net-winning frequency;
- a circular bootstrap with blocks of FOUR consecutive calendar weeks, including empty weeks between first/last trades;
- use the SMALLER win-rate lower bound and also require the bootstrap mean-return lower bound >0.

Family alpha is 0.05 divided across three subsets. The minimum of the two bounds is conservative relative to their component estimates, but is not a theorem establishing coverage for arbitrary nonstationary trading returns. Bootstrap repeats=2000, fixed seed.

Require >0.90 lower bound, >=200 overall trades and >=100 each direction, >=26 overall active weeks and >=16 each direction, >=12 calendar test months, profit factor>=1.25, positive double-cost returns overall and each direction, >=60% positive months, and close-marked maximum drawdown<=25%. Code/config fingerprint must match, real archive source must be verified and test end must be within 45 days. Both directions and overall must pass; the bot does not cherry-pick only the winning side after seeing test results.

This gate evaluates a historical group, not a calibrated probability for the next individual trade. A regime change invalidates extrapolation. A strategy with 95% tiny winners and rare huge losses can still fail profitability conditions. NO_VALIDATED_90_PERCENT_EDGE is an intended outcome.

## 8. Runtime integrity and operational gaps

Use one shared workflow concurrency group for research/state-changing scans. State is small JSON in a separate branch. Dry runs and demo do not create positions. Notifications are deduplicated by mode/candidate/bar plus a persisted simulated position and cooldown. A crash after Telegram accepts a message but before state persistence can still duplicate it; exactly-once delivery is not guaranteed.

Evidence expiration prevents new strict entries but does not deliberately suppress monitoring of an already recorded matching-model position. Extreme spread/funding similarly blocks new entries. Missing market data or a changed model can still prevent meaningful observations: inspect actual account risk independently. The monitor cannot know whether the user followed the entry, used the indicated hedge, or filled at the modeled price.
