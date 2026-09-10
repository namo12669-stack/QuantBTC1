# BTC Quant Bot 2 v1.1

Research-first Bitcoin 1-hour signal scanner for GitHub Actions + a second Telegram bot. It **does not place orders**.

## Why v1.1 exists

v1.0 used Binance USD-M endpoints. Some GitHub-hosted runners returned HTTP 451. v1.1 deliberately changes the whole research/live market-data layer to **Coinbase Exchange public spot 1h OHLCV**. It does not use a proxy, VPN, geoblock bypass, or silent mixed-venue fallback.

Historical and live signals now use the same venue and symbols:

- BTC-USD
- ETH-USD
- SOL-USD
- LINK-USD
- ADA-USD
- LTC-USD

Coinbase Exchange documents its candle endpoint with a maximum of 300 candles per request, so the downloader paginates in smaller chunks and rejects missing hourly bars rather than forward-filling them.

## What the quant tests

Four predeclared signal families are compared:

1. `pair_spread` - BTC/peer relationship dislocation and re-entry. In v1.1 this is a **BTC directional signal only**; the companion coin is context, not a required hedge leg.
2. `lead_lag` - walk-forward ridge forecast that must beat a BTC-only feature baseline on an inner validation window.
3. `divergence` - confirmed RSI divergence with non-retroactive pivots.
4. `breakout` - BTC range breakout with relative-volume and companion confirmation.

Validation chooses one candidate. The later holdout does not select a replacement if that candidate fails.

## The 80% target

`config.yaml` sets `minimum_win_rate_lower_bound: 0.80`.

This means strict mode requires the **conservative lower confidence bound of the historical net win rate** to exceed 80%, plus minimum sample size, BUY/SELL coverage, positive cost-stress return, profit factor, drawdown and month-stability checks.

It does **not** mean the next alert has an estimated 80% chance of winning. No per-alert probability calibration is implemented.

## Execution assumptions

All backtested candidates express BTC direction only. The peer is signal context. A simulated signal is known only after a completed 1h candle and the entry is delayed so a GitHub/Telegram alert is not backdated. Fee and slippage values are generic research assumptions, not Coinbase account quotes. SELL/SHORT is a research direction; spot borrowing/short execution is not modeled.

## GitHub setup

The five workflows must be under `.github/workflows/`:

- `bot2_setup.yml`
- `bot2_check_data.yml`
- `bot2_research.yml`
- `bot2_scan.yml`
- `tests.yml`

Repository secrets for the second Telegram bot:

- `TELEGRAM_BOT2_TOKEN`
- `TELEGRAM_BOT2_CHAT_ID`

Run in this order:

1. **Bot2 - Telegram Setup**
2. **Bot2 - Check Data**
3. **Bot2 - Research Backtest**
4. **Bot2 - Hourly Signals** (`status` first, then `paper`; `strict` only activates automatically if the historical evidence gate actually passes)

## Data integrity

The Coinbase public candles endpoint does not provide the same archive checksum workflow that v1.0 used. v1.1 stores SHA256 hashes of the normalized CSV files and a manifest containing source, date range and retrieval time. A restored GitHub cache is reused only when those hashes and config boundaries still match.

## Important limitations

This repository does not include a real-market backtest result. GitHub must download the data and execute the research workflow. Software unit tests only validate program behavior. Repeatedly tuning parameters after looking at the same holdout destroys its out-of-sample meaning.

See `docs/METHODOLOGY.md`, `docs/RESEARCH.md`, and `START_HERE_TH.md`.
