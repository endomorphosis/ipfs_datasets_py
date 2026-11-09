"""Inference-only engineering qualification of one retained two-update checkpoint.

The original two authored source groups and arbitrary384 vectors are exposed
training fixtures, not statutory examples or a holdout. Eleven real GRU calls
are enrolled: two independent references and nine trained-runtime calls. No
optimizer may be constructed or stepped, and no checkpoint is trained here.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat

import pytest
import torch
from torch.nn import functional as functional

from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as batch
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

FIXTURE_SHA = '1c4b7c37eba6870c2a746cb3e3191013a1d25906cb75427d4f7be0ca6583dab7'
CHECKPOINT_SHA = '0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0'


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def snapshot(path):
    assert path.is_absolute() and path.resolve(strict=True) == path
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 16 * 1024**2
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    assert identity(before) == identity(after) and len(raw) == before.st_size
    return raw


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def no_authority(value):
    assert value['authority'] and all(flag is False for flag in value['authority'].values())
    assert type(value['training_mask']) is int and value['training_mask'] == 0
    assert type(value['evaluation_gold_mask']) is int and value['evaluation_gold_mask'] == 0


@pytest.fixture(scope='module', autouse=True)
def no_optimizer_or_training():
    attempts = []
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    def forbidden(*args, **kwargs):
        attempts.append('optimizer allocation, update, or training call')
        pytest.fail('inference qualification attempted optimizer construction, restoration, or training')
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.optim.Optimizer, '__init__', forbidden)
        patch.setattr(torch.optim.Adam, '__init__', forbidden)
        patch.setattr(torch.optim.Adam, 'step', forbidden)
        patch.setattr(numerical, '_optimizer', forbidden)
        patch.setattr(trainer, '_restore', forbidden)
        patch.setattr(trainer, 'train_compact_content_v2', forbidden)
        patch.setattr(trainer, 'build_compact_content_training_v2', forbidden)
        try:
            yield attempts
        finally:
            torch.set_num_threads(previous)


@pytest.fixture(scope='module')
def retained(no_optimizer_or_training):
    # The native request pins this explicit path and all27 original artifacts.
    # No search, alternate checkpoint, cache, download, or seeded fallback.
    spelling = os.environ.get('LEGAL_COMPACT_TRAINED_INFERENCE_FIXTURE')
    assert spelling, 'the native harness must supply one exact retained fixture path'
    path = Path(spelling)
    raw = snapshot(path)
    assert sha(raw) == FIXTURE_SHA
    manifest = json.loads(raw)
    assert manifest['schema'] == 'authored-compact-training-fixture/v2'
    assert len(manifest['artifacts']) == 27
    bodies, values = {}, {}
    for name, descriptor in manifest['artifacts'].items():
        selected = Path(descriptor['path'])
        assert selected.parent == path.parent and selected.name == name
        body = snapshot(selected)
        assert len(body) == descriptor['bytes'] and sha(body) == descriptor['sha256']
        bodies[name] = body
        if name.endswith('.json'):
            values[name] = json.loads(body)
    checkpoint = values['resumed-checkpoint.json']
    assert sha(bodies['resumed-checkpoint.json']) == digest(checkpoint) == CHECKPOINT_SHA
    assert checkpoint['progress'] == {'optimizer_steps': 2, 'epochs_completed': 1, 'row_cursor': 0}
    assert checkpoint['initial_checkpoint'] == values['initial-parent-v1.json']
    assert checkpoint['weights_sha256'] != checkpoint['initial_weights_sha256']
    assert values['scope.json']['actual_optimizer_updates'] == 4  # Historical fixture only.
    row = values['input-rows.json'][0]
    bound = values['population.json']['rows'][0]
    assert row['id'] == bound['id'] == 'fictional-retention'
    for key in ('source', 'context', 'target'):
        assert sha(bodies[row[key + '_file']]) == bound[key + '_sha256']
    assert digest(row['conditioning']) == bound['conditioning_sha256']
    return dict(manifest_path=path, manifest_raw=raw, manifest=manifest, bodies=bodies, values=values,
        checkpoint=checkpoint, conditioning=row['conditioning'], context_raw=bodies[row['context_file']])


def args(case, *, checkpoint=None, prefix=None):
    value = case['checkpoint'] if checkpoint is None else checkpoint
    return (value, deepcopy(case['conditioning']), [1] if prefix is None else list(prefix), case['context_raw'])


def score_options(case, checkpoint=None):
    return dict(expected_checkpoint_sha256=digest(case['checkpoint'] if checkpoint is None else checkpoint),
                expected_context_sha256=sha(case['context_raw']))


def generation_options(case):
    return {**score_options(case), 'max_new_tokens': 2, 'prefix_origin': 'bos_seed',
            'context_origin': 'caller_supplied_unverified'}


def independent_logits(checkpoint, conditioning, prefix):
    """Raw retained tensors, public Torch ops and a separate GRU; no owner model helper."""
    state = {name: torch.tensor(value, dtype=torch.float32, device='cpu')
             for name, value in checkpoint['model_state'].items()}
    config = checkpoint['config']
    with torch.random.fork_rng(devices=[]):
        recurrent = torch.nn.GRU(config['token_embedding_dim'], config['hidden_size'], batch_first=True,
                                 device='cpu', dtype=torch.float32)
    recurrent.load_state_dict({name.removeprefix('decoder.'): value for name, value in state.items()
                              if name.startswith('decoder.')}, strict=True)
    recurrent.eval()
    with torch.inference_mode():
        vector = torch.tensor([conditioning], dtype=torch.float32, device='cpu')
        ids = torch.tensor([prefix], dtype=torch.long, device='cpu')
        projected = vector + functional.linear(torch.tanh(functional.linear(vector,
            state['projection_down.weight'], state['projection_down.bias'])),
            state['projection_up.weight'], state['projection_up.bias'])
        hidden = torch.tanh(functional.linear(projected, state['condition.weight'], state['condition.bias'])).unsqueeze(0)
        embedded = functional.embedding(ids, state['target_embedding.weight'], padding_idx=0)
        output, _ = recurrent(embedded, hidden)
        logits = functional.linear(output, state['output.weight'], state['output.bias'])[0, -1]
        assert list(logits.shape) == [537] and bool(torch.isfinite(logits).all())
        return logits.tolist()


def evaluation_material(case):
    originals = case['values']['population.json']['rows']
    population = {'schema': 'legal-relational-batch-population/v1',
        'partition': 'exposed-authored-training-fixtures-inference-engineering',
        'selection_sha256': sha(b'Both retained authored groups; no inference-based population selection'),
        'rows': [{key: row[key] for key in ('id', 'source_sha256', 'context_sha256')} for row in originals]}
    population_raw = wire(population)
    references = {'schema': 'legal-relational-batch-references/v1', 'population_sha256': sha(population_raw),
        'rows': [{'id': row['id'], 'status': 'unavailable', 'request_utf8': None, 'request_sha256': None,
                 'report': None, 'report_sha256': None,
                 'reason': 'Inference engineering on exposed authored training fixtures; no legal evaluation reference supplied'}
                for row in population['rows']]}
    return population_raw, wire(references)


def retain_evidence(case, records, events, directory):
    bodies = {'prior-training-' + name: raw for name, raw in case['bodies'].items()}
    bodies['prior-training-manifest.json'] = case['manifest_raw']
    bodies.update({name + '.json': wire(value) for name, value in records.items()})
    bodies['observed-calls.json'] = wire(events)
    manifest = {}
    for name, raw in bodies.items():
        path = directory / name
        write_new(path, raw)
        manifest[name] = {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}
    assert len(manifest) == 41 and sum(item['bytes'] for item in manifest.values()) < 13 * 1024**2
    path = directory / 'manifest.json'
    raw = wire({'schema': 'authored-compact-trained-inference-fixture/v2', 'artifacts': manifest})
    write_new(path, raw)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {'path': str(path), 'sha256': sha(raw)}


@pytest.fixture(scope='module')
def inference(retained, no_optimizer_or_training, tmp_path_factory):
    case = retained
    before = deepcopy((case['checkpoint'], case['conditioning'], case['context_raw']))
    directory = tmp_path_factory.mktemp('compact-trained-inference-v2', numbered=False)
    events, active = [], {'phase': None, 'prefix': [1]}
    real_forward, real_gru = subject._forward, torch.nn.GRU.forward

    def observed_gru(model, input, *values, **options):
        result = real_gru(model, input, *values, **options)
        output = result[0]
        kind = 'independent_reference' if active['phase'].startswith('reference_') else 'trained_runtime'
        events.append({'event': 'gru_forward', 'kind': kind, 'phase': active['phase'],
            'prefix_ids': list(active['prefix']), 'input_shape': list(input.shape),
            'output_shape': list(output.shape), 'gru_output_sha256': digest(output.detach().tolist())})
        return result

    def observed_forward(checkpoint, conditioning, prefix_ids):
        assert checkpoint['weights_sha256'] == case['checkpoint']['weights_sha256']
        active['prefix'] = list(prefix_ids)
        result = real_forward(checkpoint, conditioning, prefix_ids)
        events.append({'event': 'trained_forward', 'phase': active['phase'], 'prefix_ids': list(prefix_ids),
            'checkpoint_sha256': digest(checkpoint), 'weights_sha256': checkpoint['weights_sha256'],
            'conditioning_sha256': digest(conditioning), 'logits_sha256': digest(result['logits']),
            'output_shape': result['output_shape']})
        return result

    values, options = args(case), generation_options(case)
    population_raw, references_raw = evaluation_material(case)
    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(subject, '_forward', observed_forward)
        patch.setattr(torch.nn.GRU, 'forward', observed_gru)
        active['phase'] = 'reference_trained'
        trained_reference = independent_logits(case['checkpoint'], values[1], values[2])
        active['phase'] = 'reference_initial'
        initial_reference = independent_logits(case['values']['initial-parent-v1.json'], values[1], values[2])
        active['phase'] = 'score'
        score = subject.score_compact_content_trained_v2(*values, **score_options(case))
        active['phase'] = 'generation'
        generated = subject.generate_compact_content_trained_v2(*values, **options)
        active['phase'] = 'generation_replay'
        replay = subject.validate_compact_content_trained_generation_v2(generated, *values,
            expected_report_sha256=digest(generated), **options)
        active['phase'] = 'batch_replay'
        adapted = subject.prepare_compact_content_trained_batch_prediction_v2(generated, *values, population_raw,
            expected_generation_sha256=digest(generated), expected_population_sha256=sha(population_raw),
            occurrence_id='fictional-retention', **options)
        malformed = deepcopy(generated)
        malformed['trace'][0]['logits'][0] += 1.
        malformed['trace'][0]['logits_sha256'] = digest(malformed['trace'][0]['logits'])
        active['phase'] = 'tampered_replay'
        preceding_calls = len([event for event in events if event['event'] == 'gru_forward'])
        with pytest.raises(ValueError, match='replay') as refusal:
            subject.validate_compact_content_trained_generation_v2(malformed, *values,
                expected_report_sha256=digest(malformed), **options)
        assert len([event for event in events if event['event'] == 'gru_forward']) - preceding_calls == 2
    assert (case['checkpoint'], case['conditioning'], case['context_raw']) == before
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert no_optimizer_or_training == []
    predictions_raw = wire(adapted['predictions'])
    evaluated = batch.prepare_relational_content_token_batch_evaluation_v1(population_raw, references_raw,
        predictions_raw, expected_population_sha256=sha(population_raw),
        expected_references_sha256=sha(references_raw), expected_predictions_sha256=sha(predictions_raw))
    assert score['logits'] == trained_reference and score['logits'] != initial_reference
    assert len([event for event in events if event['event'] == 'gru_forward']) == 11
    assert len([event for event in events if event['event'] == 'trained_forward']) == 9
    assert evaluated['coverage']['expected_count'] == 2
    assert evaluated['terminal_counts']['missing'] == evaluated['terminal_counts']['unverifiable_generation'] == 1
    records = {
        'inference-inputs': {'original_fixture': {'path': str(case['manifest_path']), 'sha256': FIXTURE_SHA},
            'checkpoint_file': 'prior-training-resumed-checkpoint.json', 'checkpoint_sha256': CHECKPOINT_SHA,
            'context_file': 'prior-training-fictional-retention-context.json',
            'source_file': 'prior-training-fictional-retention-source.txt',
            'conditioning': values[1], 'conditioning_sha256': digest(values[1]),
            'prefix_ids': [1], 'context_sha256': sha(case['context_raw']), **options},
        'independent-logits': {'trained': {'logits': trained_reference, 'weights_sha256': case['checkpoint']['weights_sha256']},
            'initial': {'logits': initial_reference, 'weights_sha256': case['checkpoint']['initial_weights_sha256']},
            'maximum_absolute_difference': max(abs(a - b) for a, b in zip(trained_reference, initial_reference)),
            'prefix_ids': [1], 'conditioning_sha256': digest(values[1]),
            'independent_reference_model': 'separate torch.nn.GRU and functional linear/embedding from retained tensors'},
        'score': score, 'generation': generated, 'generation-replay': replay,
        'batch-adapter': adapted, 'evaluation-population': json.loads(population_raw),
        'evaluation-references': json.loads(references_raw), 'batch-evaluation': evaluated,
        'tampered-generation': malformed, 'tampered-replay-refusal': {'expected_report_sha256': digest(malformed),
            'type': type(refusal.value).__name__, 'message': str(refusal.value),
            'actual_trained_replay_forwards': 2, 'rejected': True},
        'scope': {'actual_gru_forward_count': 11, 'trained_runtime_forward_count': 9,
            'independent_reference_forward_count': 2, 'optimizer_allocations': 0, 'optimizer_updates': 0,
            'original_recorded_checkpoint_steps': 2, 'original_training_fixture_updates': 4,
            'scores_equal_trained_reference': True, 'scores_differ_initial': True,
            'original_training_rerun': False, 'source_encoder_verified': False, 'heldout_evaluated': False,
            'statutory_meaning_verified': False, 'complete_free_running_formula_generated': False,
            'population_count': 2, 'prediction_rows': 1, 'missing_rows': 1,
            'teacher_forcing': False, 'target_access_in_bos_generation': False,
            'contexts_from_independent_retained_catalog': True,
            'training_mask': 0, 'evaluation_gold_mask': 0, 'numeric_event_counters_are_overlapping': True}}
    manifest = retain_evidence(case, records, events, directory)
    return {'records': records, 'events': events, 'manifest': manifest}


def test_retained_trained_weights_score_exactly_like_independent_gru_and_continue_without_training(
        retained, inference, record_property):
    record_property('compact_trained_inference_fixture', json.dumps(inference['manifest'], sort_keys=True))
    records, events = inference['records'], inference['events']
    score, generated = records['score'], records['generation']
    reference = records['independent-logits']
    assert score['schema'] == 'legal-compact-content-head-score/v2'
    assert len(score['logits']) == 537 and all(math.isfinite(value) for value in score['logits'])
    assert score['logits'] == reference['trained']['logits']
    assert score['logits'] != reference['initial']['logits']
    assert math.isfinite(reference['maximum_absolute_difference']) and reference['maximum_absolute_difference'] > 0
    assert score['status'] == 'scored' and score['runtime_verified'] is True
    assert score['optimizer_constructed'] is score['optimizer_state_restored'] is score['optimizer_executed'] is False
    assert score['logits_sha256'] == digest(score['logits'])
    allowed = score['prefix_report']['allowed_token_ids']
    chosen = min(allowed, key=lambda index: (-score['logits'][index], index))
    assert score['selection']['selected_token_id'] == chosen
    assert score['selection']['logits'] == score['logits']
    assert generated['schema'] == 'legal-compact-content-generation/v2'
    assert generated['status'] == 'step_budget_exhausted' and generated['reason'] == 'max_new_tokens_reached'
    assert generated['numerical_forward_count'] == generated['score_call_count'] == generated['emitted_token_count'] == 2
    assert generated['initial_prefix_ids'] == [1] and generated['generated_ids'] == [1] + generated['selected_token_ids']
    assert generated['trace'][0] == score
    assert generated['trace'][1]['prefix_ids'] == score['next_prefix_ids']
    assert generated['final_decoding']['status'] == 'incomplete'
    assert generated['exposure']['teacher_forcing'] is generated['exposure']['target_access'] is False
    assert generated['exposure']['source_encoder_authenticated'] is False and generated['exposure']['encoder_sha256'] is None
    assert generated['optimizer_constructed'] is generated['optimizer_state_restored'] is False
    assert generated['training_executed'] is generated['compact_optimizer_executed'] is False
    assert inference['records']['generation-replay'] == generated
    assert subject.compact_content_trained_generation_sha256(generated) == digest(generated)
    for value in (score, generated):
        assert value['checkpoint_sha256'] == CHECKPOINT_SHA
        assert value['weights_sha256'] == retained['checkpoint']['weights_sha256']
        assert value['compact_training_steps'] == 2 and value['training_progress'] == retained['checkpoint']['progress']
        for key in ('initial_checkpoint_sha256', 'initial_weights_sha256', 'parent_checkpoint_sha256'):
            assert value[key] == retained['checkpoint'][key]
        no_authority(value)
    grus = [event for event in events if event['event'] == 'gru_forward']
    forwards = [event for event in events if event['event'] == 'trained_forward']
    assert len(grus) == 11 and len(forwards) == 9
    assert Counter(event['kind'] for event in grus) == {'independent_reference': 2, 'trained_runtime': 9}
    assert Counter(event['phase'] for event in grus) == {'reference_trained': 1, 'reference_initial': 1,
        'score': 1, 'generation': 2, 'generation_replay': 2, 'batch_replay': 2, 'tampered_replay': 2}
    for event in forwards:
        assert event['checkpoint_sha256'] == CHECKPOINT_SHA
        assert event['weights_sha256'] == retained['checkpoint']['weights_sha256']
        assert event['conditioning_sha256'] == digest(retained['conditioning'])
    assert all(event['input_shape'] == [1, len(event['prefix_ids']), 8] for event in grus)


def test_complete_two_row_population_retains_one_missing_and_one_unverifiable_observation(inference):
    records = inference['records']
    adapted, evaluated = records['batch-adapter'], records['batch-evaluation']
    assert adapted['schema'] == 'legal-compact-content-generation-batch-prediction/v2'
    assert adapted['population_sha256'] == digest(records['evaluation-population'])
    assert len(records['evaluation-population']['rows']) == 2 and len(adapted['predictions']['rows']) == 1
    assert adapted['predictions']['generation']['encoder_sha256'] is None
    assert evaluated['coverage']['expected_count'] == 2
    assert evaluated['terminal_counts']['missing'] == evaluated['terminal_counts']['unverifiable_generation'] == 1
    assert sum(evaluated['terminal_counts'].values()) == 2
    no_authority(adapted)


def test_rehashed_tampered_trace_was_replayed_twice_and_rejected(inference):
    records = inference['records']
    refusal, malformed = records['tampered-replay-refusal'], records['tampered-generation']
    assert refusal['rejected'] is True and refusal['actual_trained_replay_forwards'] == 2
    assert refusal['expected_report_sha256'] == digest(malformed)
    assert malformed['trace'][0]['logits'] != records['generation']['trace'][0]['logits']
    assert 'replay' in refusal['message']


def forbid_models(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('structural or terminal inference allocated/restored a numerical model')
    original_owners = head._owners
    def pure_owners(*, numeric=False, transfer=False):
        assert numeric is False and transfer is False, 'terminal path requested numerical/transfer owners'
        return original_owners(numeric=False, transfer=False)
    monkeypatch.setattr(head, '_owners', pure_owners)
    monkeypatch.setattr(torch.nn.Module, '__init__', forbidden)
    monkeypatch.setattr(numerical, '_model', forbidden)
    monkeypatch.setattr(numerical, '_tensor', forbidden)
    monkeypatch.setattr(head, 'validate_compact_content_head_v1', forbidden)
    monkeypatch.setattr(trainer, 'validate_compact_content_training_v2', forbidden)
    monkeypatch.setattr(subject, '_forward', forbidden)


def test_structural_inspection_returns_exact_checkpoint_without_model_or_optimizer(retained, monkeypatch):
    forbid_models(monkeypatch)
    checkpoint = retained['checkpoint']
    assert subject.inspect_compact_content_trained_checkpoint_v2(checkpoint,
        expected_checkpoint_sha256=CHECKPOINT_SHA) == checkpoint
    with pytest.raises(ValueError):
        parent = retained['values']['initial-parent-v1.json']
        subject.inspect_compact_content_trained_checkpoint_v2(parent, expected_checkpoint_sha256=digest(parent))


def test_runtime_declaration_is_structural_until_live_runtime_check_before_model(retained, monkeypatch):
    checkpoint = deepcopy(retained['checkpoint'])
    checkpoint['runtime']['machine'] = 'authored-declaration-different-from-live-machine'
    expected = digest(checkpoint)
    with pytest.MonkeyPatch.context() as pure:
        forbid_models(pure)
        assert subject.inspect_compact_content_trained_checkpoint_v2(checkpoint,
            expected_checkpoint_sha256=expected) == checkpoint
    def forbidden(*args, **kwargs):
        pytest.fail('runtime mismatch reached model allocation, tensor restore, or GRU forward')
    monkeypatch.setattr(numerical, '_model', forbidden)
    monkeypatch.setattr(numerical, '_tensor', forbidden)
    monkeypatch.setattr(torch.nn.Module, '__init__', forbidden)
    monkeypatch.setattr(torch.nn.GRU, 'forward', forbidden)
    before = deepcopy(checkpoint)
    with pytest.raises(ValueError, match='actual inference runtime differs'):
        subject.score_compact_content_trained_v2(*args(retained, checkpoint=checkpoint),
            **score_options(retained, checkpoint))
    assert checkpoint == before


@pytest.mark.parametrize('kind', ['complete', 'rejected'])
def test_terminal_prefix_has_no_model_scores_or_verified_runtime(retained, monkeypatch, kind):
    forbid_models(monkeypatch)
    prefix = retained['values']['fictional-retention-target-encoding.json']['target_ids'] if kind == 'complete' else [1, 2]
    values = args(retained, prefix=prefix)
    score = subject.score_compact_content_trained_v2(*values, **score_options(retained))
    report = subject.generate_compact_content_trained_v2(*values, **{
        **generation_options(retained), 'prefix_origin': 'target_derived_label' if kind == 'complete' else 'caller_supplied_unverified'})
    assert score['status'] == 'no_forward' and score['runtime_verified'] is False
    assert score['numerical_forward_executed'] is score['model_restore_performed'] is False
    assert score['logits'] is score['logits_sha256'] is score['selection'] is score['output_shape'] is None
    assert report['runtime_verified'] is report['model_executed'] is False
    assert report['numerical_forward_count'] == report['emitted_token_count'] == 0
    assert report['status'] == ('supplied_complete' if kind == 'complete' else 'blocked')
    if kind == 'complete':
        assert report['exposure']['teacher_forcing'] is report['exposure']['target_access'] is True
    no_authority(score)
    no_authority(report)


@pytest.mark.parametrize('mutation', ['current_weights_pin', 'initial_parent_pin', 'progress', 'missing_moment',
    'moment_step', 'negative_second_moment', 'optimizer_policy', 'model_shape', 'authority'])
def test_corrupt_checkpoint_refused_by_pure_inspection(retained, monkeypatch, mutation):
    forbid_models(monkeypatch)
    checkpoint = deepcopy(retained['checkpoint'])
    moments = checkpoint['optimizer_state']['parameters']
    first = next(iter(moments))
    if mutation == 'current_weights_pin':
        checkpoint['weights_sha256'] = '0' * 64
    elif mutation == 'initial_parent_pin':
        checkpoint['initial_checkpoint_sha256'] = '0' * 64
    elif mutation == 'progress':
        checkpoint['progress']['row_cursor'] = 1
    elif mutation == 'missing_moment':
        del moments[first]
    elif mutation == 'moment_step':
        moments[first]['step'] += 1
    elif mutation == 'negative_second_moment':
        value = moments[first]['exp_avg_sq']
        while isinstance(value[0], list):
            value = value[0]
        value[0] = -.125
    elif mutation == 'optimizer_policy':
        checkpoint['optimizer_policy']['defaults']['foreach'] = True
    elif mutation == 'model_shape':
        checkpoint['model_state']['output.bias'].pop()
        checkpoint['weights_sha256'] = digest(checkpoint['model_state'])
    else:
        checkpoint['authority'][next(iter(checkpoint['authority']))] = True
    with pytest.raises(ValueError):
        subject.inspect_compact_content_trained_checkpoint_v2(checkpoint, expected_checkpoint_sha256=digest(checkpoint))


@pytest.mark.parametrize('mutation', ['checkpoint_pin', 'context_pin', 'conditioning_dimension', 'nonfinite_conditioning',
    'prefix_type', 'step_budget', 'origin'])
def test_bad_call_bindings_refuse_before_numerical_dispatch(retained, monkeypatch, mutation):
    forbid_models(monkeypatch)
    values, options = list(args(retained)), generation_options(retained)
    if mutation == 'checkpoint_pin':
        options['expected_checkpoint_sha256'] = '0' * 64
    elif mutation == 'context_pin':
        options['expected_context_sha256'] = '0' * 64
    elif mutation == 'conditioning_dimension':
        values[1].append(0.)
    elif mutation == 'nonfinite_conditioning':
        values[1][0] = float('nan')
    elif mutation == 'prefix_type':
        values[2] = [True]
    elif mutation == 'step_budget':
        options['max_new_tokens'] = 0
    else:
        options['context_origin'] = 'verified_statutory_permission'
    with pytest.raises(ValueError):
        subject.generate_compact_content_trained_v2(*values, **options)
