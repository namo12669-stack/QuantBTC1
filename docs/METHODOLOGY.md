# Methodology - v1.1

## Market and target

The target is BTC direction on **Coinbase Exchange BTC-USD spot 1h candles**. Companion products are ETH-USD, SOL-USD, LINK-USD, ADA-USD and LTC-USD. They are explanatory/signal inputs, not automatically traded legs.

A `BUY` signal means the research model takes positive BTC direction. A `SELL` signal means negative BTC direction. The repository does not implement spot borrowing, derivatives execution or a broker connection.

## Data

Historical and live candles are fetched from the same Coinbase Exchange public REST venue. The documented endpoint limits a single request to at most 300 candles, so v1.1 paginates using smaller windows. OHLCV is normalized to UTC 1h bars. Missing bars, conflicting duplicates, invalid OHLC or non-hour timestamps abort the research instead of being forward-filled.

Coinbase does not provide an archive checksum file for this REST history endpoint. The repository therefore stores SHA256 of every normalized CSV plus source/range/retrieval metadata. This verifies cached bytes have not changed after download; it is not a provider-signed proof of historical correctness.

## Signal families

### Pair spread

A rolling log-price relationship is estimated using only past formation data. Cointegration p-value, spread half-life and return correlation are gates. Entry requires a prior extreme spread followed by partial re-entry. In v1.1 the inferred direction is tested on BTC only; the peer is context.

### Lead-lag

The model predicts a later BTC open-to-open log return from lagged BTC and peer features. A ridge model using peer features must improve mean-squared error over a BTC-only feature model and meet a minimum inner rank correlation before forecasts are considered. Every training target must mature before the prediction timestamp.

### RSI divergence

Pivots require left and right confirmation bars. The signal timestamp is the first time the second pivot can actually be known. The algorithm therefore does not retroactively place the alert at the visual low/high.

### Breakout

BTC close must exceed the prior rolling range, relative volume must clear its threshold, price must agree with EMA direction, and the companion return cannot oppose the breakout direction.

## Validation and holdout

The research window is split into formation history, validation and holdout. Candidate selection occurs on validation. Only the selected candidate is evaluated on holdout; a poor holdout result does not trigger replacement by the second-best candidate.

BTC-only breakout/divergence baselines are computed so a peer-based candidate must add value beyond simple BTC-only alternatives on the selection metric.

## Costs and timing

The backtest includes generic fee and slippage assumptions on BTC notional and doubles them in cost stress. Funding is not included because this version uses spot market data. Signals are generated only after a completed hourly candle; simulated entry is delayed so the backtest never fills before a scheduled Telegram workflow could have known the signal.

Stop/target tests use OHLC. If both could be touched in the same candle, the stop is assumed first. This is conservative but still not tick/order-book replay.

## Historical 80% evidence gate

Strict mode requires the configured conservative lower bound on historical net win rate to exceed 80% for overall, BUY and SELL subsets, with sample-size and active-week minimums. It also requires positive stress return, minimum profit factor, acceptable close-marked drawdown and sufficient positive months.

Confidence checks use the lower of a one-sided Wilson bound and a calendar-week block bootstrap bound. This describes uncertainty around a historical group. It does **not** calibrate the probability that the next individual alert wins.

## Main limitations

- Survivorship/researcher choice in the fixed peer universe.
- No order-book replay or actual account fees.
- No short-borrow/derivatives model for SELL execution.
- No news, liquidation, options or on-chain features in v1.1.
- Repeated parameter tuning after inspecting the holdout invalidates its independence.
- Market regime changes can destroy a historical relationship.
