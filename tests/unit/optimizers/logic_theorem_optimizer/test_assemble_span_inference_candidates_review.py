"""Fictional byte fixtures for four experiment joins; no model execution."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).absolute().parents[6]
SOURCE = WORKSPACE/'artifacts/codebase_ir_terminal_bench/assemble_span_inference_candidates_review_20261004.py'
SOURCE_SHA = 'a483d4d80378c63aa4101a2e9eddc27bf3e7860f051eccb793a478f59349fb3b'


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA
    spec = importlib.util.spec_from_file_location('_span_review_controls', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert SOURCE.read_bytes() == raw
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    source = tmp_path/'current.py'; source.write_text('pass\n')
    source_pin = {'path': str(source), 'bytes': 5, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    selected, results, audits, dirs, records = {}, [], [], {}, []

    def save(path, value):
        target = tmp_path/path; target.parent.mkdir(parents=True, exist_ok=True)
        encoded = module.wire(value)
        if target.exists(): target.chmod(0o600)
        target.write_bytes(encoded); target.chmod(0o444)
        pin = {'path': path, 'bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()}
        selected[path] = pin
        return pin

    for dimension, cohort in ((768, 'A'), (768, 'B'), (4096, 'A'), (4096, 'B')):
        namespace = f'archive-{dimension}-{cohort}'
        result = {'schema': module.RESULT_SCHEMA, 'qualified': True, 'error': None,
            'dimension': dimension, 'cohort': cohort, 'selected_existing_profile_changed': False,
            'public_return_count': 126, 'complete_four_logit_snapshot_count': 126, 'timed_return_count': 108,
            'actual_cuda_execution': True,
            **dict.fromkeys(('performance_qualified', 'production_qualified', 'proof_authority',
                'execution_attestation', 'native_leanstral_outputs_qualified', 'trained4096_qualification_established',
                'encoder_execution_performed', 'native_due_renewal_qualified', 'native_lease_expiry_qualified'), False),
            **dict.fromkeys(('new_training_fits', 'optimizer_steps', 'optimizer_constructor_calls', 'training_mode_true_calls'), 0)}
        result_path = namespace+'/result.json'; result_pin = save(result_path, result)
        absolute = {**result_pin, 'path': str(tmp_path/result_path)}
        audit = {'schema': module.AUDIT_SCHEMA, 'qualified': True, 'closed_artifacts_consistent': True,
            'error': None, 'dimension': dimension, 'cohort': cohort,
            'check_current_sources': True, 'current_sources_verified': True, 'current_source_pins': [source_pin],
            'public_reports': 126, 'complete_four_logit_snapshots': 126, 'timed_public_reports': 108,
            'expected_result_sha256': result_pin['sha256'], 'result_pin': absolute,
            'retained_pins': [absolute], 'bounded_archive_files': 1, 'bounded_archive_bytes': result_pin['bytes'],
            'performance_qualified': False, 'production_qualified': False, 'proof_authority': False, 'execution_attestation': False}
        audit_path = f'audit-{dimension}-{cohort}.json'
        audit_pin = save(audit_path, audit)
        dirs[f'experiment_{dimension}_{cohort}'] = namespace
        results.append(result_pin); audits.append(audit_pin)
        records.append((result_path, result, audit_path, audit))

    def joins():
        return module.audit_result_joins(audits, results, selected, dirs)

    def result_change(key, value):
        path, result, audit_path, audit = records[0]
        result = deepcopy(result); result[key] = value
        new_pin = save(path, result); results[0] = new_pin
        audit = deepcopy(audit)
        audit.update(expected_result_sha256=new_pin['sha256'], result_pin={**new_pin, 'path': str(tmp_path/path)},
                     retained_pins=[{**new_pin, 'path': str(tmp_path/path)}], bounded_archive_bytes=new_pin['bytes'])
        audits[0] = save(audit_path, audit)

    def audit_change(key, value):
        _, _, path, audit = records[0]
        audit = deepcopy(audit); audit[key] = value
        audits[0] = save(path, audit)

    return module, joins, result_change, audit_change, source, results, audits, selected, dirs


def test_four_experiments_join_independent_of_audit_order(fixture):
    _, joins, _, _, _, _, audits, _, _ = fixture
    audits.reverse()
    values, inventories = joins()
    assert {(item['dimension'], item['cohort']) for item in values} == {(768, 'A'), (768, 'B'), (4096, 'A'), (4096, 'B')}
    assert len(inventories) == 4 and all(len(items) == 1 for items in inventories.values())


@pytest.mark.parametrize('key,value', [('dimension', True), ('dimension', 768.), ('dimension', 4096),
    ('dimension', 384), ('cohort', 'B'), ('cohort', False), ('cohort', 'C')])
def test_experiment_identity_must_cover_both_dimensions_twice(fixture, key, value):
    _, joins, change, *_ = fixture
    change(key, value)
    with pytest.raises(ValueError): joins()


@pytest.mark.parametrize('key', ['public_return_count', 'complete_four_logit_snapshot_count', 'timed_return_count'])
@pytest.mark.parametrize('value', [True, 0, 126., 125, None])
def test_producer_coverage_is_plain_and_complete(fixture, key, value):
    _, joins, change, *_ = fixture
    change(key, value)
    with pytest.raises(ValueError): joins()


@pytest.mark.parametrize('key', ['public_reports', 'complete_four_logit_snapshots', 'timed_public_reports'])
@pytest.mark.parametrize('value', [True, 0, 126., 125, None])
def test_audit_coverage_is_plain_and_complete(fixture, key, value):
    _, joins, _, change, *_ = fixture
    change(key, value)
    with pytest.raises(ValueError): joins()


@pytest.mark.parametrize('key', ['new_training_fits', 'optimizer_steps', 'optimizer_constructor_calls', 'training_mode_true_calls'])
@pytest.mark.parametrize('value', [False, 0., 1, None])
def test_no_new_training_or_adam_claim_is_plain_zero(fixture, key, value):
    _, joins, change, *_ = fixture
    change(key, value)
    with pytest.raises(ValueError): joins()


@pytest.mark.parametrize('key', ['native_due_renewal_qualified', 'native_lease_expiry_qualified',
    'encoder_execution_performed', 'trained4096_qualification_established', 'native_leanstral_outputs_qualified',
    'performance_qualified', 'production_qualified', 'proof_authority', 'execution_attestation', 'selected_existing_profile_changed'])
def test_result_authority_cannot_be_upgraded(fixture, key):
    _, joins, change, *_ = fixture
    change(key, True)
    with pytest.raises(ValueError): joins()


@pytest.mark.parametrize('key,value', [('dimension', True), ('dimension', 768.), ('dimension', 4096),
    ('cohort', 'B'), ('cohort', False), ('check_current_sources', False), ('current_sources_verified', False),
    ('expected_result_sha256', '0'*64), ('bounded_archive_files', True), ('bounded_archive_bytes', 0),
    ('current_source_pins', []), ('retained_pins', [])])
def test_audit_scope_and_inventory_must_join_selected_result(fixture, key, value):
    _, joins, _, change, *_ = fixture
    change(key, value)
    with pytest.raises(ValueError): joins()


def test_nested_authority_and_current_source_byte_change_refused(fixture):
    _, joins, _, change, source, *_ = fixture
    change('extra', {'proof_authority': True})
    with pytest.raises(ValueError): joins()
    change('extra', {'proof_authority': False})
    source.write_text('fail\n')
    with pytest.raises(ValueError, match='current source bytes'): joins()


@pytest.mark.parametrize('group', ['results', 'audits'])
def test_four_distinct_archives_are_required(fixture, group):
    module, _, _, _, _, results, audits, selected, dirs = fixture
    values = results if group == 'results' else audits
    values.pop()
    with pytest.raises(ValueError, match='four distinct'):
        module.audit_result_joins(audits, results, selected, dirs)
