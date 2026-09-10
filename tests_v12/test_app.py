from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from btc_quant.common import VERSION,SCHEMA,HOUR,DataError,fingerprint,write_json
from btc_quant.store import Store,StateError
from btc_quant.app import (scan,main,default_runtime,account_checks,update_account,model_reasons,emit,demo_plan)
from btc_quant.signals import Signal
from conftest import bars,funding

NOW=pd.Timestamp('2026-09-10 10:07Z')

def model(cfg,approved=False):
    return {'schema':SCHEMA,'version':VERSION,'venue':'binance_usdm','source':'real_binance_usdm_archive', 'unit_test_only':True,
        'fingerprint':fingerprint(cfg),'test_end_exclusive':'2026-09-01','selected':{'family':'trend_pullback','peer':'ETHUSDT','reward_risk':2.},
        'approved':approved,'approved_sides':['LONG'] if approved else [],'next_trade_probability':None}


def test_no_model_is_status_not_crash(cfg,tmp_path):
    out=tmp_path/'out';out.mkdir();store=Store(tmp_path/'state')
    assert scan(cfg,out,store,'strict',dry_run=True,now=NOW)=='MODEL_BLOCK'
    assert 'NO_RESEARCH_MODEL' in (out/'telegram_preview.txt').read_text()


def test_demo_never_writes_state(cfg,tmp_path):
    out=tmp_path/'out';out.mkdir();store=Store(tmp_path/'state')
    scan(cfg,out,store,'demo',manual=True,dry_run=True,now=NOW)
    assert 'SYNTHETIC' in (out/'telegram_preview.txt').read_text()
    assert not store.local.exists()

@pytest.mark.parametrize('mode',['paper','demo','status'])
def test_schedule_cannot_enable_paper(cfg,tmp_path,mode):
    with pytest.raises(ValueError):scan(cfg,tmp_path,Store(tmp_path/'state'),mode,manual=False,dry_run=True,now=NOW)


def test_old_model_rejected(cfg):
    m=model(cfg);m['schema']=3;m['venue']='coinbase_exchange_spot'
    assert 'OLD_OR_WRONG_VENUE_MODEL' in model_reasons(m,cfg,NOW)


def test_changed_config_invalidates_approval(cfg):
    m=model(cfg,True);cfg['execution']['fee_bps_per_side']+=1
    assert 'CODE_OR_CONFIG_CHANGED_RERUN_RESEARCH' in model_reasons(m,cfg,NOW)


def test_stale_evidence(cfg):
    m=model(cfg,True);m['test_end_exclusive']='2025-01-01'
    assert any('STALE' in r for r in model_reasons(m,cfg,NOW))


def test_account_confirmation_and_staleness(cfg,tmp_path):
    store=Store(tmp_path);acc=update_account(store,500,True,cfg,NOW)
    assert not account_checks(acc,default_runtime(),cfg,NOW)
    assert 'EQUITY_CONFIRMATION_EXPIRED' in account_checks(acc,default_runtime(),cfg,NOW+25*HOUR)


def test_flat_confirmation_required(cfg,tmp_path):
    with pytest.raises(ValueError):update_account(Store(tmp_path),500,False,cfg,NOW)


def test_loss_risk_blocks(cfg,tmp_path):
    s=Store(tmp_path);update_account(s,500,True,cfg,NOW-HOUR);acc=update_account(s,450,True,cfg,NOW)
    assert 'DAILY_RESERVED_RISK_LIMIT' in account_checks(acc,default_runtime(),cfg,NOW,10)


def test_active_plan_only_cleared_by_flat_confirmation(cfg,tmp_path):
    s=Store(tmp_path);r=default_runtime();r['active']={'id':'old'};s.put('runtime.json',r)
    update_account(s,500,True,cfg,NOW)
    assert s.get('runtime.json')['active'] is None


def test_data_451_explicit_no_plan(cfg,tmp_path,monkeypatch):
    import btc_quant.app as app
    s=Store(tmp_path/'state');s.put('model.json',model(cfg,True));update_account(s,500,True,cfg,NOW)
    def fail(*a,**k):raise DataError('PROVIDER_ACCESS_DENIED HTTP 451')
    monkeypatch.setattr(app,'live_snapshot',fail)
    out=tmp_path/'output';out.mkdir()
    assert scan(cfg,out,s,'strict',manual=True,dry_run=True,now=NOW)=='DATA_BLOCK'
    assert '451' in (out/'telegram_preview.txt').read_text() and not (out/'trade_plan.json').exists()


def snapshot(cfg):
    idx=pd.date_range(NOW.floor('h')-40*HOUR,periods=40,freq='h')
    b=pd.DataFrame({'open':100000.,'high':100400.,'low':99400.,'close':100000.,'volume':100.,'quote_volume':10000000.},index=idx)
    return {'prices':{'BTCUSDT':b,'ETHUSDT':b.copy()},'mark':b.copy(),'funding':funding(b),
            'rules':cfg['research_rules'],'asof':str(NOW),'quote':{'mid':100000.,'spread_bps':1.,'mark_basis_bps':1.,'funding_rate':.0001}}


def test_paper_has_actual_plan_but_not_probability_claim(cfg,tmp_path,monkeypatch):
    import btc_quant.app as app
    out=tmp_path/'out';out.mkdir();store=Store(tmp_path/'state');store.put('model.json',model(cfg))
    snap=snapshot(cfg);b=snap['prices']['BTCUSDT']
    sig=Signal(len(b)-1,b.index[-1],'trend_pullback','ETHUSDT',1,600.,{'test':'synthetic transport fixture'})
    monkeypatch.setattr(app,'live_snapshot',lambda *a,**k:snap)
    monkeypatch.setattr(app,'generate_signals',lambda *a,**k:[sig])
    assert scan(cfg,out,store,'paper',manual=True,dry_run=True,now=NOW)=='PLAN'
    text=(out/'telegram_preview.txt').read_text()
    assert 'PAPER ONLY - UNVALIDATED' in text and 'ENTRY LIMIT' in text and 'STOP LOSS' in text
    assert store.get('runtime.json') is None


def test_delivery_error_reserves_plan_instead_of_resending(cfg,tmp_path,monkeypatch):
    import btc_quant.app as app
    out=tmp_path/'out';out.mkdir();store=Store(tmp_path/'state');runtime=default_runtime();plan=demo_plan(cfg,NOW)
    def fail(*a):raise app.TelegramError('unconfirmed')
    monkeypatch.setattr(app,'send',fail)
    with pytest.raises(app.TelegramError):emit('test',out,store,runtime,manual=True,plan=plan)
    assert plan['id'] in store.get('runtime.json')['seen']
    assert store.get('runtime.json')['active']['id']==plan['id']


def test_state_branch_uses_sha_not_default_branch(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_SHA','a'*40)
    s=Store(tmp_path)
    assert s._base_sha_for_state_branch()=='a'*40


def test_state_no_base_sha_diagnostic(tmp_path,monkeypatch):
    for key in ['GITHUB_SHA','GITHUB_REF_NAME','GITHUB_EVENT_PATH']:monkeypatch.delenv(key,raising=False)
    with pytest.raises(StateError,match='STATE_BRANCH_BASE_SHA'):Store(tmp_path)._base_sha_for_state_branch()


def test_state_whitelist(tmp_path):
    with pytest.raises(StateError):Store(tmp_path).put('../../escape',{})


def test_cli_demo(tmp_path):
    assert main(['scan','--manual','--mode','demo','--dry-run','--output',str(tmp_path/'out')])==0


def test_strict_end_to_end_transport_mock(cfg,tmp_path,monkeypatch):
    """Protocol test with a mocked approval; NOT a real market approval."""
    import btc_quant.app as app
    out=tmp_path/'out';out.mkdir();store=Store(tmp_path/'state');store.put('model.json',model(cfg,True))
    update_account(store,500,True,cfg,NOW)
    snap=snapshot(cfg);b=snap['prices']['BTCUSDT'];sig=Signal(len(b)-1,b.index[-1],'trend_pullback','ETHUSDT',1,600.,{})
    monkeypatch.setattr(app,'live_snapshot',lambda *a,**k:snap)
    monkeypatch.setattr(app,'generate_signals',lambda *a,**k:[sig])
    sent=[];monkeypatch.setattr(app,'send',lambda text:sent.append(text))
    assert scan(cfg,out,store,'strict',manual=True,dry_run=False,now=NOW)=='PLAN'
    assert len(sent)==1 and store.get('runtime.json')['active']
    assert 'HISTORICAL-GATE-QUALIFIED' in sent[0]
    assert scan(cfg,out,store,'strict',manual=True,dry_run=True,now=NOW)=='ACTIVE_LOCK'


def test_synthetic_model_cannot_be_promoted_by_flag(cfg):
    m=model(cfg,True);m['source']='synthetic'
    assert 'UNVERIFIED_MODEL_DATA_SOURCE' in model_reasons(m,cfg,NOW)
