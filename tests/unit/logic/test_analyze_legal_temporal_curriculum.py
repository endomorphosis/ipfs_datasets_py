"""Failure-aware metrics and group-preserving comparisons."""
import copy

import pytest

from scripts.ops.legal_ir import analyze_legal_temporal_curriculum as analysis


def target(temporal=True):
    return {'canonical_ir': {'rules': [{'modality': 'O', 'actor': 'Board', 'action': 'file', 'object': 'notice',
        'conditions': ['permit active'], 'exceptions': [], 'temporal': ['within5days'] if temporal else []}]},
        'facet_spans': {'temporal': [0, 11] if temporal else None}}


def prediction(wanted):
    positive = bool(wanted['canonical_ir']['rules'][0]['temporal'])
    return {'status': 'decoded', 'canonical_ir': copy.deepcopy(wanted['canonical_ir']),
        'span_diagnostics': {'facets': {'temporal': {'present': positive,
            'char_start': 0 if positive else None, 'char_end': 11 if positive else None}}}}


@pytest.mark.parametrize('positive', [True, False])
def test_abstention_never_counts_as_correct_absence_or_coordinates(positive):
    row = analysis.temporal_record({'status': 'abstained'}, target(positive))
    assert row['temporal_presence'] == ('abstained_positive' if positive else 'abstained_negative')
    assert not any(row[k] for k in ('exact', 'temporal_value_exact', 'temporal_coordinate_exact',
        'temporal_condition_routing_exact', 'actor_exact', 'modality_exact'))


def test_copied_deadline_does_not_imply_correct_applicability_attachment():
    wanted = target()
    actual = prediction(wanted)
    actual['canonical_ir']['rules'][0]['conditions'] = []
    result = analysis.temporal_record(actual, wanted)
    assert result['temporal_value_exact'] and result['temporal_coordinate_exact']
    assert not result['temporal_condition_routing_exact'] and not result['exact']


def test_wrong_value_is_presence_true_positive_but_fidelity_failure():
    wanted = target(); actual = prediction(wanted)
    actual['canonical_ir']['rules'][0]['temporal'] = ['within9days']
    result = analysis.temporal_record(actual, wanted)
    assert result['temporal_presence'] == 'true_positive'
    assert result['temporal_failure'] == 'wrong_value' and not result['temporal_value_exact']


def test_presence_rates_retain_abstentions_and_separate_decoded_false_positives():
    positive, negative = target(), target(False)
    rows = [analysis.temporal_record(prediction(positive), positive),
        analysis.temporal_record({'status': 'abstained'}, positive),
        analysis.temporal_record(prediction(positive), negative),
        analysis.temporal_record({'status': 'abstained'}, negative)]
    totals = analysis.summarize_rows(rows)
    assert totals['presence_recall_all_positives'] == .5
    assert totals['correct_absence_rate_all_negatives'] == 0
    assert totals['false_positive_rate_decoded_negatives'] == 1
    assert totals['presence_confusion']['abstained_negative'] == 1


def slots(values):
    return [{'id': f'{group}-{variant}', 'seed': seed, 'case_group': group, 'exact': result}
        for group, result in values.items() for variant in range(6) for seed in analysis.SEEDS]


def test_bootstrap_clusters_variants_and_repeated_seeds_together():
    left, right = slots({'a': True, 'b': False}), slots({'a': False, 'b': True})
    result = analysis.paired_clusters(left, right)
    assert result['case_groups'] == 2 and result['slots_per_case_group'] == 18
    assert result['exact_rate_difference'] == 0
    assert result['case_group_bootstrap_95_percentile'] == [-1, 1]
    assert result['left_only_correct'] == result['right_only_correct'] == 18
    assert result == analysis.paired_clusters(left[::-1], right)


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'group'])
def test_pairing_rejects_invalid_identity_or_membership(mutation):
    left = slots({'a': True, 'b': False}); right = copy.deepcopy(left)
    if mutation == 'duplicate': right[-1] = right[0]
    elif mutation == 'missing': right.pop()
    else: right[0]['case_group'] = 'wrong'
    with pytest.raises(ValueError): analysis.paired_clusters(left, right)


def test_unfinished_qualification_never_opens_reference(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('reference opened')
    monkeypatch.setattr(analysis, 'read_ref', forbidden)
    with pytest.raises(ValueError, match='completed qualification'):
        analysis.analyze(tmp_path / 'run', tmp_path / 'qualification', tmp_path / 'output')


def test_cluster_ledger_rejects_wrong_source_split_and_duplicate_identity():
    ledger = [{'id': f'{group}-{variant}', 'case_group': str(group), 'variant': str(variant),
        'split': 'challenge', 'source_sha256': f'hash{group}-{variant}'} for group in range(30) for variant in range(6)]
    sources = [{k: row[k] for k in ('id', 'source_sha256')} for row in ledger]
    assert len(analysis.verify_membership(ledger, sources)) == 180
    wrong = copy.deepcopy(ledger); wrong[0]['split'] = 'train'
    with pytest.raises(ValueError, match='split'): analysis.verify_membership(wrong, sources)
    wrong = copy.deepcopy(ledger); wrong[-1] = wrong[0]
    with pytest.raises(ValueError, match='duplicate'): analysis.verify_membership(wrong, sources)


def test_artifact_binding_accepts_optional_size_but_verifies_recorded_size(tmp_path):
    path = tmp_path / 'receipt.json'; path.write_text('{}')
    reference = analysis.ref(path)
    minimal = {k: reference[k] for k in ('path', 'sha256')}
    assert analysis.verify_binding(minimal, reference) == {}
    with pytest.raises(ValueError, match='size'):
        analysis.verify_binding({**reference, 'bytes': reference['bytes'] + 1}, reference)
    with pytest.raises(ValueError, match='binding'):
        analysis.verify_binding({**minimal, 'sha256': 'wrong'}, reference)
