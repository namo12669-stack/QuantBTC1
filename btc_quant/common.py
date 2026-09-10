from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOUR = pd.Timedelta(hours=1)
VERSION = '1.2.0'
SCHEMA = 4
class DataError(RuntimeError):
    """Market observations are never replaced with synthetic observations."""
class PlanError(ValueError):
    """No executable plan fits the declared risk and execution constraints."""

def utc(value: Any) -> pd.Timestamp:
    t = pd.Timestamp(value)
    if pd.isna(t): raise ValueError('Invalid timestamp')
    return t.tz_localize('UTC') if t.tz is None else t.tz_convert('UTC')

def json_safe(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)): return [json_safe(v) for v in x]
    if isinstance(x, (pd.Timestamp, Path)): return str(x)
    if isinstance(x, np.bool_): return bool(x)
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (float, np.floating)): return float(x) if math.isfinite(float(x)) else None
    return x

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(json_safe(data), indent=2, sort_keys=True, allow_nan=False), encoding='utf-8')
    tmp.replace(path)

def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def fingerprint(config: dict) -> str:
    h = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for p in sorted((ROOT / 'btc_quant').glob('*.py')):
        h.update(p.name.encode()); h.update(p.read_bytes())
    h.update((ROOT / 'requirements.txt').read_bytes())
    return h.hexdigest()

def load_config(path: str | Path = ROOT / 'config.yaml') -> dict:
    c = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if c.get('version') != VERSION: raise ValueError('CONFIG_VERSION_MISMATCH: replace config.yaml together with code')
    def reject_nonfinite(value):
        if isinstance(value, dict):
            for v in value.values(): reject_nonfinite(v)
        elif isinstance(value, list):
            for v in value: reject_nonfinite(v)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value): raise ValueError('Config numeric values must be finite')
    reject_nonfinite(c)
    d, a, e = c['data'], c['account'], c['execution']
    if d['venue'] != 'binance_usdm' or d['bitcoin'] != 'BTCUSDT' or d['interval'] != '1h':
        raise ValueError('Only Binance USD-M BTCUSDT perpetual 1h is supported; no mixed-venue fallback')
    times = [utc(d[k]) for k in ('start','validation_start','test_start','end_exclusive')]
    if not all(x < y for x,y in zip(times,times[1:])): raise ValueError('Invalid chronological research split')
    if len(d['peers']) != len(set(d['peers'])) or d['bitcoin'] in d['peers']: raise ValueError('Invalid peers')
    if not 0 < a['risk_fraction'] <= .10: raise ValueError('risk_fraction must be > 0 and <= 10%; 2% is default')
    if not 0 < a['hard_risk_cap_usdt'] <= 50: raise ValueError('Risk cap exceeds the user limit of 50 USDT')
    if type(a['max_leverage']) is not int or not 1 <= a['max_leverage'] <= 3: raise ValueError('This release caps leverage at 3x; higher leverage not validated')
    if not 0 < a['max_margin_fraction'] <= .60: raise ValueError('Keep at least 40% of equity outside initial margin')
    if a['equity_usdt'] <= 0 or a['margin_mode'] != 'ISOLATED': raise ValueError('Positive equity and isolated margin required')
    if e['entry_delay_bars'] != 2 or e['order_valid_hours'] < 1: raise ValueError('Entry starts one full hour after signal close')
    if not e['funding_required']: raise ValueError('Perpetual backtests require actual funding events')
    if min(e['fee_bps_per_side'],e['slippage_bps_per_side'],e['funding_reserve_bps']) < 0: raise ValueError('Negative costs')
    gate = c['proof_gate']
    if not .80 <= gate['minimum_win_rate_lower_bound'] < 1: raise ValueError('Strict evidence threshold must be >= 80% and < 100%')
    if not 0 < gate['family_alpha'] <= .05: raise ValueError('Invalid confidence alpha')
    if gate['bootstrap_repetitions'] < 1000 or gate['confidence_checks'] < 6: raise ValueError('Insufficient bootstrap/confidence settings')
    if any(r <= 1 or r > 5 for r in c['selection']['reward_risk_candidates']): raise ValueError('Gross reward/risk candidates must be >1 and <=5')
    if not 0 < a['daily_loss_fraction'] <= a['weekly_loss_fraction'] < 1: raise ValueError('Invalid account risk limits')
    if not 0 < a['drawdown_pause_fraction'] < 1: raise ValueError('Invalid drawdown pause')
    return c
