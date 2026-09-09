# Frozen baseline protocol - BTC Bot 2 v1.0.0

Prepared 2026-09-09. This is a declaration of this code's initial comparison protocol, not a prospective historical preregistration and not a claim of unseen real-data results.

1. Fixed instruments: BTCUSDT versus ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, LINKUSDT; same-venue USDT linear perpetuals, 1h.
2. Fixed four hypothesis families and default parameters in config.yaml. Twenty candidate combinations; two BTC-only technical baselines. No random search to meet a desired win rate.
3. Initial data coverage 2021-01-01 to 2026-09-01 exclusive; validation 2024; only one validation-selected candidate goes to the 2025-2026 holdout.
4. Declare net profitable-trade outcome and all exits BEFORE ranking the validation results. No TP/SL selection based on holdout win rate.
5. Record source/archive hashes, all validation candidates, BTC-only baselines, holdout trade ledger, daily-equity metrics, friction assumptions and code/config fingerprint.
6. No replacing the selected candidate after a disappointing holdout. No changing dates, costs or entry thresholds while continuing to describe the same holdout as independent.
7. Report count, win rate, mean winner/loser, expected net return, profit factor, close-marked drawdown, daily Sharpe, monthly consistency, stress costs and BUY/SELL subsets. Winning percentage alone is insufficient.
8. Historical strict admission requires the conditions in METHODOLOGY.md. Reject or hold in research-only mode otherwise. No label >90% on an individual signal.
9. Forward observation remains necessary even if the historical gate passes. Preserve failed experiments as well as successful ones. Changing the implementation invalidates the previous fingerprint.
10. Do not trade solely from a GitHub/Telegram alert. No automatic order execution is present. A pair's hedge is part of the tested strategy; removing it creates an untested strategy.

## Honest build-time result

Real price download failed due to network/DNS access in the build environment. Therefore pair ranking, historical net returns, holdout confidence and a best pair are **NOT AVAILABLE YET**. Synthetic tests verify software behavior only. Your GitHub real-data workflow produces the actual research record or an explicit provider failure.
