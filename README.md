# BTC Quant Bot 2 v1.2 - Conditional Trade Plans

**Binance USD-M BTCUSDT perpetual | 1h | GitHub Actions -> Telegram | NO order execution**

This release replaces the old Coinbase-spot research pipeline. It builds an explicit,
conditional LIMIT-entry plan with stop loss, take profit, BTC quantity, notional,
planned loss including cost reserves, isolated leverage, and a deadline. The same
plan builder is used in historical simulation and live alerts.

## Read these limits before enabling alerts

- No real-market backtest result is included in this delivery. See `reports/BUILD_STATUS.json`.
- The strict target is a **historical net-win-rate lower bound above 80%**, not an
  80% probability of winning the next trade. Passing software tests proves neither profitability nor safety.
- Your 50 USDT tolerance is treated as a **hard ceiling**. Default risk is **2% of
  current manually confirmed equity**, or **10 USDT at 500 USDT**. Leverage is at
  most **3x isolated**, and position size may be reduced further for margin.
- Stops do not guarantee the planned maximum loss. Liquidation, slippage, outages,
  fees and funding can make losses larger. The exchange liquidation price is NOT
  calculated from your account; conservative margin stress is only a screening assumption.
- Binance live HTTP 451 restrictions cannot be fixed by changing a trading rule.
  The history job uses official archives independently. Live requires an authorized
  environment that can access Binance USD-M. No proxy, VPN or venue substitution is supplied.
- Keep this repository private. State includes manually entered equity and trade-plan history.

## Quick start

1. Extract the ZIP. Replace code/config and the workflows in the existing BTC Bot 2
   repository. Do NOT overwrite the separate US-stock repository.
2. Ensure files are under **`.github/workflows/`**, not `workflows/` in the root.
3. Keep the existing Actions secrets `TELEGRAM_BOT2_TOKEN` and `TELEGRAM_BOT2_CHAT_ID`.
   No Binance account API key is needed or used.
4. Run **Bot2 - Offline Tests** and then **Bot2 - Hourly Signals -> demo**.
5. Run **Bot2 - Check Data**. `HISTORY_ONLY` means archives work but live does not.
6. Run **Bot2 - Research Backtest** with `download=true`. This can run even when
   Binance live access is blocked. Read the generated `BACKTEST_REPORT.md`.
7. Run **Bot2 - Hourly Signals -> status**. A failed statistical gate is not a crash.
8. For unvalidated observations, `paper` is available only through a manual run.
9. Only after evidence passes and live data is available, run **Bot2 - Account Settings**,
   enter your current equity, and confirm that no actual BTC position or pending
   order is open. Then use `strict`.

Full instructions: **[START_HERE.md](START_HERE.md)**.
Research interpretation: **[docs/RESEARCH_ADJUSTMENTS.md](docs/RESEARCH_ADJUSTMENTS.md)**.
Exact model/plan rules: **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)**.
Data access: **[docs/BINANCE_DATA_ACCESS.md](docs/BINANCE_DATA_ACCESS.md)**.

## What is tested

26 fixed candidates: trend-pullback, breakout, confirmed RSI divergence, BTC-direction
spread re-entry, and lead-lag. ETHUSDT/SOLUSDT are the two possible companions. BTC-only
baselines are included for the first three families. Each is evaluated at gross
reward/risk 1.5 and 2.0, with costs included separately. The companion is **context only**;
the tested trade is BTCUSDT alone, never an unannounced two-legged hedge.

One candidate is chosen on the selection period. It is frozen before its later
holdout. A failing holdout does NOT cause the code to try another candidate on the
same holdout. A companion must outperform the matching BTC-only baseline when one
exists. Selection among this fixed set does not establish a universally best pair.

## Default time split

- History / indicator warmup: January 2022 onward.
- Selection: January 2023 through May 2025.
- Holdout: June 2025 through August 2026.
- No sample is a substitute for a new forward/paper trial.

The split starts holdout after the Lancaster proposal's reported backtest ends,
but this is source-informed research, not a preregistered independent experiment.

## Alert timing

At minute 07 each UTC hour, the workflow scans the last fully closed hourly candle.
A signal candle opening at 10:00 closes at 11:00; an alert can arrive after 11:07;
its conditional limit is only allowed to activate at **12:00**, not at a historical
11:00 price. The user must check validity at activation, place/cancel the order,
and place exchange-side protection after an actual fill. The bot does none of that.

Late workflows do not backdate entries. `manual -> paper` still enforces a fresh
signal window, so running it late in the hour can correctly return no plan.

## Account confirmation and duplicate protection

An emitted strict plan locks further strict entries until you confirm that actual
positions and pending orders are flat through **Account Settings**. The lock is
reserved before Telegram delivery. An unconfirmed network delivery is NOT blindly
retried. Check Telegram/the report and your exchange before clearing it.

Equity confirmation expires after 24h for new entries. The bot never reads your
Binance balance. Withdrawals may be conservatively treated as losses unless you
review the manual account state. It monitors the candle-based hypothetical outcome
of an existing plan, not your real fill, fee tier, realized PnL or position.

## Outputs

`pair_selection.csv`, `holdout_trades.csv`, `holdout_plans.csv`, `holdout_equity.csv`,
`BACKTEST_REPORT.md`, `model.json`, `data_manifest.json`, and `run_environment.json`.
Each live run includes diagnostics and, when one is allowed, `trade_plan.json`.

No plan is sent solely to fill a daily quota. No martingale, averaging down,
pyramiding, automatic leverage changes or exchange trading endpoints are included.
