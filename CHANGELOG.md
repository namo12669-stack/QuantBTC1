# Changelog

## 1.1.1 - 2026-09-10

- Replaced Binance USD-M live/archive dependency with Coinbase Exchange public spot OHLCV after GitHub runner HTTP 451 failures.
- Historical and live research now use the same `coinbase_exchange_spot` venue.
- Symbols changed to BTC-USD with ETH-USD, SOL-USD, LINK-USD, ADA-USD and LTC-USD peers.
- Pair-spread relationships now create BTC-direction signals only; no fabricated companion short leg or perpetual funding model on spot data.
- Historical evidence target changed from 90% to 80% lower-bound target as requested; still not a next-trade probability.
- Added public level-1 spread gate, provider diagnostics for every configured product, paginated candle downloads and normalized CSV SHA256 manifest.
- Cached processed data can be reused only when manifest/range/symbol/hash checks pass.
- Updated Telegram wording and research report for spot data.
- Offline suite: 98 tests passing at build time.

## 1.0.0

Initial research-first BTC 1H prototype.
