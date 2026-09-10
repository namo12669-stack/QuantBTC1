"""Historical frequency/expectancy diagnostics, never next-trade win probabilities."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy.stats import norm
from .common import utc
from .backtest import BacktestResult

REAL_SOURCE='real_binance_usdm_archive'

def wilson_lower(wins:int,n:int,alpha=.05)->float:
    if n<=0:return 0.
    z=float(norm.ppf(1-alpha));p=wins/n
    return float((p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n))


def metrics(result:BacktestResult,config:dict)->dict:
    tr=result.trades;eq=result.equity;initial=config['account']['equity_usdt']
    if eq.empty:raise ValueError('Empty equity clock')
    daily=eq.resample('1D').last().ffill();dr=daily.pct_change(fill_method=None);dr.iloc[0]=daily.iloc[0]/initial-1
    sd=float(dr.std(ddof=1));sharpe=float(dr.mean()/sd*math.sqrt(365)) if sd>1e-12 else 0.
    hist=np.r_[initial,eq.to_numpy(float)];dd=float(np.max(1-hist/np.maximum.accumulate(hist)))
    # Intrabar lows are ordered conservatively and can overstate attainable drawdown.
    low=np.r_[initial,result.worst_equity.to_numpy(float)];worstdd=float(np.max(1-low/np.maximum.accumulate(hist)))
    me=eq.resample('ME').last();mr=me.pct_change(fill_method=None);mr.iloc[0]=me.iloc[0]/initial-1
    pnl=tr.net_pnl.to_numpy(float) if len(tr) else np.array([])
    pos=float(pnl[pnl>0].sum());neg=float(-pnl[pnl<0].sum())
    return {'trades':len(tr),'wins':int((pnl>0).sum()),'win_rate':float((pnl>0).mean()) if len(tr) else None,
            'profit_factor':pos/neg if neg>0 else (None if pos>0 else 0.),
            'no_losing_trades':bool(pos>0 and neg==0),'gross_wins_usdt':pos,'gross_losses_usdt':neg,
            'mean_net_r':float(tr.net_r.mean()) if len(tr) else None,'mean_net_pnl_usdt':float(pnl.mean()) if len(tr) else None,
            'mean_stress_pnl_usdt':float(tr.stress_net_pnl.mean()) if len(tr) else None,
            'net_profit_usdt':float(eq.iloc[-1]-initial),'final_equity_usdt':float(eq.iloc[-1]),
            'total_return':float(eq.iloc[-1]/initial-1),'daily_net_sharpe':sharpe,
            'max_drawdown_close_mark':dd,'max_drawdown_intrabar_conservative':worstdd,
            'positive_month_fraction':float((mr>0).mean()),'months':len(me),
            'uncertain_trades':int(tr.uncertain.sum()) if len(tr) else 0,
            'margin_stress_events':int(tr.margin_stress.sum()) if len(tr) else 0,
            'plans':len(result.plans),'skips':result.skips}


def block_bounds(trades:pd.DataFrame,alpha:float,repetitions:int,seed:int)->dict:
    if trades.empty:return {'block_win_lower':0.,'block_expectancy_lower_r':-1.,'active_weeks':0}
    x=trades.copy();st=pd.to_datetime(x.entry_time,utc=True)
    x['week']=st.dt.floor('D')-pd.to_timedelta(st.dt.dayofweek,unit='D')
    g=x.groupby('week').agg(n=('net_r','size'),wins=('win','sum'),r=('net_r','sum'))
    calendar=pd.date_range(g.index.min(),g.index.max(),freq='7D');a=g.reindex(calendar,fill_value=0).to_numpy(float)
    n=len(a);length=min(4,n);rng=np.random.default_rng(seed)
    starts=rng.integers(0,n,size=(repetitions,math.ceil(n/length)))
    ids=((starts[:,:,None]+np.arange(length))%n).reshape(repetitions,-1)[:,:n]
    totals=a[ids].sum(axis=1);valid=totals[:,0]>0
    if valid.sum()<repetitions/2:return {'block_win_lower':0.,'block_expectancy_lower_r':-1.,'active_weeks':len(g)}
    return {'block_win_lower':float(np.quantile(totals[valid,1]/totals[valid,0],alpha)),
            'block_expectancy_lower_r':float(np.quantile(totals[valid,2]/totals[valid,0],alpha)),
            'active_weeks':len(g),'calendar_weeks':n,'block_weeks':length}


def validate_evidence(result:BacktestResult,config:dict,source:str)->dict:
    gate=config['proof_gate'];m=metrics(result,config);threshold=gate['minimum_win_rate_lower_bound']
    common=[];alpha=gate['family_alpha']/gate['confidence_checks']
    if source!=REAL_SOURCE:common.append('NOT_VERIFIED_REAL_BINANCE_DATA')
    if m['months']<gate['minimum_test_calendar_months']:common.append('TOO_FEW_TEST_MONTHS')
    if m['max_drawdown_intrabar_conservative']>gate['maximum_drawdown']:common.append('DRAWDOWN_TOO_HIGH')
    if m['positive_month_fraction']<gate['minimum_positive_month_fraction']:common.append('UNSTABLE_MONTHLY_RESULTS')
    if m['uncertain_trades']:common.append('UNOBSERVED_TRADE_PATHS_REQUIRE_DATA_REPAIR')
    if m['margin_stress_events']:common.append('MARGIN_STRESS_REQUIRES_EXACT_EXCHANGE_REVIEW')
    if m['mean_stress_pnl_usdt'] is None or m['mean_stress_pnl_usdt']<=0:common.append('DOUBLE_COST_STRESS_FAILED')
    subsets={}
    for name,d in [('overall',None),('LONG',1),('SHORT',-1)]:
        t=result.trades if d is None or result.trades.empty else result.trades.loc[result.trades.direction==d]
        n=len(t);w=int(t.win.sum()) if n else 0;reasons=[]
        lo=wilson_lower(w,n,alpha);bb=block_bounds(t,alpha,gate['bootstrap_repetitions'],gate['seed']+(d or 0))
        lower=min(lo,bb['block_win_lower']);minimum=gate['minimum_test_trades'] if d is None else gate['minimum_direction_trades']
        weeks=gate['minimum_active_weeks'] if d is None else gate['minimum_direction_active_weeks']
        if n<minimum:reasons.append('INSUFFICIENT_TRADES')
        if bb['active_weeks']<weeks:reasons.append('INSUFFICIENT_ACTIVE_WEEKS')
        if lower<=threshold:reasons.append('HISTORICAL_LOWER_BOUND_NOT_ABOVE_80_PERCENT')
        if bb['block_expectancy_lower_r']<=0:reasons.append('EXPECTANCY_BOUND_NOT_POSITIVE')
        if n:
            gains=float(t.loc[t.net_pnl>0,'net_pnl'].sum());losses=float(-t.loc[t.net_pnl<0,'net_pnl'].sum())
            if losses>0 and gains/losses<gate['minimum_profit_factor']:reasons.append('PROFIT_FACTOR_TOO_LOW')
            if t.stress_net_pnl.mean()<=0:reasons.append('SIDE_DOUBLE_COST_STRESS_FAILED')
        subsets[name]={'n':n,'wins':w,'win_rate':w/n if n else None,'wilson_lower':lo,**bb,
                       'historical_lower_bound':lower,'passed':not reasons,'reasons':reasons}
    allowed=[s for s in ('LONG','SHORT') if not common and subsets['overall']['passed'] and subsets[s]['passed']]
    return {'metrics':m,'subsets':subsets,'approved_sides':allowed,'approved':bool(allowed),
            'reasons':common,'per_test_alpha':alpha,'next_trade_probability':None,
            'target':'historical net win-rate lower bound >80%; NOT a next-trade probability',
            'method':'one-sided Wilson + 4-week circular block bootstrap; smaller win bound; positive net R bound',
            'uncertainty_note':'These diagnostics cannot establish stationarity, eliminate selection bias, or guarantee future outcomes.'}
