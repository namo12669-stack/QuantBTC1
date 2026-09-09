from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from btc_quant.common import HOUR, fingerprint, load_config
from btc_quant.evidence import wilson_lower, block_bounds, metrics, validate_evidence
from btc_quant.research import select_candidate
from btc_quant.app import eligibility

def ledger(n=600,win_fraction=.97):
    rng=np.random.default_rng(14)
    r=np.full(n,.02); r[rng.choice(n,int(n*(1-win_fraction)),replace=False)]=-.01
    t=pd.DataFrame({'entry_time':pd.date_range('2025-01-01',periods=n,freq='20h',tz='UTC'),
                    'direction':np.where(np.arange(n)%2,1,-1),'net_return':r,'stress_net_return':r-.001,'win':r>0})
    idx=pd.date_range('2025-01-01','2026-08-31 23:00',freq='h',tz='UTC')
    eq=pd.Series(np.linspace(1,2,len(idx)),index=idx)
    return t,eq

@pytest.mark.parametrize('wins,trials',[(0,0),(9,10),(90,100),(180,200),(900,1000)])
def test_ninety_percent_observed_not_ninety_lower_bound(wins,trials):
    assert wilson_lower(wins,trials)<.9

def test_all_wins_small_sample_still_insufficient():
    assert wilson_lower(10,10,.05/3)<.9

def test_more_evidence_tightens_bound():
    assert wilson_lower(970,1000)>wilson_lower(97,100)

def test_block_bootstrap_reproducible():
    t,eq=ledger()
    assert block_bounds(t,.05,300,4)==block_bounds(t,.05,300,4)

def test_empty_evidence_blocks(cfg):
    _,eq=ledger()
    result=validate_evidence(pd.DataFrame(),eq,cfg,eq.index[0],eq.index[-1]+HOUR,'real_exchange_archive')
    assert not result['approved']

def test_synthetic_never_certified(cfg):
    t,eq=ledger()
    out=validate_evidence(t,eq,cfg,eq.index[0],eq.index[-1]+HOUR,'synthetic')
    assert 'REAL_DATA_NOT_VERIFIED' in out['reasons']
    assert not out['approved'] and out['per_trade_probability'] is None

def test_strict_can_pass_statistical_fixture_but_not_market_claim(cfg):
    t,eq=ledger(win_fraction=1)
    out=validate_evidence(t,eq,cfg,eq.index[0],eq.index[-1]+HOUR,'real_exchange_archive')
    # Unit fixture explicitly supplies a source label; this is NOT a real backtest result.
    assert out['approved']
    assert out['per_trade_probability'] is None

def test_high_win_rate_can_have_negative_expectancy(cfg):
    t,eq=ledger(win_fraction=.96)
    t['net_return']=np.where(t.win,.0005,-.05)
    t['stress_net_return']=t.net_return-.001
    out=validate_evidence(t,eq,cfg,eq.index[0],eq.index[-1]+HOUR,'real_exchange_archive')
    assert not out['approved']
    assert 'COST_STRESS_NOT_PROFITABLE' in out['reasons']

def test_one_direction_is_not_evidence_for_other(cfg):
    t,eq=ledger(win_fraction=1);t['direction']=1
    out=validate_evidence(t,eq,cfg,eq.index[0],eq.index[-1]+HOUR,'real_exchange_archive')
    assert not out['approved']
    assert out['subsets']['SELL']['trades']==0

def test_clustered_short_history_rejected(cfg):
    t,eq=ledger(win_fraction=1)
    t['entry_time']=pd.date_range('2025-01-01',periods=len(t),freq='h',tz='UTC')
    out=validate_evidence(t,eq,cfg,eq.index[0],eq.index[-1]+HOUR,'real_exchange_archive')
    assert not out['approved']
    assert out['subsets']['overall']['active_weeks']<26

def test_select_on_validation_not_holdout(cfg):
    base={'trades':100,'mean_net_return':.01,'profit_factor':2,'positive_month_fraction':.75,'mean_stress_return':.005}
    rec=[dict(base,candidate='a',daily_net_sharpe=1,holdout_sharpe=100),dict(base,candidate='b',daily_net_sharpe=2,holdout_sharpe=-100)]
    assert select_candidate(rec,cfg,0)[0]['candidate']=='b'

def test_must_beat_btc_only_baseline(cfg):
    rec=[{'candidate':'a','trades':100,'mean_net_return':.01,'profit_factor':2,'positive_month_fraction':.75,'mean_stress_return':.005,'daily_net_sharpe':1}]
    assert select_candidate(rec,cfg,2)[0] is None

def test_config_change_invalidates_model(cfg):
    model={'source':'real_exchange_archive','fingerprint':fingerprint(cfg),'approved':True,'evidence':{'approved':True},'test_end_exclusive':'2026-09-01'}
    assert eligibility(model,cfg,'2026-09-09')[0]
    cfg['execution']['fee_bps_per_side']+=1
    assert not eligibility(model,cfg,'2026-09-09')[0]

@pytest.mark.parametrize('when',['2026-08-01','2026-12-01'])
def test_future_or_stale_evidence_blocks(when,cfg):
    model={'source':'real_exchange_archive','fingerprint':fingerprint(cfg),'approved':True,'evidence':{'approved':True},'test_end_exclusive':'2026-09-01'}
    assert not eligibility(model,cfg,when)[0]

def test_absent_model_blocks(cfg): assert not eligibility(None,cfg,'2026-09-09')[0]
