import numpy as np
import pandas as pd
import pytest
from btc_quant.common import HOUR
from btc_quant.signals import Candidate, Signal
from btc_quant.backtest import directional_exit, funding_cashflow, run_backtest
from conftest import bars, constant_bars, funding

@pytest.mark.parametrize('d,op,hi,lo,sl,tp,expected,reason',[
    (1,100,105,95,98,102,98,'STOP_OR_AMBIGUOUS_STOP_FIRST'),
    (-1,100,105,95,102,98,102,'STOP_OR_AMBIGUOUS_STOP_FIRST'),
    (1,95,100,94,98,102,95,'STOP_GAP'),
    (-1,105,106,100,102,98,105,'STOP_GAP'),
    (1,100,103,99,98,102,102,'TAKE_PROFIT'),
    (-1,100,101,97,102,98,98,'TAKE_PROFIT'),
    (1,100,101,99,98,102,None,None),
])
def test_native_barriers(d,op,hi,lo,sl,tp,expected,reason):
    assert directional_exit(pd.Series({'open':op,'high':hi,'low':lo}),d,sl,tp)==(expected,reason)

@pytest.mark.parametrize('quantity,expected',[(.01,-.001),(-.01,.001)])
def test_funding_direction(quantity,expected):
    b=constant_bars(); f=funding(b,.001)
    value=funding_cashflow(f,b,b.index[1],b.index[9],quantity)
    assert value==pytest.approx(expected)

def test_entry_settlement_is_excluded():
    b=constant_bars(); f=funding(b,.001)
    assert funding_cashflow(f,b,b.index[8],b.index[9],.01)==0

def test_signal_enters_after_alert_not_past_open(cfg):
    b=constant_bars(); f=funding(b)
    s=Signal(20,b.index[20],'breakout',None,1,1.)
    tr,eq=run_backtest(b,None,f,None,Candidate('breakout',None),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert len(tr)==1
    assert tr.entry_time.iloc[0]==b.index[22]
    assert tr.signal_time.iloc[0]==b.index[21]
    assert tr.exit_time.iloc[0]==b.index[46]
    assert tr.net_return.iloc[0]==pytest.approx(-.002)
    assert tr.stress_net_return.iloc[0]==pytest.approx(-.004)
    assert eq.iloc[-1]==pytest.approx(.998)

def test_overlapping_trades_and_cooldown_filtered(cfg):
    b=constant_bars(); f=funding(b)
    ss=[Signal(i,b.index[i],'breakout',None,1,1.) for i in (20,21,45,52,53)]
    tr,eq=run_backtest(b,None,f,None,Candidate('breakout',None),cfg,b.index[0],b.index[-1]+HOUR,ss)
    assert list(tr.entry_time)==[b.index[22],b.index[55]]
    assert eq.iloc[-1]==pytest.approx(.998**2)

def test_end_embargo_does_not_keep_only_fast_winners(cfg):
    b=constant_bars(100); f=funding(b)
    s=Signal(90,b.index[90],'breakout',None,1,1.)
    tr,eq=run_backtest(b,None,f,None,Candidate('breakout',None),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert tr.empty
    assert (eq==1).all()

def test_pair_beta_sizes_notionals_and_charges_both_legs(cfg):
    b=constant_bars(); p=constant_bars(); p[['open','high','low','close']]*=2
    s=Signal(20,b.index[20],'pair_spread','ETHUSDT',1,1.,beta=2.,alpha=np.log(100)-2*np.log(200),spread_mean=0,spread_std=.01)
    tr,eq=run_backtest(b,p,funding(b),funding(p),Candidate('pair_spread','ETHUSDT'),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert len(tr)==1
    r=tr.iloc[0]
    assert r.bitcoin_notional_weight==pytest.approx(1/3)
    assert r.peer_notional_weight==pytest.approx(2/3)
    assert r.fees_and_slippage==pytest.approx(.002)
    assert r.exit_time==b.index[24]
    assert r.exit_reason=='SPREAD_CONVERGED'

def test_pair_stop_is_delayed_not_same_close(cfg):
    b=constant_bars(); p=constant_bars()
    # At entry close a positive spread is adverse for a SHORT-BTC pair.
    b.loc[b.index[22],['high','close']]=[110,110]
    b.loc[b.index[23],['open','high','low','close']]=[110,112,109,111]
    b.loc[b.index[24],['open','high','low','close']]=[112,113,111,112]
    s=Signal(20,b.index[20],'pair_spread','ETHUSDT',-1,1.,beta=1.,alpha=0,spread_std=.01)
    tr,eq=run_backtest(b,p,funding(b),funding(p),Candidate('pair_spread','ETHUSDT'),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert tr.exit_time.iloc[0]==b.index[24]
    assert tr.bitcoin_exit.iloc[0]==112
    assert tr.exit_reason.iloc[0]=='SPREAD_STOP_CLOSE_BASED'
    assert tr.net_return.iloc[0]<-.02

def test_mark_to_market_drawdown_present(cfg):
    b=constant_bars(); f=funding(b)
    b.loc[b.index[23],['open','high','low','close']]=[100,100,96,97]
    s=Signal(20,b.index[20],'breakout',None,1,10.)
    tr,eq=run_backtest(b,None,f,None,Candidate('breakout',None),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert eq.iloc[23]<.97
    assert eq.iloc[-1]>.99
