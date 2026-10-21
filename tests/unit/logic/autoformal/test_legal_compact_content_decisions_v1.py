"""Pure target-position inventory and saved-score scalar diagnostics.

The two historical modal observations are read, never regenerated. Authored
uniform/nonuniform vectors below test arithmetic only. No Torch, encoder,
optimizer, checkpoint update or legal-semantic qualification is permitted.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

import pytest


class DenyNeuralImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('torch', 'transformers', 'sentence_transformers'):
            raise AssertionError('pure decision diagnostics attempted a neural-library import: ' + fullname)
        return None


_collection_guard = DenyNeuralImports()
sys.meta_path.insert(0, _collection_guard)
try:
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_decisions_v1 as subject
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
finally:
    sys.meta_path.remove(_collection_guard)

FIXTURE_SHA = '1c4b7c37eba6870c2a746cb3e3191013a1d25906cb75427d4f7be0ca6583dab7'
SAVED_SCORES_SHA = '3d9a931694f0edf8d5f32f8cb29eb5504da7178714dd7004bd9745b965721c3f'
CHECKPOINT_SHA = '0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0'
ROLES = {'transport', 'constructor', 'modal_letter', 'predicate_reference',
         'variable_reference', 'binder_declaration', 'eos'}
ROW_IDS = ('fictional-retention', 'fictional-inspection')


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
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 16 * 1024**2
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    assert identity(before) == identity(after) and len(raw) == before.st_size
    return raw


def no_authority(report):
    assert report['authority'] and all(flag is False for flag in report['authority'].values())
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert report['model_executed'] is report['training_executed'] is False
    assert report['teacher_forcing'] is report['target_access'] is True


@pytest.fixture(scope='module', autouse=True)
def forbid_neural_imports():
    blocked = ('torch', 'transformers', 'sentence_transformers')
    assert not any(name.split('.')[0] in blocked for name in sys.modules)
    guard = DenyNeuralImports()
    sys.meta_path.insert(0, guard)
    try:
        yield
        assert not any(name.split('.')[0] in blocked for name in sys.modules)
    finally:
        sys.meta_path.remove(guard)


@pytest.fixture(scope='module')
def retained(forbid_neural_imports):
    manifest_path = Path(os.environ['LEGAL_COMPACT_DECISION_FIXTURE_MANIFEST'])
    manifest_raw = snapshot(manifest_path)
    assert sha(manifest_raw) == FIXTURE_SHA
    manifest = json.loads(manifest_raw)
    assert manifest['schema'] == 'authored-compact-training-fixture/v2' and len(manifest['artifacts']) == 27
    bodies, values = {}, {}
    for name, descriptor in manifest['artifacts'].items():
        path = Path(descriptor['path'])
        assert path.parent == manifest_path.parent and path.name == name
        body = snapshot(path)
        assert sha(body) == descriptor['sha256'] and len(body) == descriptor['bytes']
        bodies[name] = body
        if name.endswith('.json'):
            values[name] = json.loads(body)
    assert sha(bodies['resumed-checkpoint.json']) == CHECKPOINT_SHA
    assert values['resumed-checkpoint.json']['progress']['optimizer_steps'] == 2
    saved_path = Path(os.environ['LEGAL_COMPACT_DECISION_SAVED_SCORES'])
    saved_raw = snapshot(saved_path)
    assert sha(saved_raw) == SAVED_SCORES_SHA
    saved = json.loads(saved_raw)
    assert saved['schema'] == 'legal-compact-prepared-runtime-differential/v3'
    assert saved['checkpoint_sha256'] == CHECKPOINT_SHA
    rows, population = values['input-rows.json'], values['population.json']['rows']
    assert len(rows) == len(population) == 2
    assert tuple(row['id'] for row in rows) == tuple(row['id'] for row in population) == ROW_IDS
    codec = values['codec.json']
    assert codec == tokens.build_compact_content_token_codec_v1()
    assert digest(codec) == values['resumed-checkpoint.json']['codec_sha256']
    cases = []
    for index, (row, bound) in enumerate(zip(rows, population)):
        for key in ('source', 'context', 'target'):
            assert sha(bodies[row[key + '_file']]) == bound[key + '_sha256']
        conditioning_sha = digest(row['conditioning'])
        assert conditioning_sha == bound['conditioning_sha256']
        score = saved['calls']['score_' + str(index) + '_v3']['report']
        encoding = values[row['id'] + '-target-encoding.json']
        assert len(encoding['target_ids']) == 47
        assert score['checkpoint_sha256'] == CHECKPOINT_SHA and score['status'] == 'scored'
        assert score['prefix_ids'] == encoding['target_ids'][:21]
        assert score['context_raw_sha256'] == bound['context_sha256']
        assert score['conditioning_sha256'] == conditioning_sha and score['codec_sha256'] == digest(codec)
        assert len(score['logits']) == 537 and digest(score['logits']) == score['logits_sha256']
        cases.append({'id': row['id'], 'content_raw': bodies[row['target_file']],
            'context_raw': bodies[row['context_file']], 'codec': codec,
            'conditioning_sha256': conditioning_sha, 'checkpoint_sha256': CHECKPOINT_SHA,
            'saved_score': score, 'target_encoding': encoding})
    return {'manifest': manifest, 'manifest_path': manifest_path, 'manifest_raw': manifest_raw,
        'saved_path': saved_path, 'saved_raw': saved_raw, 'bodies': bodies, 'values': values, 'cases': cases}


def inventory_options(case):
    return {'expected_content_sha256': sha(case['content_raw']), 'expected_context_sha256': sha(case['context_raw']),
            'codec': case['codec'], 'expected_codec_sha256': digest(case['codec'])}


def inventory(case):
    return subject.prepare_compact_content_decisions_v1(case['content_raw'], case['context_raw'], **inventory_options(case))


def packet(case, rows):
    return {'schema': 'legal-compact-saved-score-population/v1',
        'target_raw_sha256': sha(case['content_raw']), 'context_raw_sha256': sha(case['context_raw']),
        'codec_sha256': digest(case['codec']), 'checkpoint_sha256': case['checkpoint_sha256'],
        'conditioning_sha256': case['conditioning_sha256'], 'rows': rows}


def saved_row(prefix, logits, provenance):
    return {'prefix_ids': list(prefix), 'logits': logits, 'logits_sha256': digest(logits),
            'source_observation_sha256': digest(provenance)}


def analyze(case, offered, **weights):
    raw = offered if type(offered) is bytes else wire(offered)
    return subject.analyze_compact_saved_scores_v1(case['content_raw'], case['context_raw'], raw,
        **inventory_options(case), expected_scores_sha256=sha(raw),
        expected_checkpoint_sha256=case['checkpoint_sha256'],
        expected_conditioning_sha256=case['conditioning_sha256'], **weights)


@pytest.fixture(scope='module')
def integration(retained, tmp_path_factory):
    records = []
    for case in retained['cases']:
        positions = inventory(case)
        score = case['saved_score']
        offered = packet(case, [saved_row(score['prefix_ids'], score['logits'], score)])
        report = analyze(case, offered)
        records.append({'id': case['id'], 'inventory': positions, 'inventory_sha256': digest(positions),
            'diagnostic': report, 'diagnostic_sha256': digest(report), 'scores_packet': offered,
            'scores_raw_utf8': wire(offered).decode('utf-8'), 'scores_raw_sha256': digest(offered),
            'source_observation_sha256': digest(score)})
    counts = {'target_rows': len(records),
        'supervised_positions': sum(row['inventory']['counts']['supervised_positions'] for row in records),
        'observed_score_positions': sum(row['diagnostic']['counts']['observed_positions'] for row in records),
        'missing_score_positions': sum(row['diagnostic']['counts']['missing_positions'] for row in records),
        'new_model_forwards': 0, 'new_optimizer_updates': 0}
    assert counts == {'target_rows': 2, 'supervised_positions': 92, 'observed_score_positions': 2,
                      'missing_score_positions': 90, 'new_model_forwards': 0, 'new_optimizer_updates': 0}
    value = {'schema': 'legal-compact-decision-loss-evidence/v1', 'checkpoint_sha256': CHECKPOINT_SHA,
        'observation_selection': ['score_0_v3', 'score_1_v3'],
        'missing_observation_scope': 'Missing relative to these two supplied modal-score rows; other historical observations may exist',
        'measurement_scope': 'Targeted modal-loss view over complete92-position authored inventory; not full training-loss measurement',
        'position_count_scope': 'Equal-weight token allocation only; not measured gradient or loss contribution',
        'input_descriptors': {'training_manifest': {'path': str(retained['manifest_path']),
            'bytes': len(retained['manifest_raw']), 'sha256': FIXTURE_SHA},
            'saved_numerical_evidence': {'path': str(retained['saved_path']),
            'bytes': len(retained['saved_raw']), 'sha256': SAVED_SCORES_SHA},
            'training_artifacts': retained['manifest']['artifacts']}, 'rows': records, 'counts': counts,
        'exposure': {'teacher_forcing': True, 'target_access': True, 'authored_training_fixtures': True,
            'heldout_evaluated': False, 'semantic_accuracy_measured': False, 'source_encoder_authenticated': False,
            'model_executed': False, 'training_executed': False, 'training_mask': 0, 'evaluation_gold_mask': 0}}
    directory = tmp_path_factory.mktemp('decision-loss-diagnostics', numbered=False)
    path = directory / 'decision-loss-evidence.json'
    raw = wire(value)
    assert len(raw) < 4 * 1024**2
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    assert snapshot(Path(retained['manifest']['artifacts']['resumed-checkpoint.json']['path'])) == retained['bodies']['resumed-checkpoint.json']
    return value, {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


@pytest.fixture(scope='module')
def authored(retained):
    context = json.loads(retained['cases'][0]['context_raw'])
    symbol = context['signature']['symbols'][0]
    symbol['name'] = 'AuthoredPredicate'
    symbol['domain'] = symbol['domain'][:1]
    context['argument_roles'] = [{'symbol': 'AuthoredPredicate', 'roles': ['actor']}]
    content = {'schema': 'legal-relational-compact-content/v1',
               'tree': ['forall', 0, ['predicate', 0, [['variable', 0]]]]}
    case = {'content_raw': wire(content), 'context_raw': wire(context), 'codec': retained['cases'][0]['codec'],
        'checkpoint_sha256': digest({'authored_scalar_fixture': 'no checkpoint or model'}),
        'conditioning_sha256': digest({'authored_scalar_fixture': 'no encoder'})}
    case['inventory'] = inventory(case)
    return case


def synthetic_packet(case, mode='uniform', shift=0.0):
    result = []
    ids = case['inventory']['target_ids']
    for position in case['inventory']['positions']:
        logits = [float(shift)] * 537
        if mode == 'nonuniform':
            logits[position['target_token_id']] += 2. if position['decision_kind'] == 'choice' else -2.
        elif mode == 'extreme':
            logits = [-1e6] * 537
            logits[position['target_token_id']] = 1e6
        result.append(saved_row(ids[:position['target_position']], logits,
            {'authored_scalar_fixture': True, 'position': position['target_position'], 'mode': mode, 'shift': shift}))
    return packet(case, result)


def test_two_full_inventories_preserve90_missing_supplied_score_positions(integration, retained, record_property):
    value, descriptor = integration
    record_property('decision_loss_evidence', json.dumps(descriptor, sort_keys=True))
    assert value['counts']['supervised_positions'] == 92
    assert value['counts']['observed_score_positions'] == 2 and value['counts']['missing_score_positions'] == 90
    for row, case in zip(value['rows'], retained['cases']):
        inv, report = row['inventory'], row['diagnostic']
        assert inv['target_ids'] == case['target_encoding']['target_ids']
        assert len(inv['target_ids']) == 47 and len(inv['positions']) == 46
        assert [position['target_position'] for position in inv['positions']] == list(range(1, 47))
        assert inv['positions'][-1]['role'] == 'eos' and inv['positions'][-1]['target_token_id'] == 2
        assert inv['counts']['forced_positions'] + inv['counts']['choice_positions'] == 46
        assert set(inv['counts']['by_role']) == ROLES
        # Independently reconstructed lexical roles on the exact authored bytes,
        # with constructor/active-binder choices read from the public grammar.
        assert inv['counts']['forced_positions'] == 39 and inv['counts']['choice_positions'] == 7
        assert inv['counts']['by_role'] == {'transport': 33, 'constructor': 6, 'modal_letter': 1,
            'predicate_reference': 1, 'variable_reference': 2, 'binder_declaration': 2, 'eos': 1}
        for position in inv['positions']:
            i = position['target_position']
            assert position['prefix_length'] == i and position['prefix_ids_sha256'] == digest(inv['target_ids'][:i])
            assert position['target_token_id'] in position['allowed_token_ids']
            assert position['allowed_count'] == len(position['allowed_token_ids'])
            assert position['decision_kind'] == ('forced' if position['allowed_count'] == 1 else 'choice')
            assert position['local_prefix_only'] is True and position['global_completability_proven'] is False
        assert report['counts'] == {'supervised_positions': 46, 'observed_positions': 1, 'missing_positions': 45}
        assert report['observations_complete'] is False and report['complete_weighted_full537_objective'] is None
        observed = [position for position in report['rows'] if position['status'] == 'observed']
        assert len(observed) == 1 and observed[0]['target_position'] == 21 and observed[0]['role'] == 'modal_letter'
        assert observed[0]['source_observation_sha256'] == row['source_observation_sha256']
        missing = [position for position in report['rows'] if position['status'] == 'unavailable']
        assert len(missing) == 45 and all(position['metrics'] is None and position['reason'] == 'missing_saved_score' for position in missing)
        assert report['inventory_sha256'] == row['inventory_sha256'] and report['scores_raw_sha256'] == row['scores_raw_sha256']
        assert report['by_decision_kind']['forced']['observed_positions'] == 0
        assert report['by_decision_kind']['forced']['observed_mean_full537_nll'] is None
        no_authority(inv); no_authority(report)


def test_nested_authored_binder_predicate_and_variable_integer_roles_remain_distinct(retained):
    context = json.loads(retained['cases'][0]['context_raw'])
    first = context['signature']['symbols'][0]
    first['name'] = 'AuthoredFirst'
    second = deepcopy(first); second['name'] = 'AuthoredSecond'
    context['signature']['symbols'] = [first, second]
    context['argument_roles'] = [{'symbol': name, 'roles': ['actor', 'object']}
                                for name in ('AuthoredFirst', 'AuthoredSecond')]
    first_predicate = ['predicate', 0, [['variable', 0], ['variable', 1]]]
    second_predicate = ['predicate', 1, [['variable', 1], ['variable', 0]]]
    content = {'schema': 'legal-relational-compact-content/v1',
        'tree': ['forall', 0, ['exists', 1, ['and', first_predicate, ['extension', 'O', second_predicate]]]]}
    case = {**retained['cases'][0], 'content_raw': wire(content), 'context_raw': wire(context)}
    report = inventory(case)
    counts = report['counts']['by_role']
    assert counts['binder_declaration'] == 2 and counts['predicate_reference'] == 2 and counts['variable_reference'] == 4
    assert counts['modal_letter'] == 1
    for role, expected in [('binder_declaration', ['0', '1']), ('predicate_reference', ['0', '1']),
                           ('variable_reference', ['0', '1', '1', '0'])]:
        selected = [position for position in report['positions'] if position['role'] == role]
        assert [position['lexical_token'] for position in selected] == expected
        assert all(position['tree_path'] is not None for position in selected)
    forced_binders = [position for position in report['positions'] if position['role'] == 'binder_declaration']
    assert all(position['decision_kind'] == 'forced' for position in forced_binders)
    assert all(position['global_completability_proven'] is False for position in forced_binders)
    # Local singleton grammar is not a proof of source meaning or binder intent.
    no_authority(report)


def test_uniform_full_and_allowed_losses_shift_invariance_and_forced_semantic_positions(authored):
    report = analyze(authored, synthetic_packet(authored))
    shifted = analyze(authored, synthetic_packet(authored, shift=1000.0))
    assert report['observations_complete'] is shifted['observations_complete'] is True
    assert math.isclose(report['complete_weighted_full537_objective'], math.log(537), abs_tol=1e-12)
    inventory_rows = authored['inventory']['positions']
    forced_semantic = []
    for row, translated, position in zip(report['rows'], shifted['rows'], inventory_rows):
        metrics, other = row['metrics'], translated['metrics']
        assert math.isclose(metrics['full537_nll'], math.log(537), abs_tol=1e-12)
        assert math.isclose(metrics['allowed_nll'], math.log(position['allowed_count']), abs_tol=1e-12)
        assert math.isclose(metrics['forbidden_probability_mass'], 1 - position['allowed_count'] / 537, abs_tol=1e-12)
        assert metrics['raw_argmax_token_id'] == 0
        assert metrics['constrained_argmax_token_id'] == min(position['allowed_token_ids'])
        for key in ('full537_nll', 'allowed_nll', 'forbidden_probability_mass'):
            assert math.isclose(metrics[key], other[key], abs_tol=1e-12)
        if position['decision_kind'] == 'forced':
            assert metrics['allowed_nll'] == 0. and metrics['full537_nll'] > 0
            if position['role'] in {'predicate_reference', 'variable_reference', 'binder_declaration'}:
                forced_semantic.append(position)
    assert {position['role'] for position in forced_semantic} == {'predicate_reference', 'variable_reference', 'binder_declaration'}
    no_authority(report)


def test_stable_logsumexp_handles_extreme_finite_saved_logits(authored):
    report = analyze(authored, synthetic_packet(authored, 'extreme'))
    assert report['observations_complete'] is True
    for row in report['rows']:
        values = row['metrics']
        assert math.isfinite(values['full537_nll']) and math.isfinite(values['allowed_nll'])
        assert values['full537_nll'] == values['allowed_nll'] == 0.0
        assert values['raw_correct'] is values['constrained_correct'] is True


def test_all_one_identity_and_explicit_positive_weighted_objective(authored):
    offered = synthetic_packet(authored, 'nonuniform')
    ordinary = analyze(authored, offered)
    explicit = analyze(authored, offered, forced_weight=1.0, choice_weight=1.0)
    weighted = analyze(authored, offered, forced_weight=.5, choice_weight=3.)
    subnormal = analyze(authored, offered, forced_weight=5e-324, choice_weight=5e-324)
    assert ordinary == explicit
    unweighted_expected = math.fsum(row['metrics']['full537_nll'] for row in ordinary['rows']) / len(ordinary['rows'])
    expected = math.fsum(row['weight'] * row['metrics']['full537_nll'] for row in weighted['rows']) / math.fsum(row['weight'] for row in weighted['rows'])
    assert math.isclose(ordinary['complete_weighted_full537_objective'], unweighted_expected, abs_tol=1e-12)
    assert math.isclose(subnormal['complete_weighted_full537_objective'], unweighted_expected, abs_tol=1e-12)
    assert math.isclose(weighted['complete_weighted_full537_objective'], expected, abs_tol=1e-12)
    assert not math.isclose(expected, unweighted_expected, abs_tol=1e-8)
    assert all(row['weight'] == (.5 if row['decision_kind'] == 'forced' else 3.) for row in weighted['rows'])
    assert weighted['policy']['normalization'] == 'sum_position_weights'
    assert weighted['policy']['complete_objective_requires_all_positions'] is True


def test_empty_score_population_retains_every_missing_position_and_null_means(authored):
    report = analyze(authored, packet(authored, []))
    expected = len(authored['inventory']['positions'])
    assert report['counts'] == {'supervised_positions': expected, 'observed_positions': 0, 'missing_positions': expected}
    assert report['observations_complete'] is False and report['complete_weighted_full537_objective'] is None
    assert all(row['status'] == 'unavailable' and row['metrics'] is None for row in report['rows'])
    assert report['observed_summary']['observed_mean_full537_nll'] is None
    assert report['observed_summary']['observed_weighted_full537_nll'] is None


@pytest.mark.parametrize('kind', ['target', 'context', 'codec', 'checkpoint', 'conditioning', 'scores'])
def test_independent_packet_pins_cannot_be_rebound(authored, kind):
    raw = wire(packet(authored, []))
    options = {**inventory_options(authored), 'expected_scores_sha256': sha(raw),
        'expected_checkpoint_sha256': authored['checkpoint_sha256'], 'expected_conditioning_sha256': authored['conditioning_sha256']}
    key = {'target': 'expected_content_sha256', 'context': 'expected_context_sha256',
        'codec': 'expected_codec_sha256', 'checkpoint': 'expected_checkpoint_sha256',
        'conditioning': 'expected_conditioning_sha256', 'scores': 'expected_scores_sha256'}[kind]
    options[key] = '0' * 64
    with pytest.raises(ValueError):
        subject.analyze_compact_saved_scores_v1(authored['content_raw'], authored['context_raw'], raw, **options)


@pytest.mark.parametrize('kind', ['invalid_constructor', 'malformed_json', 'changed_codec'])
def test_invalid_target_or_fixed_codec_refuses_without_repair(authored, kind):
    case = deepcopy(authored)
    if kind == 'invalid_constructor':
        case['content_raw'] = wire({'schema': 'legal-relational-compact-content/v1', 'tree': ['unsupported_truth']})
    elif kind == 'malformed_json':
        case['content_raw'] = b'{"schema":'
    else:
        case['codec']['vocabulary'][3] = '"Z"'
    with pytest.raises(ValueError):
        inventory(case)


@pytest.mark.parametrize('kind', ['width', 'nonfinite', 'prefix', 'duplicate', 'order', 'boolean_logit',
                                'logits_pin', 'extra_population_field', 'magnitude', 'duplicate_json_key'])
def test_invalid_saved_score_population_or_rows_refuse(authored, kind):
    offered = synthetic_packet(authored)
    offered['rows'] = offered['rows'][:2]
    row = offered['rows'][0]
    if kind == 'width':
        row['logits'].pop(); row['logits_sha256'] = digest(row['logits'])
    elif kind == 'nonfinite':
        row['logits'][0] = float('nan')
    elif kind == 'prefix':
        row['prefix_ids'][0] = 2
    elif kind == 'duplicate':
        offered['rows'] = [row, deepcopy(row)]
    elif kind == 'order':
        offered['rows'].reverse()
    elif kind == 'boolean_logit':
        row['logits'][0] = True; row['logits_sha256'] = digest(row['logits'])
    elif kind == 'logits_pin':
        row['logits_sha256'] = '0' * 64
    elif kind == 'extra_population_field':
        offered['accepted'] = True
    elif kind == 'magnitude':
        row['logits'][0] = 1e6 + 1.; row['logits_sha256'] = digest(row['logits'])
    raw = json.dumps(offered, sort_keys=True, separators=(',', ':'), allow_nan=True).encode('utf-8')
    if kind == 'duplicate_json_key':
        raw = b'{"rows":[],' + raw[1:]
    with pytest.raises(ValueError):
        analyze(authored, raw)


@pytest.mark.parametrize('options', [dict(forced_weight=0), dict(choice_weight=float('nan')),
                                    dict(forced_weight=True), dict(choice_weight=17)])
def test_weights_reject_zero_nonfinite_boolean_or_oversize(authored, options):
    with pytest.raises(ValueError):
        analyze(authored, packet(authored, []), **options)
