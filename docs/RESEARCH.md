# Research notes for BTC Quant Bot 2 v1.1

## Design conclusions from the literature

The project treats correlation, cointegration, lead-lag, momentum and divergence as hypotheses that require out-of-sample validation rather than as automatic edges. Crypto relationships can change across regimes, and trading costs can turn visually strong signals into negative strategies.

Important papers reviewed when designing the research protocol include:

- Sifat, Mohamad and Shariff, work on Bitcoin/Ethereum lead-lag relationships. The implication here is to test direction and stability instead of assuming one asset always leads.
- Fil and Kristoufek, *Pairs Trading in Cryptocurrency Markets*. The implication is to separate formation from trading and explicitly include costs.
- Research on cointegration/coupla-based crypto pairs. The implication is that statistical dependence alone is not a profit guarantee.
- Hourly crypto strategy research showing that transaction costs and directional market exposure can dominate nominal pair effects.
- Classical momentum and post-signal validation literature. The implication is to avoid look-ahead bias and to keep a genuine holdout.

## v1.1 provider choice

v1.0's Binance USD-M endpoints returned HTTP 451 on the user's GitHub-hosted runner. v1.1 does not bypass that restriction. It changes both historical and live market data to Coinbase Exchange public spot OHLCV so the venue is consistent between research and alerts.

Coinbase Exchange product-candle documentation:
https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles

The endpoint documents a maximum of 300 candles per request. The downloader therefore paginates smaller windows, validates hourly continuity, and stores SHA256 hashes of normalized CSVs.

## Why the peer is context, not a forced second trade

Using spot data while pretending to execute a frictionless short hedge would introduce an unmodeled borrow/funding assumption. v1.1 therefore asks a narrower question: does ETH/SOL/LINK/ADA/LTC information improve a BTC directional strategy? Pair spread and lead-lag can trigger BTC direction, but only BTC PnL is scored.

## About the 80% target

The configured 80% threshold is deliberately a historical evidence gate, not an asserted next-trade probability. A high observed win rate can coexist with poor expectancy if losses are large; therefore the gate also checks stress-cost profitability, profit factor, drawdown, active weeks, months and both BUY/SELL subsets.

No reviewed source establishes that this exact repository will win 80% of future 1h BTC trades. The real GitHub backtest and subsequent forward observations are required.
