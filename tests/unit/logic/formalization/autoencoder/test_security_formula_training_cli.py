"""Training CLI pins, actual bounded native learning and fail-closed envelopes."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from .test_codebase_autoencoder_transfer import teacher, fork  # noqa: F401
from .test_published_legal_initializer import metadata, source, binding  # noqa: F401
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder as decoder


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[5] / 'scripts/training/train_security_formula_decoder.py'
    spec = importlib.util.spec_from_file_location('authored_security_formula_training_cli', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def invocation(tmp_path, fork):
    samples = [
        {'id': 'authored-train', 'split': 'train', 'source': 'def add(value):\n    return value + 1\n'},
        {'id': 'authored-validation', 'split': 'validation', 'source': 'def multiply(value):\n    return value * 3\n'},
        {'id': 'authored-test', 'split': 'test', 'source': 'def negate(value):\n    return -value\n'},
    ]
    for row in samples: row['source_sha256'] = _sha(row['source'].encode())
    files = {'samples': tmp_path/'samples.json', 'initializer': tmp_path/'initializer-descriptor.json',
        'provenance': tmp_path/'provenance.json'}
    files['samples'].write_text(json.dumps(samples))
    files['initializer'].write_text(json.dumps(fork))
    files['provenance'].write_text(json.dumps({'schema':'authored-training-cli-provenance@1',
        'source_scope':'authored fixtures only', 'split_identities': {row['split']:[row['id']] for row in samples},
        'source_hashes':{row['id']:row['source_sha256'] for row in samples},'proof_authority':False}))
    output = tmp_path/'new-security-formula-decoder'
    argv = ['--samples',str(files['samples']),'--initializer-descriptor',str(files['initializer']),
        '--provenance',str(files['provenance']),'--output',str(output),'--epochs','2',
        '--training-data-scope','authored_development_controls']
    return argv, files, output, samples


@pytest.mark.parametrize('with_binding',[False,True])
def test_actual_small_cpu_training_preserves_parent_and_pins_inputs(cli, invocation, teacher, fork, binding, capsys, with_binding):
    argv, files, output, samples = invocation
    if with_binding:
        files['published'] = output.parent/'published-binding-descriptor.json'
        files['published'].write_text(json.dumps(binding))
        argv += ['--published-binding',str(files['published'])]
    before={key:path.read_bytes() for key,path in files.items()}
    assert cli.main(argv)==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='trained' and result['exit_code']==0
    assert result['provider_calls']==result['download_calls']==0 and result['legal_parent_modified'] is False
    assert result['input_sha256']=={str(files[key]):_sha(raw) for key,raw in before.items()}
    assert {p.name for p in output.iterdir()}==decoder.FILES
    loaded=decoder.load_security_formula_decoder(result['decoder'])
    training=loaded['training']
    assert training['training_steps']==training['epochs']==2
    assert training['initial_head_sha256']!=training['final_head_sha256']
    assert any(x>0 for x in training['gradient_norms']) and training['native_kernel_calls']>0
    assert training['training_data_scope']=='authored_development_controls'
    assert training['training_provenance_sha256']==_sha(before['provenance'])
    assert training['heldout_used_for_fit'] is False and training['proof_authority'] is False
    assert {name:[row['id'] for row in rows] for name,rows in training['splits'].items()}=={
        row['split']:[row['id']] for row in samples}
    for sample in samples:
        assert training['splits'][sample['split']][0]['source_sha256']==sample['source_sha256']
    lexical=loaded['weights']['lexical']
    assert lexical['parent_checkpoint_sha256']==teacher[1]
    assert lexical['initializer_sha256']==fork['initializer_sha256']
    assert lexical['published_source_pin']==(binding['source_pin'] if with_binding else None)
    assert teacher[0].read_bytes()==teacher[2]
    assert Path(fork['output'],'source.checkpoint').read_bytes()==teacher[2]
    assert not any('legal-only' in key for key in lexical['keys'])
    assert all(path.read_bytes()==before[key] for key,path in files.items())
    assert all(sample['source'].encode() not in b''.join(p.read_bytes() for p in output.iterdir()) for sample in samples)


@pytest.mark.parametrize('changed',['samples','initializer','provenance','published'])
def test_declaration_drift_after_real_training_cannot_claim_qualification(cli, invocation, teacher, binding, monkeypatch, capsys, changed):
    argv, files, output, _=invocation
    files['published']=output.parent/'published-binding-descriptor.json'
    files['published'].write_text(json.dumps(binding))
    argv+=['--published-binding',str(files['published'])]
    actual=decoder.train_security_formula_decoder
    def train(**kwargs):
        result=actual(**kwargs)
        files[changed].write_bytes(files[changed].read_bytes()+b' ')
        return result
    monkeypatch.setattr(decoder,'train_security_formula_decoder',train)
    assert cli.main(argv)==2
    result=json.loads(capsys.readouterr().out)
    assert result=={'status':'not_qualified','error_type':'ValueError','exit_code':2}
    assert 'decoder' not in result
    # A completed but unqualified package remains inspectable; it cannot be
    # presented by the CLI as bound to the now-changed input declarations.
    assert {p.name for p in output.iterdir()}==decoder.FILES
    assert teacher[0].read_bytes()==teacher[2]


@pytest.mark.parametrize('change',['not_list','missing_split','source_hash','cross_split_alias','bad_parent','bad_epoch'])
def test_bad_declared_inputs_refuse_before_package_creation(cli, invocation, capsys, change):
    argv, files, output, samples=invocation
    values=deepcopy(samples)
    if change=='not_list': values={'samples':values}
    elif change=='missing_split': values[-1]['split']='train'
    elif change=='source_hash': values[0]['source_sha256']='0'*64
    elif change=='cross_split_alias':
        values[-1]['source']='def renamed(other):\n    return other + 8\n'
        values[-1]['source_sha256']=_sha(values[-1]['source'].encode())
    elif change=='bad_parent':
        parent=json.loads(files['initializer'].read_bytes());parent['source_checkpoint_sha256']='0'*64
        files['initializer'].write_text(json.dumps(parent))
    else: argv[argv.index('--epochs')+1]='0'
    files['samples'].write_text(json.dumps(values))
    assert cli.main(argv)==2
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='not_qualified' and 'decoder' not in result
    assert not output.exists()


def test_duplicate_json_field_is_rejected_before_native_trainer(cli, invocation, monkeypatch, capsys):
    argv, files, output, _=invocation
    files['initializer'].write_bytes(b'{"output":"first","output":"second"}')
    monkeypatch.setattr(decoder,'train_security_formula_decoder',lambda **kwargs:pytest.fail('duplicate JSON reached trainer'))
    assert cli.main(argv)==2
    assert json.loads(capsys.readouterr().out)['status']=='not_qualified'
    assert not output.exists()


def test_unknown_scope_is_argparse_failure_before_training(cli, invocation, monkeypatch):
    argv, _, output, _=invocation
    argv[argv.index('--training-data-scope')+1]='proved_production_security'
    monkeypatch.setattr(decoder,'train_security_formula_decoder',lambda **kwargs:pytest.fail('unknown scope reached trainer'))
    with pytest.raises(SystemExit) as error: cli.main(argv)
    assert error.value.code==2 and not output.exists()
