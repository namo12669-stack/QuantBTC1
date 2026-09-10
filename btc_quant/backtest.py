"""Causal conditional-limit simulation with explicit unknown outcomes.

1h bars cannot reveal queue position or intrabar order. Entry requires a trade-through,
not a touch. Stop wins ambiguous brackets; profit is not awarded on the entry candle.
Unknown held periods are retained as adverse margin-loss sensitivity cases and block
strict approval. This is deliberately NOT an exchange-accurate liquidation simulator.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import Counter
import math
import numpy as np
import pandas as pd
from .common import HOUR, PlanError, utc
from .plans import build_plan,cost_per_btc
from .signals import Candidate,Signal


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    worst_equity: pd.Series
    plans: pd.DataFrame
    skips: dict


def _finite_row(frame,t):
    return t in frame.index and np.isfinite(frame.loc[t,['open','high','low','close']].to_numpy(float)).all()


def evaluate_plan(plan: dict, btc: pd.DataFrame, mark: pd.DataFrame, funding: pd.DataFrame, config: dict, end=None) -> dict:
    d=plan['direction'];ep=plan['entry_price'];sl=plan['stop_loss'];tp=plan['take_profit'];q=plan['quantity_btc']
    begin=utc(plan['signal']['signal_bar_open'])+HOUR
    activate=utc(plan['activate_at']);expires=utc(plan['entry_expires_at']);latest=utc(plan['latest_time_exit'])
    end=min(utc(end) if end is not None else btc.index[-1]+HOUR,latest+HOUR)
    fill_time=None;funding_paid=0.;funding_abs=0.;path=[]
    tick=float(plan['rules']['tick_size']);through=tick*config['execution']['touch_through_ticks']
    out={'plan_id':plan['id'],'direction':d,'strategy':plan['strategy']['id'],'entry_price':ep,'sl':sl,'tp':tp,
        'quantity_btc':q,'leverage':plan['leverage'],'initial_margin_usdt':plan['initial_margin_usdt'],
        'risk_budget_usdt':plan['planned_loss_usdt'],'signal_time':plan['signal']['signal_time'],
        'entry_time':None,'exit_time':None,'status':'PENDING','net_pnl':None,'stress_net_pnl':None,
        'uncertain':False,'margin_stress':False,'filled':False,'path':path}

    def finish(status,t,xp=None,uncertain=False,margin_stress=False):
        out.update(status=status,exit_time=str(t),entry_time=str(fill_time) if fill_time is not None else None,
                   filled=fill_time is not None,uncertain=uncertain,margin_stress=margin_stress)
        if fill_time is None and not uncertain:
            out.update(net_pnl=0.,stress_net_pnl=0.,net_r=0.,win=False,fees_slippage_usdt=0.,funding_usdt=0.)
            return out
        if uncertain or margin_stress:
            # Sensitivity, not a fabricated observed stop or observed liquidation.
            gross=-plan['initial_margin_usdt'];xp=ep
        else:gross=q*d*(xp-ep)
        cost=q*cost_per_btc(ep,xp,config,funding_reserve=False)
        net=gross-cost-funding_paid
        stress=gross-config['execution']['stress_multiplier']*cost-config['execution']['stress_multiplier']*funding_abs
        out.update(exit_price=xp,net_pnl=net,stress_net_pnl=stress,net_r=net/plan['planned_loss_usdt'],
                   win=bool(net>0),fees_slippage_usdt=cost,funding_usdt=funding_paid)
        path.append({'time':str(t),'pnl':net,'worst_pnl':net})
        return out

    for t in pd.date_range(begin,end-HOUR,freq='h'):
        if fill_time is None and t>=expires:return finish('NOT_FILLED',t)
        if not _finite_row(btc,t) or not _finite_row(mark,t):
            if t<activate:return finish('CANCELLED_UNOBSERVED_WAIT',t,uncertain=True)
            return finish('UNOBSERVED_DATA_GAP',t,uncertain=True)
        row=btc.loc[t];mr=mark.loc[t]
        if t<activate:
            if (d>0 and (row.low<=sl or row.high>=tp)) or (d<0 and (row.high>=sl or row.low<=tp)):
                return finish('CANCELLED_BEFORE_ACTIVATION',t)
            continue
        was_open=fill_time is not None
        if fill_time is None:
            if t==activate and (d*(row.open-sl)<=0 or d*(tp-row.open)<=0):return finish('CANCELLED_AT_ACTIVATION_OR_GAP',t)
            can_fill=(row.low<=ep-through) if d>0 else (row.high>=ep+through)
            if not can_fill:
                if (d>0 and row.high>=tp) or (d<0 and row.low<=tp):return finish('CANCELLED_TARGET_BEFORE_FILL',t)
                continue
            fill_time=t
        settlements=funding.loc[(funding.index>=t)&(funding.index<t+HOUR)]
        for ft,event in settlements.iterrows():
            flow=d*q*float(mr.open)*float(event['rate'])
            # Charge adverse funding if order/time within the candle is ambiguous.
            if flow>0 or (was_open and ft==t):funding_paid+=flow
            funding_abs+=abs(flow)
        if was_open and t>=fill_time+plan['hold_hours']*HOUR:
            return finish('TIME_EXIT',t,float(row.open))
        stress_hit=(mr.low<=plan['margin_stress_price']) if d>0 else (mr.high>=plan['margin_stress_price'])
        if stress_hit:return finish('MARGIN_STRESS_SENSITIVITY',t,margin_stress=True)
        stop_hit=(row.low<=sl) if d>0 else (row.high>=sl)
        if stop_hit:
            xp=min(float(row.open),sl) if d>0 else max(float(row.open),sl)
            return finish('STOP_FIRST',t,xp)
        # No entry-bar profit: target may have happened before the limit fill.
        if was_open and ((d>0 and row.high>=tp+through) or (d<0 and row.low<=tp-through)):
            return finish('TAKE_PROFIT',t,tp)
        close_pnl=q*d*(float(mr.close)-ep)-q*cost_per_btc(ep,float(mr.close),config,False)-funding_paid
        adverse=float(mr.low) if d>0 else float(mr.high)
        worst=q*d*(adverse-ep)-q*cost_per_btc(ep,adverse,config,False)-funding_paid
        path.append({'time':str(t),'pnl':close_pnl,'worst_pnl':min(close_pnl,worst)})
    out.update(status='OPEN' if fill_time is not None else 'PENDING',filled=fill_time is not None,
               entry_time=str(fill_time) if fill_time is not None else None,funding_usdt=funding_paid)
    return out


def run_backtest(btc: pd.DataFrame,mark: pd.DataFrame,funding: pd.DataFrame,signals: list[Signal],
                 candidate: Candidate,config: dict,start,end) -> BacktestResult:
    start,end=utc(start),utc(end);grid=btc.index[(btc.index>=start)&(btc.index<end)]
    initial=float(config['account']['equity_usdt']);cash=initial;peak=initial
    eq=pd.Series(np.nan,index=grid,dtype=float);worst=eq.copy();trades=[];plans=[];skips=Counter()
    cooldown=start;cursor=0;daily_loss={};weekly_loss={};daily_base={};weekly_base={}
    for sig in sorted(signals,key=lambda s:s.time):
        if sig.time<start or sig.time>=end:continue
        if sig.time<cooldown:continue
        # Do not use a test-ending rule to create truncated artificial winners.
        if sig.time+(config['execution']['entry_delay_bars']+config['execution']['order_valid_hours']+config['execution']['hold_hours']+1)*HOUR>=end:
            skips['END_OF_PERIOD_NO_FULL_WINDOW']+=1;continue
        if cash<=0 or cash<peak*(1-config['account']['drawdown_pause_fraction']):skips['DRAWDOWN_PAUSE']+=1;break
        day=sig.time.floor('D');week=day-pd.Timedelta(days=day.dayofweek)
        daily_base.setdefault(day,cash);weekly_base.setdefault(week,cash)
        try:plan=build_plan(sig,btc,candidate,config,cash)
        except PlanError as exc:skips[str(exc)]+=1;continue
        risk=plan['planned_loss_usdt']
        if daily_loss.get(day,0)+risk>daily_base[day]*config['account']['daily_loss_fraction']+1e-9:
            skips['DAILY_RISK_LIMIT']+=1;continue
        if weekly_loss.get(week,0)+risk>weekly_base[week]*config['account']['weekly_loss_fraction']+1e-9:
            skips['WEEKLY_RISK_LIMIT']+=1;continue
        result=evaluate_plan(plan,btc,mark,funding,config,end)
        if result['status'] in ('OPEN','PENDING'):raise RuntimeError('Unexpected incomplete backtest window')
        done=utc(result['exit_time']);lo=int(grid.searchsorted(sig.time))
        eq.iloc[cursor:lo]=cash;worst.iloc[cursor:lo]=cash
        hi=min(len(grid),int(grid.searchsorted(done,side='right')))
        eq.iloc[lo:hi]=cash;worst.iloc[lo:hi]=cash
        for point in result['path']:
            t=utc(point['time'])
            if t in eq.index:
                eq.loc[t]=cash+point['pnl'];worst.loc[t]=cash+point['worst_pnl']
        plans.append({'plan_id':plan['id'],'signal_time':str(sig.time+HOUR),'activate_at':plan['activate_at'],
                      'status':result['status'],'entry_price':plan['entry_price'],'sl':plan['stop_loss'],'tp':plan['take_profit'],
                      'risk_usdt':risk,'quantity_btc':plan['quantity_btc']})
        if result['filled'] or result['uncertain']:
            item={k:v for k,v in result.items() if k!='path'}
            if item['entry_time'] is None:item['entry_time']=plan['activate_at']
            item['equity_before']=cash;cash+=float(result['net_pnl']);item['equity_after']=cash
            trades.append(item);peak=max(peak,cash)
            exitday=done.floor('D');exitweek=exitday-pd.Timedelta(days=exitday.dayofweek)
            daily_base.setdefault(exitday,item['equity_before']);weekly_base.setdefault(exitweek,item['equity_before'])
            loss=max(0.,-float(result['net_pnl']))
            daily_loss[exitday]=daily_loss.get(exitday,0)+loss;weekly_loss[exitweek]=weekly_loss.get(exitweek,0)+loss
        cursor=hi;cooldown=done+config['execution']['signal_cooldown_hours']*HOUR
    eq.iloc[cursor:]=cash;worst.iloc[cursor:]=cash
    eq=eq.ffill().fillna(initial);worst=worst.ffill().fillna(initial)
    return BacktestResult(pd.DataFrame(trades),eq,worst,pd.DataFrame(plans),dict(skips))
