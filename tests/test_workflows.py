from pathlib import Path
import yaml
from btc_quant.common import ROOT

def test_workflows_and_visible_copies_match():
    paths=list((ROOT/'.github/workflows').glob('*.yml'))
    assert len(paths)==5
    for p in paths:
        assert p.read_bytes()==(ROOT/'WORKFLOW_COPIES'/f'{p.name}.txt').read_bytes()
        obj=yaml.load(p.read_text(),Loader=yaml.BaseLoader)
        assert 'workflow_dispatch' in obj['on']
        assert obj.get('permissions',{}).get('contents') in ('read','write')

def test_scheduled_scan_strict_and_shared_concurrency():
    scan=yaml.load((ROOT/'.github/workflows/bot2_scan.yml').read_text(),Loader=yaml.BaseLoader)
    research=yaml.load((ROOT/'.github/workflows/bot2_research.yml').read_text(),Loader=yaml.BaseLoader)
    assert scan['concurrency']['group']==research['concurrency']['group']
    assert scan['on']['schedule'][0]['cron']=='7 * * * *'
    assert '--mode strict' in (ROOT/'.github/workflows/bot2_scan.yml').read_text()

def test_no_first_bot_secret_names_in_workflows():
    for p in (ROOT/'.github/workflows').glob('*.yml'):
        assert 'secrets.TELEGRAM_BOT_TOKEN' not in p.read_text()
        assert 'secrets.TELEGRAM_CHAT_ID' not in p.read_text()
