# BTC Quant Bot 2 - hourly research and evidence-gated Telegram alerts

**Build status: OFFLINE LOGIC TESTED; REAL-MARKET BACKTEST NOT RUN IN THE BUILD ENVIRONMENT.**

The build environment could read research pages but could not download exchange historical data. This project therefore ships **no verified market performance, no winning pair, and no approved model**. The included GitHub research workflow downloads real archives, checks their integrity, performs the comparison and creates its report. A successful code test is not evidence of a trading edge.

Start with **START_HERE_TH.md** for the Thai installation guide. Use a NEW repository, e.g. `btc-quant-bot2`. Do not overwrite the stock-alert repository or its secrets.

## What this project does

- Hourly, closed-candle signals on BTCUSDT, using ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT or LINKUSDT as a companion.
- Four fixed hypotheses: cointegrated pair re-entry, lead-lag forecasting, confirmed RSI divergence and volume-confirmed breakout.
- One fixed candidate selected from 20 combinations using chronological validation only. No candidate substitution based on holdout results.
- Explicit distinction between **BTC-only directional trades** and **two-leg pair trades**. A pair BUY-BTC signal REQUIRES a simultaneous opposite companion leg. SELL means opening a short, not selling existing spot holdings.
- Real published funding rates, fees and slippage assumptions; conservative hourly execution and same-candle barrier handling.
- Strict mode with a historical >90% **lower-bound** gate, sample-size and profitability conditions; no guessed per-signal probabilities.
- Telegram notifications and simulated alert-position observations, not orders. No exchange trading keys, broker connection, leverage optimization, averaging down or martingale.

## What it does NOT establish

There is no known >90% next-trade probability in this release. The confidence procedure describes the historical frequency of net winners within tested groups, under statistical assumptions. It does not make the next trade safe, calibrate individual forecasts, or guarantee future profits. Even a passed gate requires independent forward validation. The historical study is retrospective, not a prospective preregistration made before those prices occurred.

The bibliography includes supportive and negative findings. The code is a deliberately simpler original implementation, **not a replication of the cited copula studies**.

## Data and execution scope

Supported venue: public **Binance USD-M USDT perpetual futures**, not Binance spot, Binance.US, Bybit, Coinbase or an unspecified broker. Symbols are instrument identifiers, not instructions to use a service where unavailable. Public archives and live API may not be accessible from every runner or jurisdiction. HTTP 403/451 stops with an explicit diagnosis; no proxy or geoblock bypass is included, and no other venue is silently substituted.

Archives: 2021-01-01 through 2026-08-31, complete monthly files with SHA256 checksums, 1h candles plus funding. Validation: calendar 2024. Single chosen holdout: 2025-01-01 through 2026-08-31. Date boundaries are in `config.yaml` and UTC. Any code/config change invalidates the stored model fingerprint.

Fees: 6 basis points and slippage: 4 basis points, **each way**, by gross traded notional. These are conservative starting assumptions, NOT a quote of an account's fee tier. Stress doubles these costs; all pair legs are included. Funding is not assumed zero, but its cash amount uses the hourly open as a proxy for the exact historical mark price.

Signals use 1h candles, but positions may last 6, 24 or up to 48 hours depending on the family. "1H" does not mean a one-hour outcome or that the bot runs continuously.

## Important clock example

A candle opens at 10:00 UTC and closes at 11:00. The workflow is requested at 11:07, subject to delay. The planned/model entry is **12:00**, not 11:00: the notification cannot trade at a price that occurred before it arrived. Entry alerts more than 25 minutes after the close are withheld. Pair close-based exits also allow an extra hour for notification. Native directional stop/target orders are a simulation assumption; **this bot cannot place those orders**.

## Four workflows to use, plus tests

| Workflow | Purpose |
|---|---|
| Bot2 - Telegram Setup | Verifies the NEW bot; reuses an existing configured Chat ID, avoiding unnecessary rediscovery |
| Bot2 - Check Data | Diagnoses archive and live data access before long jobs |
| Bot2 - Research Backtest | Downloads verified real data; compares candidates; tests one candidate; saves model and report |
| Bot2 - Hourly Signals | Every hour at minute 7; strict gate by default; manual demo/status/paper options |
| Bot2 - Offline Tests | Unit and synthetic integration tests; no network and no real performance claims |

The `mode` options in Hourly Signals are `strict`, `paper`, `demo`, `status`. Paper mode is available only via manual dispatch and always labelled as unverified. It does not claim a 90% edge. Demo sends a synthetic connection message, not a fabricated market backtest.

### Secrets for the SECOND bot only

```
TELEGRAM_BOT2_TOKEN
TELEGRAM_BOT2_CHAT_ID
```

The repository's built-in `GITHUB_TOKEN` is passed by the workflow; do not create a personal access token. Research/scan need `contents: write` to persist three JSON files on `btc-bot2-state`. No account balance, token, Chat ID or exchange key is written to that branch. Use a private repository; users with repository read access can still see logs, reports and signals.

If `.github` is omitted by an upload tool, use the identical visible copies in `WORKFLOW_COPIES/`. Create each file under `.github/workflows/` using GitHub's Add file / Create new file. Files under a root-level `workflows/` folder will not run.

## Local commands (Python 3.13)

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python main.py check-data
python main.py research --download
python main.py scan --mode status --manual --dry-run
python main.py scan --mode demo --manual
python main.py scan --mode strict --manual
```

Local mode uses `state/`. GitHub mode uses the state branch. Never switch from research paper observation to real trading just because a test passes.

## Research outputs

`BACKTEST_REPORT.md`, `pair_selection.csv`, `btc_only_baselines.csv`, per-candidate validation ledgers, one `holdout_trades.csv`, `holdout_equity.csv`, `model.json`, `data_manifest.json`, and a passive BTC benchmark. These are created by your real-data run, not bundled as fabricated results.

Model status `NO_VALIDATED_90_PERCENT_EDGE` means the evidence requirement was not met, not a connection failure. It may be the economically correct conclusion. The top candidate can still be examined as research-only, but is not promoted to strict alerts. No parameter sweep is run until a desired win rate appears.

After a strict-approved model exists, scheduled scans may still return no signal. Notifications are event-based, not forced BUY/SELL every hour. There is one daily heartbeat at 00:07 UTC when a run succeeds; delayed/missed GitHub jobs can delay it.

## Operational limitations

GitHub scheduling is best effort, not an execution service. It can be delayed or dropped; public inactive repositories may have schedules disabled. Monitor Actions failures. Exchange/API outages can prevent both entries and exit observations. An existing alert-position is not your brokerage position; check the actual account independently. Use venue-native risk controls where appropriate. Do not depend on Telegram to enforce stops.

The current freshness limit is 45 days after the end of the holdout. To extend the study, preserve the original report and record all changes; repeatedly retuning on the same historical holdout is not new independent evidence. Changing assumptions during an open alert-position can prevent safe model monitoring. Review/close actual positions and deliberately manage state before replacing a model.

See `docs/METHODOLOGY.md`, `docs/RESEARCH.md`, `docs/RESEARCH_PROTOCOL.md`, `SECURITY.md` and `reports/BUILD_STATUS.json`.
