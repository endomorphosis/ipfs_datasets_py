from copy import deepcopy
import pytest
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_runtime as subject


@pytest.fixture
def runtime():
    import torch
    torch.set_num_threads(1); torch.manual_seed(boundary.CONFIG['seed'])
    checkpoint = boundary.checkpoint(boundary.model(torch), steps=0,
        training_manifest_sha256='a' * 64, tuning_manifest_sha256='b' * 64)
    return subject.GuardedClauseBoundaryDecoder(checkpoint)


def sources():
    text = 'Guard Fixture Board must retain reports.'
    return [{'candidate_id': 'guard-fixture', 'source_text': text, 'source_sha256': boundary.text_sha(text)}]


def test_guard_preserves_every_original_prediction_and_adds_integrity(runtime):
    expected = boundary.ClauseBoundaryDecoder(runtime.checkpoint).decode(sources())
    actual = runtime.decode(sources())
    receipt = actual.pop('runtime_integrity')
    assert actual == expected
    assert receipt['model_state_sha256_before'] == receipt['model_state_sha256_after']
    assert receipt['model_state_unchanged'] and not receipt['source_semantics_verified']


def test_public_checkpoint_mutation_cannot_change_owned_state(runtime):
    before = runtime.decode(sources())
    exposed = runtime.checkpoint
    exposed['config']['hidden_size'] += 1
    exposed['model_state']['boundary.bias'][0] += 2
    assert runtime.decode(sources()) == before


def test_caller_checkpoint_alias_does_not_change_runtime(runtime):
    caller = runtime.checkpoint
    owned = subject.GuardedClauseBoundaryDecoder(caller)
    before = owned.decode(sources())
    caller['model_state']['scope.bias'][0] += 3
    assert owned.decode(sources()) == before


def test_live_torch_weight_mutation_is_rejected(runtime):
    with runtime._decoder.torch.no_grad():
        runtime._decoder.network.boundary.bias.add_(1.)
    with pytest.raises(ValueError, match='model state changed'):
        runtime.decode(sources())


def test_private_checkpoint_receipt_corruption_is_rejected(runtime):
    runtime._decoder.checkpoint['optimizer_steps'] += 1
    with pytest.raises(ValueError, match='checkpoint changed'):
        runtime.decode(sources())


def test_mutation_during_inference_is_rejected(runtime, monkeypatch):
    original = runtime._decoder.decode
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with runtime._decoder.torch.no_grad():
            runtime._decoder.network.scope.bias.add_(1.)
        return result
    monkeypatch.setattr(runtime._decoder, 'decode', changed)
    with pytest.raises(ValueError, match='model state changed'):
        runtime.decode(sources())
