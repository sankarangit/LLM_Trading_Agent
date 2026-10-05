from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path
import pytest
from test_baselines_cli import cli_config, strategy_config
from test_engine import dataset,cfg
from test_llm_strategy_provider import Fake,response
from llm_trading.cli import main,replay,load_config
from llm_trading.llm_runs import run_llm_experiment
from llm_trading.storage import load_saved

@pytest.fixture(autouse=True)
def isolate_project_ledger(tmp_path,monkeypatch):
    import llm_trading.llm_runs as module
    prompt=(module.PROJECT/'prompts/system-v1.txt').read_bytes()
    (tmp_path/'prompts').mkdir()
    (tmp_path/'prompts/system-v1.txt').write_bytes(prompt)
    monkeypatch.setattr(module,'PROJECT',tmp_path)

def setup_config(tmp_path):
    p=cli_config(tmp_path)
    raw=json.loads(p.read_text())
    raw['strategy'].update({'stop_distance_pct':3,'horizon_bars':None,'target_r_multiple':None,'trailing_stop_pct':None})
    raw['llm']={'model':'gpt-4o-mini','temperature':0,'max_output_tokens':512,'timeout_seconds':30,
                'journal_limit':20,'budget_cap_usd':'10','budget_path':str(tmp_path/'data/cache/llm-budget.sqlite'),
                'cache_path':str(tmp_path/'data/cache/llm')}
    p.write_text(json.dumps(raw))
    return p

def test_llm_cli_requires_explicit_api_and_pilot_before_resolving_key(tmp_path,capsys,monkeypatch):
    p=setup_config(tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    assert main(['backtest','--config',str(p),'--experiment','stats_llm'])==2
    assert 'allow-api' in capsys.readouterr().err
    assert main(['backtest','--config',str(p),'--experiment','stats_llm','--allow-api','--pilot-decisions','21'])==2
    assert '20' in capsys.readouterr().err
    real_config=Path(__file__).parents[1]/'config/research-SPY.json'
    assert main(['backtest','--config',str(real_config),'--experiment','stats_llm','--allow-api','--pilot-decisions','2'])==2
    assert 'OPENAI_API_KEY' in capsys.readouterr().err
    assert main(['backtest','--config',str(p),'--experiment','momentum'])==0

def test_paid_fake_pilot_archived_offline_replay_and_report(tmp_path,monkeypatch):
    p=setup_config(tmp_path)
    raw,data,higher,path=load_config(p)
    fake=Fake(response())
    monkeypatch.setattr('llm_trading.llm_runs.provider_from_environment',lambda settings:fake)
    dest=run_llm_experiment(raw,data,higher,path,'stats_llm',True,2,offline_provider=fake)
    saved=load_saved(dest)
    assert saved['metadata']['research_status']=='pilot_only'
    assert saved['metadata']['model_id']=='gpt-4o-mini'
    assert len(fake.calls)==2
    records=[json.loads(line) for line in (dest/'llm_audit.jsonl').read_text().splitlines()]
    assert len(records)==2
    assert Decimal(saved['metadata']['llm_summary']['new_spend_usd'])==Decimal('.00084')
    def forbidden(*a,**k): raise AssertionError('network/environment forbidden in replay')
    monkeypatch.setattr('llm_trading.llm_runs.provider_from_environment',forbidden)
    monkeypatch.setattr('urllib.request.OpenerDirector.open',forbidden)
    assert replay(dest)['identical'] is True
    from llm_trading.reporting import single_report
    report=single_report(dest)
    assert 'pilot_only' in report.read_text()
    assert load_saved(dest)

def test_failed_run_keeps_incremental_audit_and_incomplete_marker(tmp_path,monkeypatch):
    from llm_trading.llm_contract import ConfigurationError
    p=setup_config(tmp_path)
    raw,data,higher,path=load_config(p)
    monkeypatch.setattr('llm_trading.llm_runs.provider_from_environment',lambda settings:Fake(error=ConfigurationError('auth')))
    with pytest.raises(ConfigurationError): run_llm_experiment(raw,data,higher,path,'stats_llm',True,2,
        offline_provider=Fake(error=ConfigurationError('auth')))
    root=tmp_path/'output'
    interrupted=next(root.glob('llm-*'))
    assert (interrupted/'INCOMPLETE').exists()
    assert list((interrupted/'request_audit').glob('*.json'))
    assert all((interrupted/name).exists() for name in ('source.zip','config.json','data.csv','prompt.txt'))
    with pytest.raises(ValueError,match='incomplete'): load_saved(interrupted)

def test_replay_detects_modified_request_and_artifact(tmp_path,monkeypatch):
    p=setup_config(tmp_path)
    raw,data,higher,path=load_config(p)
    monkeypatch.setattr('llm_trading.llm_runs.provider_from_environment',lambda settings:Fake())
    dest=run_llm_experiment(raw,data,higher,path,'stats_llm',True,1,offline_provider=Fake())
    audit=dest/'llm_audit.jsonl'
    audit.write_text('{}\n')
    with pytest.raises(ValueError,match='integrity'): replay(dest)

def test_fixture_source_label_cannot_redirect_paid_budget(tmp_path,monkeypatch):
    from llm_trading.llm_contract import ConfigurationError
    p=setup_config(tmp_path)
    raw,data,higher,path=load_config(p)
    raw['llm']['budget_path']=str(tmp_path/'fresh-budget.sqlite')
    monkeypatch.setattr('llm_trading.llm_runs.provider_from_environment',lambda settings:Fake())
    with pytest.raises(ConfigurationError,match='share'):
        run_llm_experiment(raw,data,higher,path,'stats_llm',True,2,offline_provider=Fake())
    assert not (tmp_path/'fresh-budget.sqlite').exists()

def test_initial_pilot_rejects_changed_development_boundary_before_credentials(tmp_path,monkeypatch):
    from llm_trading.llm_contract import ConfigurationError
    original=Path(__file__).parents[1]/'config/research-GLD.json'
    raw,data,higher,path=load_config(original)
    raw['research']['start']='2006-01-01T00:00:00-05:00'
    def forbidden(settings): raise AssertionError('credentials must not be resolved')
    monkeypatch.setattr('llm_trading.llm_runs.provider_from_environment',forbidden)
    with pytest.raises(ConfigurationError,match='approved development'):
        run_llm_experiment(raw,data,higher,path,'stats_llm',True,2)
