from copy import deepcopy
import pytest
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as experiment
from scripts.ops.legal_ir import verify_legal_clause_boundary_experiment as subject
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary


def fixture():
    gold = experiment.authored_document('test', 0)
    tokens = boundary.tokenize(gold['source_text'])
    ends = [i for i, t in enumerate(tokens) if t['char_end'] in {r['char_end'] for r in gold['clauses']}]
    plan = boundary.source_plan(experiment.source_rows([gold])[0], tokens, ends)
    prediction = {'candidate_id': gold['candidate_id'], 'source_sha256': gold['source_sha256'], 'status': 'segmented',
        'target_access': False, 'boundary_token_indices': ends, 'predicted_rule_count': len(ends),
        'boundary_logits': [1. if i in ends else -1. for i in range(len(tokens))], 'plan': plan,
        'raw_learned_scope_supported': True, 'reason': None}
    return {'rows': [prediction]}, [gold]


def test_independent_counts_preserve_repeat_occurrences():
    value = subject.independent_counts(*fixture())
    assert value['reference_rule_occurrences'] == 3
    assert value['repeated_documents_exact'] == value['exact_supported_segmentation'] == 1


@pytest.mark.parametrize('mutation', ['dropped', 'logit', 'source', 'partial_abstention'])
def test_mutated_boundary_receipts_or_partial_documents_are_rejected(mutation):
    generation, references = fixture()
    row = generation['rows'][0]
    if mutation == 'dropped':
        row['boundary_token_indices'].pop()
    elif mutation == 'logit':
        row['boundary_logits'][row['boundary_token_indices'][0]] = -1.
    elif mutation == 'source':
        row['source_sha256'] = 'f' * 64
    else:
        row['status'] = 'abstained'
    with pytest.raises(ValueError):
        subject.independent_counts(generation, references)
