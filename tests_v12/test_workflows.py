from pathlib import Path
import ast
import yaml
import pytest
from btc_quant.common import ROOT,load_config

@pytest.mark.parametrize('name',['bot2_scan','bot2_research','bot2_check_data','bot2_setup','bot2_account','tests'])
def test_workflow_location_and_copy(name):
    p=ROOT/'.github/workflows'/f'{name}.yml';assert p.exists()
    wf=yaml.safe_load(p.read_text());assert 'jobs' in wf and (True in wf or 'on' in wf)
    assert p.read_bytes()==(ROOT/'WORKFLOW_COPIES'/f'{name}.yml.txt').read_bytes()


def test_schedule_strict_and_safe_inputs():
    s=(ROOT/'.github/workflows/bot2_scan.yml').read_text()
    assert "cron: '7 * * * *'" in s and 'args+=(--mode strict)' in s
    assert '${{ inputs.mode }}' in s and 'REQUESTED_MODE' in s
    assert 'BOT2_LIVE_RUNNER' in s and 'cancel-in-progress: false' in s


def test_research_can_run_without_live_access():
    s=(ROOT/'.github/workflows/bot2_research.yml').read_text()
    assert 'check-data' not in s and 'TELEGRAM_BOT2_TOKEN' not in s


def test_no_exchange_trade_endpoints():
    combined='\n'.join(p.read_text() for p in (ROOT/'btc_quant').glob('*.py'))
    assert '/fapi/v1/order' not in combined and '/fapi/v1/leverage' not in combined
    assert 'BINANCE_API_SECRET' not in combined and 'pickle' not in combined.replace('no pickle','')


def test_source_files_compile():
    for p in (ROOT/'btc_quant').glob('*.py'):ast.parse(p.read_text(),filename=str(p))

@pytest.mark.parametrize('section,key,value',[('account','risk_fraction',.11),('account','max_leverage',10),('account','hard_risk_cap_usdt',51),('account','max_margin_fraction',1.),('execution','funding_required',False)])
def test_unsafe_configuration_rejected(cfg,tmp_path,section,key,value):
    cfg[section][key]=value;p=tmp_path/'cfg.yaml';p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):load_config(p)


@pytest.mark.parametrize('section,key,value',[
    ('proof_gate','minimum_win_rate_lower_bound',float('nan')),
    ('proof_gate','minimum_win_rate_lower_bound',1.0),
    ('proof_gate','bootstrap_repetitions',0),
    ('account','max_leverage',2.5),
    ('account','equity_usdt',float('inf')),
])
def test_bad_numeric_configuration_cannot_bypass_guards(cfg,tmp_path,section,key,value):
    import yaml
    from btc_quant.common import load_config
    cfg[section][key]=value
    path=tmp_path/'bad.yaml';path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):load_config(path)
