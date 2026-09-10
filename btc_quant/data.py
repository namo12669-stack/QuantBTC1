"""Coinbase Exchange public spot OHLCV provider for v1.1.

This module deliberately avoids proxy/bypass behavior. Historical research and live
signals use the same venue (Coinbase spot) so a provider switch cannot silently
change the market being modeled.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .common import DataError, HOUR, utc, write_json

API = "https://api.exchange.coinbase.com"
GRANULARITY_SECONDS = 3600
MAX_CANDLES_PER_REQUEST = 300
# Keep below the documented 300-candle maximum and avoid edge ambiguity.
CHUNK_HOURS = 250


class PublicClient:
    def __init__(self, timeout: int = 25, retries: int = 3, pause_seconds: float = 0.18):
        self.timeout = int(timeout)
        self.retries = int(retries)
        self.pause_seconds = float(pause_seconds)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "BTC-Quant-Research/1.1 (public-market-data; no-trading)",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        })

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt + 1 == self.retries:
                    raise DataError(
                        f"NETWORK_UNAVAILABLE {type(exc).__name__}; data request was not completed"
                    ) from None
                time.sleep(min(2 ** attempt, 8))
                continue

            if response.status_code in (403, 451):
                raise DataError(
                    f"PROVIDER_ACCESS_DENIED HTTP {response.status_code}; use an authorized, supported environment. "
                    "No proxy/bypass is supplied."
                )
            if response.status_code == 404:
                raise DataError("COINBASE_PRODUCT_OR_ENDPOINT_NOT_FOUND HTTP 404")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < self.retries:
                    try:
                        delay = float(response.headers.get("Retry-After", 2 ** attempt))
                    except ValueError:
                        delay = float(2 ** attempt)
                    time.sleep(min(max(delay, self.pause_seconds), 30.0))
                    continue
            if not response.ok:
                raise DataError(f"PROVIDER_HTTP_{response.status_code}")
            if self.pause_seconds:
                time.sleep(self.pause_seconds)
            return response
        raise DataError("PROVIDER_RETRY_EXHAUSTED")

    def json(self, url: str, params: dict | None = None):
        response = self.get(url, params)
        try:
            return response.json()
        except ValueError:
            raise DataError("PROVIDER_INVALID_JSON") from None


def validate_bars(df: pd.DataFrame, contiguous: bool = False) -> pd.DataFrame:
    out = df.copy().sort_index()
    required = ["open", "high", "low", "close", "volume"]
    if not set(required).issubset(out.columns):
        raise DataError("Candle schema missing required OHLCV fields")
    if not isinstance(out.index, pd.DatetimeIndex) or out.index.tz is None:
        raise DataError("Candle times must be timezone-aware UTC")
    out.index = out.index.tz_convert("UTC")
    out.index.name = "time"

    if out.index.has_duplicates:
        dup = out[out.index.duplicated(keep=False)]
        for _, group in dup.groupby(level=0):
            if group[required].nunique(dropna=False).max() > 1:
                raise DataError("Conflicting duplicated candles")
        out = out[~out.index.duplicated(keep="first")]

    if out.empty or not np.isfinite(out[required].to_numpy(dtype=float)).all():
        raise DataError("Empty or non-finite candle data")
    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataError("Non-positive price")
    if (out["volume"] < 0).any():
        raise DataError("Negative volume")
    if (out["high"] < out[["open", "close", "low"]].max(axis=1) - 1e-8).any():
        raise DataError("OHLC high inconsistency")
    if (out["low"] > out[["open", "close", "high"]].min(axis=1) + 1e-8).any():
        raise DataError("OHLC low inconsistency")
    if (out.index != out.index.floor("h")).any():
        raise DataError("Candle is not aligned to a UTC hour")
    if contiguous and len(out) > 1 and not (np.diff(out.index.asi8) == HOUR.value).all():
        missing = pd.date_range(out.index[0], out.index[-1], freq="h", tz="UTC").difference(out.index)
        sample = ", ".join(map(str, missing[:3]))
        raise DataError(f"MISSING_HOURLY_BARS: no forward-fill is allowed; examples: {sample}")
    return out


def normalize_coinbase_candles(payload) -> pd.DataFrame:
    """Normalize Coinbase Exchange candle arrays.

    Exchange REST returns: [time, low, high, open, close, volume].
    """
    if not isinstance(payload, list) or not payload:
        raise DataError("Coinbase candle response is empty")
    rows = []
    for row in payload:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise DataError("Coinbase candle schema mismatch")
        rows.append(row[:6])
    raw = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
    idx = pd.to_datetime(pd.to_numeric(raw["time"], errors="raise"), unit="s", utc=True)
    out = pd.DataFrame(index=pd.DatetimeIndex(idx, name="time"))
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(raw[col], errors="raise").to_numpy(dtype=float)
    return validate_bars(out)


def _iso(ts: pd.Timestamp) -> str:
    return utc(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_candles(client: PublicClient, product: str, start, end) -> pd.DataFrame:
    """Fetch [start, end) 1h candles by paginating below Coinbase's 300-candle cap."""
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError("start must be before end")
    frames = []
    cursor = start
    while cursor < end:
        stop = min(cursor + pd.Timedelta(hours=CHUNK_HOURS), end)
        payload = client.json(
            f"{API}/products/{product}/candles",
            {"granularity": GRANULARITY_SECONDS, "start": _iso(cursor), "end": _iso(stop)},
        )
        frame = normalize_coinbase_candles(payload)
        # Coinbase may include observations slightly outside the requested range.
        frame = frame.loc[(frame.index >= cursor) & (frame.index < stop)]
        if frame.empty:
            raise DataError(f"{product}: no candles for {_iso(cursor)} to {_iso(stop)}")
        frames.append(frame)
        cursor = stop
    out = validate_bars(pd.concat(frames), contiguous=True)
    out = out.loc[(out.index >= start) & (out.index < end)]
    expected = int((end - start) / HOUR)
    if len(out) != expected:
        raise DataError(f"{product}: expected {expected} hourly candles, received {len(out)}")
    return out


def fetch_book(client: PublicClient, product: str) -> dict:
    payload = client.json(f"{API}/products/{product}/book", {"level": 1})
    try:
        bid = float(payload["bids"][0][0])
        ask = float(payload["asks"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        raise DataError(f"{product}: invalid level-1 book response") from None
    if bid <= 0 or ask < bid:
        raise DataError(f"{product}: invalid bid/ask")
    mid = (bid + ask) / 2.0
    return {"bid": bid, "ask": ask, "spread_bps": (ask - bid) / mid * 10000.0}


def download_history(config: dict, data_dir: Path, report_dir: Path) -> None:
    cfg = config["data"]
    start, end = utc(cfg["start"]), utc(cfg["end_exclusive"])
    if end > pd.Timestamp.now(tz="UTC").floor("h"):
        raise DataError("Historical research end must be fully in the past")
    client = PublicClient(cfg["timeout_seconds"], cfg["retries"], cfg.get("pause_seconds", 0.18))
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    # GitHub Actions may restore a previously verified processed-data cache.
    # Reuse only if the manifest, date range, symbols and SHA256 checks all match.
    if (data_dir / "manifest.json").exists():
        try:
            load_history(config, data_dir)
            from .common import read_json
            cached_manifest = read_json(data_dir / "manifest.json", {})
            write_json(report_dir / "data_manifest.json", cached_manifest)
            print("REUSING VERIFIED COINBASE SPOT DATA CACHE", flush=True)
            return
        except (DataError, ValueError, KeyError):
            print("Cached processed data is incomplete or stale; downloading again.", flush=True)

    manifest = {
        "venue": "coinbase_exchange_spot",
        "interval": "1h",
        "source": "real_coinbase_spot_api",
        "start": str(start),
        "end_exclusive": str(end),
        "retrieved_at": str(pd.Timestamp.now(tz="UTC")),
        "integrity": "normalized CSV SHA256; provider does not supply archive checksums for this endpoint",
        "symbols": {},
    }
    for product in [cfg["bitcoin"], *cfg["peers"]]:
        print(f"DOWNLOAD {product} {start} -> {end}", flush=True)
        bars = fetch_candles(client, product, start, end)
        path = data_dir / f"{product.replace('-', '_')}_1h.csv"
        bars.to_csv(path)
        manifest["symbols"][product] = {
            "bars": len(bars),
            "first": str(bars.index[0]),
            "last": str(bars.index[-1]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest["status"] = "VERIFIED_NORMALIZED_DATA"
    write_json(data_dir / "manifest.json", manifest)
    write_json(report_dir / "data_manifest.json", manifest)


def load_history(config: dict, directory: Path) -> tuple[dict, dict]:
    from .common import read_json

    manifest = read_json(directory / "manifest.json", {})
    if manifest.get("source") != "real_coinbase_spot_api" or manifest.get("status") != "VERIFIED_NORMALIZED_DATA":
        raise DataError("REAL_COINBASE_SPOT_MANIFEST_REQUIRED")
    start, end = utc(config["data"]["start"]), utc(config["data"]["end_exclusive"])
    if utc(manifest.get("start")) != start or utc(manifest.get("end_exclusive")) != end:
        raise DataError("Manifest date range does not match config")

    prices, funding = {}, {}
    for product in [config["data"]["bitcoin"], *config["data"]["peers"]]:
        path = directory / f"{product.replace('-', '_')}_1h.csv"
        item = manifest.get("symbols", {}).get(product, {})
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            raise DataError(f"{product}: processed data checksum mismatch; redownload from provider")
        p = pd.read_csv(path, index_col="time", parse_dates=True)
        p.index = pd.to_datetime(p.index, utc=True)
        p = validate_bars(p, contiguous=True)
        if p.index[0] != start or p.index[-1] + HOUR != end:
            raise DataError(f"{product}: history range does not match config")
        prices[product] = p
        # Spot v1.1 has no perpetual funding component. Keep an empty table so
        # downstream interfaces stay explicit rather than fabricating zero events.
        funding[product] = pd.DataFrame(columns=["rate"], index=pd.DatetimeIndex([], tz="UTC", name="time"))

    reference = prices[config["data"]["bitcoin"]].index
    if not all(reference.equals(prices[p].index) for p in prices):
        raise DataError("Historical series are not perfectly aligned; no forward-fill is allowed")
    return prices, funding


def live_history(config: dict, symbols: list[str], now=None) -> tuple[dict, dict]:
    cfg = config["data"]
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    closed_end = now.floor("h")
    bars_needed = int(cfg["live_bars"])
    start = closed_end - HOUR * bars_needed
    client = PublicClient(cfg["timeout_seconds"], cfg["retries"], cfg.get("pause_seconds", 0.18))
    prices, diagnostics = {}, {}

    for product in symbols:
        p = fetch_candles(client, product, start, closed_end)
        if len(p) < 2500:
            raise DataError(f"{product}: too few live bars for rolling models")
        if p.index[-1] + HOUR != closed_end:
            raise DataError(f"{product}: latest completed hourly bar is missing")
        book = fetch_book(client, product)
        spread_block = book["spread_bps"] > config["execution"]["max_live_spread_bps"]
        diagnostics[product] = {
            "provider": "coinbase_exchange_spot",
            "last_closed_bar": str(p.index[-1] + HOUR),
            "spread_bps": book["spread_bps"],
            "spread_entry_block": spread_block,
            "funding": "NOT_APPLICABLE_SPOT",
            "bars": len(p),
        }
        prices[product] = p

    if not all(prices[symbols[0]].index.equals(prices[s].index) for s in symbols):
        raise DataError("Live series are not aligned; no forward-filled relationship signal")
    return prices, diagnostics
