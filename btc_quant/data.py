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
from .common import DataError, HOUR, utc, write_json, read_json

KLINE_FIELDS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly"
API = "https://fapi.binance.com"

class PublicClient:
    def __init__(self, timeout: int = 25, retries: int = 3):
        self.timeout, self.retries = timeout, retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BTC-Quant-Research/1.2 (public-market-data; no-trading)"})

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
            time.sleep(0.08)
            return response
        raise DataError("PROVIDER_RETRY_EXHAUSTED")


    def json(self, url, params=None):
        try: return self.get(url, params).json()
        except ValueError: raise DataError("PROVIDER_INVALID_JSON") from None


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
    df = df.rename(columns={"quote_asset_volume":"quote_volume", "opentime":"open_time"})
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




def gap_summary(df: pd.DataFrame, start, end) -> dict:
    """Describe missing hourly observations without inventing candles."""
    start, end = utc(start), utc(end)
    expected = pd.date_range(start, end - HOUR, freq="h", tz="UTC")
    missing = expected.difference(df.index)
    max_run = 0
    if len(missing):
        vals = missing.asi8
        run = 1
        max_run = 1
        for i in range(1, len(vals)):
            if vals[i] - vals[i-1] == HOUR.value:
                run += 1
            else:
                max_run = max(max_run, run)
                run = 1
        max_run = max(max_run, run)
    return {
        "expected_bars": int(len(expected)),
        "observed_bars": int(len(df.index.intersection(expected))),
        "missing_bars": int(len(missing)),
        "missing_fraction": float(len(missing) / len(expected)) if len(expected) else 0.0,
        "max_consecutive_missing_hours": int(max_run),
        "missing_examples": [str(x) for x in missing[:10]],
    }


def enforce_gap_policy(summary: dict, config: dict, product: str) -> None:
    max_fraction = float(config["data"].get("max_missing_fraction", 0.005))
    max_run = int(config["data"].get("max_consecutive_missing_hours", 24))
    if summary["missing_fraction"] > max_fraction:
        raise DataError(
            f"{product}: missing hourly bars {summary['missing_bars']}/{summary['expected_bars']} "
            f"({summary['missing_fraction']:.3%}) exceeds {max_fraction:.3%}; no forward-fill used"
        )
    if summary["max_consecutive_missing_hours"] > max_run:
        raise DataError(
            f"{product}: longest missing run {summary['max_consecutive_missing_hours']}h exceeds {max_run}h; "
            "no forward-fill used"
        )


def to_hourly_grid(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Reindex to the real hourly clock. Missing candles remain NaN, never forward-filled."""
    grid = pd.date_range(utc(start), utc(end) - HOUR, freq="h", tz="UTC", name="time")
    out = df.reindex(grid)
    out.index.name = "time"
    return out



def archive_url(symbol: str, kind: str, period: str) -> str:
    if not re.fullmatch(r'[A-Z0-9]{5,20}', symbol) or not re.fullmatch(r'\d{4}-\d{2}', period):
        raise DataError('Unsafe archive symbol or month')
    if kind == 'fundingRate': return f'{ARCHIVE}/{kind}/{symbol}/{symbol}-fundingRate-{period}.zip'
    if kind not in ('klines','markPriceKlines'): raise DataError('Unknown archive kind')
    return f'{ARCHIVE}/{kind}/{symbol}/1h/{symbol}-1h-{period}.zip'


def download_history(config: dict, data_dir: Path, report_dir: Path) -> dict:
    """Historical archive only: this does not call the geographically restricted live API."""
    c=config['data']; start,end=utc(c['start']),utc(c['end_exclusive'])
    now=pd.Timestamp.now(tz='UTC')
    if end > now.replace(day=1).normalize(): raise DataError('Only complete calendar months supported')
    if start.day != 1 or end.day != 1 or start.hour or end.hour: raise DataError('Use month boundaries')
    data_dir.mkdir(parents=True,exist_ok=True);report_dir.mkdir(parents=True,exist_ok=True)
    manifest={'schema':4,'venue':'binance_usdm','source':'real_binance_usdm_archive',
        'start':str(start),'end_exclusive':str(end),'files':[],'datasets':{},'gap_summary':{}}
    client=PublicClient(c['timeout_seconds'],c['retries'])
    todo=[(sym,'klines') for sym in [c['bitcoin'],*c['peers']]]
    todo += [(c['bitcoin'],'markPriceKlines'),(c['bitcoin'],'fundingRate')]
    months=pd.date_range(start,end-HOUR,freq='MS')
    for sym,kind in todo:
        frames=[]
        print(f'DOWNLOAD {sym} {kind} {start.date()} -> {end.date()}',flush=True)
        for month in months:
            url=archive_url(sym,kind,month.strftime('%Y-%m'))
            blob,item=archive_blob(client,data_dir/'archive_cache',url)
            manifest['files'].append(item)
            fields=['calc_time','funding_interval_hours','last_funding_rate'] if kind=='fundingRate' else KLINE_FIELDS
            raw=_csv_from_zip(blob,fields)
            frame=normalize_funding(raw) if kind=='fundingRate' else normalize_klines(raw)
            frames.append(frame)
        merged=pd.concat(frames).sort_index()
        merged=merged.loc[(merged.index>=start)&(merged.index<end)]
        if kind=='fundingRate':
            if merged.index.has_duplicates: raise DataError('DUPLICATED_ARCHIVE_FUNDING_EVENTS')
            validate_funding(merged,start,end)
        else:
            merged=validate_bars(merged)
            quality=gap_summary(merged,start,end)
            enforce_gap_policy(quality,config,f'{sym}/{kind}')
            manifest['gap_summary'][f'{sym}/{kind}']=quality
            merged=to_hourly_grid(merged,start,end)
        name=f'{sym}_{kind}.csv'; path=data_dir/name
        merged.to_csv(path,index_label='time',float_format='%.12g')
        manifest['datasets'][name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rows':len(merged)}
        write_json(report_dir/'download_progress.json',manifest)
    write_json(data_dir/'manifest.json',manifest);write_json(report_dir/'data_manifest.json',manifest)
    return manifest


def load_history(config: dict, data_dir: Path):
    manifest=read_json(data_dir/'manifest.json')
    c=config['data']
    if not manifest or manifest.get('schema')!=4 or manifest.get('venue')!='binance_usdm' or manifest.get('source')!='real_binance_usdm_archive':
        raise DataError('NO_VERIFIED_BINANCE_HISTORY; run research with --download')
    if utc(manifest['start'])!=utc(c['start']) or utc(manifest['end_exclusive'])!=utc(c['end_exclusive']):
        raise DataError('HISTORY_DATE_MISMATCH')
    frames={}
    names=[f'{s}_klines.csv' for s in [c['bitcoin'],*c['peers']]]+[f"{c['bitcoin']}_markPriceKlines.csv",f"{c['bitcoin']}_fundingRate.csv"]
    for name in names:
        path=data_dir/name; info=manifest['datasets'].get(name)
        if not info or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:
            raise DataError(f'HISTORY_INTEGRITY_FAILED {name}')
        frame=pd.read_csv(path,index_col='time',parse_dates=['time'])
        frame.index=pd.DatetimeIndex(pd.to_datetime(frame.index,utc=True),name='time')
        frames[name]=frame
    prices={s:frames[f'{s}_klines.csv'] for s in [c['bitcoin'],*c['peers']]}
    for sym,frame in prices.items():frame.attrs['gap_summary']=manifest['gap_summary'][f'{sym}/klines']
    return prices,frames[f"{c['bitcoin']}_markPriceKlines.csv"],frames[f"{c['bitcoin']}_fundingRate.csv"],manifest


def fetch_live_candles(client: PublicClient, symbol: str, start, end, mark=False) -> pd.DataFrame:
    """Forward pagination on open timestamps; discard every unclosed candle."""
    start,end=utc(start),utc(end);cursor=start;frames=[]
    endpoint='markPriceKlines' if mark else 'klines'
    while cursor<end:
        payload=client.json(f'{API}/fapi/v1/{endpoint}',{'symbol':symbol,'interval':'1h',
            'startTime':int(cursor.timestamp()*1000),'endTime':int(end.timestamp()*1000)-1,'limit':1000})
        if not isinstance(payload,list) or not payload:raise DataError(f'EMPTY_LIVE_CANDLES {symbol}/{endpoint}')
        frame=normalize_klines(pd.DataFrame(payload,columns=KLINE_FIELDS))
        frame=frame.loc[(frame.index>=cursor)&(frame.index<end)]
        if frame.empty:raise DataError('PAGINATION_DID_NOT_ADVANCE')
        frames.append(frame);cursor=frame.index[-1]+HOUR
    return validate_bars(pd.concat(frames))


def parse_rules(payload: dict, symbol='BTCUSDT') -> dict:
    items=[s for s in payload.get('symbols',[]) if s.get('symbol')==symbol]
    if len(items)!=1 or items[0].get('status')!='TRADING' or items[0].get('contractType')!='PERPETUAL':
        raise DataError('CONTRACT_NOT_TRADING_OR_NOT_PERPETUAL')
    spec=items[0]
    if spec.get('quoteAsset')!='USDT' or spec.get('marginAsset')!='USDT':raise DataError('NOT_USDT_LINEAR_CONTRACT')
    f={x['filterType']:x for x in spec['filters']}
    try:
        out={'tick_size':f['PRICE_FILTER']['tickSize'],'step_size':f['LOT_SIZE']['stepSize'],
             'min_qty':f['LOT_SIZE']['minQty'],'min_notional':f['MIN_NOTIONAL']['notional'],'source':'BINANCE_EXCHANGE_INFO'}
        if any(float(out[k])<=0 for k in ('tick_size','step_size','min_qty','min_notional')): raise ValueError()
        return out
    except (KeyError,ValueError): raise DataError('EXCHANGE_FILTER_SCHEMA_CHANGED') from None


def live_snapshot(config: dict, peer: str|None=None, bars: int|None=None) -> dict:
    c=config['data'];client=PublicClient(c['timeout_seconds'],c['retries'])
    server=utc(pd.to_datetime(client.json(f'{API}/fapi/v1/time')['serverTime'],unit='ms',utc=True))
    local=pd.Timestamp.now(tz='UTC')
    if abs((server-local).total_seconds())>90:raise DataError('LOCAL_CLOCK_SKEW')
    end=server.floor('h');start=end-pd.Timedelta(hours=bars or c['live_bars'])
    prices={}
    for sym in [c['bitcoin']]+([peer] if peer else []):
        df=fetch_live_candles(client,sym,start,end)
        q=gap_summary(df,start,end);enforce_gap_policy(q,config,sym)
        grid=to_hourly_grid(df,start,end)
        if grid.iloc[-1].isna().any():raise DataError(f'LATEST_CLOSED_BAR_MISSING {sym}')
        if bars is None and len(grid.dropna()) < c['min_live_complete_bars']:
            raise DataError(f'INSUFFICIENT_LIVE_OBSERVATIONS {sym}')
        prices[sym]=grid
    mark=to_hourly_grid(fetch_live_candles(client,c['bitcoin'],start,end,mark=True),start,end)
    rules=parse_rules(client.json(f'{API}/fapi/v1/exchangeInfo'),c['bitcoin'])
    # Historical funding used only for replay. Latest/predicted funding is a risk screen, not a backtest input.
    payload=client.json(f'{API}/fapi/v1/fundingRate',{'symbol':c['bitcoin'],'startTime':int((end-pd.Timedelta(days=10)).timestamp()*1000),'limit':1000})
    funding=normalize_funding(pd.DataFrame(payload).rename(columns={'fundingTime':'calc_time','fundingRate':'last_funding_rate'}))
    validate_funding(funding,end-pd.Timedelta(days=10),end)
    book=client.json(f'{API}/fapi/v1/ticker/bookTicker',{'symbol':c['bitcoin']})
    premium=client.json(f'{API}/fapi/v1/premiumIndex',{'symbol':c['bitcoin']})
    try:
        bid,ask=float(book['bidPrice']),float(book['askPrice']);mid=(bid+ask)/2
        mark_price=float(premium['markPrice']);rate=float(premium['lastFundingRate'])
        quote_time=utc(pd.to_datetime(book['time'],unit='ms',utc=True))
        mark_time=utc(pd.to_datetime(premium['time'],unit='ms',utc=True))
    except (KeyError,ValueError,TypeError):raise DataError('QUOTE_SCHEMA_MISMATCH') from None
    now=pd.Timestamp.now(tz='UTC')
    if not np.isfinite([bid,ask,mark_price,rate]).all() or bid<=0 or ask<bid or mark_price<=0:raise DataError('INVALID_QUOTE')
    if max(abs((now-quote_time).total_seconds()),abs((now-mark_time).total_seconds()))>config['execution']['max_quote_age_seconds']:
        raise DataError('STALE_QUOTE_OR_MARK')
    return {'prices':prices,'mark':mark,'funding':funding,'rules':rules,'server_time':str(server),'asof':str(now),
            'quote':{'bid':bid,'ask':ask,'mid':mid,'mark':mark_price,'funding_rate':rate,
            'spread_bps':(ask-bid)/mid*10000,'mark_basis_bps':abs(mark_price/mid-1)*10000,'time':str(quote_time)}}


def check_data(config: dict, output: Path, section='both') -> dict:
    """Availability report, not a claim that the entire archive has been verified."""
    result={'archive_sample':{'status':'NOT_TESTED'},'live':{'status':'NOT_TESTED'}}
    if section in ('both','archive'):
        try:
            c=PublicClient(20,2)
            for kind in ('klines','markPriceKlines','fundingRate'):
                url=archive_url('BTCUSDT',kind,'2025-01')
                blob,_=archive_blob(c,output/'check_cache',url)
                columns=['calc_time','funding_interval_hours','last_funding_rate'] if kind=='fundingRate' else KLINE_FIELDS
                raw=_csv_from_zip(blob,columns)
                if kind=='fundingRate':normalize_funding(raw)
                else:normalize_klines(raw)
            result['archive_sample']={'status':'OK','sample_month':'2025-01','checksum_and_parse':True}
        except DataError as exc: result['archive_sample']={'status':'BLOCKED','reason':str(exc)}
    if section in ('both','live'):
        try:
            snap=live_snapshot(config,bars=24)
            result['live']={'status':'OK','rules':snap['rules'],'quote_asof':snap['asof']}
        except DataError as exc: result['live']={'status':'BLOCKED','reason':str(exc)}
    result['can_research']=result['archive_sample']['status']=='OK'
    result['can_scan_live']=result['live']['status']=='OK'
    result['status']='READY' if result['can_research'] and result['can_scan_live'] else 'HISTORY_ONLY' if result['can_research'] else 'NOT_READY'
    write_json(output/'provider_check.json',result)
    return result
