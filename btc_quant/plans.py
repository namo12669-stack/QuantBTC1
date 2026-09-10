"""Risk-defined, conditional BTC-only plans. No exchange order is ever submitted."""
from __future__ import annotations
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import hashlib
import math
import numpy as np
import pandas as pd
from .common import HOUR, PlanError, utc
from .signals import Signal, Candidate


def quantize(value: float, step: str|float, up=False) -> float:
    x=Decimal(str(value));s=Decimal(str(step))
    if not x.is_finite() or not s.is_finite() or s<=0:raise PlanError('INVALID_ROUNDING_INPUT')
    return float((x/s).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*s)


def cost_per_btc(entry: float, exit_price: float, config: dict, funding_reserve=True) -> float:
    e=config['execution']
    trading=(entry+exit_price)*(e['fee_bps_per_side']+e['slippage_bps_per_side'])/10000
    return trading+(entry*e['funding_reserve_bps']/10000 if funding_reserve else 0.)


def size_position(entry,stop,target,equity,config,rules):
    a=config['account'];e=config['execution']
    if not np.isfinite([entry,stop,target,equity]).all() or min(entry,stop,target,equity)<=0:raise PlanError('INVALID_PLAN_NUMBER')
    risk_budget=min(equity*a['risk_fraction'],a['hard_risk_cap_usdt'])
    per_unit=abs(entry-stop)+cost_per_btc(entry,stop,config)
    q_risk=risk_budget/per_unit
    options=[]
    for lev in range(1,a['max_leverage']+1):
        stress_fraction=1/lev-a['maintenance_rate_assumption']-a['liquidation_fee_buffer_assumption']-cost_per_btc(entry,stop,config)/entry
        if stress_fraction<=a['min_margin_stress_stop_multiple']*abs(entry-stop)/entry:continue
        # Reserve entry/exit cost as well as initial margin within the 60% allocation.
        margin_budget=equity*a['max_margin_fraction']
        q_margin=margin_budget/(entry/lev+cost_per_btc(entry,stop,config))
        qty=quantize(min(q_risk,q_margin,a['max_notional_usdt']/entry),rules['step_size'])
        if qty<float(rules['min_qty']) or qty*entry<float(rules['min_notional']):continue
        options.append((qty,lev,stress_fraction))
    if not options:raise PlanError('INSUFFICIENT_MARGIN_OR_MINIMUM_ORDER_SIZE')
    qty,lev,stress=max(options,key=lambda x:(x[0],-x[1]))
    loss=qty*per_unit
    profit=qty*(abs(target-entry)-cost_per_btc(entry,target,config))
    if profit<=0 or profit/loss<e['min_net_reward_risk']:raise PlanError('INSUFFICIENT_NET_REWARD_RISK_AFTER_COST_RESERVE')
    return {'quantity_btc':qty,'notional_usdt':qty*entry,'leverage':lev,'margin_mode':'ISOLATED',
        'initial_margin_usdt':qty*entry/lev,'planned_loss_usdt':loss,'risk_budget_usdt':risk_budget,
        'hard_risk_cap_usdt':a['hard_risk_cap_usdt'],'planned_profit_usdt':profit,'net_reward_risk':profit/loss,
        'position_to_equity':qty*entry/equity,'equity_used_usdt':equity,
        'size_reduced_by_margin':qty+float(rules['step_size'])<q_risk,
        'margin_stress_price':entry*(1-stress if stop<entry else 1+stress),
        'margin_stress_price_is_NOT_exchange_liquidation_price':True,
        'liquidation_price':None,'actual_liquidation_and_fee_tier_verified':False}


def build_plan(signal: Signal, btc: pd.DataFrame, candidate: Candidate, config: dict, equity: float, rules: dict|None=None) -> dict:
    e=config['execution'];rules=rules or config['research_rules'];i=signal.index;d=signal.direction
    if d not in (-1,1) or not 0<=i<len(btc):raise PlanError('INVALID_SIGNAL_INDEX_OR_SIDE')
    n=e['structure_hours'];hist=btc.iloc[max(0,i-n+1):i+1]
    if len(hist)<n or hist[['open','high','low','close']].isna().any().any():raise PlanError('STRUCTURE_WINDOW_HAS_GAP')
    atr=float(signal.atr);close=float(btc.close.iloc[i])
    if not math.isfinite(atr) or atr<=0:raise PlanError('INVALID_ATR')
    entry=quantize(close-d*e['entry_retrace_atr']*atr,rules['tick_size'],up=d<0)
    structure=float(hist.low.min()-e['structure_buffer_atr']*atr) if d>0 else float(hist.high.max()+e['structure_buffer_atr']*atr)
    if signal.family=='divergence':
        pivot=float(signal.details['price_2'])-d*e['structure_buffer_atr']*atr
        structure=min(structure,pivot) if d>0 else max(structure,pivot)
    distance=max(e['stop_atr_min']*atr,d*(entry-structure),entry*e['stop_fraction_min'])
    if distance>min(e['stop_atr_max']*atr,entry*e['stop_fraction_max']):raise PlanError('STRUCTURE_STOP_TOO_WIDE_NO_TRADE')
    stop=quantize(entry-d*distance,rules['tick_size'],up=d<0)
    target=quantize(entry+d*candidate.reward_risk*abs(entry-stop),rules['tick_size'],up=d<0)
    if min(entry,stop,target)<=0 or d*(entry-stop)<=0 or d*(target-entry)<=0:raise PlanError('INVALID_BRACKET')
    start=signal.time+e['entry_delay_bars']*HOUR
    expiry=start+e['order_valid_hours']*HOUR
    identity=f'{candidate.name}|{signal.time}|{d}|{entry}|{stop}|{target}'
    return {'id':hashlib.sha256(identity.encode()).hexdigest()[:20],'schema':4,'venue':'binance_usdm','symbol':'BTCUSDT',
        'strategy':candidate.to_dict(),'signal':signal.to_dict(),'side':'LONG' if d==1 else 'SHORT','direction':d,
        'action':'BUY / LONG' if d==1 else 'SELL / SHORT','companion_role':'signal context only; NO companion order',
        'entry_type':'CONDITIONAL LIMIT','entry_price':entry,'stop_loss':stop,'take_profit':target,
        'stop_trigger':'CONTRACT_PRICE (Last Price); exit STOP_MARKET; check Binance UI',
        'take_profit_type':'limit/reduce-only after fill; verify one-way/hedge mode yourself',
        'activate_at':str(start),'entry_expires_at':str(expiry),'hold_hours':e['hold_hours'],
        'latest_time_exit':str(expiry+e['hold_hours']*HOUR),'rules':rules,
        'planned_loss_is_not_guaranteed_maximum':True,'orders_placed':False,
        **size_position(entry,stop,target,equity,config,rules)}


def live_plan_checks(plan: dict, snapshot: dict, config: dict, now=None) -> list[str]:
    now=utc(now or snapshot['asof']);e=config['execution'];q=snapshot['quote'];problems=[]
    closed=utc(plan['signal']['signal_time'])
    if now<closed or (now-closed).total_seconds()>60*e['max_alert_delay_minutes']:problems.append('SIGNAL_TOO_OLD')
    if now>=utc(plan['activate_at']):problems.append('ENTRY_ACTIVATION_ALREADY_PASSED')
    if q['spread_bps']>e['max_live_spread_bps']:problems.append('SPREAD_TOO_WIDE')
    if q['mark_basis_bps']>e['max_live_mark_basis_bps']:problems.append('MARK_CONTRACT_BASIS_TOO_WIDE')
    if plan['direction']*q['funding_rate']>e['max_adverse_funding_rate']:problems.append('ADVERSE_FUNDING_TOO_HIGH')
    px=q['mid'];sl=plan['stop_loss'];tp=plan['take_profit'];d=plan['direction']
    if d*(px-sl)<=0 or d*(tp-px)<=0:problems.append('SETUP_INVALIDATED_OR_TARGET_ALREADY_REACHED')
    if abs(px-plan['entry_price'])>2*plan['signal']['atr']:problems.append('PRICE_TOO_FAR_FROM_ENTRY_DO_NOT_CHASE')
    for k in ('tick_size','step_size','min_qty','min_notional'):
        if Decimal(str(snapshot['rules'][k]))!=Decimal(str(config['research_rules'][k])):
            problems.append('EXCHANGE_RULES_CHANGED_RESEARCH_MUST_BE_RERUN');break
    return problems
