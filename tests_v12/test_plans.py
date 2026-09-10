from copy import deepcopy
from decimal import Decimal
import pandas as pd
import numpy as np
import pytest
from btc_quant.common import PlanError,HOUR,load_config
from btc_quant.plans import quantize,size_position,build_plan,live_plan_checks
from btc_quant.signals import Signal,Candidate
from btc_quant.app import demo_plan
from conftest import bars

@pytest.mark.parametrize('value,step,up,expected',[(1.234,'0.01',False,1.23),(1.234,'0.01',True,1.24),(100.05,'0.1',False,100.),(.012345,'0.001',False,.012)])
def test_rounding(value,step,up,expected):assert quantize(value,step,up)==expected

@pytest.mark.parametrize('value,step',[(float('nan'),'.1'),(1,'0'),(1,'-1')])
def test_rounding_bad(value,step):
    with pytest.raises(PlanError):quantize(value,step)

@pytest.mark.parametrize('equity',[100,500,1000,5000])
@pytest.mark.parametrize('side',[1,-1])
def test_risk_sizing_limits(cfg,equity,side):
    ep=100000;sl=ep-side*1400;tp=ep+side*2800
    p=size_position(ep,sl,tp,equity,cfg,cfg['research_rules'])
    assert p['planned_loss_usdt']<=min(.02*equity,50)+1e-7
    assert p['leverage']<=3 and p['initial_margin_usdt']<=equity*.6
    assert p['notional_usdt']<=cfg['account']['max_notional_usdt']
    assert (Decimal(str(p['quantity_btc']))/Decimal(cfg['research_rules']['step_size']))%1==0
    assert p['liquidation_price'] is None


def test_leverage_does_not_multiply_risk_budget(cfg):
    p=size_position(100000,98600,102800,500,cfg,cfg['research_rules'])
    assert p['risk_budget_usdt']==10
    cfg['account']['max_leverage']=1
    q=size_position(100000,98600,102800,500,cfg,cfg['research_rules'])
    assert q['planned_loss_usdt']<=p['planned_loss_usdt']


def test_low_net_rr_rejected(cfg):
    with pytest.raises(PlanError,match='REWARD'):size_position(100000,99600,100600,500,cfg,cfg['research_rules'])


def test_insufficient_equity_no_order(cfg):
    with pytest.raises(PlanError):size_position(100000,98600,102800,1,cfg,cfg['research_rules'])


def test_demo_full_plan(cfg):
    p=demo_plan(cfg,'2026-09-10 10:07Z')
    assert p['entry_price']==99880 and p['stop_loss']==98980 and p['take_profit']==101680
    assert p['quantity_btc']==.008 and p['orders_placed'] is False
    assert p['planned_loss_usdt']==pytest.approx(9.58992)
    assert p['planned_profit_usdt']==pytest.approx(11.98848)
    assert pd.Timestamp(p['activate_at'])==pd.Timestamp('2026-09-10 11:00Z')


def good_snapshot(p,cfg):
    return {'asof':p['signal']['signal_time'],'rules':cfg['research_rules'],
            'quote':{'mid':100000,'spread_bps':1,'mark_basis_bps':1,'funding_rate':.0001}}

@pytest.mark.parametrize('case,expected',[('old','SIGNAL_TOO_OLD'),('spread','SPREAD_TOO_WIDE'),('basis','MARK_CONTRACT_BASIS_TOO_WIDE'),('funding','ADVERSE_FUNDING_TOO_HIGH'),('stop','SETUP_INVALIDATED'),('rules','EXCHANGE_RULES_CHANGED')])
def test_live_guards(cfg,case,expected):
    p=demo_plan(cfg,'2026-09-10 10:07Z');s=deepcopy(good_snapshot(p,cfg));now=pd.Timestamp('2026-09-10 10:07Z')
    if case=='old':now+=HOUR
    if case=='spread':s['quote']['spread_bps']=50
    if case=='basis':s['quote']['mark_basis_bps']=100
    if case=='funding':s['quote']['funding_rate']=.1
    if case=='stop':s['quote']['mid']=98000
    if case=='rules':s['rules']['step_size']='.01'
    assert any(expected in x for x in live_plan_checks(p,s,cfg,now))


def test_structure_window_gap(cfg):
    b=bars(40,close=np.full(40,100000.));b.loc[b.index[-5],'close']=np.nan
    sig=Signal(39,b.index[-1],'breakout',None,1,600.)
    with pytest.raises(PlanError,match='GAP'):build_plan(sig,b,Candidate('breakout',None,2),cfg,500)
