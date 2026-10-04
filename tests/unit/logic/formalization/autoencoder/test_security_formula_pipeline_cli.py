"""CLI capability exit codes and immutable selection envelopes."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from .test_security_formula_decoder import formula_checkpoint  # noqa: F401
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formalization_pipeline as pipeline


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[5] / 'scripts/evaluation/security_formula_pipeline.py'
    spec = importlib.util.spec_from_file_location('authored_security_formula_pipeline_cli', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def invocation(tmp_path):
    repository = tmp_path / 'source'; repository.mkdir()
    raw = b'def arithmetic(value):\n    return value + 1\n'
    (repository / 'authored.py').write_bytes(raw)
    ledger = tmp_path / 'ledger.json'; ledger.write_text(json.dumps({'authored.py':hashlib.sha256(raw).hexdigest()}))
    descriptor = tmp_path / 'decoder.json'; descriptor.write_text('{}')
    output = tmp_path / 'result'
    argv = ['--repository',str(repository),'--source-ledger',str(ledger),'--decoder-descriptor',str(descriptor),'--output',str(output)]
    return argv, repository, ledger, descriptor, output


@pytest.mark.parametrize('passed,diagnostic,expected', [(True,False,0),(False,False,2),(False,True,0)])
def test_capability_exit_semantics_after_actual_validator_invocation(cli, invocation, monkeypatch, capsys, passed, diagnostic, expected):
    argv, repository, ledger, descriptor, output = invocation
    calls=[]
    receipt={'schema':'authored-driver-contract@1','output':str(output),'summary':{'learned_formula_generation_passed':passed}}
    def run(**kwargs):
        calls.append(('run',kwargs)); return receipt
    def validate(**kwargs):
        calls.append(('validate',kwargs)); return {'solver_calls':0}
    monkeypatch.setattr(pipeline,'run_security_formalization_pipeline',run)
    monkeypatch.setattr(pipeline,'validate_security_formalization_pipeline',validate)
    assert cli.main(argv+(['--allow-diagnostic-only'] if diagnostic else []))==expected
    result=json.loads(capsys.readouterr().out)
    assert [x[0] for x in calls]==['run','validate']
    assert result['capability_check']==('passed' if passed else 'failed')
    assert result['input_sha256'][str(ledger)]==hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert result['input_sha256'][str(descriptor)]==hashlib.sha256(descriptor.read_bytes()).hexdigest()


@pytest.mark.parametrize('changed', ['ledger','descriptor','protocol'])
def test_cli_rejects_selection_drift_after_pipeline_validation(cli, invocation, monkeypatch, capsys, changed):
    argv, _, ledger, descriptor, output = invocation
    protocol=descriptor.parent/'protocol.json';protocol.write_text('{}')
    argv+=['--protocol',str(protocol)]
    target={'ledger':ledger,'descriptor':descriptor,'protocol':protocol}[changed]
    receipt={'schema':'authored-driver-contract@1','output':str(output),'summary':{'learned_formula_generation_passed':True}}
    monkeypatch.setattr(pipeline,'run_security_formalization_pipeline',lambda **kwargs:receipt)
    def validate(**kwargs):target.write_bytes(target.read_bytes()+b' ');return {}
    monkeypatch.setattr(pipeline,'validate_security_formalization_pipeline',validate)
    assert cli.main(argv)==2
    result=json.loads(capsys.readouterr().out)
    assert result['capability_check']=='not_established' and result['error_type']=='ValueError'


@pytest.mark.parametrize('disabled,diagnostic,expected',[(False,False,0),(True,False,2),(True,True,0)])
def test_real_frozen_decoder_cli_and_model_off_control(cli, invocation, formula_checkpoint, capsys, disabled, diagnostic, expected):
    argv, _, _, descriptor, output=invocation
    descriptor.write_text(json.dumps(formula_checkpoint))
    flags=(['--model-off'] if disabled else [])+(['--allow-diagnostic-only'] if diagnostic else [])
    assert cli.main(argv+flags)==expected
    result=json.loads(capsys.readouterr().out)
    assert result['capability_check']==('failed' if disabled else 'passed'),result
    assert result['summary']['learned_formula_count']==(0 if disabled else 1)
    assert result['model_off']==disabled
    report=json.loads((output/'formalization.json').read_bytes())
    assert report['provider_calls']==report['training_steps']==report['download_calls']==0
    assert report['proof_authority'] is False
