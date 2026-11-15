"""Bounded reconstruction diagnostics on two exposed authored training rows.

Only the installed trained runtime is called. The retained checkpoint is never
trained. Four independent gate-equation references and at most130 actual GRU
calls are enrolled: two target-exposed modal scores plus two BOS attempts
of at most64 tokens. Correctness, completion and improvement are observations,
not test pass criteria. No source encoder, public replay or batch admission is
claimed. Inputs and completed phases survive an interrupted native attempt.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

import pytest
import torch
from torch.nn import functional as functional

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

FIXTURE_SHA = '1c4b7c37eba6870c2a746cb3e3191013a1d25906cb75427d4f7be0ca6583dab7'
CHECKPOINT_SHA = '0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0'
ROW_IDS = ('fictional-retention', 'fictional-inspection')
MAX_NEW_TOKENS = 64
TARGET_POSITION = 21
REFERENCE_RTOL, REFERENCE_ATOL = 2e-5, 2e-6
MODAL_LETTERS = ('F', 'O', 'P')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def parse(raw):
    def pairs(rows):
        value = {}
        for key, child in rows:
            assert key not in value, 'duplicate retained JSON key'
            value[key] = child
        return value
    def nonfinite(_):
        raise ValueError('nonfinite retained JSON')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)


def snapshot(path):
    assert path.is_absolute() and path.resolve(strict=True) == path
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 16 * 1024**2
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


def sync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def no_authority(value):
    assert value['authority'] and all(flag is False for flag in value['authority'].values())
    assert type(value['training_mask']) is int and value['training_mask'] == 0
    assert type(value['evaluation_gold_mask']) is int and value['evaluation_gold_mask'] == 0


@pytest.fixture(scope='module', autouse=True)
def no_optimizer_or_training():
    attempts = []
    assert torch.get_num_threads() == 1 and torch.get_num_interop_threads() == 20
    assert str(torch.__version__) == '2.13.0+cu130'
    assert str(torch.get_default_device()) == 'cpu' and torch.get_default_dtype() == torch.float32
    assert not torch.cuda.is_initialized() and not torch.is_autocast_enabled('cpu')
    def forbidden(*args, **kwargs):
        attempts.append('optimizer allocation, restoration, update, or training call')
        pytest.fail('reconstruction diagnostic attempted optimizer allocation or training')
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.optim.Optimizer, '__init__', forbidden)
        patch.setattr(torch.optim.Adam, '__init__', forbidden)
        patch.setattr(torch.optim.Adam, 'step', forbidden)
        patch.setattr(numerical, '_optimizer', forbidden)
        patch.setattr(trainer, '_restore', forbidden)
        for name in ('train_compact_content_v2', 'build_compact_content_training_v2',
                     'validate_compact_content_training_v2', 'compact_content_training_bytes_v2',
                     'load_compact_content_training_v2'):
            patch.setattr(trainer, name, forbidden)
        yield attempts


@pytest.fixture(scope='module')
def retained(no_optimizer_or_training):
    spelling = os.environ.get('LEGAL_COMPACT_TRAINED_RECONSTRUCTION_FIXTURE')
    assert spelling, 'native harness must supply the exact pinned original fixture manifest'
    path = Path(spelling)
    raw = snapshot(path)
    assert sha(raw) == FIXTURE_SHA
    manifest = parse(raw)
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
            values[name] = parse(body)
    checkpoint = values['resumed-checkpoint.json']
    assert digest(checkpoint) == sha(bodies['resumed-checkpoint.json']) == CHECKPOINT_SHA
    assert checkpoint['progress'] == {'optimizer_steps': 2, 'epochs_completed': 1, 'row_cursor': 0}
    assert checkpoint['initial_checkpoint'] == values['initial-parent-v1.json']
    assert checkpoint['weights_sha256'] != checkpoint['initial_weights_sha256']
    assert values['scope.json']['actual_optimizer_updates'] == 4  # Historical, not this attempt.
    assert checkpoint['population_raw_utf8'].encode('utf-8') == bodies['population.json']
    rows = values['input-rows.json']
    population = values['population.json']['rows']
    assert len(rows) == len(population) == 2
    assert tuple(row['id'] for row in rows) == tuple(row['id'] for row in population) == ROW_IDS
    for row, bound in zip(rows, population):
        assert row['source_group'] == bound['source_group']
        for key in ('source', 'context', 'target'):
            assert sha(bodies[row[key + '_file']]) == bound[key + '_sha256']
        assert len(row['conditioning']) == 384 and digest(row['conditioning']) == bound['conditioning_sha256']
        nomination = values[row['id'] + '-source-context-report.json']
        assert nomination['status'] == 'nominated' and nomination['source_sha256'] == bound['source_sha256']
        assert nomination['catalog_sha256'] == sha(bodies[row['id'] + '-catalog.json'])
        assert wire(nomination['context']) == bodies[row['context_file']]
        no_authority(nomination)
        encoding = values[row['id'] + '-target-encoding.json']
        assert encoding['content_sha256'] == bound['target_sha256']
        assert encoding['context_raw_sha256'] == bound['context_sha256']
        assert encoding['total_token_count'] == len(encoding['target_ids']) == 47
    return dict(manifest_path=path, manifest_raw=raw, manifest=manifest, bodies=bodies, values=values,
                checkpoint=checkpoint, rows=rows, population=population)


def manual_gate_logits(checkpoint, vector, prefix):
    """Independent reset/update/new equations; no nn.GRU or product model helper.

    Same float32 CPU equations as the prior retained-handoff candidate. Gate
    order and PyTorch reset placement are explicit; tolerance accounts for
    fused-versus-unfused arithmetic. No initializer or optimizer is called.
    """
    weights = {name: torch.tensor(value, dtype=torch.float32, device='cpu')
               for name, value in checkpoint['model_state'].items()}
    def linear(value, stem):
        return functional.linear(value, weights[stem + '.weight'], weights[stem + '.bias'])
    with torch.inference_mode():
        value = torch.tensor(vector, dtype=torch.float32, device='cpu')
        projected = value + linear(torch.tanh(linear(value, 'projection_down')), 'projection_up')
        hidden = torch.tanh(linear(projected, 'condition'))
        for token in prefix:
            embedded = weights['target_embedding.weight'][token]
            input_gates = functional.linear(embedded, weights['decoder.weight_ih_l0'], weights['decoder.bias_ih_l0'])
            hidden_gates = functional.linear(hidden, weights['decoder.weight_hh_l0'], weights['decoder.bias_hh_l0'])
            ir, iz, inn = input_gates.chunk(3)
            hr, hz, hn = hidden_gates.chunk(3)
            reset, update = torch.sigmoid(ir + hr), torch.sigmoid(iz + hz)
            candidate = torch.tanh(inn + reset * hn)
            hidden = (1 - update) * candidate + update * hidden
        output = linear(hidden, 'output')
        assert list(output.shape) == [537] and bool(torch.isfinite(output).all())
        return output.tolist()


def target_nll(logits, target, allowed=None):
    indices = list(range(len(logits))) if allowed is None else allowed
    assert target in indices and len(indices) > 1
    maximum = max(logits[index] for index in indices)
    result = maximum + math.log(math.fsum(math.exp(logits[index] - maximum) for index in indices)) - logits[target]
    assert math.isfinite(result) and result >= 0
    return result


def input_records(case):
    vocabulary = case['checkpoint']['codec']['vocabulary']
    positions = {piece: index for index, piece in enumerate(vocabulary)}
    allowed = sorted(positions[json.dumps(name)] for name in MODAL_LETTERS)
    diagnostic, bos = [], []
    for row, bound in zip(case['rows'], case['population']):
        encoding = case['values'][row['id'] + '-target-encoding.json']
        ids = encoding['target_ids']
        # Position fixed before any logits: after two forall binders, immediately
        # before its modal letter. The prefix is identical across the two rows;
        # targets P and O are different and are not supplied as prefix tokens.
        # This IS target exposure, not an assertion about learned legal meaning.
        expected_letter = 'P' if row['id'] == 'fictional-retention' else 'O'
        assert encoding['lexical_tokens'][20] == json.dumps(expected_letter)
        assert ids[TARGET_POSITION] == positions[json.dumps(expected_letter)]
        assert encoding['lexical_tokens'][:20] == ['{', '"schema"', ':',
            '"legal-relational-compact-content/v1"', ',', '"tree"', ':', '[', '"forall"', ',', '0', ',',
            '[', '"forall"', ',', '1', ',', '[', '"extension"', ',']
        prefix = ids[:TARGET_POSITION]
        assert len(prefix) == TARGET_POSITION and prefix[0] == 1
        common = {'id': row['id'], 'source_group': row['source_group'],
            'source_file': 'prior-training-' + row['source_file'], 'source_sha256': bound['source_sha256'],
            'context_file': 'prior-training-' + row['context_file'], 'context_sha256': bound['context_sha256'],
            'conditioning': deepcopy(row['conditioning']), 'conditioning_sha256': bound['conditioning_sha256'],
            'checkpoint_sha256': CHECKPOINT_SHA, 'context_origin': 'caller_supplied_unverified'}
        diagnostic.append({**common, 'prefix_ids': prefix, 'prefix_origin': 'target_derived_label',
            'teacher_forcing': True, 'target_access': True, 'target_position': TARGET_POSITION,
            'target_token_id': ids[TARGET_POSITION], 'target_token': json.dumps(expected_letter),
            'target_file': 'prior-training-' + row['target_file'], 'target_sha256': bound['target_sha256'],
            'independent_allowed_token_ids': allowed, 'target_selected_before_logits': True})
        bos.append({**common, 'prefix_ids': [1], 'prefix_origin': 'bos_seed',
                    'max_new_tokens': MAX_NEW_TOKENS, 'teacher_forcing': False, 'target_access': False})
    assert diagnostic[0]['prefix_ids'] == diagnostic[1]['prefix_ids']
    assert [row['target_token_id'] for row in diagnostic] == [5, 4]
    return diagnostic, bos


@pytest.fixture(scope='module')
def reconstruction(retained, no_optimizer_or_training, tmp_path_factory):
    case = retained
    directory = tmp_path_factory.mktemp('compact-trained-reconstruction-v2', numbered=False)
    descriptors, events, records = {}, [], {}
    active = {'row_id': None, 'phase': None, 'prefix_ids': []}
    original = wire({'checkpoint': case['checkpoint'], 'rows': case['rows']})
    rng = torch.get_rng_state().clone()

    def save_raw(name, raw):
        path = directory / name
        write_new(path, raw)
        descriptors[name] = {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}
        sync_directory(directory)

    def save(name, value):
        save_raw(name + '.json', wire(value))
        records[name] = value

    for name, raw in case['bodies'].items():
        save_raw('prior-training-' + name, raw)
    save_raw('prior-training-manifest.json', case['manifest_raw'])
    diagnostic_inputs, bos_inputs = input_records(case)
    outcomes = [{'id': row_id, 'diagnostic_status': 'not_started', 'generation_status': 'not_started'} for row_id in ROW_IDS]
    save('enrollment', {'schema': 'authored-compact-reconstruction-enrollment/v2',
        'original_fixture': {'path': str(case['manifest_path']), 'sha256': FIXTURE_SHA},
        'checkpoint_sha256': CHECKPOINT_SHA, 'population_sha256': sha(case['bodies']['population.json']),
        'rows': deepcopy(outcomes), 'max_new_tokens_per_row': MAX_NEW_TOKENS,
        'budget_basis': '64 exceeds each exposed authored training target of47 IDs including BOS; not chosen from heldout outcomes',
        'maximum_product_gru_forwards': 130, 'manual_gate_reference_evaluations': 4,
        'new_optimizer_updates': 0, 'public_replay_enrolled': False, 'batch_adapter_enrolled': False,
        'training_mask': 0, 'evaluation_gold_mask': 0})
    save('diagnostic-inputs', {'schema': 'authored-target-exposed-modal-inputs/v2', 'rows': diagnostic_inputs})
    save('bos-inputs', {'schema': 'authored-source-context-bos-inputs/v2', 'rows': bos_inputs})
    event_path = directory / 'observed-calls.jsonl'
    event_path.touch(exist_ok=False)
    sync_directory(directory)

    def observe(event, **fields):
        value = {'sequence': len(events), 'event': event, 'row_id': active['row_id'],
                 'phase': active['phase'], **fields}
        with event_path.open('ab') as stream:
            stream.write(wire(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        events.append(value)

    real_forward, real_gru = subject._forward, torch.nn.GRU.forward
    def observed_gru(model, inputs, *values, **options):
        observe('gru_forward_started', prefix_ids=list(active['prefix_ids']), input_shape=list(inputs.shape))
        started = time.perf_counter()
        result = real_gru(model, inputs, *values, **options)
        elapsed = time.perf_counter() - started
        observe('gru_forward_completed', prefix_ids=list(active['prefix_ids']), input_shape=list(inputs.shape),
            output_shape=list(result[0].shape), gru_output_sha256=digest(result[0].detach().tolist()),
            elapsed_seconds=elapsed, clock_scope='single GRU call; excludes observation serialization/fsync')
        return result

    def observed_forward(checkpoint, conditioning, prefix_ids):
        active['prefix_ids'] = list(prefix_ids)
        assert digest(checkpoint) == CHECKPOINT_SHA
        observe('trained_forward_started', prefix_ids=list(prefix_ids), conditioning_sha256=digest(conditioning))
        started = time.perf_counter()
        result = real_forward(checkpoint, conditioning, prefix_ids)
        elapsed = time.perf_counter() - started
        observe('trained_forward_completed', prefix_ids=list(prefix_ids), checkpoint_sha256=CHECKPOINT_SHA,
            weights_sha256=checkpoint['weights_sha256'], conditioning_sha256=digest(conditioning),
            logits_sha256=digest(result['logits']), output_shape=result['output_shape'], elapsed_seconds=elapsed,
            clock_scope='trained forward including nested GRU event retention; overlaps GRU clock')
        return result

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(subject, '_forward', observed_forward)
            patch.setattr(torch.nn.GRU, 'forward', observed_gru)
            # Finish and durably retain both diagnostics before either long BOS attempt.
            for index, row in enumerate(diagnostic_inputs):
                row_id = row['id']
                active.update(row_id=row_id, phase='diagnostic', prefix_ids=list(row['prefix_ids']))
                outcomes[index]['diagnostic_status'] = 'started'
                observe('phase_started', outcome_rows=deepcopy(outcomes))
                references = {}
                for label, checkpoint in (('trained', case['checkpoint']), ('initial', case['values']['initial-parent-v1.json'])):
                    active['phase'] = label + '_manual_reference'
                    observe('manual_reference_started', prefix_ids=row['prefix_ids'], weights_sha256=checkpoint['weights_sha256'])
                    started = time.perf_counter()
                    logits = manual_gate_logits(checkpoint, row['conditioning'], row['prefix_ids'])
                    elapsed = time.perf_counter() - started
                    reference = {'id': row_id, 'kind': label, 'logits': logits, 'logits_sha256': digest(logits),
                        'weights_sha256': checkpoint['weights_sha256'], 'prefix_ids': row['prefix_ids'],
                        'conditioning_sha256': row['conditioning_sha256'], 'elapsed_seconds': elapsed,
                        'clock_scope': 'independent manual gate equations; excludes event retention',
                        'reference_method': 'float32 CPU residual projection and explicit reset/update/new gates',
                        'training_mask': 0, 'evaluation_gold_mask': 0}
                    save(row_id + '-' + label + '-reference', reference)
                    observe('manual_reference_completed', reference_sha256=digest(reference), logits_sha256=digest(logits))
                    references[label] = reference
                active['phase'] = 'diagnostic_score'
                score_started = time.perf_counter()
                score = subject.score_compact_content_trained_v2(case['checkpoint'], deepcopy(row['conditioning']),
                    list(row['prefix_ids']), case['bodies'][case['rows'][index]['context_file']],
                    expected_checkpoint_sha256=CHECKPOINT_SHA, expected_context_sha256=row['context_sha256'])
                score_public_call_seconds = time.perf_counter() - score_started
                save(row_id + '-score', score)
                actual, expected = score['logits'], references['trained']['logits']
                assert len(actual) == len(expected) == 537
                torch.testing.assert_close(torch.tensor(actual), torch.tensor(expected), rtol=REFERENCE_RTOL, atol=REFERENCE_ATOL)
                allowed, target = score['prefix_report']['allowed_token_ids'], row['target_token_id']
                assert allowed == row['independent_allowed_token_ids'] and len(allowed) == 3 and target in allowed
                best = min(allowed, key=lambda token: (-actual[token], token))
                assert best == score['selection']['selected_token_id']
                all_nll, allowed_nll = target_nll(actual, target), target_nll(actual, target, allowed)
                reference_nll = target_nll(expected, target)
                torch_ce = float(functional.cross_entropy(torch.tensor([actual], dtype=torch.float32), torch.tensor([target])))
                assert math.isclose(all_nll, reference_nll, rel_tol=REFERENCE_RTOL, abs_tol=REFERENCE_ATOL)
                assert math.isclose(all_nll, torch_ce, rel_tol=REFERENCE_RTOL, abs_tol=REFERENCE_ATOL)
                initial_nll = target_nll(references['initial']['logits'], target)
                diagnostic = {'id': row_id, 'target_position': TARGET_POSITION, 'prefix_ids': row['prefix_ids'],
                    'prefix_origin': 'target_derived_label', 'teacher_forcing': True, 'target_access': True,
                    'target_token_id': target, 'target_token': row['target_token'], 'allowed_token_ids': allowed,
                    'allowed_count': len(allowed), 'selected_token_id': best, 'greedy_matches_authored_target': best == target,
                    'all_vocabulary_target_nll': all_nll, 'allowed_vocabulary_target_nll': allowed_nll,
                    'manual_trained_target_nll': reference_nll, 'torch_target_cross_entropy': torch_ce,
                    'manual_initial_target_nll': initial_nll, 'trained_minus_initial_target_nll': all_nll - initial_nll,
                    'trained_nll_lower_than_initial': all_nll < initial_nll,
                    'maximum_absolute_reference_error': max(abs(a - b) for a, b in zip(actual, expected)),
                    'reference_rtol': REFERENCE_RTOL, 'reference_atol': REFERENCE_ATOL,
                    'score_public_call_seconds': score_public_call_seconds,
                    'score_public_clock_scope': 'public score API including nested forward/event retention; excludes post-return serialization/fsync',
                    'score_sha256': digest(score), 'trained_reference_sha256': digest(references['trained']),
                    'initial_reference_sha256': digest(references['initial']),
                    'semantic_accuracy_measured': False, 'source_encoder_verified': False,
                    'training_mask': 0, 'evaluation_gold_mask': 0}
                save(row_id + '-diagnostic', diagnostic)
                outcomes[index]['diagnostic_status'] = 'recorded'
                observe('phase_completed', outcome_rows=deepcopy(outcomes), diagnostic_sha256=digest(diagnostic))
            for index, row in enumerate(bos_inputs):
                row_id = row['id']
                active.update(row_id=row_id, phase='bos_generation', prefix_ids=[1])
                outcomes[index]['generation_status'] = 'started'
                observe('phase_started', outcome_rows=deepcopy(outcomes))
                generation_started = time.perf_counter()
                generated = subject.generate_compact_content_trained_v2(case['checkpoint'], deepcopy(row['conditioning']),
                    [1], case['bodies'][case['rows'][index]['context_file']], expected_checkpoint_sha256=CHECKPOINT_SHA,
                    expected_context_sha256=row['context_sha256'], max_new_tokens=MAX_NEW_TOKENS,
                    prefix_origin='bos_seed', context_origin='caller_supplied_unverified')
                generation_public_call_seconds = time.perf_counter() - generation_started
                save(row_id + '-generation', generated)
                encoding = case['values'][row_id + '-target-encoding.json']
                decoded = generated['final_decoding']
                complete = decoded['status'] == 'valid_candidate'
                target = case['values'][case['rows'][index]['target_file']]
                outcomes[index].update(generation_status='recorded', generation_outcome=generated['status'],
                    generation_reason=generated['reason'], generated_tokens=generated['emitted_token_count'],
                    numerical_forward_count=generated['numerical_forward_count'], final_decoding_status=decoded['status'],
                    complete_formula_observed=complete, generated_ids_equal_authored_target=generated['generated_ids'] == encoding['target_ids'],
                    decoded_content_equal_authored_target=(decoded['prediction']['content'] == target) if complete else None,
                    generation_sha256=digest(generated), public_replay_verified=False,
                    generation_public_call_seconds=generation_public_call_seconds,
                    generation_public_clock_scope='public generation API including nested score/forward/event retention; excludes post-return serialization/fsync',
                    source_encoder_authenticated=False, semantic_accuracy_measured=False)
                observe('phase_completed', outcome_rows=deepcopy(outcomes), generation_sha256=digest(generated))
    except BaseException as error:
        # SIGKILL can prevent this final record; fsynced enrollment/events still
        # establish completed/started/not-started slots without inventing totals.
        for row in outcomes:
            if row['id'] == active['row_id']:
                for field in ('diagnostic_status', 'generation_status'):
                    if row[field] == 'started':
                        row[field] = 'interrupted_or_error'
        partial = {'schema': 'authored-compact-reconstruction-interruption/v2', 'rows': outcomes,
            'error_type': type(error).__name__, 'active': deepcopy(active),
            'completed_product_gru_calls': sum(event['event'] == 'gru_forward_completed' for event in events),
            'completed_manual_references': sum(event['event'] == 'manual_reference_completed' for event in events),
            'complete_population_retained': True, 'total_numeric_work_known': False}
        save('interrupted-outcomes', partial)
        raise
    assert wire({'checkpoint': case['checkpoint'], 'rows': case['rows']}) == original
    assert torch.equal(rng, torch.get_rng_state()) and no_optimizer_or_training == []
    gru = [event for event in events if event['event'] == 'gru_forward_completed']
    forwards = [event for event in events if event['event'] == 'trained_forward_completed']
    manual = [event for event in events if event['event'] == 'manual_reference_completed']
    generation_counts = {row_id: records[row_id + '-generation']['numerical_forward_count'] for row_id in ROW_IDS}
    expected_gru = 2 + sum(generation_counts.values())
    assert len(gru) == len(forwards) == expected_gru <= 130 and len(manual) == 4
    assert Counter(event['row_id'] for event in gru) == {row_id: 1 + generation_counts[row_id] for row_id in ROW_IDS}
    save('outcomes', {'schema': 'authored-compact-reconstruction-outcomes/v2', 'population_count': 2,
        'population_sha256': sha(case['bodies']['population.json']), 'rows': outcomes,
        'fixed_population_preserved': True, 'public_replay_verified': False, 'batch_adapter_executed': False,
        'heldout_evaluated': False, 'semantic_accuracy_measured': False, 'training_mask': 0, 'evaluation_gold_mask': 0})
    save('scope', {'actual_product_gru_forward_count': len(gru), 'trained_runtime_forward_count': len(forwards),
        'manual_gate_reference_evaluations': len(manual), 'maximum_product_gru_forwards': 130,
        'actual_generation_forwards_by_row': generation_counts, 'diagnostic_score_forwards': 2,
        'optimizer_allocations': 0, 'optimizer_updates': 0, 'original_recorded_checkpoint_steps': 2,
        'original_training_fixture_updates': 4, 'original_training_rerun': False,
        'source_encoder_verified': False, 'heldout_evaluated': False, 'statutory_meaning_verified': False,
        'population_count': 2, 'public_replay_verified': False, 'batch_adapter_executed': False,
        'batch_evaluator_executed': False, 'new_content_admission_claimed': False,
        'teacher_forcing_in_modal_diagnostic': True, 'target_access_in_modal_diagnostic': True,
        'target_access_in_bos_generation': False, 'contexts_from_independent_retained_catalog': True,
        'semantic_accuracy_measured': False, 'throughput_comparison_performed': False,
        'numeric_event_counters_are_overlapping': True,
        'clock_policy': 'manual, GRU, enclosing trained-forward, public API and native job clocks are separate; nested clocks are not summed',
        'training_mask': 0, 'evaluation_gold_mask': 0})
    raw_events = snapshot(event_path)
    assert [parse(line) for line in raw_events.splitlines()] == events
    descriptors['observed-calls.jsonl'] = {'path': str(event_path), 'bytes': len(raw_events), 'sha256': sha(raw_events)}
    assert len(descriptors) == 44 and sum(row['bytes'] for row in descriptors.values()) < 30 * 1024**2
    for name, raw in case['bodies'].items():
        assert snapshot(Path(case['manifest']['artifacts'][name]['path'])) == raw
    assert snapshot(case['manifest_path']) == case['manifest_raw']
    manifest = {'schema': 'authored-compact-trained-reconstruction-fixture/v2', 'artifacts': descriptors}
    manifest_path = directory / 'manifest.json'
    manifest_raw = wire(manifest)
    write_new(manifest_path, manifest_raw)
    sync_directory(directory)
    return {'records': records, 'events': events,
            'manifest': {'path': str(manifest_path), 'sha256': sha(manifest_raw)}}


@pytest.mark.parametrize('row_id', ROW_IDS)
def test_exposed_nontrivial_modal_scores_match_independent_equations(retained, reconstruction, row_id, record_property):
    record_property('compact_trained_reconstruction_fixture', json.dumps(reconstruction['manifest'], sort_keys=True))
    values = reconstruction['records']
    diagnostic, score = values[row_id + '-diagnostic'], values[row_id + '-score']
    assert diagnostic['teacher_forcing'] is diagnostic['target_access'] is True
    assert diagnostic['prefix_origin'] == 'target_derived_label' and diagnostic['target_position'] == 21
    assert diagnostic['allowed_count'] == 3 and len(score['logits']) == 537
    assert diagnostic['target_token_id'] in diagnostic['allowed_token_ids']
    assert diagnostic['greedy_matches_authored_target'] == (diagnostic['selected_token_id'] == diagnostic['target_token_id'])
    assert diagnostic['trained_nll_lower_than_initial'] == (diagnostic['trained_minus_initial_target_nll'] < 0)
    assert math.isfinite(diagnostic['score_public_call_seconds']) and diagnostic['score_public_call_seconds'] > 0
    assert all(math.isfinite(diagnostic[name]) for name in ('all_vocabulary_target_nll', 'allowed_vocabulary_target_nll',
        'manual_trained_target_nll', 'manual_initial_target_nll', 'trained_minus_initial_target_nll', 'maximum_absolute_reference_error'))
    assert score['checkpoint_sha256'] == CHECKPOINT_SHA and score['weights_sha256'] == retained['checkpoint']['weights_sha256']
    assert score['compact_training_steps'] == 2 and score['runtime_verified'] is True
    assert score['optimizer_constructed'] is score['optimizer_state_restored'] is score['optimizer_executed'] is False
    no_authority(score)


@pytest.mark.parametrize('row_id', ROW_IDS)
def test_bounded_bos_generation_preserves_every_observed_outcome(reconstruction, row_id):
    values = reconstruction['records']
    generated = values[row_id + '-generation']
    outcome = next(row for row in values['outcomes']['rows'] if row['id'] == row_id)
    assert generated['status'] in {'complete', 'blocked', 'step_budget_exhausted'}
    assert generated['initial_prefix_ids'] == [1] and generated['prefix_origin'] == 'bos_seed'
    assert generated['settings']['max_new_tokens'] == MAX_NEW_TOKENS
    assert 0 < generated['numerical_forward_count'] == generated['emitted_token_count'] <= MAX_NEW_TOKENS
    assert generated['generated_ids'] == [1] + generated['selected_token_ids']
    assert generated['exposure']['teacher_forcing'] is generated['exposure']['target_access'] is False
    assert generated['exposure']['source_encoder_authenticated'] is False and generated['exposure']['encoder_sha256'] is None
    assert generated['optimizer_constructed'] is generated['optimizer_state_restored'] is False
    assert generated['training_executed'] is generated['compact_optimizer_executed'] is False
    for step in generated['trace']:
        if step['numerical_forward_executed']:
            allowed = step['prefix_report']['allowed_token_ids']
            best = min(allowed, key=lambda token: (-step['logits'][token], token))
            assert step['selection']['selected_token_id'] == best
            assert step['logits_sha256'] == digest(step['logits'])
    assert outcome['generation_outcome'] == generated['status'] and outcome['generation_reason'] == generated['reason']
    assert math.isfinite(outcome['generation_public_call_seconds']) and outcome['generation_public_call_seconds'] > 0
    assert outcome['complete_formula_observed'] == (generated['final_decoding']['status'] == 'valid_candidate')
    assert outcome['public_replay_verified'] is False
    no_authority(generated)


def test_full_population_and_durable_phase_order_survive_as_explicit_evidence(reconstruction):
    values, events = reconstruction['records'], reconstruction['events']
    assert tuple(row['id'] for row in values['enrollment']['rows']) == ROW_IDS
    assert all(row['generation_status'] == row['diagnostic_status'] == 'not_started' for row in values['enrollment']['rows'])
    assert tuple(row['id'] for row in values['outcomes']['rows']) == ROW_IDS
    assert all(row['generation_status'] == row['diagnostic_status'] == 'recorded' for row in values['outcomes']['rows'])
    first_bos = next(event['sequence'] for event in events if event['phase'] == 'bos_generation')
    completed = [event for event in events if event['event'] == 'phase_completed' and event['phase'] == 'diagnostic_score']
    assert len(completed) == 2 and all(event['sequence'] < first_bos for event in completed)
    for row in values['bos-inputs']['rows']:
        assert row['prefix_ids'] == [1] and row['prefix_origin'] == 'bos_seed'
        assert not any(key.startswith('target_') for key in row if key != 'target_access')
        assert row['target_access'] is False
    assert values['scope']['public_replay_verified'] is values['scope']['batch_adapter_executed'] is False
    assert values['scope']['batch_evaluator_executed'] is values['scope']['new_content_admission_claimed'] is False


def test_exact_numerical_accounting_and_unchanged_parent_without_training(retained, reconstruction, no_optimizer_or_training):
    events, scope = reconstruction['events'], reconstruction['records']['scope']
    counts = Counter(event['event'] for event in events)
    expected = 2 + sum(scope['actual_generation_forwards_by_row'].values())
    assert counts['gru_forward_started'] == counts['gru_forward_completed'] == expected <= 130
    assert counts['trained_forward_started'] == counts['trained_forward_completed'] == expected
    assert counts['manual_reference_started'] == counts['manual_reference_completed'] == 4
    assert scope['actual_product_gru_forward_count'] == scope['trained_runtime_forward_count'] == expected
    assert scope['manual_gate_reference_evaluations'] == 4 and scope['numeric_event_counters_are_overlapping'] is True
    assert scope['optimizer_allocations'] == scope['optimizer_updates'] == 0 and no_optimizer_or_training == []
    assert digest(retained['checkpoint']) == CHECKPOINT_SHA
    assert retained['checkpoint']['initial_checkpoint'] == retained['values']['initial-parent-v1.json']
    assert scope['original_recorded_checkpoint_steps'] == 2 and scope['original_training_rerun'] is False
    assert scope['training_mask'] == scope['evaluation_gold_mask'] == 0
