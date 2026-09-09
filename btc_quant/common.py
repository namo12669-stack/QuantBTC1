from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import yaml

HOUR = pd.Timedelta(hours=1)
ROOT = Path(__file__).resolve().parents[1]

class DataError(RuntimeError):
    """An explicit failure: never replace unavailable market data with demo data."""


def utc(value: Any) -> pd.Timestamp:
    x = pd.Timestamp(value)
    return x.tz_localize("UTC") if x.tz is None else x.tz_convert("UTC")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(json_safe(data), indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def fingerprint(config: dict) -> str:
    """A changed implementation or execution assumption invalidates old approval."""
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for path in sorted((ROOT / "btc_quant").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update((ROOT / "requirements.txt").read_bytes())
    return digest.hexdigest()


def load_config(path: Path | str = ROOT / "config.yaml") -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if cfg["data"]["venue"] != "binance_usdm" or cfg["data"]["interval"] != "1h":
        raise ValueError("This release supports only Binance USDT-M perpetual 1h data; do not mix venues or spot/futures.")
    dates = [utc(cfg["data"][k]) for k in ("start", "validation_start", "test_start", "end_exclusive")]
    if not all(a < b for a, b in zip(dates, dates[1:])):
        raise ValueError("Dates must satisfy start < validation_start < test_start < end_exclusive")
    if cfg["execution"]["entry_delay_bars"] < 2 or cfg["execution"]["close_exit_delay_bars"] < 2:
        raise ValueError("At least two bars from the signal candle open are required for scheduled alerts.")
    if cfg["execution"]["gross_exposure"] != 1.0:
        raise ValueError("No leverage model is implemented; gross exposure must remain 1.0")
    if not cfg["execution"]["funding_required"]:
        raise ValueError("Funding cannot be disabled for perpetual-futures validation")
    if cfg["proof_gate"]["minimum_win_rate_lower_bound"] < 0.90:
        raise ValueError("Strict mode cannot be relabelled as 90%-evidence mode after lowering the threshold")
    peers = cfg["data"]["peers"]
    if len(peers) != len(set(peers)) or cfg["data"]["bitcoin"] in peers:
        raise ValueError("Peers must be unique and exclude Bitcoin")
    return cfg
