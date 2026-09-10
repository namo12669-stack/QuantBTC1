from copy import deepcopy
import pandas as pd
import numpy as np
import pytest
from btc_quant.common import HOUR
from btc_quant.backtest import evaluate_plan,run_backtest
from btc_quant.signals import Signal,Candidate
from btc_quant.app import demo_plan
from conftest import bars,funding


def fixture(cfg,side=1):
    b=bars(40,close=np.full(40,100.));b['open']=100.;b['high']=100.5;b['low']=99.5
    t=b.index[0];p={'id':'test','strategy':{'id':'test'},'direction':side,'entry_price':100.,'stop_loss':98. if side==1 else 102.,
       'take_profit':104. if side==1 else 96.,'quantity_btc':1.,'leverage':2,'initial_margin_usdt':50.,'planned_loss_usdt':2.3,
       'signal':{'signal_bar_open':str(t),'signal_time':str(t+HOUR)},'activate_at':str(t+2*HOUR),
       'entry_expires_at':str(t+4*HOUR),'latest_time_exit':str(t+28*HOUR),'hold_hours':24,
       'rules':{'tick_size':'.01'},'margin_stress_price':52. if side==1 else 148.}
    return p,b,b.copy(),funding(b)

@pytest.mark.parametrize('side',[1,-1])
def test_stop_first_same_bar(cfg,side):
    p,b,m,f=fixture(cfg,side);b.loc[b.index[2],['high','low']]=[105,95]
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['status']=='STOP_FIRST' and o['net_pnl']<0
    assert pd.Timestamp(o['entry_time'])==b.index[2]

@pytest.mark.parametrize('side',[1,-1])
def test_tp_only_after_entry_bar(cfg,side):
    p,b,m,f=fixture(cfg,side)
    if side==1:b.loc[b.index[2],'high']=105;b.loc[b.index[3],'high']=105
    else:b.loc[b.index[2],'low']=95;b.loc[b.index[3],'low']=95
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['status']=='TAKE_PROFIT' and pd.Timestamp(o['exit_time'])==b.index[3]

@pytest.mark.parametrize('side',[1,-1])
def test_touch_not_fill(cfg,side):
    p,b,m,f=fixture(cfg,side)
    if side==1:b.loc[b.index[2:4],'low']=100
    else:b.loc[b.index[2:4],'high']=100
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['status']=='NOT_FILLED' and not o['filled']


def test_stop_gap_worse_than_sl(cfg):
    p,b,m,f=fixture(cfg);b.loc[b.index[3],['open','high','low','close']]=[90,91,89,90]
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['exit_price']==90 and o['net_pnl']<-10


def test_pending_order_gap_not_cancelled_retroactively(cfg):
    p,b,m,f=fixture(cfg);b.loc[b.index[2],'low']=100
    b.loc[b.index[3],['open','high','low','close']]=[90,91,89,90]
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['filled'] and o['net_pnl']<-10


def test_pre_activation_invalidation(cfg):
    p,b,m,f=fixture(cfg);b.loc[b.index[1],'low']=97
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['status']=='CANCELLED_BEFORE_ACTIVATION' and not o['filled']


def test_gap_not_silently_dropped(cfg):
    p,b,m,f=fixture(cfg);b.loc[b.index[3],'close']=np.nan
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['uncertain'] and o['filled'] and o['net_pnl']<=-50 and not o['win']


def test_mark_not_last_drives_margin_stress(cfg):
    p,b,m,f=fixture(cfg);m.loc[m.index[3],'low']=40
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['margin_stress'] and o['net_pnl']<=-50


def test_funding_debit_and_credit(cfg):
    p,b,m,f=fixture(cfg);f['rate']=.001
    long=evaluate_plan(p,b,m,f,cfg)
    p['direction']=-1;p['stop_loss']=102.;p['take_profit']=96.;p['margin_stress_price']=148.
    short=evaluate_plan(p,b,m,f,cfg)
    assert long['funding_usdt']>0 and short['funding_usdt']<0
    assert short['stress_net_pnl']<short['net_pnl']


def test_costs_count_both_legs_of_btc_roundtrip(cfg):
    p,b,m,f=fixture(cfg);b.loc[b.index[3],'high']=105
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['fees_slippage_usdt']==pytest.approx((100+104)*.001)
    assert o['net_pnl']==pytest.approx(4-.204)


def test_paper_evaluation_can_remain_open(cfg):
    p,b,m,f=fixture(cfg)
    o=evaluate_plan(p,b.iloc[:4],m.iloc[:4],f,cfg)
    assert o['status']=='OPEN' and o['net_pnl'] is None


def test_time_exit(cfg):
    p,b,m,f=fixture(cfg)
    o=evaluate_plan(p,b,m,f,cfg)
    assert o['status']=='TIME_EXIT' and pd.Timestamp(o['exit_time'])==b.index[26]


def test_portfolio_nonoverlap_and_equity(cfg):
    b=bars(240,close=np.full(240,100000.));b['open']=100000.;b['high']=100400.;b['low']=99400.
    sigs=[Signal(i,b.index[i],'trend_pullback',None,1,600.,{}) for i in range(40,170)]
    result=run_backtest(b,b.copy(),funding(b),sigs,Candidate('trend_pullback',None,2.),cfg,b.index[30],b.index[-1]+HOUR)
    assert not result.trades.empty
    assert result.equity.iloc[-1]==pytest.approx(500+result.trades.net_pnl.sum())
    entries=pd.to_datetime(result.trades.entry_time,utc=True);exits=pd.to_datetime(result.trades.exit_time,utc=True)
    assert all(entries.iloc[i]>exits.iloc[i-1] for i in range(1,len(entries)))
    assert (result.trades.risk_budget_usdt<=10).all()
