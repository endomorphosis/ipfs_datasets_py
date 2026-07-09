"""Tests for PORTAL-CXTP-085 — production evidence intake scaffold.

Covers the evidence-bundle JSON Schema, the fail-closed validator script,
and the accompanying documentation.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'validate_production_evidence_bundle.py'
)
SCHEMA_PATH = REPO_ROOT / 'security_ir_artifacts' / 'production' / 'evidence-bundle.schema.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'production_evidence_intake.md'


def _load_script_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        'validate_production_evidence_bundle',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load production evidence bundle validator')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def module() -> types.ModuleType:
    return _load_script_module()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _valid_bundle(module: types.ModuleType, repo_root: Path) -> dict:
    return module.build_example_bundle(repo_root=repo_root, task_id='PORTAL-CXTP-077')


# ---------------------------------------------------------------------------
# Schema file checks
# ---------------------------------------------------------------------------


def test_schema_file_is_valid_json_schema_2020_12() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['title'].startswith('Production Evidence Bundle')
    required_top_level = set(schema['required'])
    assert required_top_level == {
        'schema_version',
        'task_id',
        'bundle_id',
        'generated_at_utc',
        'freshness_policy',
        'source_snapshots',
        'environment_evidence',
        'runtime_traces',
        'owner_signoff',
        'solver_reports',
    }
    assert schema['properties']['schema_version']['const'] == 'production-evidence-bundle/v1'

    jsonschema = pytest.importorskip('jsonschema')
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_defines_review_status_and_outcome_vocabularies() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))

    assert set(schema['$defs']['reviewStatus']['enum']) == {
        'heuristic',
        'machine_extracted',
        'human_reviewed',
        'trusted_fixture',
    }
    assert set(schema['$defs']['solverReportItem']['allOf'][1]['properties']['outcome']['enum']) == {
        'prove',
        'disprove',
        'unknown',
        'not-modeled',
        'stale-evidence',
        'missing-solver',
        'blocked-production',
    }


# ---------------------------------------------------------------------------
# Example bundle generation + happy path validation
# ---------------------------------------------------------------------------


def test_write_example_produces_bundle_conforming_to_schema(tmp_path: Path, module: types.ModuleType) -> None:
    out_path = tmp_path / 'example-bundle.json'

    rc = module.main(
        [
            '--repo-root', REPO_ROOT.as_posix(),
            '--write-example', out_path.as_posix(),
            '--example-task-id', 'PORTAL-CXTP-078',
        ]
    )

    assert rc == 0
    bundle = json.loads(out_path.read_text(encoding='utf-8'))
    assert bundle['schema_version'] == 'production-evidence-bundle/v1'
    assert bundle['task_id'] == 'PORTAL-CXTP-078'

    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    jsonschema.validate(bundle, schema)


def test_example_bundle_passes_validation_with_no_blockers(tmp_path: Path, module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    out_path = tmp_path / 'report.json'
    bundle_path = tmp_path / 'bundle.json'
    bundle_path.write_text(json.dumps(bundle), encoding='utf-8')

    rc = module.main(
        [
            '--repo-root', REPO_ROOT.as_posix(),
            '--bundle', bundle_path.as_posix(),
            '--out', out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['overall_status'] == 'pass'
    assert report['production_release_blocked'] is False
    assert report['security_decision'] == 'PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED'
    assert report['blockers'] == []
    assert report['task_id'] == 'PORTAL-CXTP-085'
    for category in module.EVIDENCE_CATEGORIES:
        assert report['summary']['categories'][category]['item_count'] >= 1
        assert report['summary']['categories'][category]['blocker_count'] == 0


def test_example_bundle_covers_every_blocking_and_high_release_claim(module: types.ModuleType) -> None:
    from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
        release_policy_entries,
    )

    bundle = _valid_bundle(module, REPO_ROOT)
    covered = {report['claim_id'] for report in bundle['solver_reports']}
    required = {
        entry.claim_id
        for entry in release_policy_entries()
        if entry.release_gate in ('blocking', 'high')
    }

    assert required.issubset(covered)
    assert all(report['outcome'] == 'prove' for report in bundle['solver_reports'])


# ---------------------------------------------------------------------------
# Fail-closed structural checks
# ---------------------------------------------------------------------------


def test_missing_category_blocks_with_category_empty_or_missing(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    del bundle['runtime_traces']

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_PRODUCTION_EVIDENCE_INTAKE'
    codes = {b['code'] for b in report['blockers']}
    assert 'CATEGORY_EMPTY_OR_MISSING' in codes


def test_wrong_schema_version_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['schema_version'] = 'production-evidence-bundle/v0'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'BUNDLE_SCHEMA_VERSION_MISMATCH' in codes


def test_missing_freshness_policy_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    del bundle['freshness_policy']

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'BUNDLE_FRESHNESS_POLICY_MISSING' in codes


def test_item_missing_required_field_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    del bundle['source_snapshots'][0]['commit']

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'EVIDENCE_ITEM_FIELD_MISSING')
    assert blocker['category'] == 'source_snapshots'
    assert 'commit' in blocker['fields']


# ---------------------------------------------------------------------------
# File existence / digest checks
# ---------------------------------------------------------------------------


def test_evidence_file_missing_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['environment_evidence'][0]['path'] = 'security_ir_artifacts/production/does-not-exist.json'
    bundle['environment_evidence'][0]['sha256'] = None

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'EVIDENCE_FILE_MISSING')
    assert blocker['category'] == 'environment_evidence'


def test_evidence_digest_mismatch_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['source_snapshots'][0]['sha256'] = '0' * 64

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'EVIDENCE_DIGEST_MISMATCH')
    assert blocker['category'] == 'source_snapshots'
    assert blocker['expected_sha256'] == '0' * 64


# ---------------------------------------------------------------------------
# Review status checks
# ---------------------------------------------------------------------------


def test_unreviewed_evidence_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['source_snapshots'][0]['review_status'] = 'heuristic'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'EVIDENCE_NOT_REVIEWED')
    assert blocker['review_status'] == 'heuristic'


def test_invalid_review_status_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['source_snapshots'][0]['review_status'] = 'not-a-real-status'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'EVIDENCE_REVIEW_STATUS_INVALID' in codes


# ---------------------------------------------------------------------------
# Freshness checks
# ---------------------------------------------------------------------------


def test_stale_evidence_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat().replace('+00:00', 'Z')
    bundle['source_snapshots'][0]['collected_at_utc'] = stale_ts

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'EVIDENCE_STALE')
    assert blocker['category'] == 'source_snapshots'
    assert blocker['max_age_days'] == 30


def test_future_timestamp_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    future_ts = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat().replace('+00:00', 'Z')
    bundle['source_snapshots'][0]['collected_at_utc'] = future_ts

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'EVIDENCE_TIMESTAMP_IN_FUTURE' in codes


def test_unparseable_timestamp_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['source_snapshots'][0]['collected_at_utc'] = 'not-a-date'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'EVIDENCE_TIMESTAMP_INVALID' in codes


def test_now_override_yields_deterministic_freshness_evaluation(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    fixed_now = bundle['freshness_policy']['evaluated_at_utc']

    report = module.validate_bundle(
        bundle,
        repo_root=REPO_ROOT,
        now=module._parse_dt(fixed_now),
    )

    assert report['overall_status'] == 'pass'
    assert report['evaluated_at_utc'] == fixed_now


def test_runtime_trace_window_inverted_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    trace = bundle['runtime_traces'][0]
    trace['window_start_utc'], trace['window_end_utc'] = trace['window_end_utc'], trace['window_start_utc']
    trace['window_start_utc'] = (
        datetime.fromisoformat(trace['window_end_utc'].replace('Z', '+00:00')) + timedelta(hours=1)
    ).isoformat().replace('+00:00', 'Z')

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'RUNTIME_TRACE_WINDOW_INVERTED' in codes


# ---------------------------------------------------------------------------
# Owner signoff checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('decision', ['pending', 'rejected'])
def test_owner_signoff_not_approved_blocks(module: types.ModuleType, decision: str) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['owner_signoff'][0]['decision'] = decision

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'OWNER_SIGNOFF_NOT_APPROVED')
    assert blocker['decision'] == decision


# ---------------------------------------------------------------------------
# Solver report / release-policy cross-checks
# ---------------------------------------------------------------------------


def test_solver_outcome_unrecognized_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['solver_reports'][0]['outcome'] = 'maybe'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    codes = {b['code'] for b in report['blockers']}
    assert 'SOLVER_OUTCOME_UNRECOGNIZED' in codes


def test_blocking_claim_not_proved_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    for report_item in bundle['solver_reports']:
        if report_item['claim_id'] == 'no_unauthorized_withdrawal':
            report_item['outcome'] = 'unknown'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'BLOCKING_CLAIM_NOT_PROVED')
    assert blocker['claim_id'] == 'no_unauthorized_withdrawal'
    assert blocker['release_gate'] == 'blocking'


def test_blocking_claim_not_covered_blocks(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle['solver_reports'] = [
        report_item
        for report_item in bundle['solver_reports']
        if report_item['claim_id'] != 'global_asset_conservation'
    ]

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    assert report['overall_status'] == 'blocked'
    blocker = next(b for b in report['blockers'] if b['code'] == 'BLOCKING_CLAIM_NOT_COVERED')
    assert blocker['claim_id'] == 'global_asset_conservation'


def test_latest_solver_report_wins_when_claim_reported_more_than_once(module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    base = next(
        r for r in bundle['solver_reports'] if r['claim_id'] == 'no_unauthorized_withdrawal'
    )
    stale_bad = copy.deepcopy(base)
    stale_bad['id'] = 'solver-report-no_unauthorized_withdrawal-stale'
    stale_bad['outcome'] = 'disprove'
    stale_bad['collected_at_utc'] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat().replace('+00:00', 'Z')
    bundle['solver_reports'].append(stale_bad)

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    # The most recent report for the claim is still `prove`, so it should not block.
    codes = [b['code'] for b in report['blockers'] if b.get('claim_id') == 'no_unauthorized_withdrawal']
    assert 'BLOCKING_CLAIM_NOT_PROVED' not in codes


# ---------------------------------------------------------------------------
# CLI-level fail-closed behavior
# ---------------------------------------------------------------------------


def test_main_blocks_when_bundle_argument_missing(tmp_path: Path, module: types.ModuleType) -> None:
    out_path = tmp_path / 'report.json'

    rc = module.main(
        [
            '--repo-root', REPO_ROOT.as_posix(),
            '--out', out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 2
    assert report['overall_status'] == 'blocked'
    assert report['blockers'][0]['code'] == 'BUNDLE_ARGUMENT_MISSING'


def test_main_blocks_when_bundle_file_missing(tmp_path: Path, module: types.ModuleType) -> None:
    out_path = tmp_path / 'report.json'

    rc = module.main(
        [
            '--repo-root', REPO_ROOT.as_posix(),
            '--bundle', 'does/not/exist.json',
            '--out', out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 2
    assert report['blockers'][0]['code'] == 'BUNDLE_FILE_MISSING'


def test_main_blocks_when_schema_file_missing(tmp_path: Path, module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle_path = tmp_path / 'bundle.json'
    bundle_path.write_text(json.dumps(bundle), encoding='utf-8')
    out_path = tmp_path / 'report.json'

    rc = module.main(
        [
            '--repo-root', REPO_ROOT.as_posix(),
            '--bundle', bundle_path.as_posix(),
            '--schema', 'does/not/exist.schema.json',
            '--out', out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 2
    assert report['blockers'][0]['code'] == 'SCHEMA_FILE_MISSING'


def test_main_blocks_on_invalid_now_argument(tmp_path: Path, module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    bundle_path = tmp_path / 'bundle.json'
    bundle_path.write_text(json.dumps(bundle), encoding='utf-8')
    out_path = tmp_path / 'report.json'

    rc = module.main(
        [
            '--repo-root', REPO_ROOT.as_posix(),
            '--bundle', bundle_path.as_posix(),
            '--now', 'not-a-date',
            '--out', out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 2
    assert report['blockers'][0]['code'] == 'NOW_ARGUMENT_INVALID'


def test_main_prints_report_to_stdout_when_no_out_given(capsys, module: types.ModuleType) -> None:
    bundle = _valid_bundle(module, REPO_ROOT)
    fixed_now = bundle['freshness_policy']['evaluated_at_utc']
    bundle_path = REPO_ROOT / 'security_ir_artifacts' / 'production'
    # Write bundle next to the schema so relative evidence paths still resolve.
    tmp_bundle = bundle_path / '.tmp-test-bundle.json'
    tmp_bundle.write_text(json.dumps(bundle), encoding='utf-8')
    try:
        rc = module.main(
            [
                '--repo-root', REPO_ROOT.as_posix(),
                '--bundle', tmp_bundle.as_posix(),
                '--now', fixed_now,
            ]
        )
        captured = capsys.readouterr()
        printed = json.loads(captured.out)
        assert rc == 0
        assert printed['overall_status'] == 'pass'
    finally:
        tmp_bundle.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Documentation checks
# ---------------------------------------------------------------------------


def test_documentation_references_schema_validator_and_blocked_tasks() -> None:
    text = DOC_PATH.read_text(encoding='utf-8')

    assert 'security_ir_artifacts/production/evidence-bundle.schema.json' in text
    assert 'scripts/ops/security_verification/validate_production_evidence_bundle.py' in text
    for task_id in (
        'PORTAL-CXTP-077',
        'PORTAL-CXTP-078',
        'PORTAL-CXTP-079',
        'PORTAL-CXTP-080',
        'PORTAL-CXTP-081',
        'PORTAL-CXTP-082',
        'PORTAL-CXTP-083',
        'PORTAL-CXTP-084',
    ):
        assert task_id in text
    for category in (
        'source_snapshots',
        'environment_evidence',
        'runtime_traces',
        'owner_signoff',
        'solver_reports',
    ):
        assert category in text
    assert 'freshness_policy' in text
