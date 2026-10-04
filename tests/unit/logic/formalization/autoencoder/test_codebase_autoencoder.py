"""Real code-only weight fitting, checkpoint replay and isolation contracts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder as ae
PROGRAM = '''# Authored fixture, independent of any benchmark repository.
def convert(raw, encoding='utf8', errors='strict'):
    if isinstance(raw, (bytes, bytearray)):
        return str(raw, encoding, errors)
    return '' if raw is None else str(raw)

def clean_label(raw):
    label = convert(raw)
    return label.title().replace('_', '-')

def clean_payload(raw):
    payload = convert(raw)
    return payload

class WireResponse:
    def __init__(self):
        self._values = {}

    def put(self, label, payload):
        self._values[clean_label(label)] = [clean_payload(payload)]

    @property
    def fields_for_wire(self):
        pairs = list(self._values.items())
        return [(label, value) for label, values in pairs for value in values]

def application(environ, respond):
    response = WireResponse()
    respond('200 OK', response.fields_for_wire)
'''


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    (root / 'authored.py').write_text(PROGRAM)
    (root / 'note.txt').write_text('public permitted input\n')
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('authored.py', 'note.txt')}
    return dict(repository=root, paths=['authored.py'], source_hashes=hashes,
                output=tmp_path / 'training' / 'code-autoencoder', epochs=8)


def test_actual_native_training_updates_weights_reduces_loss_and_reloads(inputs, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as legal
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as kernel
    calls = []
    original = kernel._loss_chunk
    def recorded(*args, **kwargs):
        calls.append(args[3])
        assert args[2][1].shape[1] == args[2][2].shape[1] == 0
        return original(*args, **kwargs)
    monkeypatch.setattr(kernel, '_loss_chunk', recorded)
    monkeypatch.setattr(legal.AdaptiveModalAutoencoder, '__init__', lambda *_args, **_kwargs: pytest.fail('no legal engine/state construction'))
    before = {name: (inputs['repository'] / name).read_bytes() for name in inputs['source_hashes']}
    receipt = ae.train_codebase_autoencoder(**inputs)
    assert receipt['domain'] == 'security-code@1'
    assert receipt['epochs_completed'] == 8 and receipt['training_elapsed_seconds'] > 0
    assert calls and all(item == {'decoded_embedding'} for item in calls)
    metrics = receipt['metrics']
    assert metrics['initial_weights_sha256'] != metrics['final_weights_sha256']
    assert metrics['after_reconstruction_loss'] < metrics['before_reconstruction_loss']
    assert metrics['holdout_evaluated'] is False
    assert receipt['source_hashes'] == inputs['source_hashes']
    assert len(receipt['ranks']) == receipt['sample_count']
    checked = ae.validate_codebase_autoencoder(repository=inputs['repository'], expected_receipt=receipt)
    assert checked['status'] == 'verified'
    assert checked['proof_authority'] is checked['formalization_authority'] is checked['omission_authority'] is False
    checkpoint = json.loads((inputs['output'] / 'checkpoint.json').read_text())
    assert checkpoint['legal_ir_weights_loaded'] is checkpoint['legal_ir_views_loaded'] is False
    assert checkpoint['tla_projection']['status'] == 'unsupported'
    assert checkpoint['implementation']['reused_functions'] == ['_loss_chunk', '_gradient_norm', 'plan_gradient_accumulation']
    assert {name: (inputs['repository'] / name).read_bytes() for name in before} == before


@pytest.mark.parametrize('kind', ['checkpoint', 'features', 'index', 'receipt', 'descriptor', 'source', 'omitted_source'])
def test_replay_refuses_modified_artifacts_or_any_bound_source(inputs, kind):
    receipt = ae.train_codebase_autoencoder(**inputs)
    if kind in {'checkpoint', 'features', 'index', 'receipt'}:
        artifact = inputs['output'] / (kind + '.json')
        artifact.chmod(0o644)
        artifact.write_bytes(artifact.read_bytes() + b' ')
    elif kind == 'descriptor':
        receipt = {**receipt, 'sample_count': receipt['sample_count'] + 1}
    else:
        path = inputs['repository'] / ('authored.py' if kind == 'source' else 'note.txt')
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
    with pytest.raises(ValueError):
        ae.validate_codebase_autoencoder(repository=inputs['repository'], expected_receipt=receipt)


def test_source_drift_during_training_is_not_published(inputs, monkeypatch):
    original = ae._inference
    calls = []
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            path = inputs['repository'] / 'authored.py'
            path.write_bytes(path.read_bytes() + b'\n# concurrent change\n')
        calls.append(True)
        return result
    monkeypatch.setattr(ae, '_inference', drift)
    with pytest.raises(ValueError, match='source drift'):
        ae.train_codebase_autoencoder(**inputs)
    assert not inputs['output'].exists()


@pytest.mark.parametrize('kind', ['existing', 'legal', 'shared', 'inside', 'symlink', 'foreign_schema'])
def test_distinct_code_namespace_cannot_overwrite_legal_or_shared_state(inputs, tmp_path, kind):
    if kind == 'foreign_schema':
        with pytest.raises(ValueError, match='code-domain'):
            ae.validate_codebase_autoencoder(repository=inputs['repository'], expected_receipt={'schema': 'modal-autoencoder-state-v1', 'domain': 'legal'})
        return
    if kind == 'existing':
        output = inputs['output']
        output.mkdir(parents=True)
        (output / 'checkpoint.json').write_text('preserve existing state')
    elif kind == 'legal':
        output = tmp_path / 'legal_ir' / 'code-autoencoder'
    elif kind == 'shared':
        output = tmp_path / 'shared-weights' / 'code-autoencoder'
    elif kind == 'inside':
        output = inputs['repository'] / 'code-autoencoder'
    else:
        (tmp_path / 'actual').mkdir()
        (tmp_path / 'linked').symlink_to(tmp_path / 'actual', target_is_directory=True)
        output = tmp_path / 'linked' / 'code-autoencoder'
    with pytest.raises(ValueError, match='namespace'):
        ae.train_codebase_autoencoder(**{**inputs, 'output': output})
    if kind == 'existing':
        assert (output / 'checkpoint.json').read_text() == 'preserve existing state'


@pytest.mark.parametrize('changed', [{'epochs': 33}, {'latent_dim': 44}, {'max_functions': 1}, {'paths': ['other.py']}, {'epochs': True}])
def test_training_bounds_and_admitted_input_set_are_closed(inputs, changed):
    with pytest.raises(ValueError):
        ae.train_codebase_autoencoder(**{**inputs, **changed})
    assert not inputs['output'].exists()


def test_same_seed_retrains_same_code_weights_without_touching_prior_checkpoint(inputs, tmp_path):
    first = ae.train_codebase_autoencoder(**inputs)
    second = ae.train_codebase_autoencoder(**{**inputs, 'output': tmp_path / 'second' / 'code-autoencoder'})
    assert first['checkpoint_sha256'] == second['checkpoint_sha256']
    assert first['ranks'] == second['ranks']
    assert first['metrics']['native_objective_losses'] == second['metrics']['native_objective_losses']


def test_native_secret_screen_refuses_before_training_without_retaining_flagged_body(inputs, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder.source_screening import PlanningAnalysisSecretError
    path = inputs['repository'] / 'authored.py'
    marker = 'AUTHORED-DUMMY-NOT-A-CREDENTIAL'
    path.write_text(PROGRAM + '\npassword = "' + marker + '"\n')
    inputs['source_hashes']['authored.py'] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(ae, '_dependencies', lambda: pytest.fail('screen before loading/training any model'))
    with pytest.raises(PlanningAnalysisSecretError) as observed:
        ae.train_codebase_autoencoder(**inputs)
    assert marker not in str(observed.value) and 'authored.py' not in str(observed.value)
    assert not inputs['output'].exists()


@pytest.mark.parametrize('kind', ['architecture', 'tla', 'receipt_schema', 'authority'])
def test_even_repinned_foreign_architecture_or_authority_claim_refused(inputs, kind):
    descriptor = ae.train_codebase_autoencoder(**inputs)
    receipt_path = inputs['output'] / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    if kind in {'architecture', 'tla'}:
        checkpoint_path = inputs['output'] / 'checkpoint.json'
        checkpoint = json.loads(checkpoint_path.read_text())
        if kind == 'architecture':
            checkpoint['architecture'] = 'foreign-architecture'
        else:
            checkpoint['tla_projection'] = {'status': 'proved'}
        raw = ae._json(checkpoint)
        checkpoint_path.chmod(0o644)
        checkpoint_path.write_bytes(raw)
        receipt['checkpoint_sha256'] = hashlib.sha256(raw).hexdigest()
        descriptor['checkpoint_sha256'] = receipt['checkpoint_sha256']
    elif kind == 'receipt_schema':
        receipt['schema'] = 'foreign-receipt'
    else:
        receipt['formalization_authority'] = True
    raw = ae._json(receipt)
    receipt_path.chmod(0o644)
    receipt_path.write_bytes(raw)
    descriptor['receipt_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        ae.validate_codebase_autoencoder(repository=inputs['repository'], expected_receipt=descriptor)
