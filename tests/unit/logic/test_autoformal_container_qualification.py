"""Negative transport qualification is not a passing proof or repair."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def qualifier():
    scripts = Path(__file__).resolve().parents[3] / 'scripts/ops/legal_ir'
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location('container_qualification_test', scripts / 'qualify_autoformal_container_validator.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(scripts))


@pytest.fixture
def results():
    metadata = json.dumps({'sealed_container_dependencies': {'passed': True}}) + '\n'
    first = {'returncode': 2, 'output': metadata + 'task-owned regression test is missing or a symlink'}
    baseline = {'returncode': 1, 'output': metadata + json.dumps({
        'passed': False, 'gate': 'extended_structural_roundtrip_not_legal_equivalence',
        'admitted': False, 'formalized': False, 'checked_count': 11,
        'failures': [{'case': 'sealed_source', 'passed': False, 'reason': 'structured_slots_differ_or_abstain'}]})}
    rejected = {'returncode': 75, 'error': 'external_validation_isolation_unavailable',
                'reason': 'sealed container command or image differs from binding'}
    return first, baseline, rejected


def test_only_expected_negative_replay_qualifies(qualifier, results):
    assert all(qualifier.observed_checks(*results).values())


@pytest.mark.parametrize('fault', ['not_run', 'returncode', 'generic_failure', 'no_dependencies', 'malformed_marker', 'changed_command_ran'])
def test_missing_or_generic_failure_is_not_qualification(qualifier, results, fault):
    first, replay, rejected = results
    if fault == 'not_run':
        replay.clear()
        replay.update(attempted=False, passed=True, reason='not_run')
    elif fault == 'returncode':
        replay['returncode'] = 0
    elif fault == 'generic_failure':
        replay['output'] = json.dumps({'passed': False})
    elif fault == 'no_dependencies':
        first['output'] = 'task-owned regression test is missing or a symlink'
    elif fault == 'malformed_marker':
        first['output'] = json.dumps({'sealed_container_dependencies': True})
    else:
        rejected['returncode'] = 0
    assert not all(qualifier.observed_checks(first, replay, rejected).values())


@pytest.mark.parametrize('fault', ['', 'wrong_source', 'wrong_gate', 'empty_failures', 'admitted', 'generic_failure'])
def test_baseline_gate_requires_selected_source_failure(qualifier, results, fault):
    first, replay, rejected = results
    data = {'passed': False, 'gate': 'source_replay_not_legal_equivalence',
            'admitted': False, 'formalized': False, 'checked_count': 4,
            'failures': [{'id': 'sha256:selected-source', 'reason': 'dropped_clause'}]}
    if fault == 'wrong_source':
        data['failures'][0]['id'] = 'sha256:preserved-source'
    elif fault == 'wrong_gate':
        data['gate'] = 'extended_structural_roundtrip_not_legal_equivalence'
    elif fault == 'empty_failures':
        data['failures'] = []
    elif fault == 'admitted':
        data['admitted'] = True
    elif fault == 'generic_failure':
        data = {'passed': False, 'error': 'pytest failed'}
    replay['output'] = json.dumps({'sealed_container_dependencies': {'passed': True}}) + '\n' + json.dumps(data)
    checks = qualifier.observed_checks(first, replay, rejected, source_span_id='sha256:selected-source')
    assert all(checks.values()) is (not fault)


def test_extension_replay_cannot_qualify_a_baseline_task(qualifier, results):
    assert not all(qualifier.observed_checks(*results, source_span_id='sha256:selected-source').values())
