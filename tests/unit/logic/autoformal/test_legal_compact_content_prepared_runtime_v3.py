"""Prepared-runtime mechanics against the original installed v2 consumer.

No training or statutory reconstruction claim. The exposed retained two-step
checkpoint stays fixed. The bounded cohort enrolls57 actual GRU calls, including
seven faulted one-forward operations. Old64-token reconstruction outcomes are
not rerun or revised. Product modules are imported only by the owned runner.
"""
from collections import Counter
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import time

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as baseline
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_prepared_runtime_v3 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

# Reuse the qualified source's strict original27-file joins and no-optimizer
# fixtures. Execute these exact checked source bytes, never a pyc or package root.
SUPPORT_PATH = Path('/home/barberb/lift_coding/external/ipfs_datasets/tests/unit/logic/autoformal/test_legal_compact_trained_reconstruction_v2.py')
SUPPORT_SHA = '12effc09ea6a0cf245e271f06c3eef68b85095cddc46835bf8193424d8a9c894'
import hashlib
_support_raw = SUPPORT_PATH.read_bytes()
assert hashlib.sha256(_support_raw).hexdigest() == SUPPORT_SHA
_support_spec = importlib.util.spec_from_file_location('_prepared_runtime_retained_support', SUPPORT_PATH)
_support = importlib.util.module_from_spec(_support_spec)
exec(compile(_support_raw, str(SUPPORT_PATH), 'exec'), _support.__dict__)
assert SUPPORT_PATH.read_bytes() == _support_raw
retained = _support.retained
no_optimizer_or_training = _support.no_optimizer_or_training
wire, sha, digest = _support.wire, _support.sha, _support.digest
no_authority = _support.no_authority
CHECKPOINT_SHA, FIXTURE_SHA = _support.CHECKPOINT_SHA, _support.FIXTURE_SHA
ROW_IDS = _support.ROW_IDS

GENERATION_CASES = (
    ('retention_bos2', 0, 'bos', 2),
    ('inspection_bos12', 1, 'bos', 12),
    ('retention_modal3', 0, 'modal', 3),
    ('inspection_modal3', 1, 'modal', 3),
)
MUTATIONS = ('caller_checkpoint', 'caller_vector', 'caller_prefix', 'prepared_state',
             'live_runtime', 'ambient_rng', 'source_witness')
BAD_BINDINGS = ('checkpoint_pin', 'context_pin', 'vector_nan', 'model_shape', 'zero_budget', 'invalid_origin')


def arguments(case, row_index, kind='bos', steps=2):
    row = case['rows'][row_index]
    prefix = [1] if kind == 'bos' else case['values'][row['id'] + '-target-encoding.json']['target_ids'][:21]
    context = case['bodies'][row['context_file']]
    values = [deepcopy(case['checkpoint']), deepcopy(row['conditioning']), list(prefix), context]
    options = {'expected_checkpoint_sha256': CHECKPOINT_SHA, 'expected_context_sha256': sha(context),
        'max_new_tokens': steps, 'prefix_origin': 'bos_seed' if kind == 'bos' else 'target_derived_label',
        'context_origin': 'caller_supplied_unverified'}
    return values, options


def score_options(options):
    return {key: options[key] for key in ('expected_checkpoint_sha256', 'expected_context_sha256')}


def score_semantics(report):
    value = deepcopy(report)
    for key in ('schema', 'profile', 'owner_pins', 'limitations', 'preparation',
                'prepared_model_reused', 'model_restore_performed'):
        value.pop(key, None)
    return value


def generation_semantics(report):
    value = deepcopy(report)
    for key in ('schema', 'profile', 'owner_pins', 'limitations', 'preparation'):
        value.pop(key, None)
    value['trace'] = [score_semantics(step) for step in value['trace']]
    return value


def check_preparation(report, restores):
    preparation = report['preparation']
    assert preparation['checkpoint_inspection_count'] == 1
    assert preparation['model_restore_count'] == restores
    assert preparation['scope'] == 'enclosing_public_operation'
    assert preparation['full_prefix_each_step'] is True
    assert preparation['cross_call_model_cache'] is preparation['incremental_hidden_state'] is False


def model_globals(module):
    """Only inspect bounded plain containers; never traverse imported modules."""
    found, seen = [], set()
    def visit(value, path, depth):
        if isinstance(value, (torch.nn.Module, subject._PreparedModel)):
            found.append(path)
        elif depth < 3 and type(value) in (dict, list, tuple) and id(value) not in seen:
            seen.add(id(value))
            iterable = value.items() if type(value) is dict else enumerate(value)
            for key, child in iterable:
                visit(child, path + '/' + str(key), depth + 1)
    for name, value in vars(module).items():
        if name != '__builtins__':
            visit(value, name, 0)
    return found


@pytest.fixture(scope='module')
def differential(retained, no_optimizer_or_training, tmp_path_factory):
    case = retained
    directory = tmp_path_factory.mktemp('prepared-runtime-v3', numbered=False)
    events, calls, models = [], {}, []
    active = {'case': None, 'mode': None, 'prefix': None, 'mutate': None, 'mutation_done': False}
    real_model = numerical._model
    real_inspect = baseline._inspect
    real_load = torch.nn.Module.load_state_dict
    real_embedding = torch.nn.Embedding.forward
    real_gru = torch.nn.GRU.forward
    parent_before = wire(case['checkpoint'])
    rng_before = torch.get_rng_state().clone()
    global_before = model_globals(subject)
    assert global_before == []

    def event(kind, **fields):
        value = {'sequence': len(events), 'event': kind, 'case': active['case'], 'mode': active['mode'], **fields}
        events.append(value)
        return value

    def observed_model(*values, **options):
        model = real_model(*values, **options)
        models.append(model)  # Test-owned references prevent Python ID reuse.
        event('model_constructed', model_identity=len(models) - 1)
        return model

    def observed_inspect(*values, **options):
        result = real_inspect(*values, **options)
        event('checkpoint_inspected')
        return result

    def observed_load(model, *values, **options):
        result = real_load(model, *values, **options)
        if any(model is known for known in models):
            event('model_weights_loaded', model_identity=next(i for i, known in enumerate(models) if model is known),
                  weights_sha256=digest({key: value.detach().tolist() for key, value in model.state_dict().items()}))
        return result

    def observed_embedding(model, ids):
        assert list(ids.shape)[0] == 1
        prefix = ids.detach().tolist()[0]
        active['prefix'] = prefix
        event('full_prefix_embedding', prefix_ids=prefix, shape=list(ids.shape))
        return real_embedding(model, ids)

    def observed_gru(model, inputs, *values, **options):
        started = time.perf_counter()
        result = real_gru(model, inputs, *values, **options)
        elapsed = time.perf_counter() - started
        event('gru_forward', prefix_ids=list(active['prefix']), input_shape=list(inputs.shape),
            output_shape=list(result[0].shape), output_sha256=digest(result[0].detach().tolist()),
            elapsed_seconds=elapsed, clock_scope='single GRU call excluding observation serialization')
        if active['mutate'] is not None and not active['mutation_done']:
            active['mutation_done'] = True
            active['mutate']()
            event('mutation_injected')
        return result

    def run(name, mode, function, values, options, *, mutation=None):
        active.update(case=name, mode=mode, prefix=None, mutate=mutation, mutation_done=False)
        start_event = len(events)
        # This test-only before/after comparison permits the deliberately offered
        # NaN refusal input. It is not a public JSON/checkpoint commitment.
        def offered_snapshot():
            def transport(value):
                if type(value) is bytes:
                    return {'transport_type': 'bytes', 'hex': value.hex()}
                raise TypeError('unexpected test input observation type')
            return json.dumps({'values': values, 'options': options}, default=transport,
                sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=True)
        before = offered_snapshot()
        rng = torch.get_rng_state().clone()
        event('public_call_started')
        started = time.perf_counter()
        report, error = None, None
        try:
            report = function(*values, **options)
        except ValueError as caught:
            error = {'type': type(caught).__name__, 'message': str(caught)}
        elapsed = time.perf_counter() - started
        event('public_call_completed', failed=error is not None)
        selected = events[start_event:]
        count = Counter(item['event'] for item in selected)
        after = offered_snapshot()
        record = {'name': name, 'mode': mode, 'report': report, 'error': error,
            'elapsed_seconds': elapsed, 'clock_scope': 'public API including nested event accounting; excludes final evidence serialization',
            'gru_forward_count': count['gru_forward'], 'model_restore_count': count['model_weights_loaded'],
            'model_construction_count': count['model_constructed'],
            'checkpoint_inspection_count': count['checkpoint_inspected'],
            'embedding_inputs': [item['prefix_ids'] for item in selected if item['event'] == 'full_prefix_embedding'],
            'model_identities': [item['model_identity'] for item in selected if item['event'] == 'model_constructed'],
            'inputs_unchanged': before == after, 'rng_unchanged': bool(torch.equal(rng, torch.get_rng_state())),
            'mutation_injected': active['mutation_done']}
        calls[name] = record
        return record

    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(numerical, '_model', observed_model)
        observe.setattr(baseline, '_inspect', observed_inspect)
        observe.setattr(torch.nn.Module, 'load_state_dict', observed_load)
        observe.setattr(torch.nn.Embedding, 'forward', observed_embedding)
        observe.setattr(torch.nn.GRU, 'forward', observed_gru)
        for label, row, prefix, steps in GENERATION_CASES:
            for mode, function in (('v2', baseline.generate_compact_content_trained_v2),
                                   ('v3', subject.generate_compact_content_prepared_v3)):
                values, options = arguments(case, row, prefix, steps)
                run(label + '_' + mode, mode, function, values, options)
        for row in range(2):
            for mode, function in (('v2', baseline.score_compact_content_trained_v2),
                                   ('v3', subject.score_compact_content_prepared_v3)):
                values, options = arguments(case, row, 'modal', 1)
                run('score_' + str(row) + '_' + mode, mode, function, values, score_options(options))
        values, options = arguments(case, 0, 'bos', 2)
        run('fresh_operation_v3', 'v3', subject.generate_compact_content_prepared_v3, values, options)
        original_report = calls['retention_bos2_v3']['report']
        assert original_report is not None
        population = {'schema': 'legal-relational-batch-population/v1',
            'partition': 'exposed-authored-training-fixtures-prepared-runtime',
            'selection_sha256': sha(b'both retained authored training groups; no result-based population selection'),
            'rows': [{key: row[key] for key in ('id', 'source_sha256', 'context_sha256')} for row in case['population']]}
        population_raw = wire(population)
        values, options = arguments(case, 0, 'bos', 2)
        run('public_replay_v3', 'v3', subject.validate_compact_content_prepared_generation_v3,
            [deepcopy(original_report), *values], {**options, 'expected_report_sha256': digest(original_report)})
        values, options = arguments(case, 0, 'bos', 2)
        run('batch_replay_v3', 'v3', subject.prepare_compact_content_prepared_batch_prediction_v3,
            [deepcopy(original_report), *values, population_raw], {**options,
                'expected_generation_sha256': digest(original_report), 'expected_population_sha256': sha(population_raw),
                'occurrence_id': ROW_IDS[0]})

        for kind in MUTATIONS:
            values, options = arguments(case, 0, 'bos', 2)
            original_rng = torch.get_rng_state().clone()
            original_mkldnn = torch.backends.mkldnn.enabled
            source_changed = [False]
            original_sources = subject._sources
            def changed_sources():
                root, observed = original_sources()
                if source_changed[0]:
                    descriptor, witness = observed[0]
                    observed = [(descriptor, (*witness[:-1], witness[-1] + 1)), *observed[1:]]
                return root, observed
            def mutate():
                if kind == 'caller_checkpoint':
                    values[0]['model_state']['output.bias'][0] += .125
                elif kind == 'caller_vector':
                    values[1][0] += .125
                elif kind == 'caller_prefix':
                    values[2].append(2)
                elif kind == 'prepared_state':
                    with torch.no_grad():
                        models[-1].output.bias[0].add_(.125)
                elif kind == 'live_runtime':
                    torch.backends.mkldnn.enabled = not original_mkldnn
                elif kind == 'ambient_rng':
                    torch.rand(1)
                else:
                    source_changed[0] = True
            try:
                with pytest.MonkeyPatch.context() as fault:
                    if kind == 'source_witness':
                        fault.setattr(subject, '_sources', changed_sources)
                    run('mutation_' + kind, 'v3', subject.generate_compact_content_prepared_v3,
                        values, options, mutation=mutate)
            finally:
                torch.backends.mkldnn.enabled = original_mkldnn
                torch.set_rng_state(original_rng)

        def forbidden(*args, **kwargs):
            pytest.fail('terminal/refused operation requested numerical execution')
        with pytest.MonkeyPatch.context() as pure:
            pure.setattr(numerical, '_model', forbidden)
            pure.setattr(numerical, '_tensor', forbidden)
            pure.setattr(torch.nn.GRU, 'forward', forbidden)
            pure.setattr(subject, '_PreparedModel', forbidden)
            for kind in ('complete', 'rejected'):
                values, options = arguments(case, 0, 'bos', 2)
                values[2] = list(case['values']['fictional-retention-target-encoding.json']['target_ids']) if kind == 'complete' else [1, 2]
                options['prefix_origin'] = 'target_derived_label' if kind == 'complete' else 'caller_supplied_unverified'
                run('terminal_' + kind, 'v3', subject.generate_compact_content_prepared_v3, values, options)
                run('terminal_score_' + kind, 'v3', subject.score_compact_content_prepared_v3, values, score_options(options))
            for kind in BAD_BINDINGS:
                values, options = arguments(case, 0, 'bos', 2)
                if kind == 'checkpoint_pin':
                    options['expected_checkpoint_sha256'] = '0' * 64
                elif kind == 'context_pin':
                    options['expected_context_sha256'] = '0' * 64
                elif kind == 'vector_nan':
                    values[1][0] = float('nan')
                elif kind == 'model_shape':
                    values[0]['model_state']['output.bias'].pop()
                    values[0]['weights_sha256'] = digest(values[0]['model_state'])
                    options['expected_checkpoint_sha256'] = digest(values[0])
                elif kind == 'zero_budget':
                    options['max_new_tokens'] = 0
                else:
                    options['context_origin'] = 'verified_legal_authority'
                run('binding_' + kind, 'v3', subject.generate_compact_content_prepared_v3, values, options)
            for kind in ('validator', 'adapter'):
                values, options = arguments(case, 0, 'bos', 2)
                if kind == 'validator':
                    run('replay_binding_' + kind, 'v3', subject.validate_compact_content_prepared_generation_v3,
                        [deepcopy(original_report), *values], {**options, 'expected_report_sha256': '0' * 64})
                else:
                    run('replay_binding_' + kind, 'v3', subject.prepare_compact_content_prepared_batch_prediction_v3,
                        [deepcopy(original_report), *values, population_raw], {**options,
                            'expected_generation_sha256': '0' * 64, 'expected_population_sha256': sha(population_raw),
                            'occurrence_id': ROW_IDS[0]})

    assert no_optimizer_or_training == []
    assert wire(case['checkpoint']) == parent_before
    assert torch.equal(rng_before, torch.get_rng_state())
    global_after = model_globals(subject)
    assert global_after == []
    event_counts = Counter(row['event'] for row in events)
    input_artifacts = {name: descriptor for name, descriptor in case['manifest']['artifacts'].items()}
    parity = {'generation': {}, 'score': {}}
    for label, _, _, _ in GENERATION_CASES:
        left, right = calls[label + '_v2']['report'], calls[label + '_v3']['report']
        parity['generation'][label] = left is not None and right is not None and generation_semantics(left) == generation_semantics(right)
    for row in range(2):
        left, right = calls['score_' + str(row) + '_v2']['report'], calls['score_' + str(row) + '_v3']['report']
        parity['score'][str(row)] = left is not None and right is not None and score_semantics(left) == score_semantics(right)
    evidence = {'schema': 'legal-compact-prepared-runtime-differential/v3',
        'original_fixture': {'path': str(case['manifest_path']), 'bytes': len(case['manifest_raw']), 'sha256': FIXTURE_SHA},
        'input_artifacts': input_artifacts, 'checkpoint_sha256': CHECKPOINT_SHA,
        'support_source': {'path': str(SUPPORT_PATH), 'bytes': len(_support_raw), 'sha256': SUPPORT_SHA},
        'generation_cases': [list(row) for row in GENERATION_CASES], 'calls': calls, 'events': events,
        'exact_parity': parity,
        'batch_population': population, 'batch_population_sha256': sha(population_raw),
        'counts': {'actual_gru_forwards': event_counts['gru_forward'], 'actual_model_constructions': event_counts['model_constructed'],
            'actual_model_restores': event_counts['model_weights_loaded'], 'expected_gru_forwards': 57,
            'expected_model_restores': 38, 'optimizer_allocations': 0, 'optimizer_updates': 0},
        'scope': {'parent_unchanged': True, 'rng_restored_after_fault_controls': True,
            'module_global_models_before': global_before, 'module_global_models_after': global_after,
            'source_witness_fault_simulated': True, 'source_files_mutated': False,
            'historical_reconstruction_outcomes_revised': False, 'heldout_evaluated': False,
            'semantic_accuracy_measured': False, 'source_encoder_authenticated': False,
            'fixed_authored_training_exposure': True, 'training_mask': 0, 'evaluation_gold_mask': 0,
            'timing_scope': 'one sequential bounded mechanical comparison; no statistical throughput or reconstruction improvement claim'}}
    path = directory / 'prepared-runtime-evidence.json'
    raw = wire(evidence)
    assert len(raw) < 4 * 1024**2
    _support.write_new(path, raw)
    _support.sync_directory(directory)
    return {'value': evidence, 'descriptor': {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}}


@pytest.mark.parametrize('label,row,prefix,steps', GENERATION_CASES)
def test_full_prefix_generation_parity_restores_once(retained, differential, label, row, prefix, steps, record_property):
    if label == 'retention_bos2':
        record_property('prepared_runtime_evidence', json.dumps(differential['descriptor'], sort_keys=True))
    calls = differential['value']['calls']
    original, prepared = calls[label + '_v2'], calls[label + '_v3']
    assert original['error'] is prepared['error'] is None
    left, right = original['report'], prepared['report']
    assert generation_semantics(left) == generation_semantics(right)
    assert left['numerical_forward_count'] == right['numerical_forward_count'] == steps
    assert original['gru_forward_count'] == prepared['gru_forward_count'] == steps
    assert original['model_restore_count'] == original['model_construction_count'] == steps
    assert prepared['model_restore_count'] == prepared['model_construction_count'] == 1
    assert prepared['checkpoint_inspection_count'] == 1 and original['checkpoint_inspection_count'] == steps
    check_preparation(right, 1)
    expected_prefixes = [step['prefix_ids'] for step in right['trace'] if step['numerical_forward_executed']]
    assert original['embedding_inputs'] == prepared['embedding_inputs'] == expected_prefixes
    for index, (old, new) in enumerate(zip(left['trace'], right['trace'])):
        assert len(old['logits']) == len(new['logits']) == 537
        assert old['logits'] == new['logits'] and old['selection'] == new['selection']
        assert new['model_restore_performed'] is (index == 0)
        assert new['prepared_model_reused'] is (index > 0)
        if index:
            assert new['prefix_ids'] == right['trace'][index - 1]['next_prefix_ids']
        no_authority(new)
    assert original['inputs_unchanged'] is prepared['inputs_unchanged'] is True
    assert original['rng_unchanged'] is prepared['rng_unchanged'] is True
    assert all(math.isfinite(call['elapsed_seconds']) and call['elapsed_seconds'] > 0 for call in (original, prepared))
    no_authority(right)


@pytest.mark.parametrize('row', [0, 1])
def test_single_score_matches_all537_logits_and_modal_selection(differential, row):
    calls = differential['value']['calls']
    original, prepared = calls['score_' + str(row) + '_v2'], calls['score_' + str(row) + '_v3']
    assert original['error'] is prepared['error'] is None
    assert score_semantics(original['report']) == score_semantics(prepared['report'])
    for call in (original, prepared):
        assert call['gru_forward_count'] == call['model_restore_count'] == call['model_construction_count'] == 1
        assert call['checkpoint_inspection_count'] == 1
        assert len(call['report']['logits']) == 537
        assert call['report']['prefix_report']['allowed_token_ids'] == [3, 4, 5]
        assert len(call['embedding_inputs'][0]) == 21
        assert call['inputs_unchanged'] is call['rng_unchanged'] is True
    check_preparation(prepared['report'], 1)


def test_fresh_operation_does_not_reuse_global_model_or_mutate_parent(differential):
    evidence = differential['value']
    first, second = evidence['calls']['retention_bos2_v3'], evidence['calls']['fresh_operation_v3']
    assert first['report'] == second['report'] and second['error'] is None
    assert second['model_restore_count'] == second['model_construction_count'] == 1
    assert second['gru_forward_count'] == 2 and first['model_identities'] != second['model_identities']
    assert evidence['counts']['actual_gru_forwards'] == 57
    assert evidence['counts']['actual_model_restores'] == evidence['counts']['actual_model_constructions'] == 38
    assert evidence['counts']['optimizer_allocations'] == evidence['counts']['optimizer_updates'] == 0
    assert evidence['scope']['parent_unchanged'] is True
    assert evidence['scope']['module_global_models_before'] == evidence['scope']['module_global_models_after'] == []


@pytest.mark.parametrize('kind', MUTATIONS)
def test_mid_operation_mutation_is_rejected_after_one_forward(differential, kind):
    call = differential['value']['calls']['mutation_' + kind]
    assert call['report'] is None and call['error'] is not None and call['mutation_injected'] is True
    assert call['gru_forward_count'] == call['model_restore_count'] == call['model_construction_count'] == 1
    assert len(call['embedding_inputs']) == 1
    if kind.startswith('caller_'):
        assert call['inputs_unchanged'] is False
    else:
        assert call['inputs_unchanged'] is True
    if kind == 'ambient_rng':
        assert call['rng_unchanged'] is False


@pytest.mark.parametrize('kind', ['complete', 'rejected'])
def test_terminal_prefix_has_no_prepared_model_or_verified_runtime(differential, kind):
    calls = differential['value']['calls']
    for name in ('terminal_' + kind, 'terminal_score_' + kind):
        call = calls[name]
        assert call['error'] is None and call['gru_forward_count'] == call['model_restore_count'] == 0
        assert call['model_construction_count'] == 0 and call['embedding_inputs'] == []
        report = call['report']
        check_preparation(report, 0)
        assert report['runtime_verified'] is False
        no_authority(report)
    assert calls['terminal_' + kind]['report']['status'] == ('supplied_complete' if kind == 'complete' else 'blocked')
    assert calls['terminal_score_' + kind]['report']['status'] == 'no_forward'


@pytest.mark.parametrize('kind', BAD_BINDINGS)
def test_invalid_bindings_refuse_without_numerical_allocation(differential, kind):
    call = differential['value']['calls']['binding_' + kind]
    assert call['report'] is None and call['error'] is not None
    assert call['gru_forward_count'] == call['model_restore_count'] == call['model_construction_count'] == 0
    assert call['embedding_inputs'] == []


def test_public_original_input_validator_replays_with_fresh_preparation(differential):
    calls = differential['value']['calls']
    original, replay = calls['retention_bos2_v3'], calls['public_replay_v3']
    assert replay['error'] is None and replay['report'] == original['report']
    assert replay['gru_forward_count'] == 2
    assert replay['model_restore_count'] == replay['model_construction_count'] == replay['checkpoint_inspection_count'] == 1
    assert replay['model_identities'] != original['model_identities']
    assert replay['inputs_unchanged'] is replay['rng_unchanged'] is True


def test_content_adapter_replays_and_keeps_whole_population_and_missing_encoder(differential):
    evidence = differential['value']
    original, call = evidence['calls']['retention_bos2_v3'], evidence['calls']['batch_replay_v3']
    assert call['error'] is None and call['gru_forward_count'] == 2
    assert call['model_restore_count'] == call['model_construction_count'] == call['checkpoint_inspection_count'] == 1
    report = call['report']
    assert report['generation_report_sha256'] == digest(original['report'])
    assert report['population_sha256'] == evidence['batch_population_sha256']
    assert len(evidence['batch_population']['rows']) == 2
    assert len(report['predictions']['rows']) == 1 and report['prediction_row']['id'] == ROW_IDS[0]
    assert report['predictions']['generation']['encoder_sha256'] is None
    assert report['prediction_row']['generated_ids'] == original['report']['generated_ids']
    assert call['inputs_unchanged'] is call['rng_unchanged'] is True
    no_authority(report)


@pytest.mark.parametrize('kind', ['validator', 'adapter'])
def test_replay_hash_refusals_never_restore_or_forward(differential, kind):
    call = differential['value']['calls']['replay_binding_' + kind]
    assert call['report'] is None and call['error'] is not None
    assert call['gru_forward_count'] == call['model_restore_count'] == call['model_construction_count'] == 0
    assert call['embedding_inputs'] == []


def no_numerical_for_fingerprint(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('pure streaming fingerprint requested numerical work')
    monkeypatch.setattr(numerical, '_model', forbidden)
    monkeypatch.setattr(numerical, '_tensor', forbidden)
    monkeypatch.setattr(torch.nn.GRU, 'forward', forbidden)
    monkeypatch.setattr(subject, '_PreparedModel', forbidden)


def test_streaming_fingerprint_preserves_types_signed_zero_and_key_order(monkeypatch):
    no_numerical_for_fingerprint(monkeypatch)
    fingerprint = subject._fingerprint
    assert fingerprint({'b': [1, 'x'], 'a': True}) == fingerprint({'a': True, 'b': [1, 'x']})
    assert len({fingerprint(True), fingerprint(1), fingerprint(1.0)}) == 3
    assert fingerprint(0.0) != fingerprint(-0.0)
    assert fingerprint(b'x') != fingerprint('x')
    assert fingerprint([1, 2]) != fingerprint([2, 1])
    assert fingerprint({'a': [1]}) != digest({'a': [1]})  # Separate custody/public hash contracts.
    copied = subject._copy({'a': [True, 1, 1.0, -0.0, b'x']}, 128, allow_bytes=True)
    assert fingerprint(copied) == fingerprint({'a': [True, 1, 1.0, -0.0, b'x']})
    assert math.copysign(1, copied['a'][3]) == -1


@pytest.mark.parametrize('kind', ['cycle', 'subclass', 'nonfinite', 'bytes_disabled'])
def test_streaming_fingerprint_refuses_non_plain_or_disabled_values(monkeypatch, kind):
    no_numerical_for_fingerprint(monkeypatch)
    options = {}
    if kind == 'cycle':
        value = []
        value.append(value)
    elif kind == 'subclass':
        class NotPlain(dict):
            pass
        value = NotPlain(a=1)
    elif kind == 'nonfinite':
        value = float('nan')
    else:
        value, options = b'x', {'allow_bytes': False}
    with pytest.raises(ValueError):
        subject._fingerprint(value, **options)
    with pytest.raises(ValueError):
        subject._copy(value, 128, allow_bytes=options.get('allow_bytes', True))


@pytest.mark.parametrize('kind', ['bytes', 'items', 'depth'])
def test_streaming_fingerprint_enforces_exact_small_budget_boundaries(monkeypatch, kind):
    no_numerical_for_fingerprint(monkeypatch)
    if kind == 'bytes':
        assert subject._fingerprint('x', maximum=3)
        assert subject._copy('x', 3) == 'x'
        with pytest.raises(ValueError):
            subject._fingerprint('xx', maximum=3)
        with pytest.raises(ValueError):
            subject._copy('xx', 3)
    elif kind == 'items':
        monkeypatch.setattr(subject, 'MAX_JSON_ITEMS', 3)
        assert subject._fingerprint([None, None], maximum=64)
        assert subject._copy([None, None], 64) == [None, None]
        with pytest.raises(ValueError):
            subject._fingerprint([None, None, None], maximum=64)
        with pytest.raises(ValueError):
            subject._copy([None, None, None], 64)
    else:
        monkeypatch.setattr(subject, 'MAX_JSON_DEPTH', 1)
        assert subject._fingerprint([None], maximum=64)
        assert subject._copy([None], 64) == [None]
        with pytest.raises(ValueError):
            subject._fingerprint([[None]], maximum=64)
        with pytest.raises(ValueError):
            subject._copy([[None]], 64)
