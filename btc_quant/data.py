"""Official exchange archives + public REST; no keys, proxies or mixed-venue fallback."""
from __future__ import annotations
import hashlib
import io
import re
import time
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from .common import DataError, HOUR, utc, write_json

KLINE_FIELDS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly"
API = "https://fapi.binance.com"

class PublicClient:
    def __init__(self, timeout: int = 25, retries: int = 3):
        self.timeout, self.retries = timeout, retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BTC-Quant-Research/1.0 (public-market-data; no-trading)"})

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt + 1 == self.retries:
                    raise DataError(f"NETWORK_UNAVAILABLE {type(exc).__name__}; data download was not completed") from None
                time.sleep(min(2 ** attempt, 8)); continue
            if response.status_code in (403, 451):
                raise DataError(f"PROVIDER_ACCESS_DENIED HTTP {response.status_code}; use an authorized, supported environment. No proxy/bypass is supplied.")
            if response.status_code == 404:
                raise DataError("ARCHIVE_OR_ENDPOINT_NOT_FOUND HTTP 404; the requested month may not yet be published")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < self.retries:
                    try: delay = float(response.headers.get("Retry-After", 2 ** attempt))
                    except ValueError: delay = 2 ** attempt
                    time.sleep(min(delay, 30)); continue
            if not response.ok:
                raise DataError(f"PROVIDER_HTTP_{response.status_code}")
            return response
        raise DataError("PROVIDER_RETRY_EXHAUSTED")


def epoch_index(values) -> pd.DatetimeIndex:
    vals = pd.to_numeric(pd.Series(values), errors="raise")
    median = float(vals.abs().median())
    unit = "us" if median >= 1e14 else "ms" if median >= 1e11 else "s"
    return pd.DatetimeIndex(pd.to_datetime(vals.to_numpy(), unit=unit, utc=True))


def _csv_from_zip(blob: bytes, columns: list[str]) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1: raise DataError("Expected exactly one CSV inside archive")
            info = z.getinfo(names[0])
            if info.file_size > 100_000_000: raise DataError("Archive exceeds safety size limit")
            raw = z.read(names[0])
    except zipfile.BadZipFile:
        raise DataError("Downloaded file is not a ZIP archive") from None
    if not raw.strip(): raise DataError("Empty CSV inside archive")
    first = raw.splitlines()[0].decode("utf-8-sig").split(",")[0].strip()
    has_header = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", first) is None
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if not has_header:
        if len(df.columns) != len(columns): raise DataError("Unexpected archive column count")
        df.columns = columns
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def normalize_klines(df: pd.DataFrame) -> pd.DataFrame:
    if not set(["open_time", "open", "high", "low", "close", "volume"]).issubset(df.columns):
        raise DataError("Kline schema missing required fields")
    out = pd.DataFrame(index=epoch_index(df["open_time"]))
    out.index.name = "time"
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(df[c], errors="raise").to_numpy(dtype=float)
    if "quote_volume" in df:
        out["quote_volume"] = pd.to_numeric(df["quote_volume"], errors="raise").to_numpy(dtype=float)
    else:
        raise DataError("quote_volume required; do not silently substitute estimated turnover")
    return validate_bars(out)


def validate_bars(df: pd.DataFrame, contiguous: bool = False) -> pd.DataFrame:
    out = df.copy().sort_index()
    if not isinstance(out.index, pd.DatetimeIndex) or out.index.tz is None:
        raise DataError("Candle times must be timezone-aware UTC")
    out.index = out.index.tz_convert("UTC")
    if out.index.has_duplicates:
        duplicates = out[out.index.duplicated(keep=False)]
        if any(g.nunique().max() > 1 for _, g in duplicates.groupby(level=0)):
            raise DataError("Conflicting duplicated candles")
        out = out[~out.index.duplicated(keep="first")]
    fields = ["open", "high", "low", "close", "volume", "quote_volume"]
    if out.empty or not np.isfinite(out[fields].to_numpy()).all(): raise DataError("Empty or non-finite candle data")
    if (out[["open", "high", "low", "close"]] <= 0).any().any(): raise DataError("Non-positive price")
    if (out[["volume", "quote_volume"]] < 0).any().any(): raise DataError("Negative volume")
    if (out["high"] < out[["open", "close", "low"]].max(axis=1) - 1e-8).any(): raise DataError("OHLC high inconsistency")
    if (out["low"] > out[["open", "close", "high"]].min(axis=1) + 1e-8).any(): raise DataError("OHLC low inconsistency")
    if (out.index != out.index.floor("h")).any(): raise DataError("Candle is not aligned to a UTC hour")
    if contiguous and len(out) > 1 and not (np.diff(out.index.asi8) == HOUR.value).all():
        raise DataError("MISSING_HOURLY_BARS: not forward-filled; inspect diagnostics and source archive")
    return out


def normalize_funding(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"fundingtime": "calc_time", "fundingrate": "last_funding_rate"})
    if not {"calc_time", "last_funding_rate"}.issubset(df): raise DataError("Funding schema mismatch")
    out = pd.DataFrame(index=epoch_index(df["calc_time"]))
    out.index.name = "time"
    out["rate"] = pd.to_numeric(df["last_funding_rate"], errors="raise").to_numpy(float)
    if "funding_interval_hours" in df:
        out["interval_hours"] = pd.to_numeric(df["funding_interval_hours"], errors="raise").to_numpy(float)
    else:
        out["interval_hours"] = np.nan
    out = out.sort_index()
    if out.index.has_duplicates:
        for _, group in out[out.index.duplicated(keep=False)].groupby(level=0):
            if group["rate"].nunique() > 1: raise DataError("Conflicting funding events")
        out = out[~out.index.duplicated()]
    if not np.isfinite(out["rate"]).all() or (out["rate"].abs() > 0.1).any(): raise DataError("Implausible funding rate")
    return out


def validate_funding(f: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> None:
    if f.empty: raise DataError("FUNDING_MISSING: net perpetual returns cannot be validated")
    if f.index[0] > start + pd.Timedelta(hours=8) or f.index[-1] < end - pd.Timedelta(hours=8):
        raise DataError("FUNDING_COVERAGE_INCOMPLETE")
    gaps = np.diff(f.index.asi8) / HOUR.value
    # Exchange may change settlement intervals. Never invent zero events for gaps.
    expected = f["interval_hours"].to_numpy()[1:]
    expected = np.where(np.isfinite(expected), expected, 8.0)
    if np.any(gaps > expected + 0.05): raise DataError("FUNDING_GAP: missing settlement(s)")
    if np.any(gaps <= 0): raise DataError("FUNDING_TIME_ORDER")


def archive_blob(client: PublicClient, cache: Path, url: str) -> tuple[bytes, dict]:
    filename = url.rsplit("/", 1)[1]
    path = cache / hashlib.sha256(url.encode()).hexdigest()[:12] / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_path = path.with_suffix(path.suffix + ".CHECKSUM")
    if not expected_path.exists():
        expected_path.write_bytes(client.get(url + ".CHECKSUM").content)
    expected = expected_path.read_text().strip().split()[0].lower()
    if not re.fullmatch("[a-f0-9]{64}", expected): raise DataError("Invalid archive checksum document")
    if not path.exists(): path.write_bytes(client.get(url).content)
    blob = path.read_bytes()
    actual = hashlib.sha256(blob).hexdigest()
    if actual != expected:
        path.unlink(missing_ok=True)
        raise DataError("ARCHIVE_CHECKSUM_MISMATCH; cache file removed")
    return blob, {"url": url, "sha256": actual, "bytes": len(blob)}


def download_history(config: dict, data_dir: Path, report_dir: Path) -> None:
    cfg = config["data"]
    start, end = utc(cfg["start"]), utc(cfg["end_exclusive"])
    now = pd.Timestamp.now(tz="UTC")
    if end > now.replace(day=1).normalize(): raise DataError("Only fully completed calendar months may be researched")
    if start.day != 1 or end.day != 1: raise DataError("Archive boundaries must be first-of-month, end exclusive")
    months = pd.date_range(start, end - HOUR, freq="MS")
    client = PublicClient(cfg["timeout_seconds"], cfg["retries"])
    manifest = {"venue": "binance_usdm", "interval": "1h", "source": "real_exchange_archive", "start": str(start), "end_exclusive": str(end), "files": [], "symbols": {}}
    report_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        for symbol in [cfg["bitcoin"], *cfg["peers"]]:
            prices, funds = [], []
            for month in months:
                period = month.strftime("%Y-%m")
                for kind in ("klines", "fundingRate"):
                    suffix = f"klines/{symbol}/1h/{symbol}-1h-{period}.zip" if kind == "klines" else f"fundingRate/{symbol}/{symbol}-fundingRate-{period}.zip"
                    blob, item = archive_blob(client, data_dir / "cache", f"{ARCHIVE}/{suffix}")
                    manifest["files"].append(item)
                    if kind == "klines": prices.append(normalize_klines(_csv_from_zip(blob, KLINE_FIELDS)))
                    else: funds.append(normalize_funding(_csv_from_zip(blob, ["calc_time", "funding_interval_hours", "last_funding_rate"])))
                print(f"Fetched {symbol} {period}", flush=True)
            p = validate_bars(pd.concat(prices), contiguous=True)
            p = p.loc[(p.index >= start) & (p.index < end)]
            if len(p) != int((end - start) / HOUR): raise DataError(f"{symbol}: incomplete full-range candle coverage")
            f = pd.concat(funds).sort_index()
            f = f[~f.index.duplicated()]
            validate_funding(f, start, end)
            price_path, funding_path = data_dir / f"{symbol}_1h.csv", data_dir / f"{symbol}_funding.csv"
            p.to_csv(price_path)
            f.to_csv(funding_path)
            manifest["symbols"][symbol] = {"bars": len(p), "funding_events": len(f), "first": str(p.index[0]), "last": str(p.index[-1]),
                "price_sha256": hashlib.sha256(price_path.read_bytes()).hexdigest(),
                "funding_sha256": hashlib.sha256(funding_path.read_bytes()).hexdigest()}
    except Exception as exc:
        manifest["status"] = "FAILED"
        manifest["error"] = str(exc)[:350]
        write_json(report_dir / "data_manifest.json", manifest)
        raise
    manifest["status"] = "VERIFIED"
    write_json(data_dir / "manifest.json", manifest)
    write_json(report_dir / "data_manifest.json", manifest)


def load_history(config: dict, directory: Path) -> tuple[dict, dict]:
    from .common import read_json
    manifest = read_json(directory / "manifest.json", {})
    if manifest.get("source") != "real_exchange_archive" or manifest.get("status") != "VERIFIED":
        raise DataError("REAL_ARCHIVE_MANIFEST_REQUIRED: demo data cannot be certified")
    prices, funds = {}, {}
    start, end = utc(config["data"]["start"]), utc(config["data"]["end_exclusive"])
    if utc(manifest.get("start")) != start or utc(manifest.get("end_exclusive")) != end:
        raise DataError("Manifest date range does not match config")
    for symbol in [config["data"]["bitcoin"], *config["data"]["peers"]]:
        item = manifest.get("symbols", {}).get(symbol, {})
        for suffix, field in (("1h", "price_sha256"), ("funding", "funding_sha256")):
            path = directory / f"{symbol}_{suffix}.csv"
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item.get(field):
                raise DataError(f"{symbol}: processed data checksum mismatch; redownload verified archives")
        p = pd.read_csv(directory / f"{symbol}_1h.csv", index_col="time", parse_dates=True)
        p.index = pd.to_datetime(p.index, utc=True)
        f = pd.read_csv(directory / f"{symbol}_funding.csv", index_col="time", parse_dates=True)
        f.index = pd.to_datetime(f.index, utc=True)
        p = validate_bars(p, contiguous=True)
        start, end = utc(config["data"]["start"]), utc(config["data"]["end_exclusive"])
        if p.index[0] != start or p.index[-1] + HOUR != end: raise DataError("History range does not match config")
        validate_funding(f, start, end)
        prices[symbol], funds[symbol] = p, f
    return prices, funds


def live_history(config: dict, symbols: list[str], now=None) -> tuple[dict, dict]:
    cfg = config["data"]
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    client = PublicClient(cfg["timeout_seconds"], cfg["retries"])
    end_ms = int(now.floor("h").timestamp() * 1000) - 1
    prices, diagnostics = {}, {}
    for symbol in symbols:
        frames, cursor = [], end_ms
        remaining = int(cfg["live_bars"])
        while remaining > 0:
            limit = min(remaining, 1500)
            response = client.get(f"{API}/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": limit, "endTime": cursor}).json()
            if not isinstance(response, list) or not response: raise DataError(f"{symbol}: missing live candles")
            frame = normalize_klines(pd.DataFrame(response, columns=KLINE_FIELDS))
            frames.append(frame)
            cursor = int(frame.index[0].timestamp() * 1000) - 1
            remaining -= len(frame)
            if len(frame) < limit: break
            time.sleep(0.12)
        p = validate_bars(pd.concat(frames), contiguous=True)
        p = p.loc[p.index + HOUR <= now].tail(int(cfg["live_bars"]))
        if len(p) < 2500: raise DataError(f"{symbol}: too few live bars for rolling models")
        if p.index[-1] + HOUR != now.floor("h"): raise DataError(f"{symbol}: latest completed hourly bar is missing")
        ticker = client.get(f"{API}/fapi/v1/ticker/bookTicker", {"symbol": symbol}).json()
        bid, ask = float(ticker["bidPrice"]), float(ticker["askPrice"])
        if bid <= 0 or ask < bid: raise DataError(f"{symbol}: invalid order-book quote")
        spread_bps = (ask - bid) / ((ask + bid) / 2) * 10000
        spread_entry_block = spread_bps > config["execution"]["max_live_spread_bps"]
        funding = client.get(f"{API}/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1}).json()
        if not funding: raise DataError(f"{symbol}: no recent funding context")
        last_rate = float(funding[-1]["fundingRate"])
        last_time = pd.to_datetime(int(funding[-1]["fundingTime"]), unit="ms", utc=True)
        if now - last_time > pd.Timedelta(hours=12): raise DataError(f"{symbol}: stale funding context")
        # Extreme funding blocks NEW entries in app.py, but must not block monitoring an existing position.
        funding_entry_block = abs(last_rate) > config["execution"]["max_abs_recent_funding_rate"]
        diagnostics[symbol] = {"last_closed_bar": str(p.index[-1] + HOUR), "spread_bps": spread_bps, "spread_entry_block": spread_entry_block, "recent_funding_rate": last_rate, "funding_entry_block": funding_entry_block, "bars": len(p)}
        prices[symbol] = p
    if not all(prices[symbols[0]].index.equals(prices[s].index) for s in symbols):
        raise DataError("Live series are not aligned; no forward-filled relationship signal")
    return prices, diagnostics
