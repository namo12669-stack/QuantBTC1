"""Selection period chooses ONE candidate. Holdout cannot choose a replacement."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import pandas as pd
from .common import VERSION,SCHEMA,utc,fingerprint,write_json
from .signals import Candidate,generate_signals
from .backtest import run_backtest
from .evidence import REAL_SOURCE,metrics,validate_evidence


def candidates(config):
    for family in config['signals']['families']:
        peers=([None] if family not in ('lead_lag','pair_spread') else [])+config['data']['peers']
        for peer in peers:
            for rr in config['selection']['reward_risk_candidates']:
                yield Candidate(family,peer,float(rr))


def select(records,config):
    s=config['selection'];qual=[]
    for r in records:
        pf=r['profit_factor']
        okay=(r['trades']>=s['min_validation_trades'] and (r['mean_net_r'] or 0)>0
            and (r['no_losing_trades'] or (pf is not None and pf>=s['min_validation_profit_factor']))
            and r['positive_month_fraction']>=s['min_validation_positive_month_fraction']
            and (r['mean_stress_pnl_usdt'] or 0)>0 and r['daily_net_sharpe']>0
            and not r['uncertain_trades'] and not r['margin_stress_events'])
        # A companion must improve its matching BTC-only strategy when that baseline exists.
        baselines=[b for b in records if b['family']==r['family'] and b['peer'] is None and b['reward_risk']==r['reward_risk']]
        if r['peer']:
            if not baselines:
                # A pair-only method has no identical BTC-only counterpart. Use the
                # strongest declared BTC-only selection benchmark, not a fabricated hedge result.
                baselines=[b for b in records if b['peer'] is None]
            if not baselines or r['daily_net_sharpe']<=max(b['daily_net_sharpe'] for b in baselines):okay=False
        if okay:qual.append(r)
    order=lambda r:(-r['daily_net_sharpe'],r['id'])
    return (sorted(qual,key=order)[0] if qual else None), (sorted(records,key=order)[0] if records else None)


def research(config,prices,mark,funding,output:Path,manifest:dict,source=REAL_SOURCE):
    output.mkdir(parents=True,exist_ok=True);d=config['data'];btc=prices[d['bitcoin']]
    vs,ts,end=[utc(d[k]) for k in ('validation_start','test_start','end_exclusive')]
    records=[];event_cache={}
    for cand in candidates(config):
        key=(cand.family,cand.peer)
        if key not in event_cache:
            mask=btc.index<ts
            peer=prices[cand.peer].loc[mask] if cand.peer else None
            event_cache[key]=generate_signals(btc.loc[mask],peer,cand,config)
        result=run_backtest(btc,mark,funding,event_cache[key],cand,config,vs,ts)
        rec={**cand.to_dict(),**metrics(result,config)};records.append(rec)
        folder=output/'selection_trades';folder.mkdir(exist_ok=True)
        result.trades.to_csv(folder/f'{cand.name}.csv',index=False)
        print(f"SELECTION {cand.name}: {rec['trades']} trades; net={rec['net_profit_usdt']:.2f}; sharpe={rec['daily_net_sharpe']:.3f}",flush=True)
    pd.DataFrame(records).to_csv(output/'pair_selection.csv',index=False)
    winner,best=select(records,config);chosen=winner or best
    model={'schema':SCHEMA,'version':VERSION,'venue':'binance_usdm','source':source,
        'fingerprint':fingerprint(config),'created_at':str(pd.Timestamp.now(tz='UTC')),
        'validation_start':str(vs),'test_start':str(ts),'test_end_exclusive':str(end),
        'selection_trials':len(records),'selection_used_holdout':False,'validation_qualified':bool(winner),
        'selected':None,'approved':False,'approved_sides':[],'status':'NO_SELECTION_CANDIDATE',
        'research_rules':config['research_rules'],'data_quality':manifest.get('gap_summary',{}),
        'next_trade_probability':None,
        'limitations':['No live execution or account visibility.','Source-informed model design, not a preregistered independent experiment.',
          'A 1h fill model is not order-book replay. Intrabar ordering is conservative.',
          'Funding rates are historical; valuation uses mark price at the opening of the funding hour.',
          'Maintenance-rate and liquidation buffers are assumptions, not account-specific Binance liquidation calculations.',
          'Historical exchange filters and your exact fee tier have not been reconstructed.',
          'Strict approval does not prove a next-trade 80% probability. Repeated holdout tuning compromises independence.',
          'No news engine or gold factor is active. Crypto companion is context, not a hedge order.']}
    if chosen:
        cand=Candidate(chosen['family'],chosen['peer'],chosen['reward_risk']);model['selected']=cand.to_dict();model['selection_metrics']=chosen
        # Signal computation is causal. Models refit only on labels that have matured.
        events=generate_signals(btc,prices[cand.peer] if cand.peer else None,cand,config)
        result=run_backtest(btc,mark,funding,events,cand,config,ts,end)
        result.trades.to_csv(output/'holdout_trades.csv',index=False)
        result.plans.to_csv(output/'holdout_plans.csv',index=False)
        pd.DataFrame({'equity_usdt':result.equity,'intrabar_conservative_equity':result.worst_equity}).to_csv(output/'holdout_equity.csv',index_label='time')
        ev=validate_evidence(result,config,source);model['evidence']=ev
        model['approved_sides']=ev['approved_sides'] if winner else []
        model['approved']=bool(model['approved_sides'])
        model['status']='HISTORICAL_GATE_PASSED' if model['approved'] else 'NO_VALIDATED_80_PERCENT_EDGE'
        model['holdout_ledger_sha256']=hashlib.sha256((output/'holdout_trades.csv').read_bytes()).hexdigest()
    write_json(output/'model.json',model)
    write_json(output/'data_manifest.json',manifest)
    write_json(output/'run_environment.json',{'python':platform.python_version(),**{x:importlib.metadata.version(x) for x in ['numpy','pandas','scipy','statsmodels','requests']}})
    (output/'BACKTEST_REPORT.md').write_text(render_report(model,records,config),encoding='utf-8')
    return model


def _fmt(x,digits=3):return 'N/A' if x is None else f'{x:.{digits}f}'

def render_report(model,records,config):
    lines=['# BTC Bot 2 v1.2 - conditional trade-plan research','',f"Status: **{model['status']}**",'',
      f"Source: `{model['source']}` / market: `Binance USD-M BTCUSDT perpetual`",
      f"Selection: {model['validation_start']} to {model['test_start']} (exclusive).",
      f"Holdout: {model['test_start']} to {model['test_end_exclusive']} (exclusive).",
      f"Initial equity: {config['account']['equity_usdt']} USDT. Risk: {config['account']['risk_fraction']:.1%}, capped at 50 USDT; leverage <=3x.",
      '', '**No next-trade win probability has been estimated. NO_VALIDATED_80_PERCENT_EDGE is a valid research outcome, not a software failure.**',
      '', '## Research-to-code decisions',
      '- Uploaded SWU thesis: monthly Thai gold response, not a BTC 1h trading strategy. BTC coefficient p=0.3271; no gold factor imposed.',
      '- Lancaster proposal: EMA27/125, ADX90, ATR14 inspire a pullback hypothesis; exits/short side are our adaptations, not a replication.',
      '- All candidates use the SAME limit-entry timing and risk rules. Relative best means best among these candidates only.',
      '- The holdout starts June 2025, after the Lancaster reported sample ended. It is still not a preregistered forward trial.',
      '', '## Selection (not holdout optimization)',
      '| Candidate | Trades | Win rate | Net USDT | Profit factor | Daily Sharpe |',
      '|---|---:|---:|---:|---:|---:|']
    for r in sorted(records,key=lambda x:-x['daily_net_sharpe']):
        wr='N/A' if r['win_rate'] is None else f"{r['win_rate']:.1%}"
        pf='no losses' if r['no_losing_trades'] else _fmt(r['profit_factor'])
        lines.append(f"| {r['id']} | {r['trades']} | {wr} | {r['net_profit_usdt']:.2f} | {pf} | {r['daily_net_sharpe']:.3f} |")
    if model.get('evidence'):
        ev=model['evidence'];m=ev['metrics']
        lines+=['','## Frozen holdout result',f"Selected: `{model['selected']['id']}`",f"Selection-qualified: {model['validation_qualified']}",
            f"Approved sides: {', '.join(model['approved_sides']) or 'NONE'}",'',
            f"Trades: {m['trades']}; wins: {m['wins']}; final equity: {m['final_equity_usdt']:.2f} USDT.",
            f"Net profit: {m['net_profit_usdt']:.2f} USDT; net expectancy per trade: {_fmt(m['mean_net_r'])} R.",
            f"Close-mark drawdown: {m['max_drawdown_close_mark']:.1%}; conservative intrabar drawdown: {m['max_drawdown_intrabar_conservative']:.1%}.",
            f"Unobserved cases: {m['uncertain_trades']}; margin stress events: {m['margin_stress_events']}.",
            f"Double-cost stress mean PnL (same fills/size, not a separately rebalanced account): {_fmt(m['mean_stress_pnl_usdt'])} USDT.",
            '', '| Subset | N | Observed win | Conservative historical lower bound | Result |', '|---|---:|---:|---:|---|']
        for side,x in ev['subsets'].items():
            wr='N/A' if x['win_rate'] is None else f"{x['win_rate']:.1%}"
            lines.append(f"| {side} | {x['n']} | {wr} | {x['historical_lower_bound']:.1%} | {'PASS' if x['passed'] else ', '.join(x['reasons'])} |")
        lines+=['',f"Shared blocks: {', '.join(ev['reasons']) or 'None'}"]
    lines+=['','## Data quality - no invented candles','| Series | Missing bars | Fraction | Longest gap |','|---|---:|---:|---:|']
    for symbol,q in model['data_quality'].items():lines.append(f"| {symbol} | {q['missing_bars']} | {q['missing_fraction']:.3%} | {q['max_consecutive_missing_hours']}h |")
    lines+=['','Gaps reset signal models. Unobserved trade paths remain in the ledger as adverse margin-loss sensitivity cases and block strict approval; they are NOT silently discarded.',
        '', '## Execution and remaining limitations',
        'A signal at candle open T is known at T+1h. Its conditional limit may only activate at T+2h, expires after 2h, and requires a one-tick trade-through. Stop wins a same-bar conflict. No TP is credited on the fill candle. The user must check validity at activation and place exchange-side protection.',
        *[f'- {x}' for x in model['limitations']], '',
        'The strategy may produce no acceptable edge. Never alter this report, lower gates silently, or substitute Coinbase spot data to obtain a Binance perpetual trade plan.']
    return '\n'.join(lines)+'\n'
