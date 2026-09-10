from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from btc_quant.common import DataError, HOUR
from btc_quant.signals import Candidate, Signal, indicator_frame, confirmed_pivots, generate_signals, _refits
from conftest import bars, constant_bars

def test_pivot_not_observable_early():
    v=np.array([5.,4,3,1,3,4,5])
    assert confirmed_pivots(v[:6],3,3,'low')==[]
    assert confirmed_pivots(v,3,3,'low')==[(3,6)]

def test_plateau_is_not_unique_pivot():
    assert confirmed_pivots(np.array([3.,2,1,1,2,3]),2,2,'low')==[]

@pytest.mark.parametrize('direction,label',[(1,'BUY'),(-1,'SELL')])
def test_signal_timestamp(direction,label):
    b=bars(10); s=Signal(2,b.index[2],'divergence','ETH-USD',direction,1.)
    assert s.label==label
    assert pd.Timestamp(s.to_dict()['signal_time'])==b.index[3]

def test_flat_rsi_neutral():
    f=indicator_frame(constant_bars())
    assert f.rsi.iloc[-1]==50
    assert f.atr.iloc[-1]>0

def test_rsi_bounds():
    f=indicator_frame(bars(800))
    assert f.rsi.dropna().between(0,100).all()

def test_rvol_uses_previous_bars():
    b=constant_bars(); b['volume']=100; b.iloc[100,b.columns.get_loc('volume')]=500
    f=indicator_frame(b)
    assert f.rvol.iloc[100]==5

@pytest.mark.parametrize('family',['pair_spread','lead_lag'])
def test_peer_required(family,cfg):
    with pytest.raises(ValueError): generate_signals(bars(100),None,Candidate(family,None),cfg)

def test_mismatched_clocks_rejected(cfg):
    b=bars(100); p=bars(100,start='2025-01-02')
    with pytest.raises(DataError): generate_signals(b,p,Candidate('breakout','ETH-USD'),cfg)

def test_unknown_family(cfg):
    with pytest.raises(ValueError): generate_signals(bars(100),None,Candidate('magic',None),cfg)

def test_calendar_refit_anchors_invariant():
    b=bars(3500)
    full=[b.index[i] for i in _refits(b.index,720,168)]
    cut=b.iloc[200:]
    part=[cut.index[i] for i in _refits(cut.index,720,168)]
    assert all(t in full for t in part)

@pytest.mark.parametrize('family',['breakout','divergence','pair_spread','lead_lag'])
def test_no_future_data_changes_past_signals(family,cfg):
    # Synthetic series tests causality, not profitability.
    rng=np.random.default_rng(104)
    n=3600
    x=np.cumsum(rng.normal(0,.006,n))+5
    e=np.zeros(n)
    for i in range(1,n): e[i]=.85*e[i-1]+rng.normal(0,.003)
    b=bars(n,close=np.exp(.8+x+e)); p=bars(n,close=np.exp(x),seed=18)
    cand=Candidate(family,'ETH-USD')
    full=generate_signals(b,p,cand,cfg)
    cut=3100
    prefix=generate_signals(b.iloc[:cut],p.iloc[:cut],cand,cfg)
    a=[s.to_dict() for s in full if s.index<cut]
    assert a==[s.to_dict() for s in prefix]
    for signal in full:
        if family=='pair_spread': assert pd.Timestamp(signal.details['formation_end'])<signal.time
        if family=='lead_lag': assert pd.Timestamp(signal.details['last_training_label_before'])<=signal.time

def test_breakout_excludes_current_high(cfg):
    b=constant_bars(200); b['volume']=100
    b.loc[b.index[100],['open','high','low','close','volume']]=[100,110,99,109,300]
    cfg['signals']['max_atr_fraction']=1
    s=generate_signals(b,None,Candidate('breakout',None),cfg)
    found=[x for x in s if x.index==100]
    assert len(found)==1 and found[0].direction==1
    assert found[0].details['prior_high']<109

def test_opposing_peer_blocks_breakout(cfg):
    b=constant_bars(200); b['volume']=100
    b.loc[b.index[100],['open','high','low','close','volume']]=[100,110,99,109,300]
    p=bars(200,close=np.linspace(100,90,200))
    cfg['signals']['max_atr_fraction']=1
    s=generate_signals(b,p,Candidate('breakout','ETH-USD'),cfg)
    assert not any(x.index==100 for x in s)

@pytest.mark.parametrize('mirror',[False,True])
def test_actual_divergence_only_after_pivot_confirmation(cfg,mirror):
    cl=np.interp(np.arange(230),[0,30,60,80,100,115,150,180,200,229],[100,102,120,90,115,88,110,100,105,105])
    if mirror: cl=220-cl
    b=bars(230,close=cl);b['open']=cl;b['high']=cl+.05;b['low']=cl-.05
    p=constant_bars(230)
    candidate=Candidate('divergence','ETH-USD')
    signals=generate_signals(b,p,candidate,cfg)
    assert signals
    event=next(x for x in signals if x.index==118)
    assert event.direction==(-1 if mirror else 1)
    assert not any(x.index==118 for x in generate_signals(b.iloc[:118],p.iloc[:118],candidate,cfg))
    assert any(x.index==118 for x in generate_signals(b.iloc[:119],p.iloc[:119],candidate,cfg))

def test_actual_lead_lag_prediction_is_causal(cfg):
    rng=np.random.default_rng(156);n=3700
    returns=rng.normal(0,.009,n)
    btc_returns=np.r_[np.zeros(7),returns[:-7]]*.9+rng.normal(0,.001,n)
    p=bars(n,close=100*np.exp(np.cumsum(returns)))
    b=bars(n,close=100*np.exp(np.cumsum(btc_returns)))
    c=Candidate('lead_lag','ETH-USD')
    full=generate_signals(b,p,c,cfg)
    part=generate_signals(b.iloc[:3150],p.iloc[:3150],c,cfg)
    assert len(part)>20
    assert [s.to_dict() for s in full if s.index<3150]==[s.to_dict() for s in part]
    assert all(s.details['probability']=='NOT_ESTIMATED' for s in full)

def test_signal_engine_does_not_bridge_missing_bar(cfg):
    from btc_quant.signals import Candidate, generate_signals
    b=bars(400)
    p=bars(400, close=b.close.to_numpy()*1.01)
    gap=b.index[200]
    b.loc[gap,['open','high','low','close','volume']]=np.nan
    p.loc[gap,['open','high','low','close','volume']]=np.nan
    # Must not crash and any emitted signal must lie on a real bar.
    out=generate_signals(b,p,Candidate('divergence','ETH-USD'),cfg)
    assert all(s.time != gap for s in out)
