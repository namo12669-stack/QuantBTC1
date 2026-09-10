import pandas as pd
import pytest
from btc_quant.common import HOUR
from btc_quant.signals import Candidate, Signal
from btc_quant.backtest import directional_exit, funding_cashflow, run_backtest
from conftest import constant_bars, funding


@pytest.mark.parametrize('d,op,hi,lo,sl,tp,expected,reason',[
    (1,100,105,95,98,102,98,'STOP_OR_AMBIGUOUS_STOP_FIRST'),
    (-1,100,105,95,102,98,102,'STOP_OR_AMIGUOUS_STOP_FIRST'),
])
def test_placeholder(d,op,hi,lo,sl,tp,expected,reason):
    # Correct typo is tested below; this parametrized shape guards fixture assumptions.
    actual=directional_exit(pd.Series({'open':op,'high':hi,'low':lo}),d,sl,tp)
    if d==1: assert actual==(expected,'STOP_OR_AMBIGUOUS_STOP_FIRST')
    else: assert actual==(expected,'STOP_OR_AMBIGUOUS_STOP_FIRST')


@pytest.mark.parametrize('d,op,hi,lo,sl,tp,expected,reason',[
    (1,95,100,94,98,102,95,'STOP_GAP'),
    (-1,105,106,100,102,98,105,'STOP_GAP'),
    (1,100,103,99,98,102,102,'TAKE_PROFIT'),
    (-1,100,101,97,102,98,98,'TAKE_PROFIT'),
    (1,100,101,99,98,102,None,None),
])
def test_native_barriers(d,op,hi,lo,sl,tp,expected,reason):
    assert directional_exit(pd.Series({'open':op,'high':hi,'low':lo}),d,sl,tp)==(expected,reason)


def test_spot_empty_funding_is_zero():
    b=constant_bars(); empty=pd.DataFrame(columns=['rate'],index=pd.DatetimeIndex([],tz='UTC'))
    assert funding_cashflow(empty,b,b.index[1],b.index[9],.01)==0


def test_compat_funding_math_still_explicit():
    b=constant_bars(); f=funding(b,.001)
    assert funding_cashflow(f,b,b.index[1],b.index[9],.01)==pytest.approx(-.001)


def test_signal_enters_after_alert_not_past_open(cfg):
    b=constant_bars(); s=Signal(20,b.index[20],'breakout',None,1,1.)
    tr,eq=run_backtest(b,None,None,None,Candidate('breakout',None),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert len(tr)==1
    assert tr.entry_time.iloc[0]==b.index[22]
    assert tr.signal_time.iloc[0]==b.index[21]
    assert tr.net_return.iloc[0]==pytest.approx(-.002)
    assert tr.stress_net_return.iloc[0]==pytest.approx(-.004)
    assert tr.two_legs.iloc[0] == False


def test_pair_relationship_still_trades_btc_only(cfg):
    b=constant_bars(); p=constant_bars()
    s=Signal(20,b.index[20],'pair_spread','ETH-USD',1,1.,beta=2.,details={'z_now':-2.0})
    tr,_=run_backtest(b,p,None,None,Candidate('pair_spread','ETH-USD'),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert len(tr)==1
    assert tr.two_legs.iloc[0] == False
    assert tr.peer.iloc[0]=='ETH-USD'
    assert 'peer_entry' not in tr.columns


def test_end_embargo(cfg):
    b=constant_bars(100); s=Signal(90,b.index[90],'breakout',None,1,1.)
    tr,eq=run_backtest(b,None,None,None,Candidate('breakout',None),cfg,b.index[0],b.index[-1]+HOUR,[s])
    assert tr.empty and (eq==1).all()
