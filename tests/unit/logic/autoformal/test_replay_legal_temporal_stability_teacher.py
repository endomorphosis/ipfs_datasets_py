"""Teacher replay checks TRAIN provenance, exact cache values and zero authority."""
from copy import deepcopy
from functools import lru_cache
import hashlib

import pytest

from scripts.ops.legal_ir import replay_legal_temporal_stability_teacher as q


@lru_cache(None)
def fixture():
    targets = []
    for i in range(1632):
        text = f'Registry {i} shall file within 7 days of notice.'
        targets.append({'id': f'q-{i}', 'source_text': text,
            'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span': {'char_start': text.index('within'), 'char_end': text.index('.')},
            'label': q.frozen.metric.CLASSES[i % 4], 'group_id': f'g-{i//4}'})
    single, paired = targets[:768], targets[768:]
    parent = {'config': {'arm': 'mixed_occurrences', 'seed': 1730}, 'optimizer_steps': 200,
              'model_state': {'head': [1.]}}
    pin = {'path': '/parent.json', 'sha256': 'a'*64, 'bytes': 1}
    outputs = []
    for i, row in enumerate(targets):
        # Includes ordinary first-argmax ties: norm tie is correct, other ties are not.
        logits = [0.]*4 if i < 4 else [5. if j == i % 4 else 0. for j in range(4)]
        outputs.append({k: row[k] for k in ('id', 'source_sha256', 'proposed_time_span', 'label')} |
            {'logits': logits, 'correct': i == 0 or i >= 4})
    sources = [{k: row[k] for k in q.SOURCE_KEYS} for row in targets]
    cache = {'schema': 'legal-temporal-stability-teacher-cache/v1', 'implementation': {}, 'seed': 1730,
        'parent_file_sha256': pin['sha256'], 'parent_payload_sha256': q.digest(parent),
        'training_manifests': {name: {'sha256': q.digest(rows), 'count': len(rows)}
            for name, rows in (('single_training', single), ('prior_paired_training', paired))},
        'sources_sha256': q.digest(sources), 'class_order': list(q.frozen.metric.CLASSES),
        'batch_size': 48, 'rows': outputs,
        'teacher_state_before_sha256': q.digest(parent['model_state']),
        'teacher_state_after_sha256': q.digest(parent['model_state']),
        'teacher_requires_grad': False, 'teacher_gradients_absent': True,
        'encoder_batch_forwards': 34, 'encoder_source_evaluations': 1632,
        'labels_used_only_for_correctness_mask': True, 'new_placement_rows_included': False,
        **{key: False for key in q.frozen.metric.FALSE_FIELDS}}
    return cache, parent, single, paired, pin


def verify(cache):
    _, parent, single, paired, pin = fixture()
    return q.verify_cache(cache, parent, single, paired, seed=1730, parent_pin=pin, expected_implementation={})


def test_exact_old_inventory_first_argmax_ties_and_correctness_counts():
    sources, counts = verify(deepcopy(fixture()[0]))
    assert len(sources) == 1632
    assert counts == {'norm': 408, 'condition': 407, 'exception': 407, 'ambiguous': 407}
    assert all(set(row) == set(q.SOURCE_KEYS) for row in sources)


@pytest.mark.parametrize('change', [
    lambda c: c.update(seed=True), lambda c: c.update(batch_size=24),
    lambda c: c.update(encoder_batch_forwards=35), lambda c: c.update(encoder_source_evaluations=True),
    lambda c: c.update(parent_file_sha256='b'*64), lambda c: c.update(parent_payload_sha256='b'*64),
    lambda c: c.update(teacher_requires_grad=True), lambda c: c.update(teacher_gradients_absent=False),
    lambda c: c.update(teacher_state_after_sha256='b'*64), lambda c: c.update(new_placement_rows_included=True),
    lambda c: c.update(owner_occurrence_resolved=True), lambda c: c.update(labels_used_only_for_correctness_mask=False),
    lambda c: c['rows'][0].update(correct=1), lambda c: c['rows'][1].update(correct=True),
    lambda c: c['rows'][0].update(label='condition'), lambda c: c['rows'][0].update(source_sha256='b'*64),
    lambda c: c['rows'][0]['proposed_time_span'].update(char_start=True),
    lambda c: c['rows'][0]['logits'].__setitem__(0, 1e-8),
    lambda c: c['rows'][0]['logits'].__setitem__(0, float('nan')),
    lambda c: c['rows'][0]['logits'].__setitem__(0, 1e100),
    lambda c: c['rows'].__setitem__(slice(0,2), list(reversed(c['rows'][:2]))),
    lambda c: c['rows'].pop(), lambda c: c['rows'][0].update(semantic_owner=True),
])
def test_cache_metadata_row_identity_mask_precision_and_authority_mutations_fail(change):
    cache = deepcopy(fixture()[0]); change(cache)
    with pytest.raises(ValueError): verify(cache)


def test_training_manifest_hash_is_over_exact_ordered_targets():
    cache, parent, single, paired, pin = deepcopy(fixture())
    paired.reverse()
    with pytest.raises(ValueError, match='inventory differs'):
        q.verify_cache(cache, parent, single, paired, seed=1730, parent_pin=pin, expected_implementation={})


class ModelFixture:
    def __init__(self, cache):
        self.rows = {row['id']: row for row in cache['rows']}
        self.encoder_batch_forwards = self.encoder_source_evaluations = 0

    def predict_many(self, queries):
        assert all(set(row) == set(q.SOURCE_KEYS) for row in queries)
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(queries)
        result = []
        for source in queries:
            logits = self.rows[source['id']]['logits']; probabilities = q.frozen.metric.softmax(logits)
            chosen = max(range(4), key=probabilities.__getitem__)
            label = q.frozen.metric.CLASSES[chosen]; confidence = probabilities[chosen]
            accepted = label != 'ambiguous' and confidence >= .8
            result.append({k: source[k] for k in ('id', 'source_sha256', 'proposed_time_span')} |
                {'logits': logits, 'probabilities': probabilities, 'predicted_label': label, 'confidence': confidence,
                 'time_token_span': q.frozen.metric.validate_source(source), 'status': 'accepted' if accepted else 'deferred',
                 'owner_type': label if accepted else None,
                 'reason': None if accepted else 'predicted_ambiguous' if label == 'ambiguous' else 'below_fixed_confidence',
                 **{k: False for k in q.frozen.metric.FALSE_FIELDS}})
        return result


def test_exact_numerical_cache_replay_binds_every_source_and_counts_all_batches():
    cache = deepcopy(fixture()[0]); sources, _ = verify(cache)
    result = q.replay_cache_logits(cache, sources, ModelFixture(cache))
    assert result['encoder_batch_forwards'] == 34 and result['exact_rows'] == 1632


def test_one_exact_float32_ulp_logit_change_rejected_even_when_argmax_unchanged():
    cache = deepcopy(fixture()[0]); sources, _ = verify(cache); model = ModelFixture(deepcopy(cache))
    cache['rows'][4]['logits'][0] = 5.000000476837158
    verify(cache)
    with pytest.raises(ValueError, match='logits differ'):
        q.replay_cache_logits(cache, sources, model)


def test_numerical_replay_does_not_call_runtime_cache_validation(monkeypatch):
    cache = deepcopy(fixture()[0]); sources, _ = verify(cache)
    monkeypatch.setattr(q.runtime, 'validate_teacher_cache', lambda *a, **kw: pytest.fail('producer validator called'))
    monkeypatch.setattr(q.runtime, 'build_teacher_cache', lambda *a, **kw: pytest.fail('producer regeneration called'))
    q.replay_cache_logits(cache, sources, ModelFixture(cache))


@pytest.mark.parametrize('change', [
    lambda f: None,
    lambda f: f.update(encoder_batch_forwards=True),
    lambda f: f.update(optimizer_updates=1),
    lambda f: f['models'].pop('1731'),
    lambda f: f['fresh_reference_guard'].update(premature_read_attempts=False),
    lambda f: f.update(extra_release=True),
])
def test_wrapper_freeze_closes_inventory_counter_and_reference_phase(change):
    pin = {'path': '/config', 'sha256': 'a'*64, 'bytes': 1}
    config = {'parents': {'1730': {}, '1731': {}}}
    freeze = {'schema': 'legal-temporal-stability-teacher-cache-freeze/v1', 'config': pin,
        'parents': config['parents'], 'models': {'1730': {}, '1731': {}}, 'producer_pins': {},
        'encoder_batch_forwards': 68, 'encoder_source_evaluations': 3264, 'optimizer_updates': 0,
        'fresh_references_opened': False, 'fresh_reference_guard': {'premature_read_attempts': 0}}
    original = deepcopy(freeze); change(freeze)
    if freeze == original and type(freeze['fresh_reference_guard']['premature_read_attempts']) is int:
        q.verify_teacher_freeze(freeze, pin, config)
    else:
        with pytest.raises(ValueError): q.verify_teacher_freeze(freeze, pin, config)
