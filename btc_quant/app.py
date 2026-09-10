from __future__ import annotations
import argparse
import copy
from pathlib import Path
import os
import sys
import traceback
import numpy as np
import pandas as pd
from .common import VERSION,SCHEMA,HOUR,DataError,PlanError,load_config,utc,fingerprint,write_json
from .data import download_history,load_history,check_data,live_snapshot
from .signals import Candidate,Signal,generate_signals
from .plans import build_plan,live_plan_checks
from .backtest import evaluate_plan
from .research import research
from .store import Store,StateError
from .telegram import send,setup_bot,TelegramError
from .report import format_plan,status_text


def default_runtime():return {'schema':SCHEMA,'seen':[],'notices':{},'active':None,'reservations':[]}


def update_account(store:Store,equity:float,flat:bool,config:dict,now=None)->dict:
    now=utc(now or pd.Timestamp.now(tz='UTC'))
    if not np.isfinite(equity) or equity<=0:raise ValueError('Positive finite equity is required')
    if not flat:raise ValueError('Confirm no open BTC position AND no pending entry order first')
    old=store.get('account.json',{});prev=float(old.get('equity',equity))
    changes=list(old.get('reported_losses',[]))
    if equity<prev:changes.append({'time':str(now),'loss':prev-equity})
    account={'schema':SCHEMA,'equity':equity,'confirmed_at':str(now),'flat_confirmed':True,
        'high_water_equity':max(equity,float(old.get('high_water_equity',equity))),
        'reported_losses':[x for x in changes if utc(x['time'])>now-pd.Timedelta(days=8)]}
    runtime=store.get('runtime.json',default_runtime())
    # The user explicitly confirms that previous actual orders/positions are flat.
    runtime['active']=None
    store.put('runtime.json',runtime);store.put('account.json',account)
    return account


def account_checks(account:dict|None,runtime:dict,config:dict,now,risk:float|None=None)->list[str]:
    a=config['account'];now=utc(now)
    if not account or not account.get('flat_confirmed'):return ['CONFIRM_CURRENT_EQUITY_AND_FLAT_POSITION']
    if (now-utc(account['confirmed_at'])).total_seconds()>a['max_equity_age_hours']*3600:return ['EQUITY_CONFIRMATION_EXPIRED']
    if utc(account['confirmed_at'])>now:return ['ACCOUNT_TIMESTAMP_IN_FUTURE']
    if account['equity']<account['high_water_equity']*(1-a['drawdown_pause_fraction']):return ['ACCOUNT_DRAWDOWN_PAUSE']
    day=now.floor('D');week=day-pd.Timedelta(days=day.dayofweek)
    # Conservative alert-risk reservation, not a claim about broker fills or realized PnL.
    entries=runtime.get('reservations',[])
    losses=account.get('reported_losses',[])
    dayrisk=sum(x['risk'] for x in entries if utc(x['time'])>=day)+sum(x['loss'] for x in losses if utc(x['time'])>=day)
    weekrisk=sum(x['risk'] for x in entries if utc(x['time'])>=week)+sum(x['loss'] for x in losses if utc(x['time'])>=week)
    reasons=[]
    if dayrisk+(risk or 0)>account['equity']*a['daily_loss_fraction']+1e-8:reasons.append('DAILY_RESERVED_RISK_LIMIT')
    if weekrisk+(risk or 0)>account['equity']*a['weekly_loss_fraction']+1e-8:reasons.append('WEEKLY_RESERVED_RISK_LIMIT')
    return reasons


def model_reasons(model:dict|None,config:dict,now,paper=False)->list[str]:
    if not model:return ['NO_RESEARCH_MODEL_RUN_BACKTEST_FIRST']
    reasons=[]
    if model.get('schema')!=SCHEMA or model.get('venue')!='binance_usdm':reasons.append('OLD_OR_WRONG_VENUE_MODEL')
    if model.get('source')!='real_binance_usdm_archive':reasons.append('UNVERIFIED_MODEL_DATA_SOURCE')
    if model.get('fingerprint')!=fingerprint(config):reasons.append('CODE_OR_CONFIG_CHANGED_RERUN_RESEARCH')
    if not model.get('selected'):reasons.append('NO_SELECTED_CANDIDATE')
    if utc(now)<utc(model['test_end_exclusive']):reasons.append('EVIDENCE_END_IN_FUTURE')
    if (utc(now)-utc(model['test_end_exclusive'])).days>config['proof_gate']['max_evidence_age_days']:reasons.append('EVIDENCE_STALE_RERUN_RESEARCH_WITH_NEW_PERIOD')
    if not paper and not model.get('approved'):reasons.append('NO_VALIDATED_80_PERCENT_EDGE')
    return reasons


def emit(text,output,store,runtime,dry_run=False,manual=False,key='status',plan=None,paper=False):
    output.mkdir(parents=True,exist_ok=True)
    (output/'telegram_preview.txt').write_text(text,encoding='utf-8')
    write_json(output/'scan_status.json',{'version':VERSION,'paper':paper,'plan':plan,'text':text})
    if dry_run:return
    now=pd.Timestamp.now(tz='UTC');day=now.strftime('%Y-%m-%d')
    if not plan and not manual and runtime['notices'].get(key)==day:return
    if plan and not paper:
        if plan['id'] in runtime['seen']:return
        # Reserve before delivery. A timeout cannot cause blind duplicate risk alerts.
        runtime['seen']=(runtime['seen']+[plan['id']])[-2000:]
        runtime['active']=plan
        runtime['reservations']=[x for x in runtime['reservations'] if utc(x['time'])>now-pd.Timedelta(days=8)]
        runtime['reservations'].append({'time':str(now),'risk':plan['planned_loss_usdt'],'id':plan['id']})
        store.put('runtime.json',runtime)
    send(text)
    runtime['notices'][key]=day
    store.put('runtime.json',runtime)


def demo_plan(config,now=None):
    """A fixture for transport/arithmetic only. No synthetic PnL is presented as evidence."""
    now=utc(now or pd.Timestamp.now(tz='UTC'));last=now.floor('h')-HOUR
    idx=pd.date_range(last-40*HOUR,last,freq='h')
    btc=pd.DataFrame({'open':100000.,'high':100400.,'low':99400.,'close':100000.,'volume':100.},index=idx)
    sig=Signal(len(btc)-1,last,'trend_pullback','ETHUSDT',1,600.,
        {'demo':'synthetic arithmetic example; NOT a detected market signal','ema_fast':99800.,'ema_slow':98800.,'adx':22.})
    cand=Candidate('trend_pullback','ETHUSDT',2.)
    return build_plan(sig,btc,cand,config,config['account']['equity_usdt'])


def scan(config,output:Path,store:Store,mode='strict',manual=False,dry_run=False,now=None):
    if mode in ('paper','demo','status') and not manual:raise ValueError('Non-strict modes require explicit manual invocation')
    now=utc(now or pd.Timestamp.now(tz='UTC'));runtime=store.get('runtime.json',default_runtime())
    if runtime.get('schema')!=SCHEMA:raise StateError('State schema mismatch; do not reuse old spot state')
    if mode=='demo':
        plan=demo_plan(config,now);text=format_plan(plan,demo=True)
        # Demo never modifies active real/paper plan state or reserves risk.
        (output/'telegram_preview.txt').write_text(text,encoding='utf-8');write_json(output/'demo_plan.json',plan)
        if not dry_run:send(text)
        return 'DEMO'
    model=store.get('model.json')
    if mode=='status':
        reasons=model_reasons(model,config,now)
        summary='\n'.join(reasons) if reasons else 'Historical gate passed; a NEW setup and operational checks are still required.'
        if model and model.get('evidence'):
            m=model['evidence']['metrics'];summary+=f"\nSelected: {model['selected']['id']}\nHoldout trades: {m['trades']}; win rate: {m['win_rate']}; net USDT: {m['net_profit_usdt']:.2f}"
        emit(status_text('STATUS',summary),output,store,runtime,dry_run,manual)
        return 'STATUS'
    reasons=model_reasons(model,config,now,paper=mode=='paper')
    if reasons:
        emit(status_text('NO TRADE PLAN','\n'.join(reasons)),output,store,runtime,dry_run,manual,key='model_block')
        return 'MODEL_BLOCK'
    account=store.get('account.json')
    if mode=='strict' and not runtime.get('active'):
        reasons=account_checks(account,runtime,config,now)
        if reasons:
            emit(status_text('NO TRADE PLAN','\n'.join(reasons)),output,store,runtime,dry_run,manual,key='account_block')
            return 'ACCOUNT_BLOCK'
    cand=Candidate(model['selected']['family'],model['selected']['peer'],model['selected']['reward_risk'])
    try:snap=live_snapshot(config,cand.peer)
    except DataError as exc:
        emit(status_text('LIVE DATA UNAVAILABLE - NO TRADE',str(exc)+'\nArchive research can still run independently. Use only an authorized environment for Binance live data.'),output,store,runtime,dry_run,manual,key='data_block')
        return 'DATA_BLOCK'
    now=utc(snap['asof']);btc=snap['prices'][config['data']['bitcoin']]
    write_json(output/'live_diagnostics.json',{'asof':snap['asof'],'quote':snap['quote'],'rules':snap['rules'],'model':cand.to_dict()})
    if mode=='strict' and runtime.get('active'):
        active=runtime['active']
        outcome=evaluate_plan(active,btc,snap['mark'],snap['funding'],config)
        write_json(output/'active_plan_simulation.json',{k:v for k,v in outcome.items() if k!='path'})
        text=status_text('EXISTING PLAN - NO ADDITIONAL POSITION',
            f"Plan {active['id']}\nCandle-based simulation: {outcome['status']}\nThis is NOT your actual fill or account PnL. Confirm actual orders are closed/cancelled with Account Settings before any new plan.")
        emit(text,output,store,runtime,dry_run,manual,key='active')
        return 'ACTIVE_LOCK'
    events=generate_signals(btc,snap['prices'].get(cand.peer),cand,config)
    events=[s for s in events if s.time==btc.index[-1]]
    if not events:
        emit(status_text('NO QUALIFYING NEW SETUP',f'Checked {cand.name} on the latest completed 1h candle.'),output,store,runtime,dry_run,manual,key='no_setup')
        return 'NO_SETUP'
    equity=account['equity'] if mode=='strict' else config['account']['equity_usdt']
    rejected=[]
    for sig in events:
        side='LONG' if sig.direction==1 else 'SHORT'
        if mode=='strict' and side not in model['approved_sides']:rejected.append('SIDE_EVIDENCE_NOT_APPROVED');continue
        try:plan=build_plan(sig,btc,cand,config,equity,snap['rules'])
        except PlanError as exc:rejected.append(str(exc));continue
        why=live_plan_checks(plan,snap,config,now)
        if mode=='strict':why+=account_checks(account,runtime,config,now,plan['planned_loss_usdt'])
        if why:rejected+=why;continue
        if mode=='strict' and plan['id'] in runtime['seen']:rejected.append('ALREADY_SENT');continue
        plan['equity_confirmation']=account.get('confirmed_at') if account and mode=='strict' else 'paper-config-only'
        write_json(output/'trade_plan.json',plan)
        emit(format_plan(plan,model,paper=mode=='paper'),output,store,runtime,dry_run,manual,key='plan',plan=plan,paper=mode=='paper')
        return 'PLAN'
    emit(status_text('SETUP REJECTED - NO TRADE','\n'.join(sorted(set(rejected)))),output,store,runtime,dry_run,manual,key='rejected')
    return 'REJECTED'


def main(argv=None):
    parser=argparse.ArgumentParser(description='BTC Bot2 v1.2 research/plan alerts only. No trading API.')
    parser.add_argument('command',choices=['setup','check-data','research','scan','account'])
    parser.add_argument('--config',default='config.yaml');parser.add_argument('--output',default='output')
    parser.add_argument('--data-dir',default='data/binance_v12');parser.add_argument('--state-dir',default='state')
    parser.add_argument('--download',action='store_true');parser.add_argument('--manual',action='store_true')
    parser.add_argument('--mode',choices=['strict','paper','demo','status'],default='strict');parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--section',choices=['archive','live','both'],default='both')
    parser.add_argument('--equity',type=float);parser.add_argument('--flat-confirmed',action='store_true')
    args=parser.parse_args(argv);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    try:
        cfg=load_config(args.config);store=Store(Path(args.state_dir),cfg['alerts']['state_branch'])
        print(f'BTC QUANT BOT2 v{VERSION} | {args.command}',flush=True)
        if args.command=='setup':setup_bot();return 0
        if args.command=='account':
            if args.equity is None:raise ValueError('--equity is required')
            value=update_account(store,args.equity,args.flat_confirmed,cfg)
            write_json(out/'account_confirmation.json',value)
            (out/'telegram_preview.txt').write_text(status_text('ACCOUNT INPUT CONFIRMED',f"Manual equity: {args.equity:.2f} USDT. No exchange connection."),encoding='utf-8')
            return 0
        if args.command=='check-data':
            result=check_data(cfg,out,args.section)
            (out/'CHECK_DATA.md').write_text('# Provider check\n\n'+str(result)+'\n\nHistory and live access are independent. HISTORY_ONLY does not authorize a live trade.\n',encoding='utf-8')
            print(result);return 0 if result['can_research'] or result['can_scan_live'] else 2
        if args.command=='research':
            if args.download:download_history(cfg,Path(args.data_dir),out)
            prices,mark,funding,manifest=load_history(cfg,Path(args.data_dir))
            model=research(cfg,prices,mark,funding,out,manifest)
            if not args.dry_run:store.put('model.json',model)
            print(model['status']);return 0
        scan(cfg,out,store,args.mode,args.manual,args.dry_run);return 0
    except (DataError,PlanError,StateError,TelegramError,ValueError,KeyError,RuntimeError) as exc:
        # Sanitized errors only; request URLs may contain Telegram tokens.
        message=f'{type(exc).__name__}: {exc}'
        write_json(out/'failure.json',{'version':VERSION,'error':message})
        (out/'FAILURE.md').write_text('# Task could not complete\n\n'+message+'\nNo approved trade plan has been manufactured.\n',encoding='utf-8')
        print('FAILED: '+message,file=sys.stderr);return 1
