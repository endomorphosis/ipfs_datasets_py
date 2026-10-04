from copy import deepcopy
import hashlib

import pytest

from scripts.ops.legal_ir import analyze_legal_role_curriculum_tuning as analysis


def fixture():
    text = 'Agency must retain files.'
    full = text + '\n' + text
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
    rule = dict(actor='Agency', modality='O', action='retain', object='files', conditions=[], exceptions=[], temporal=[])
    clauses = [dict(char_start=0, char_end=len(text), rule=deepcopy(rule)),
               dict(char_start=len(text) + 1, char_end=len(full), rule=deepcopy(rule))]
    reference = dict(supported=True, candidate_id='duplicate', source_text=full, source_sha256=sha(full), clauses=clauses)
    plan = {'clauses': [dict(char_start=c['char_start'], char_end=c['char_end'], source_text=text, source_sha256=sha(text)) for c in clauses]}
    boundary = dict(candidate_id='duplicate', plan=plan)
    rows = [dict(status='decoded', reason=None, source_sha256=sha(text), canonical_ir={'rules': [deepcopy(rule)]}) for _ in clauses]
    prediction = dict(candidate_id='duplicate', source_sha256=sha(full), clause_generation={'rows': rows}, composition=None)
    return reference, boundary, prediction


def test_duplicate_rule_occurrences_are_not_collapsed():
    reference, boundary, prediction = fixture()
    prediction['clause_generation']['rows'][1]['canonical_ir']['rules'][0]['modality'] = 'P'
    rows = analysis.clause_failures(reference, boundary, prediction)
    assert [r['kind'] for r in rows] == ['clause_exact', 'wrong_canonical_facets']
    assert rows[1]['wrong_facets'] == {'modality': {'expected': 'O', 'actual': 'P'}}
    assert rows[0]['char_start'] != rows[1]['char_start']


def test_whole_composition_abstention_keeps_both_occurrences():
    reference, boundary, prediction = fixture()
    row = prediction['clause_generation']['rows'][1]
    row.update(status='abstained', canonical_ir=None, reason='ambiguous_span')
    rows = analysis.clause_failures(reference, boundary, prediction)
    assert rows[1]['kind'] == 'clause_abstention'
    assert rows[1]['reason'] == 'ambiguous_span'
    assert len(rows) == 2 and prediction['composition'] is None


@pytest.mark.parametrize('mutation', ['interval', 'clause_hash', 'document_hash', 'missing_report'])
def test_source_and_occurrence_misalignment_refused(mutation):
    reference, boundary, prediction = fixture()
    if mutation == 'interval': boundary['plan']['clauses'][1]['char_start'] -= 1
    elif mutation == 'clause_hash': prediction['clause_generation']['rows'][1]['source_sha256'] = '0' * 64
    elif mutation == 'document_hash': prediction['source_sha256'] = '0' * 64
    else: prediction['clause_generation']['rows'].pop()
    with pytest.raises(ValueError): analysis.clause_failures(reference, boundary, prediction)


def test_all_seven_facet_errors_survive_attribution():
    reference, boundary, prediction = fixture()
    rule = prediction['clause_generation']['rows'][0]['canonical_ir']['rules'][0]
    for key in analysis.FACETS: rule[key] = ['wrong'] if isinstance(rule[key], list) else 'wrong'
    result = analysis.clause_failures(reference, boundary, prediction)
    assert set(result[0]['wrong_facets']) == set(analysis.FACETS)


def test_family_denominator_includes_abstention_and_wrong_rule():
    reference, boundary, prediction = fixture()
    rows = prediction['clause_generation']['rows']
    rows[1].update(status='abstained', canonical_ir=None)
    targets = [{'id': str(i), 'canonical_ir': {'rules': [reference['clauses'][i]['rule']]}} for i in range(2)]
    labels = [{'id': str(i), 'source_sha256': row['source_sha256'], 'family': 'heading'} for i, row in enumerate(rows)]
    assert analysis.family_counts({'rows': rows}, targets, labels) == {
        'heading': {'count': 2, 'exact': 1, 'decoded': 1, 'abstained': 1}}
