"""Authored native checkpoints: exact lexical transfer and independent reload."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder as ae
from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder_transfer as transfer


@pytest.fixture
def teacher(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
    state = ModalAutoencoderTrainingState(feature_embedding_weights={
        'token:return': [0.07 * (i + 1) for i in range(8)],
        'token:value': [0.11 * (i + 1) for i in range(8)],
        'token:raise': [-0.09 * (i + 1) for i in range(8)],
        'title:legal-only': [8.] * 8}, legal_ir_view_logits={'legal-only': 3.})
    raw = serialize_checkpoint(state, metadata={'fixture': 'authored-native-state'})
    path = tmp_path / 'legal-source' / 'checkpoint.bin'
    path.parent.mkdir()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), raw


@pytest.fixture
def fork(teacher, tmp_path):
    return transfer.fork_legal_shared_weights(source_checkpoint=teacher[0], expected_sha256=teacher[1],
              output=tmp_path / 'separate-model' / 'security-code-initializer')


def test_exact_native_weight_copy_has_no_legal_heads_and_preserves_source(teacher, fork):
    observed = transfer.validate_legal_shared_weight_fork(expected_receipt=fork)
    assert observed['keys'] == ['token:raise', 'token:return', 'token:value']
    assert observed['weights'][1] == [0.07 * (i + 1) for i in range(8)]
    assert observed['source_metadata']['fixture'] == 'authored-native-state'
    assert observed['legal_heads_loaded'] is observed['legal_views_loaded'] is observed['sample_memory_loaded'] is False
    assert teacher[0].read_bytes() == teacher[2]
    assert Path(fork['output'], 'source.checkpoint').read_bytes() == teacher[2]


def test_fork_is_relocatable_and_independent_of_later_teacher_training(teacher, fork, tmp_path):
    destination = tmp_path / 'container' / 'security-code-initializer'
    shutil.copytree(fork['output'], destination)
    (destination / 'source.checkpoint').unlink()
    teacher[0].write_bytes(b'new legal checkpoint committed by separate trainer')
    observed = transfer.validate_legal_shared_weight_fork(expected_receipt={**fork, 'output': str(destination)})
    assert observed['source_checkpoint_sha256'] == teacher[1]
    assert fork['runtime_validation_scope'] == 'admitted_initializer_integrity_not_original_legal_state_replay'
    with pytest.raises(FileNotFoundError):
        transfer.validate_legal_shared_weight_fork(expected_receipt={**fork, 'output': str(destination)}, replay_source=True)


@pytest.mark.parametrize('kind', ['source', 'weights', 'head', 'descriptor'])
def test_tampered_snapshot_or_repinning_foreign_head_rejected(fork, kind):
    if kind == 'descriptor':
        fork = {**fork, 'domain': 'legal-ir'}
    else:
        path = Path(fork['output']) / ('source.checkpoint' if kind == 'source' else 'initializer.json')
        path.chmod(0o644)
        if kind == 'source':
            path.write_bytes(path.read_bytes() + b' ')
        else:
            value = json.loads(path.read_text())
            if kind == 'weights':
                value['weights'][0][0] += 1
            else:
                value['legal_heads_loaded'] = True
            path.write_bytes(transfer._json(value))
            # Even a consistently repinned wrapper cannot alter source extraction.
            manifest_path = Path(fork['output']) / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['initializer_sha256'] = transfer._sha(path.read_bytes())
            manifest_path.chmod(0o644)
            manifest_path.write_bytes(transfer._json(manifest))
            fork = transfer._descriptor(Path(fork['output']), manifest, manifest_path.read_bytes())
    with pytest.raises(ValueError):
        transfer.validate_legal_shared_weight_fork(expected_receipt=fork, replay_source=True)


def test_native_tokenizer_coverage_and_oov_are_explicit(fork):
    observed = transfer.validate_legal_shared_weight_fork(expected_receipt=fork)
    row = transfer.lexical_observation('RETURN value value unknown the', observed)
    assert row['lexical_indices'] == [1, 2]
    assert row['lexical_coverage'] == dict(selected_tokens=4, in_vocabulary_tokens=3, oov_tokens=1,
                                          unique_matched_keys=2, token_window=40)


def test_wrong_hash_namespace_and_concurrent_source_drift_refused(teacher, tmp_path, monkeypatch):
    kwargs = dict(source_checkpoint=teacher[0], expected_sha256=teacher[1],
                  output=tmp_path / 'security-code-initializer')
    with pytest.raises(ValueError, match='SHA256'):
        transfer.fork_legal_shared_weights(**{**kwargs, 'expected_sha256': '0' * 64})
    with pytest.raises(ValueError, match='namespace'):
        transfer.fork_legal_shared_weights(**{**kwargs, 'output': teacher[0].parent / 'security-code-initializer'})
    original = transfer._extract
    def drift(raw):
        result = original(raw)
        teacher[0].write_bytes(teacher[2] + b' ')
        return result
    monkeypatch.setattr(transfer, '_extract', drift)
    with pytest.raises(ValueError, match='changed'):
        transfer.fork_legal_shared_weights(**kwargs)
    assert not kwargs['output'].exists()


def test_transferred_native_weights_actually_initialize_train_and_reload_without_random(teacher, fork, tmp_path, monkeypatch):
    import torch
    root = tmp_path / 'repo'
    root.mkdir()
    source = b'def count(value):\n    return value + 1\n\ndef demand(value):\n    if value < 0:\n        raise ValueError(value)\n    return value\n'
    (root / 'code.py').write_bytes(source)
    original = ae._inference
    captured = []
    def inspect(torch, rows, parameters):
        if not captured:
            captured.append([p.detach().tolist() for p in parameters])
        return original(torch, rows, parameters)
    monkeypatch.setattr(ae, '_inference', inspect)
    monkeypatch.setattr(torch, 'randn', lambda *_a, **_k: pytest.fail('fork path must never random initialize'))
    descriptor = ae.train_codebase_autoencoder(repository=root, paths=['code.py'],
        source_hashes={'code.py': hashlib.sha256(source).hexdigest()}, output=tmp_path / 'learned' / 'code-autoencoder',
        epochs=8, weight_transfer=fork)
    initializer = transfer.validate_legal_shared_weight_fork(expected_receipt=fork)
    assert captured[0][4] == initializer['weights']
    assert all(not torch.tensor(p).any() for p in captured[0][:4])
    metrics = descriptor['metrics']['weight_transfer']
    assert metrics['random_initialization'] is False
    assert metrics['trained_transferred_weights_sha256'] != metrics['transferred_weights_sha256']
    assert descriptor['metrics']['after_reconstruction_loss'] < descriptor['metrics']['before_reconstruction_loss']
    assert ae.validate_codebase_autoencoder(repository=root, expected_receipt=descriptor)['status'] == 'verified'
    assert teacher[0].read_bytes() == teacher[2]


def test_incompatible_width_and_zero_vocabulary_overlap_abstain(fork, tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    source = b'def xyzzy(qwerty):\n    pass\n'
    (root / 'code.py').write_bytes(source)
    kwargs = dict(repository=root, paths=['code.py'], source_hashes={'code.py': hashlib.sha256(source).hexdigest()},
                  output=tmp_path / 'learned' / 'code-autoencoder', weight_transfer=fork)
    with pytest.raises(ValueError, match='width'):
        ae.train_codebase_autoencoder(**kwargs, latent_dim=4)
    with pytest.raises(ValueError, match='zero code vocabulary'):
        ae.train_codebase_autoencoder(**kwargs)
    assert not kwargs['output'].exists()


@pytest.fixture
def joint_inputs(fork, tmp_path, monkeypatch):
    from tests.unit.logic.formalization.autoencoder.test_security_cve_canonical_export import _fixture_export
    export_root, receipt, _ = _fixture_export(tmp_path, monkeypatch)
    root = tmp_path / 'code-repository'
    root.mkdir()
    source = b'def count(value):\n    return value + 1\n'
    (root / 'code.py').write_bytes(source)
    return dict(repository=root, paths=['code.py'], source_hashes={'code.py': hashlib.sha256(source).hexdigest()},
        output=tmp_path / 'joint' / 'code-autoencoder', epochs=12, weight_transfer=fork,
        canonical_cve_training={'output': str(export_root), 'manifest_sha256': receipt['manifest_sha256']})


def test_joint_supervised_security_head_uses_canonical_targets_and_replays(joint_inputs, teacher):
    descriptor = ae.train_codebase_autoencoder(**joint_inputs)
    metrics = descriptor['metrics']['security_candidate_training']
    assert metrics['sample_count'] == 2
    assert metrics['after']['training_bce'] < metrics['before']['training_bce']
    assert metrics['after']['holdout_evaluated'] is False
    assert metrics['before']['candidate_scores'] == [[.5] * 5] * 2
    assert 'cwe:CWE-20' in metrics['after']['target_vocabulary']
    assert descriptor['canonical_cve_training'] == joint_inputs['canonical_cve_training']
    nominations = descriptor['security_candidate_nominations']
    assert nominations['target_vocabulary'] == metrics['after']['target_vocabulary']
    assert {row['row_id'] for row in nominations['rows']} == {row['row_id'] for row in descriptor['ranks']}
    assert len(nominations['rows'][0]['scores']) == 5
    assert any(value != .5 for value in nominations['rows'][0]['scores'])
    assert nominations['scores_are_calibrated_probabilities'] is False
    assert nominations['granularity_shift_validated'] is False
    assert nominations['proof_authority'] is nominations['formalization_authority'] is nominations['execution_authority'] is False
    features = json.loads((joint_inputs['output'] / 'features.json').read_text())
    security = features['security_candidate_training']
    assert security['target_graph_features_used_as_inputs'] is False
    assert all(row['body_sha256'] and row['code_unit_cids'] for row in security['rows'])
    assert security['targets'][0][2] != security['targets'][1][2]
    checkpoint = json.loads((joint_inputs['output'] / 'checkpoint.json').read_text())
    assert len(checkpoint['weights']) == 7
    assert any(value != 0 for row in checkpoint['weights'][5] for value in row)
    assert checkpoint['security_candidate_projection']['execution_authority'] is False
    assert ae.validate_codebase_autoencoder(repository=joint_inputs['repository'], expected_receipt=descriptor)['status'] == 'verified'
    assert teacher[0].read_bytes() == teacher[2]




def test_canonical_export_drift_rejects_joint_model_reuse(joint_inputs):
    descriptor = ae.train_codebase_autoencoder(**joint_inputs)
    path = Path(joint_inputs['canonical_cve_training']['output']) / 'training-pairs.json'
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError):
        ae.validate_codebase_autoencoder(repository=joint_inputs['repository'], expected_receipt=descriptor)


def test_security_training_refuses_unbound_random_initialization(joint_inputs):
    with pytest.raises(ValueError, match='inherited weight fork'):
        ae.train_codebase_autoencoder(**{**joint_inputs, 'weight_transfer': None})


def test_joint_projector_cannot_import_legal_or_execution_authority_even_if_repinned(joint_inputs):
    descriptor = ae.train_codebase_autoencoder(**joint_inputs)
    checkpoint_path = joint_inputs['output'] / 'checkpoint.json'
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint['security_candidate_projection']['execution_authority'] = True
    checkpoint_path.chmod(0o644)
    checkpoint_path.write_bytes(ae._json(checkpoint))
    receipt_path = joint_inputs['output'] / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['checkpoint_sha256'] = ae._sha(checkpoint_path.read_bytes())
    descriptor['checkpoint_sha256'] = receipt['checkpoint_sha256']
    receipt_path.chmod(0o644)
    receipt_path.write_bytes(ae._json(receipt))
    descriptor['receipt_sha256'] = ae._sha(receipt_path.read_bytes())
    with pytest.raises(ValueError, match='projection authority'):
        ae.validate_codebase_autoencoder(repository=joint_inputs['repository'], expected_receipt=descriptor)
