"""Adversarial phase, alias, and arithmetic checks for the independent qualifier."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ops.legal_ir import qualify_legal_temporal_ownership_head_v2 as q


def sample():
    text = 'Registry shall file within 7 days of notice.'
    start = text.index('within'); end = text.index('.')
    source = {'id': 'query', 'source_text': text, 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'proposed_time_span': {'char_start': start, 'char_end': end}}
    probs = q.metric.softmax([4., 0., 0., 0.])
    row = {'id': source['id'], 'source_sha256': source['source_sha256'], 'proposed_time_span': source['proposed_time_span'],
           'time_token_span': q.metric.validate_source(source), 'logits': [4., 0., 0., 0.], 'probabilities': probs,
           'confidence': probs[0], 'predicted_label': 'norm', 'status': 'accepted', 'owner_type': 'norm', 'reason': None,
           **{k: False for k in q.metric.FALSE_FIELDS}}
    cp = {'path': '/checkpoint', 'bytes': 1, 'sha256': 'a'*64}; src = {'path': '/sources', 'bytes': 1, 'sha256': 'b'*64}
    value = {'schema': 'legal-temporal-owner-type-source-generation/v1',
             'model': {'checkpoint': cp, 'arm': 'frozen_occurrence', 'seed': 1730, 'steps': 200}, 'sources': src,
             'class_order': list(q.metric.CLASSES), 'threshold': .8, 'rows': [row], 'encoder_batch_forwards': 1,
             'encoder_source_evaluations': 1, 'labels_supplied': False, 'source_text_conditioned': True,
             'time_occurrence_conditioned': True, 'source_id_used_as_feature': False, 'owner_or_cue_spans_supplied': False,
             **{k: False for k in q.metric.FALSE_FIELDS}}
    return source, row, cp, src, value


def check(value, source, cp, src):
    return q.generation(value, cp, src, [source], arm='frozen_occurrence', seed=1730, step=200)


def test_generation_binds_source_occurrence_and_fixed_model():
    source, row, cp, src, value = sample()
    assert check(value, source, cp, src) == [row]


@pytest.mark.parametrize('mutation', [
    lambda v: v['model'].update(steps=True),
    lambda v: v['model'].update(seed=1731),
    lambda v: v.update(sources={'path': '/other', 'bytes': 1, 'sha256': 'b'*64}),
    lambda v: v.update(labels_supplied=True),
    lambda v: v.update(owner_occurrence_resolved=True),
    lambda v: v.update(source_id_used_as_feature=True),
    lambda v: v.update(owner_or_cue_spans_supplied=True),
    lambda v: v.update(time_occurrence_conditioned=False),
    lambda v: v.update(encoder_batch_forwards=True),
    lambda v: v.update(encoder_source_evaluations=2),
    lambda v: v.update(rows=[]),
    lambda v: v['rows'][0].update(probabilities=[.25]*4),
    lambda v: v['rows'][0].update(proposed_time_span={'char_start': 21, 'char_end': 42}),
])
def test_generation_rejects_changed_provenance(mutation):
    source, _, cp, src, value = sample(); mutation(value)
    with pytest.raises(ValueError): check(value, source, cp, src)


def test_file_refs_reject_numeric_alias_and_changed_bytes(tmp_path):
    path = tmp_path/'evidence.json'; path.write_text('0'); pin = q.reference(path)
    assert q.read(pin) == 0
    with pytest.raises(ValueError): q.read({**pin, 'bytes': True})
    path.write_text('1')
    with pytest.raises(ValueError): q.read(pin)


def test_typed_checkpoint_reference_is_byte_and_schema_bound(tmp_path):
    path = tmp_path/'checkpoint.json'
    schema = 'legal-temporal-owner-type-checkpoint/v1'
    pin = {**q.write(path, {'schema':schema, 'model':'test'}), 'schema':schema}
    q.read_producer(pin)
    with pytest.raises(ValueError): q.read_producer({**pin, 'schema':'different'})
    with pytest.raises(ValueError): q.read_producer({**pin, 'bytes': True})
    path.write_text(json.dumps({'schema':schema, 'model':'changed'}))
    with pytest.raises(ValueError): q.read_producer(pin)


def test_typed_checkpoint_reference_rejects_wrong_inner_schema(tmp_path):
    pin = {**q.write(tmp_path/'checkpoint.json', {'schema':'wrong'}), 'schema':'legal-temporal-owner-type-checkpoint/v1'}
    with pytest.raises(ValueError, match='schema differs'): q.read_producer(pin)


def test_writes_never_overwrite_prior_evidence(tmp_path):
    path = tmp_path/'evidence.json'; q.write(path, {'a': 1})
    with pytest.raises(FileExistsError): q.write(path, {'a': 2})
    assert json.loads(path.read_text()) == {'a': 1}


def test_metrics_reconcile_independent_arithmetic_and_reject_laundered_count():
    source, row, *_ = sample()
    result = q.metric.score([source], [row], {'query': 'norm'})
    reported = q.runner.metrics([row], [{**source, 'label': 'norm'}])
    q.reconcile_metrics(result, reported)
    with pytest.raises(ValueError): q.reconcile_metrics(result, {**reported, 'correct': True})
    with pytest.raises(ValueError): q.reconcile_metrics(result, {**reported, 'macro_f1': .999})


def inventory_fixture(monkeypatch):
    objects = {}; index = 0
    def pin(value):
        nonlocal index
        index += 1
        p = {'path': f'/evidence/{index}', 'bytes': len(q.wire(value)), 'sha256': q.digest(value)}
        objects[p['path']] = value; return p
    monkeypatch.setattr(q, 'read', lambda p: objects[p['path']])
    monkeypatch.setattr(q, 'read_producer', lambda p: q.require(p['path'] in objects, 'missing byte evidence'))
    monkeypatch.setattr(q.runner, 'producer_pins', lambda: {'producer': 'hash'})
    monkeypatch.setattr(q.corpus, 'validate_query_inventory', lambda rows, expected: q.require(len(rows) == expected, 'count'))
    config = pin({}); sources = {k: pin([{'id': str(i)} for i in range(n)]) for k,n in
                               [('training',768),('tuning',144),('fresh_sources',192),('multi_fresh_sources',96)]}
    models = {}; trials = []
    for arm in q.ARMS:
        for seed in q.SEEDS:
            name = f'{arm}-{seed}'; models[name] = pin({'model': name, 'step': 0})
            stages = [{'steps': step, 'checkpoint': pin({'model': name, 'step': step}),
                       'training_report': pin({'report': name, 'step': step})} for step in q.STEPS]
            trials.append({'name': name, 'arm': arm, 'seed': seed, 'stages': stages, 'initial_checkpoint': models[name],
                'selected_steps': 200, 'selected_checkpoint': stages[-1]['checkpoint'], 'fresh_references_opened': False,
                'fresh_reference_guard': {'premature_read_attempts': 0}})
    initials = pin({'config': config, 'models': models})
    selections = pin({'config': config, 'initialization_freeze': initials, 'trials': trials,
                      'trial_references': [pin(copy.deepcopy(t)) for t in trials], 'fresh_references_opened': False, 'no_pipeline_promotion': True})
    logical = []; actual = []; cache = {}
    for trial in trials:
        for role in ('selected', 'final200'):
            for panel in q.PANELS:
                cp = trial['selected_checkpoint']; key = q.digest({'checkpoint': cp['sha256'], 'sources': sources[panel]['sha256']})
                executed = key not in cache
                if executed:
                    cache[key] = pin({'key': key}); n = len(objects[sources[panel]['path']])
                    actual.append({'key':key, 'generation':cache[key], 'encoder_batch_forwards': n//48, 'encoder_source_evaluations': n})
                logical.append({'slot': trial['name']+'__'+role, 'arm': trial['arm'], 'seed': trial['seed'], 'role': role,
                    'panel': panel, 'checkpoint': cp, 'generation': cache[key], 'generation_key': key, 'executed_here': executed})
    freeze = {'all_training_selection_and_generation_complete':True, 'fresh_references_opened':False,
        'fresh_reference_guard':{'premature_read_attempts':0}, 'config':config, 'selections':selections,
        'initialization_freeze':initials, 'producer_pins':{'producer':'hash'}, 'sources':sources,
        'logical_generations':logical, 'executed_generations':actual, 'logical_generation_slots':24,
        'physical_generation_files':12, 'logical_fresh_query_rows':3456, 'physical_fresh_query_rows':1728,
        'physical_fresh_encoder_batch_forwards':36, 'training_encoder_batch_forwards':1200,
        'training_encoder_source_evaluations':19200, 'total_optimizer_updates':1200,
        'admitted_generation_counters':{'encoder_batch_forwards':456, 'encoder_source_evaluations':21888}}
    return freeze, objects


def test_complete_inventory_preserves_logical_and_physical_counts(monkeypatch):
    freeze, _ = inventory_fixture(monkeypatch)
    _, trials, _, unique, counters = q.inventory(freeze)
    assert len(trials) == 6 and len(unique) == 12
    assert counters['logical_fresh_query_rows'] == 2*counters['physical_fresh_query_rows']


@pytest.mark.parametrize('mutation', [
    lambda f: f.update(all_training_selection_and_generation_complete=False),
    lambda f: f.update(fresh_references_opened=True),
    lambda f: f['fresh_reference_guard'].update(premature_read_attempts=1),
    lambda f: f['logical_generations'].pop(),
    lambda f: f['logical_generations'].append(f['logical_generations'][0]),
    lambda f: f['logical_generations'][0].update(generation_key='changed'),
    lambda f: f['logical_generations'][0].update(executed_here=False),
    lambda f: f['logical_generations'][2].update(generation={'path':'different'}),
    lambda f: f['logical_generations'][0].update(checkpoint={'path':'different'}),
    lambda f: f.update(physical_fresh_query_rows=3456),
    lambda f: f['executed_generations'].pop(),
    lambda f: f.update(total_optimizer_updates=True),
])
def test_inventory_rejects_missing_or_changed_provenance(monkeypatch, mutation):
    freeze, _ = inventory_fixture(monkeypatch); mutation(freeze)
    with pytest.raises(ValueError): q.inventory(freeze)


def test_score_cannot_release_references_without_exact_replay(tmp_path, monkeypatch):
    freeze = tmp_path/'generation.json'; replay = tmp_path/'replay.json'
    q.write(freeze, {'config': 'must not be loaded'})
    q.write(replay, {'schema':'legal-temporal-owner-type-independent-replay/v1', 'exact_replay':False})
    opened = []
    monkeypatch.setattr(q.corpus, 'validate_panel', lambda *a, **k: opened.append(a))
    with pytest.raises(ValueError): q.score(freeze, replay, tmp_path/'score.json')
    assert not opened and not (tmp_path/'score.json').exists()


def test_bad_admitted_metric_fails_before_any_fresh_reference_read(tmp_path, monkeypatch):
    source, row, cp, src, value = sample(); sealed_opens = []
    objects = {'manifest': {'artifacts': {'train_targets':'train', 'tuning_targets':'tune',
        'train_groups':'groups', 'tuning_groups':'groups', 'fresh_annotation_ledger':'sealed',
        'exposure_audit':'sealed', 'fresh_targets':'sealed', 'multi_fresh_targets':'sealed'}},
        'train': [{**source, 'label':'norm'}], 'tune': [{**source, 'label':'norm'}], 'groups': []}
    reported = q.runner.metrics([row], objects['train']); reported['correct'] = 99
    trial = {'arm':'frozen_occurrence', 'seed':1730, 'initial_checkpoint':cp,
             'initial_evaluation':{'training':{'generation':'saved', 'metrics':reported}}}
    initial_value = copy.deepcopy(value); initial_value['model']['steps'] = 0; objects['saved'] = initial_value
    freeze_path = tmp_path/'freeze.json'; freeze_pin = q.write(freeze_path, {'sources':{'training':src,'tuning':src}})
    replay_path = tmp_path/'replay.json'; q.write(replay_path, {
        'schema':'legal-temporal-owner-type-independent-replay/v1', 'exact_replay':True,
        'generation_freeze':freeze_pin, 'fresh_references_opened':False, 'fresh_reference_guard':{'premature_read_attempts':0},
        'producer_files':[], 'replays':[], 'encoder_batch_forwards':0, 'encoder_source_evaluations':0})
    original_read = q.read
    def read(pin):
        if pin == 'sealed':
            sealed_opens.append(pin); raise AssertionError('fresh references opened too early')
        return objects[pin] if isinstance(pin, str) else original_read(pin)
    monkeypatch.setattr(q, 'read', read)
    monkeypatch.setattr(q, 'inventory', lambda f: ({'corpus_manifest':'manifest'}, {'frozen_occurrence-1730':trial},
        {'training':[source], 'tuning':[source]}, {}, {'physical_fresh_encoder_batch_forwards':0, 'physical_fresh_query_rows':0}))
    monkeypatch.setattr(q.corpus, 'validate_panel', lambda *a, **k: None)
    monkeypatch.setattr(q.corpus, 'source_row', lambda r: {k:r[k] for k in q.metric.SOURCE_KEYS})
    with pytest.raises(ValueError, match='independent metric differs: correct'):
        q.score(freeze_path, replay_path, tmp_path/'result.json')
    assert not sealed_opens
