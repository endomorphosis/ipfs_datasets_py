"""Unmasked/grammar comparisons preserve exact source and invalid-output cohorts."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[5] / 'scripts/ops/autoencoder/evaluate_gte_grammar_controls.py'
spec = importlib.util.spec_from_file_location('_test_gte_grammar_controls', SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def rows():
    return [{'id': str(i), 'head': h, 'source_sha256': subject.digest(str(i)),
             'generation': {'generated_ids': ids}}
            for i, (h, ids) in enumerate([('primary384', [1, 2]), ('legacy8', [1, 0, 1])])]


def test_invalid_sequences_remain_in_comparison():
    baseline = rows()
    changed = deepcopy(baseline)
    changed[1]['generation']['generated_ids'] = [1, 5, 2]
    assert subject.compare_panel(changed, baseline) == 1


def test_order_does_not_change_pairing():
    baseline = rows()
    assert subject.compare_panel(list(reversed(baseline)), baseline) == 0


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'changed_source', 'changed_head'])
def test_cohort_mutation_rejected(case):
    baseline = rows()
    changed = deepcopy(baseline)
    if case == 'missing': changed.pop()
    if case == 'duplicate': changed[1] = deepcopy(changed[0])
    if case == 'changed_source': changed[0]['source_sha256'] = subject.digest('tampered')
    if case == 'changed_head': changed[0]['head'] = 'legacy8'
    with pytest.raises(ValueError, match='cohorts differ'):
        subject.compare_panel(changed, baseline)
