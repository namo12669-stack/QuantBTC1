from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from btc_quant.backtest import BacktestResult
from btc_quant.evidence import metrics,wilson_lower,block_bounds,validate_evidence
from btc_quant.research import candidates,select,research
from btc_quant.common import HOUR,fingerprint
from conftest import bars,funding


def result_with_pnl(pnl,start='2025-01-01',spacing='1D'):
    idx=pd.date_range(start,periods=len(pnl),freq=spacing,tz='UTC');pnl=np.asarray(pnl,float)
    tr=pd.DataFrame({'net_pnl':pnl,'net_r':pnl,'stress_net_pnl':pnl-.1,'win':pnl>0,'entry_time':idx.astype(str),
                     'direction':np.where(np.arange(len(pnl))%2,1,-1),'uncertain':False,'margin_stress':False})
    eq=pd.Series(500+np.cumsum(pnl),index=idx)
    return BacktestResult(tr,eq,eq.copy(),pd.DataFrame(),{})


def test_profit_factor_is_aggregate_not_payoff(cfg):
    r=result_with_pnl([3.69]*30+[-1.24]*70)
    m=metrics(r,cfg)
    assert m['win_rate']==.30
    assert m['profit_factor']==pytest.approx((30*3.69)/(70*1.24))
    assert m['profit_factor']!=pytest.approx(3.69/1.24)


def test_observed_eighty_is_not_eighty_lower_bound():
    assert wilson_lower(160,200)<.8


def test_small_sample_inconclusive():
    assert wilson_lower(8,10)<wilson_lower(800,1000)


def test_synthetic_cannot_approve(cfg):
    r=result_with_pnl(np.where(np.arange(600)%20,1.,-.5))
    ev=validate_evidence(r,cfg,'synthetic_fixture')
    assert not ev['approved'] and 'NOT_VERIFIED_REAL_BINANCE_DATA' in ev['reasons']
    assert ev['next_trade_probability'] is None


def test_missing_held_path_blocks(cfg):
    r=result_with_pnl(np.ones(600));r.trades.loc[1,'uncertain']=True
    ev=validate_evidence(r,cfg,'real_binance_usdm_archive')
    assert not ev['approved'] and 'UNOBSERVED_TRADE_PATHS_REQUIRE_DATA_REPAIR' in ev['reasons']


def test_margin_stress_blocks(cfg):
    r=result_with_pnl(np.ones(600));r.trades.loc[1,'margin_stress']=True
    ev=validate_evidence(r,cfg,'real_binance_usdm_archive')
    assert not ev['approved']


def test_losing_short_side_cannot_borrow_long_win_rate(cfg):
    r=result_with_pnl(np.where(np.arange(600)%2,2.,-1.))
    ev=validate_evidence(r,cfg,'real_binance_usdm_archive')
    assert 'SHORT' not in ev['approved_sides'] and not ev['approved']


def test_low_payoff_eighty_percent_not_edge(cfg):
    r=result_with_pnl(np.where(np.arange(600)%5,.20,-1.))
    ev=validate_evidence(r,cfg,'real_binance_usdm_archive')
    assert not ev['approved'] and ev['metrics']['mean_net_pnl_usdt']<0


def test_bootstrap_deterministic(cfg):
    r=result_with_pnl(np.tile([1,1,1,-1],100))
    a=block_bounds(r.trades,.025,300,4);b=block_bounds(r.trades,.025,300,4)
    assert a==b and a['block_weeks']==4


def test_candidates_limited_and_include_baselines(cfg):
    cs=list(candidates(cfg));assert len(cs)==26
    assert any(c.family=='trend_pullback' and c.peer is None for c in cs)
    assert not any(c.family in ('lead_lag','pair_spread') and c.peer is None for c in cs)


def record(id,peer,sharpe):
    return {'id':id,'family':'breakout','peer':peer,'reward_risk':2.,'trades':100,'mean_net_r':.1,'profit_factor':1.2,
            'no_losing_trades':False,'positive_month_fraction':.6,'mean_stress_pnl_usdt':.1,'daily_net_sharpe':sharpe,
            'uncertain_trades':0,'margin_stress_events':0}


def test_companion_must_improve_matching_baseline(cfg):
    winner,best=select([record('base',None,1.5),record('peer','ETHUSDT',1.2)],cfg)
    assert winner['peer'] is None


def test_no_selection_qualification_is_not_approval(cfg):
    rec=record('bad',None,1.5);rec['mean_stress_pnl_usdt']=-1
    winner,best=select([rec],cfg)
    assert winner is None and best['id']=='bad'


def test_synthetic_full_research_smoke(cfg,tmp_path):
    # Pipeline exercise, not market research. Keep two baseline variants and a small clock.
    cfg['data'].update(validation_start='2025-01-02',test_start='2025-01-06',end_exclusive='2025-01-10',peers=[])
    cfg['signals']['families']=['breakout'];cfg['selection']['reward_risk_candidates']=[1.5,2.]
    b=bars(240,start='2025-01-01',close=np.full(240,100000.));b['volume']=100.
    b.loc[b.index[80],['open','high','low','close','volume']]=[100000,105000,99900,104800,600]
    model=research(cfg,{'BTCUSDT':b},b.copy(),funding(b),tmp_path,{'gap_summary':{}},source='synthetic_test')
    assert (tmp_path/'BACKTEST_REPORT.md').exists() and (tmp_path/'model.json').exists()
    assert not model['approved'] and not model['selection_used_holdout']
    assert model['next_trade_probability'] is None


def test_pair_only_candidate_must_beat_declared_btc_baseline(cfg):
    base=record('base',None,1.5);pair=record('pair','ETHUSDT',1.2);pair['family']='pair_spread'
    winner,_=select([base,pair],cfg)
    assert winner['id']=='base'
