# Research protocol v1.1

1. Fixed venue: Coinbase Exchange public spot 1h.
2. Fixed instruments: BTC-USD with ETH-USD, SOL-USD, LINK-USD, ADA-USD and LTC-USD.
3. Reject missing hourly bars; do not forward-fill pair history.
4. Keep signal families fixed before viewing the holdout: pair_spread, lead_lag, divergence, breakout.
5. Use validation only to choose one candidate.
6. Evaluate exactly that candidate on the holdout.
7. Include generic fee/slippage and doubled-cost stress.
8. Require the configured historical 80% lower-bound gate plus profitability/stability checks before strict alerts.
9. Never label an individual signal as having an 80% win probability unless a separate calibrated forecasting model is built and validated.
10. Any code/config change changes the fingerprint and requires research again.
