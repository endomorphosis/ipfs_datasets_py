"""Single-width assembly; doubles never stand in for native campaign evidence."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs_single as single
from .test_fresh_scalar_source_inputs import plan, fake_reports, resign


@pytest.mark.parametrize('dimension', [8, 384, 768])
def test_single_width_matches_original_lane_without_fabricating_others(monkeypatch, dimension):
    source_plan = plan()
    reports = fake_reports(monkeypatch, source_plan)
    original = single.source.assemble(source_plan, reports)
    before = deepcopy(reports)
    result = single.assemble(source_plan, reports[str(dimension)], dimension=dimension)
    assert reports == before
    assert result['schema'] == single.SCHEMA and result['dimension'] == dimension
    assert 'dimensions' not in result
    for key in ('rows', 'clause_cache', 'source_contexts', 'representation', 'production_sha256'):
        assert result[key] == original['dimensions'][str(dimension)][key]
    assert result['inputs_sha256'] == single.source.digest({k:v for k,v in result.items() if k != 'inputs_sha256'})
    assert all(result[k] is False for k in single.source.FALSE)
    result['rows'][0]['input'][0] = 9
    assert reports == before


@pytest.mark.parametrize('dimension', [True, 0, 383, '384'])
def test_explicit_supported_width_required_before_report_access(dimension):
    with pytest.raises(ValueError, match='explicit native source dimension'):
        single.assemble(None, None, dimension=dimension)


def test_saved_width_cannot_be_relabelled(monkeypatch):
    source_plan = plan()
    report = fake_reports(monkeypatch, source_plan)['384']
    with pytest.raises(ValueError, match='dimension differs'):
        single.assemble(source_plan, report, dimension=768)


@pytest.mark.parametrize('change', ['source', 'tokens', 'vector', 'flag'])
def test_rehashed_corruption_still_reaches_original_native_contract(monkeypatch, change):
    source_plan = plan()
    report = fake_reports(monkeypatch, source_plan)['384']
    if change == 'source':
        report['vectors'][0]['source_sha256'] = 'f' * 64
    elif change == 'tokens':
        report['vectors'][0]['token_count'] = 513
    elif change == 'vector':
        report['vectors'][0]['vector'][0] = 2.
    else:
        report['transforms_fitted'] = True
    resign(report)
    with pytest.raises(ValueError):
        single.assemble(source_plan, report, dimension=384)


def test_native_binding_rejection_propagates_before_context_assembly(monkeypatch):
    source_plan = plan()
    report = fake_reports(monkeypatch, source_plan)['384']
    def refuse(*args):
        raise ValueError('native vector differs')
    monkeypatch.setattr(single.source, '_validate_native_binding', refuse)
    monkeypatch.setattr(single.clauses, 'build_source_contexts', lambda *a: pytest.fail('invalid report assembled'))
    with pytest.raises(ValueError, match='native vector differs'):
        single.assemble(source_plan, report, dimension=384)
