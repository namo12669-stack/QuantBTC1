import numpy as np
import pandas as pd
from btc_quant.common import HOUR
from btc_quant.research import research
from conftest import bars, funding

def test_complete_synthetic_pipeline_never_certifies(tmp_path,cfg):
    cfg['data'].update(start='2024-09-01',validation_start='2025-01-01',test_start='2025-02-01',end_exclusive='2025-04-01',peers=['ETH-USD'])
    cfg['proof_gate']['bootstrap_repetitions']=100
    n=int((pd.Timestamp('2025-04-01')-pd.Timestamp('2024-09-01'))/HOUR)
    rng=np.random.default_rng(50)
    r=rng.normal(0,.006,n)
    rb=np.r_[np.zeros(7),r[:-7]]*.8+rng.normal(0,.002,n)
    b=bars(n,start='2024-09-01',close=100*np.exp(np.cumsum(rb)))
    p=bars(n,start='2024-09-01',close=100*np.exp(np.cumsum(r)))
    model=research(cfg,{'BTC-USD':b,'ETH-USD':p},{'BTC-USD':funding(b),'ETH-USD':funding(p)},tmp_path,source='synthetic')
    assert model['selection_trials']==4
    assert model['source']=='synthetic'
    assert not model['approved']
    assert model['selection_used_holdout'] is False
    assert 'REAL_DATA_NOT_VERIFIED' in model['evidence']['reasons']
    assert (tmp_path/'BACKTEST_REPORT.md').exists()
    assert (tmp_path/'holdout_trades.csv').exists()
    assert pd.read_csv(tmp_path/'pair_selection.csv').shape[0]==4
