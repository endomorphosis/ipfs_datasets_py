"""Actual public537-to-counted28 transfer, using exposed authored labels only."""
from copy import deepcopy
import hashlib
import inspect
import json
import math

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as donor_owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_counted_content_head_v1 as seeded_owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_counted_content_head_transfer_v1 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as transfer_owner

CONFIG = dict(hidden_size=8, token_embedding_dim=8, projection_width=4, seed=1729)
VECTOR = [1.] + [0.] * 383
CONTEXT = b'{"distinctness":"builtin_object_identity","frame":{"event":{"sort":"EventFrame","variable":"event"},"policy":"per_event_and_time","time":{"semantics":"arbitrary_index_without_order","sort":"TimeFrame","variable":"time"}},"maximum":3,"membership":{"argument_roles":["object","event","time"],"symbol":"Member"},"object_variables":["x0","x1","x2","x3"],"predicate":{"domain":["Object","EventFrame","TimeFrame"],"name":"Member","range":"Bool"},"schema":"legal-counted-compact-context/v1","sorts":["Object","EventFrame","TimeFrame"]}'
IDS = [1, 26, 13, 23, 10, 16, 14, 23, 24, 8, 16, 17, 16, 3, 16, 24, 8, 16, 18, 16, 5, 16, 24, 8, 16, 19, 16, 4, 16, 24, 8, 16, 20, 16, 4, 16, 24, 8, 16, 21, 16, 4, 16, 24, 8, 16, 22, 16, 4, 16, 24, 9, 16, 24, 6, 16, 24, 6, 16, 24, 6, 16, 24, 12, 16, 17, 16, 24, 24, 15, 16, 19, 25, 16, 24, 15, 16, 17, 25, 16, 24, 15, 16, 18, 25, 25, 25, 16, 24, 12, 16, 17, 16, 24, 24, 15, 16, 20, 25, 16, 24, 15, 16, 17, 25, 16, 24, 15, 16, 18, 25, 25, 25, 25, 16, 24, 12, 16, 17, 16, 24, 24, 15, 16, 21, 25, 16, 24, 15, 16, 17, 25, 16, 24, 15, 16, 18, 25, 25, 25, 25, 16, 24, 12, 16, 17, 16, 24, 24, 15, 16, 22, 25, 16, 24, 15, 16, 17, 25, 16, 24, 15, 16, 18, 25, 25, 25, 25, 16, 24, 11, 16, 24, 11, 16, 24, 11, 16, 24, 11, 16, 24, 11, 16, 24, 7, 16, 24, 15, 16, 19, 25, 16, 24, 15, 16, 20, 25, 25, 16, 24, 7, 16, 24, 15, 16, 19, 25, 16, 24, 15, 16, 21, 25, 25, 25, 16, 24, 7, 16, 24, 15, 16, 19, 25, 16, 24, 15, 16, 22, 25, 25, 25, 16, 24, 7, 16, 24, 15, 16, 20, 25, 16, 24, 15, 16, 21, 25, 25, 25, 16, 24, 7, 16, 24, 15, 16, 20, 25, 16, 24, 15, 16, 22, 25, 25, 25, 16, 24, 7, 16, 24, 15, 16, 21, 25, 16, 24, 15, 16, 22, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 27, 2]
LEXICAL = {'target_embedding.weight', 'output.weight', 'output.bias'}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def forbidden(*args, **kwargs):
    pytest.fail('invalid input reached actual donor transfer or numerical forward')


@pytest.fixture(scope='module', autouse=True)
def principal_cpu_scope():
    threads, adam = torch.get_num_threads(), torch.optim.Adam
    calls = []
    def no_adam(*args, **kwargs):
        calls.append('Adam construction')
        pytest.fail('principal seeded537 transfer must not construct Adam')
    torch.set_num_threads(1)
    torch.optim.Adam = no_adam
    try:
        yield calls
    finally:
        torch.optim.Adam = adam
        torch.set_num_threads(threads)
        assert calls == []


@pytest.fixture(scope='module')
def donor(principal_cpu_scope):
    return donor_owner.create_compact_content_head_v1(config=CONFIG)


@pytest.fixture(scope='module')
def snapshot(donor):
    return subject.create_transferred_counted_content_head_v1(donor, expected_donor_sha256=digest(donor))


def validate(value, donor, **changes):
    options = dict(expected_checkpoint_sha256=digest(value), expected_donor_sha256=digest(donor))
    options.update(changes)
    return subject.validate_transferred_counted_content_head_v1(value, donor, **options)


def score(value, donor, vector=None, prefix=None, **changes):
    options = dict(expected_checkpoint_sha256=digest(value), expected_donor_sha256=digest(donor))
    options.update(changes)
    return subject.score_transferred_counted_content_head_v1(value, donor,
        list(VECTOR) if vector is None else vector, [1] if prefix is None else prefix, **options)


def evaluate(value, donor, ids=None, context=CONTEXT, **changes):
    options = dict(expected_checkpoint_sha256=digest(value), expected_donor_sha256=digest(donor),
                   expected_context_sha256=sha(context))
    options.update(changes)
    return subject.evaluate_transferred_counted_content_head_v1(value, donor, VECTOR,
        list(IDS) if ids is None else ids, context, **options)


def no_authority(value):
    assert value['authority'] and all(flag is False for flag in value['authority'].values())
    assert type(value['training_mask']) is int and value['training_mask'] == 0
    assert type(value['evaluation_gold_mask']) is int and value['evaluation_gold_mask'] == 0
    assert value['counted_training_steps'] == 0


def equal_bits(left, right):
    assert list(left.shape) == list(right.shape)
    assert torch.equal(left.contiguous().reshape(-1).view(torch.int32),
                       right.contiguous().reshape(-1).view(torch.int32))


def test_transferred_real_kernel_copies_ten_tensors_and_maps_all_28_rows(donor, snapshot):
    original = deepcopy(donor)
    before = torch.get_rng_state().clone()
    repeated = subject.create_transferred_counted_content_head_v1(donor, expected_donor_sha256=digest(donor))
    assert repeated == snapshot and donor == original and torch.equal(before, torch.get_rng_state())
    assert len(snapshot['model_state']) == 13
    assert snapshot['schema'] != seeded_owner.SCHEMA and snapshot['profile'] != seeded_owner.PROFILE
    assert snapshot['donor']['checkpoint_sha256'] == digest(donor)
    assert snapshot['donor']['compact_training_steps'] == 0
    assert snapshot['donor']['initialization_mode'] == 'seeded_new'
    assert snapshot['donor']['conditioning_profile'] == 'caller_supplied_unverified384'
    assert snapshot['donor']['original_required_for_restore'] is True
    assert snapshot['donor_modified'] is False and snapshot['optimizer_state_included'] is False
    assert snapshot['fresh_optimizer_required'] is True
    old_vocab, new_vocab = donor['codec']['vocabulary'], snapshot['codec']['vocabulary']
    assert len(old_vocab) == 537 and len(new_vocab) == 28
    old_positions = {token: index for index, token in enumerate(old_vocab)}
    mapping = snapshot['lexical_row_map']
    assert mapping == snapshot['transfer_plan']['lexical_row_map']
    assert [row['token'] for row in mapping] == new_vocab
    assert sum(token in old_positions for token in new_vocab) == 23
    assert sum(token not in old_positions for token in new_vocab) == 5
    ledger = {row['parameter']: row for row in snapshot['realized_tensor_ledger']}
    assert set(ledger) == set(snapshot['model_state']) and len(ledger) == 13
    assert len(set(ledger) - LEXICAL) == 10
    for name, values in snapshot['model_state'].items():
        actual = torch.tensor(values, dtype=torch.float32)
        prior = torch.tensor(donor['model_state'][name], dtype=torch.float32)
        assert actual.dtype is torch.float32 and actual.device.type == 'cpu'
        assert bool(torch.isfinite(actual).all())
        assert list(actual.shape) == snapshot['spec']['identity']['tensor_shapes'][name]
        assert ledger[name]['donor_tensor_sha256'] == digest(donor['model_state'][name])
        assert ledger[name]['target_tensor_sha256'] == digest(values)
        if name not in LEXICAL:
            equal_bits(actual, prior)
            assert ledger[name]['policy'] == 'exact_nonlexical_copy'
            continue
        assert actual.shape[0] == 28 and prior.shape[0] == 537
        mean = prior.mean(0)  # Full donor vocabulary, including its three specials.
        for index, token in enumerate(new_vocab):
            row = mapping[index]
            assert row['token_id'] == index and row['parent_token_id'] == old_positions.get(token)
            if token in old_positions:
                equal_bits(actual[index], prior[old_positions[token]])
                assert row['policy'] == 'copied_exact_token'
            else:
                equal_bits(actual[index], mean)
                assert row['policy'] == 'parent_lexical_row_mean'
    lineage = snapshot['kernel_transfer_lineage']
    assert lineage['exact_inherited_tensors'] == sorted(set(ledger) - LEXICAL)
    assert lineage['lexical_mapped_tensors'] == sorted(LEXICAL)
    assert lineage['parent_modified'] is False and lineage['random_parameters_used'] is False
    assert snapshot['transfer_plan']['declared_conditioning_relation'] == 'unknown'
    no_authority(snapshot)


def test_transferred_donor_required_json_replay_preserves_every_weight_and_logit(donor, snapshot):
    original = deepcopy(donor)
    restored_donor, restored = json.loads(wire(donor)), json.loads(wire(snapshot))
    assert validate(restored, restored_donor) == snapshot
    assert subject.transferred_counted_content_head_sha256(restored) == digest(snapshot)
    assert score(restored, restored_donor) == score(snapshot, donor)
    assert restored['model_state'] == snapshot['model_state'] and donor == original


def test_transferred_complete_unmasked_loss_matches_python_oracle_and_retains_artifacts(donor, snapshot, tmp_path, principal_cpu_scope):
    before = torch.get_rng_state().clone()
    result = evaluate(snapshot, donor)
    assert result['output_shape'] == [1, 292, 28]
    assert result['input_ids'] == IDS[:-1] and result['label_ids'] == IDS[1:]
    assert result['predicted_tokens'] == 292 and result['eos_included_in_loss'] is True
    assert len(result['logits']) == 292 and all(len(row) == 28 for row in result['logits'])
    expected = []
    for row, label in zip(result['logits'], IDS[1:]):
        assert all(type(x) is float and math.isfinite(x) for x in row)
        maximum = max(row)
        expected.append(maximum + math.log(sum(math.exp(x - maximum) for x in row)) - row[label])
    assert result['token_losses'] == pytest.approx(expected, rel=1e-12, abs=1e-12)
    assert result['mean_cross_entropy'] == pytest.approx(sum(expected)/292, rel=1e-12, abs=1e-12)
    assert result['prediction_ids'] == [max(range(28), key=lambda i: row[i]) for row in result['logits']]
    assert result['grammar_mask_applied'] is False and result['generation_executed'] is False
    assert result['target_context_role'] == 'label_only_target_derived'
    assert result['target_population_size'] == 1 and result['optimizer_executed'] is False
    assert result['donor_required_and_publicly_validated'] is True
    assert principal_cpu_scope == [] and torch.equal(before, torch.get_rng_state())
    no_authority(result)
    (tmp_path/'seeded-public537-donor.json').write_bytes(wire(donor))
    (tmp_path/'transferred-counted28-checkpoint.json').write_bytes(wire(snapshot))
    (tmp_path/'transferred-counted28-teacher-forced-observation.json').write_bytes(wire(result))


def test_transferred_raw_scores_remain_condition_sensitive_and_target_free(donor, snapshot):
    before = torch.get_rng_state().clone()
    a = score(snapshot, donor)
    b = score(snapshot, donor, vector=[-1.] + [0.]*383)
    assert len(a['logits']) == 28 and a['logits'] != b['logits']
    assert a['output_shape'] == [1, 1, 28]
    assert a['grammar_mask_applied'] is False and a['grammatical_prefix_verified'] is False
    assert not {'context_raw', 'target_ids', 'identity_raw'} & set(inspect.signature(subject.score_transferred_counted_content_head_v1).parameters)
    assert torch.equal(before, torch.get_rng_state())
    no_authority(a)


@pytest.mark.parametrize('damage', ['snapshot', 'donor'], ids=['snapshot_pin', 'donor_pin'])
def test_transferred_independent_original_pins_precede_kernel_transfer(donor, snapshot, monkeypatch, damage):
    monkeypatch.setattr(transfer_owner, '_transfer', forbidden)
    options = {'expected_checkpoint_sha256' if damage == 'snapshot' else 'expected_donor_sha256': '0'*64}
    with pytest.raises(ValueError):
        score(snapshot, donor, **options)


@pytest.mark.parametrize('damage', ['seeded_profile', 'old_codec', 'geometry', 'integer_scalar', 'initialization_bool', 'authority', 'torch_version'], ids=['seeded_profile', 'old_codec', 'geometry', 'integer_scalar', 'initialization_bool', 'authority', 'torch_version'])
def test_transferred_resealed_wrong_public_donor_is_refused_before_transfer(donor, monkeypatch, damage):
    value = deepcopy(donor)
    if damage == 'seeded_profile': value['profile'] = seeded_owner.PROFILE
    elif damage == 'old_codec':
        value['codec'] = seeded_owner.create_counted_content_head_v1(config=CONFIG)['codec']
        value['codec_sha256'] = digest(value['codec'])
    elif damage == 'geometry': value['config']['hidden_size'] = 16
    elif damage == 'integer_scalar': value['model_state']['condition.bias'][0] = 0
    elif damage == 'initialization_bool': value['initialization']['fresh_optimizer_required'] = 1
    elif damage == 'authority': value['authority']['training_qualified'] = True
    else: value['torch_version'] = 'not-the-installed-runtime'
    value['weights_sha256'] = digest(value['model_state'])
    value['initialization']['initial_weights_sha256'] = value['weights_sha256']
    monkeypatch.setattr(transfer_owner, '_transfer', forbidden)
    with pytest.raises(ValueError):
        subject.create_transferred_counted_content_head_v1(value, expected_donor_sha256=digest(value))


@pytest.mark.parametrize('damage', ['seeded_identity', 'state', 'state_bool', 'shape', 'plan', 'plan_bool', 'row_map', 'lineage', 'ledger', 'authority'], ids=['seeded_identity', 'state', 'state_bool', 'shape', 'plan', 'plan_bool', 'row_map', 'lineage', 'ledger', 'authority'])
def test_transferred_resealed_snapshot_cannot_replace_actual_donor_replay(donor, snapshot, damage):
    value = deepcopy(snapshot)
    if damage == 'seeded_identity': value['profile'] = seeded_owner.PROFILE
    elif damage == 'state': value['model_state']['output.bias'][0] = (torch.tensor(value['model_state']['output.bias'][0], dtype=torch.float32) + .25).item()
    elif damage == 'state_bool': value['model_state']['output.bias'][0] = False
    elif damage == 'shape': value['model_state']['output.bias'].append(0.)
    elif damage == 'plan': value['transfer_plan']['identity']['geometry']['hidden_size'] += 1
    elif damage == 'plan_bool': value['transfer_plan']['training_mask'] = False
    elif damage == 'row_map': value['lexical_row_map'][0]['parent_token_id'] = 536
    elif damage == 'lineage': value['kernel_transfer_lineage']['random_parameters_used'] = True
    elif damage == 'ledger': value['realized_tensor_ledger'][0]['target_tensor_sha256'] = '0'*64
    else: value['authority']['training_qualified'] = True
    value['weights_sha256'] = digest(value['model_state'])
    value['transfer_plan_sha256'] = digest(value['transfer_plan'])
    with pytest.raises(ValueError):
        validate(value, donor)


@pytest.mark.parametrize('damage', ['missing', 'different_valid'], ids=['missing_original_donor', 'different_valid_donor'])
def test_transferred_restore_requires_the_same_complete_original_donor(donor, snapshot, damage):
    if damage == 'missing':
        with pytest.raises(ValueError):
            subject.validate_transferred_counted_content_head_v1(snapshot, None,
                expected_checkpoint_sha256=digest(snapshot), expected_donor_sha256=digest(donor))
    else:
        other = donor_owner.create_compact_content_head_v1(config={**CONFIG, 'seed': 1730})
        with pytest.raises(ValueError):
            validate(snapshot, other)


@pytest.mark.parametrize('damage', ['truncated', 'interior_pad', 'wrong_structure', 'context', 'context_pin'], ids=['truncated', 'interior_pad', 'wrong_structure', 'context', 'context_pin'])
def test_transferred_invalid_complete_labels_precede_donor_restore_and_forward(donor, snapshot, monkeypatch, damage):
    ids, context, changes = list(IDS), CONTEXT, {}
    if damage == 'truncated': ids.pop()
    elif damage == 'interior_pad': ids[4] = 0
    elif damage == 'wrong_structure': ids[-2] = 26
    elif damage == 'context': context = b'{}'
    else: changes['expected_context_sha256'] = '0'*64
    monkeypatch.setattr(subject, '_replay', forbidden)
    with pytest.raises(ValueError):
        evaluate(snapshot, donor, ids=ids, context=context, **changes)


@pytest.mark.parametrize('damage', ['prefix_bool', 'prefix_eos', 'vector_width', 'vector_nan'], ids=['prefix_bool', 'prefix_eos', 'vector_width', 'vector_nan'])
def test_transferred_invalid_numeric_intake_precedes_donor_transfer(donor, snapshot, monkeypatch, damage):
    options = {}
    if damage == 'prefix_bool': options['prefix'] = [True]
    elif damage == 'prefix_eos': options['prefix'] = [1, 2]
    elif damage == 'vector_width': options['vector'] = [0.]*383
    else: options['vector'] = [float('nan')] + [0.]*383
    monkeypatch.setattr(subject, '_replay', forbidden)
    with pytest.raises(ValueError):
        score(snapshot, donor, **options)


def test_transferred_hash_fences_its_own_source_generation(snapshot, monkeypatch):
    monkeypatch.setattr(subject, '_SELF_SHA', '0'*64)
    with pytest.raises(ValueError):
        subject.transferred_counted_content_head_sha256(snapshot)


def test_transferred_caller_mutation_cannot_escape_final_serialization(donor, snapshot, monkeypatch):
    value = deepcopy(snapshot)
    original, fired = donor_owner._wire, []
    def mutate(offered, *args, **kwargs):
        raw = original(offered, *args, **kwargs)
        if type(offered) is dict and offered.get('schema') == subject.SCHEMA and not fired:
            value['counted_training_steps'] = 1
            fired.append(True)
        return raw
    monkeypatch.setattr(donor_owner, '_wire', mutate)
    with pytest.raises(ValueError):
        validate(value, donor)
    assert fired == [True]


def test_transferred_constructor_random_seed_does_not_survive_full_tensor_replacement(donor, snapshot, monkeypatch):
    original, calls = transfer_owner._transfer, []
    before = torch.get_rng_state().clone()
    def different_seed(parent, codec, config):
        calls.append(config['seed'])
        return original(parent, codec, {**config, 'seed': config['seed'] + 1})
    monkeypatch.setattr(transfer_owner, '_transfer', different_seed)
    repeated = subject.create_transferred_counted_content_head_v1(donor, expected_donor_sha256=digest(donor))
    assert calls == [CONFIG['seed']]
    assert repeated['model_state'] == snapshot['model_state']
    assert repeated['weights_sha256'] == snapshot['weights_sha256']
    assert torch.equal(before, torch.get_rng_state())


def test_transferred_snapshot_is_never_accepted_as_seeded_v1_identity(donor, snapshot, monkeypatch):
    monkeypatch.setattr(seeded_owner, '_model', forbidden)
    with pytest.raises(ValueError):
        seeded_owner.validate_counted_content_head_v1(snapshot, expected_checkpoint_sha256=digest(snapshot))
