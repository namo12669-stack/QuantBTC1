from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
import requests
from btc_quant.common import load_config

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError('Tests must not call the network')
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)
    for name in ('GITHUB_REPOSITORY', 'GITHUB_TOKEN', 'TELEGRAM_BOT2_TOKEN', 'TELEGRAM_BOT2_CHAT_ID'):
        monkeypatch.delenv(name, raising=False)

@pytest.fixture
def cfg(): return deepcopy(load_config())

def bars(n=500, start='2025-01-01', seed=17, close=None):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq='h', tz='UTC')
    if close is None: close = 100 * np.exp(np.cumsum(rng.normal(0, .003, n)))
    close = np.asarray(close, dtype=float)
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({'open': op, 'high': np.maximum(op, close)*1.002,
                         'low': np.minimum(op, close)*.998, 'close': close,
                         'volume': rng.uniform(50,150,n), 'quote_volume': close*100}, index=idx).rename_axis('time')

def constant_bars(n=300):
    return bars(n=n, close=np.full(n,100.0))

def funding(frame, rate=0.):
    ix = frame.index[(frame.index.hour % 8) == 0]
    return pd.DataFrame({'rate': rate, 'interval_hours': 8.}, index=ix).rename_axis('time')
