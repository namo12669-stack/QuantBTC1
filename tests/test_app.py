from copy import deepcopy
import json
import numpy as np
import pandas as pd
import pytest
import requests
from btc_quant.common import HOUR, fingerprint, DataError
from btc_quant.store import Store, StateError
from btc_quant.app import scan, entry_message
from btc_quant import telegram
from btc_quant.signals import Candidate, Signal
from btc_quant.monitor import make_position, monitor_position
from conftest import constant_bars

@pytest.mark.parametrize('name',['../token','secret.txt','random.json'])
def test_state_file_allowlist(tmp_path,name):
    s=Store(tmp_path)
    with pytest.raises(StateError): s.put(name,{})

def test_local_state_roundtrip(tmp_path):
    s=Store(tmp_path);s.put('runtime.json',{'n':1});assert s.get('runtime.json')['n']==1

def test_setup_existing_chat_does_not_rediscover(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT2_CHAT_ID','12345')
    methods=[]
    monkeypatch.setattr(telegram,'_call',lambda method,payload: methods.append(method) or {})
    telegram.setup_bot()
    assert methods==['getMe','sendMessage']

def test_setup_discovers_one_private_chat(monkeypatch):
    calls=[]
    def call(method,payload):
        calls.append((method,payload))
        return [{'message':{'chat':{'type':'private','id':123}}}] if method=='getUpdates' else {}
    monkeypatch.setattr(telegram,'_call',call)
    telegram.setup_bot()
    assert calls[-1][1]['chat_id']=='123'

def test_setup_multiple_chats_no_guess(monkeypatch):
    def call(method,payload):
        return [{'message':{'chat':{'type':'private','id':n}}} for n in (1,2)] if method=='getUpdates' else {}
    monkeypatch.setattr(telegram,'_call',call)
    with pytest.raises(telegram.TelegramError,match='CHAT_ID'): telegram.setup_bot()

def test_telegram_missing_secret(monkeypatch):
    with pytest.raises(telegram.TelegramError):telegram._call('getMe',{})

def test_token_not_leaked_on_request_error(monkeypatch):
    token='FAKE_UNIT_TEST_TOKEN_DO_NOT_USE'
    monkeypatch.setenv('TELEGRAM_BOT2_TOKEN',token)
    def fail(*a,**k):raise requests.ConnectionError('https://example.test/'+token)
    monkeypatch.setattr(requests,'post',fail)
    with pytest.raises(telegram.TelegramError) as err:telegram._call('getMe',{})
    assert token not in str(err.value)

def test_long_telegram_plain_text_split(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT2_CHAT_ID','123')
    calls=[]
    monkeypatch.setattr(telegram,'_call',lambda m,p:calls.append(p))
    telegram.send('x'*9000)
    assert len(calls)==3 and max(len(c['text']) for c in calls)<=3500
    assert not any('parse_mode' in c for c in calls)

def test_demo_no_position_or_model_created(tmp_path,cfg,monkeypatch):
    s=Store(tmp_path/'state');calls=[]
    monkeypatch.setattr(telegram,'send',lambda text:calls.append(text))
    scan(cfg,s,tmp_path/'output',mode='demo',manual=True,now='2026-09-09')
    assert 'SYNTHETIC' in calls[0]
    assert not (tmp_path/'state/runtime.json').exists()

def test_default_no_model_no_buy_sell(tmp_path,cfg,monkeypatch):
    s=Store(tmp_path/'state');calls=[]
    monkeypatch.setattr(telegram,'send',lambda text:calls.append(text))
    scan(cfg,s,tmp_path/'output',manual=True,now='2026-09-09')
    assert 'NO_BACKTEST_MODEL' in calls[0]
    assert 'BTC: BUY' not in calls[0] and 'BTC: SELL' not in calls[0]

def test_dry_run_never_sends_or_writes_state(tmp_path,cfg,monkeypatch):
    s=Store(tmp_path/'state')
    def bad(*a,**k):raise AssertionError('should not send')
    monkeypatch.setattr(telegram,'send',bad)
    scan(cfg,s,tmp_path/'output',manual=True,dry_run=True,now='2026-09-09')
    assert not (tmp_path/'state/runtime.json').exists()

def test_paper_must_be_manual(tmp_path,cfg):
    with pytest.raises(ValueError):scan(cfg,Store(tmp_path/'s'),tmp_path/'o',mode='paper')

def test_pair_message_required_second_leg(cfg):
    b=constant_bars();s=Signal(20,b.index[20],'pair_spread','ETHUSDT',-1,1.,details={'z_now':2.,'cointegration_p':.001},beta=2)
    text=entry_message(s,{},cfg,'paper')
    assert 'BTC: SELL (SHORT)' in text
    assert 'ETHUSDT: BUY / LONG - REQUIRED HEDGE LEG' in text
    assert 'PAPER ONLY' in text and 'NOT' in text

def test_monitor_directional_stop_and_cooldown(cfg):
    b=constant_bars();s=Signal(20,b.index[20],'divergence','ETHUSDT',1,1.)
    p=make_position(s,cfg,'paper')
    b.loc[b.index[22],['low','high']]=[95,105]
    p,msg=monitor_position(p,{'BTCUSDT':b.iloc[:23],'ETHUSDT':b.iloc[:23]},cfg,b.index[23]+pd.Timedelta(minutes=7))
    assert 'STOP' in msg
    assert p['paper_exit_price']==98.5
    assert pd.Timestamp(p['cooldown_until'])==b.index[30]
    same,_=monitor_position(p,{'BTCUSDT':b,'ETHUSDT':b},cfg,b.index[29])
    assert same is not None
    done,_=monitor_position(p,{'BTCUSDT':b,'ETHUSDT':b},cfg,b.index[30])
    assert done is None

def test_strict_stale_evidence_still_monitors_existing(tmp_path,cfg,monkeypatch):
    import btc_quant.app as app
    b=constant_bars();s=Signal(20,b.index[20],'divergence','ETHUSDT',1,1.)
    model={'source':'real_exchange_archive','fingerprint':fingerprint(cfg),'approved':False,
           'evidence':{'approved':False},'test_end_exclusive':'2026-09-01','selected':Candidate('divergence','ETHUSDT').to_dict()}
    state=Store(tmp_path/'s');state.put('model.json',model)
    pos=make_position(s,cfg,'strict');pos['model_fingerprint']=model['fingerprint']
    state.put('runtime.json',{'strict_position':pos})
    called=[]
    monkeypatch.setattr(app,'live_history',lambda *a:({'BTCUSDT':b,'ETHUSDT':b},{}))
    monkeypatch.setattr(app,'monitor_position',lambda *a: (called.append(True) or pos,'EXIT OBSERVATION'))
    monkeypatch.setattr(telegram,'send',lambda *a:None)
    scan(cfg,state,tmp_path/'o',manual=True,now='2026-09-09')
    assert called

def test_live_entry_deduplicated(tmp_path,cfg,monkeypatch):
    import btc_quant.app as app
    b=constant_bars();now=b.index[-1]+HOUR+pd.Timedelta(minutes=7)
    event=Signal(len(b)-1,b.index[-1],'breakout','ETHUSDT',1,1.,details={'rvol':2})
    state=Store(tmp_path/'s')
    state.put('model.json',{'source':'real_exchange_archive','fingerprint':fingerprint(cfg),'selected':Candidate('breakout','ETHUSDT').to_dict(),'approved':False})
    monkeypatch.setattr(app,'live_history',lambda *a:({'BTCUSDT':b,'ETHUSDT':b},{}))
    monkeypatch.setattr(app,'generate_signals',lambda *a:[event])
    calls=[];monkeypatch.setattr(telegram,'send',lambda m:calls.append(m))
    scan(cfg,state,tmp_path/'o',mode='paper',manual=True,now=now)
    scan(cfg,state,tmp_path/'o',mode='paper',manual=True,now=now)
    assert len([m for m in calls if 'BTC: BUY' in m])==1

def test_late_paper_entry_withheld(tmp_path,cfg,monkeypatch):
    import btc_quant.app as app
    b=constant_bars();state=Store(tmp_path/'s')
    state.put('model.json',{'fingerprint':fingerprint(cfg),'selected':Candidate('breakout','ETHUSDT').to_dict()})
    monkeypatch.setattr(app,'live_history',lambda *a:({'BTCUSDT':b,'ETHUSDT':b},{}))
    calls=[];monkeypatch.setattr(telegram,'send',lambda m:calls.append(m))
    scan(cfg,state,tmp_path/'o',mode='paper',manual=True,now=b.index[-1]+HOUR+pd.Timedelta(minutes=40))
    assert 'LATE RUN' in calls[0]

def test_scan_failure_warning_is_not_fake_no_signal_claim(tmp_path,cfg,monkeypatch):
    import btc_quant.app as app
    monkeypatch.setenv('TELEGRAM_BOT2_TOKEN','FAKE_TEST_ONLY')
    monkeypatch.setenv('TELEGRAM_BOT2_CHAT_ID','123')
    def fail(*a,**k):raise DataError('TEST_DATA_UNAVAILABLE')
    monkeypatch.setattr(app,'scan',fail)
    messages=[];monkeypatch.setattr(telegram,'send',lambda m:messages.append(m))
    with pytest.raises(SystemExit):app.main(['scan','--output',str(tmp_path/'o'),'--state-dir',str(tmp_path/'s')])
    err=json.loads((tmp_path/'o/error.json').read_text())
    assert 'delivery_status' in err and 'no_signal_emitted' not in err
    assert 'SCANNER FAILED' in messages[0]
