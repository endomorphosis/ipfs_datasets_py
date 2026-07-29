"""Tests for PORTAL-CXTP-085 production evidence intake scaffold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

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


def _load_script_module():
    spec = importlib.util.spec_from_file_location('validate_production_evidence_bundle', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load production evidence bundle validator')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_bundle(module) -> dict:
    return module.build_example_bundle(repo_root=REPO_ROOT, task_id='PORTAL-CXTP-077')


def test_schema_file_is_json_schema_with_required_categories() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['title'] == 'Production Evidence Bundle'
    assert schema['properties']['schema_version']['const'] == 'production-evidence-bundle/v1'
    assert set(schema['required']) == {
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
    assert set(schema['$defs']['reviewStatus']['enum']) == {
        'heuristic',
        'machine_extracted',
        'human_reviewed',
        'trusted_fixture',
    }

    jsonschema = pytest.importorskip('jsonschema')
    jsonschema.Draft202012Validator.check_schema(schema)


def test_example_bundle_passes_fail_closed_validator() -> None:
    module = _load_script_module()
    report = module.validate_bundle(_valid_bundle(module), repo_root=REPO_ROOT)

    assert report['overall_status'] == 'pass'
    assert report['production_release_blocked'] is False
    assert report['security_decision'] == 'PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED'
    assert report['blockers'] == []


def test_missing_bundle_cli_writes_blocked_report(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'report.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--bundle',
            (tmp_path / 'missing.json').as_posix(),
            '--out',
            out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 2
    assert report['overall_status'] == 'blocked'
    assert report['production_release_blocked'] is True
    assert report['blockers'][0]['code'] == 'BUNDLE_FILE_MISSING'


def test_unreviewed_or_stale_evidence_blocks() -> None:
    module = _load_script_module()
    bundle = _valid_bundle(module)
    stale = datetime.now(timezone.utc) - timedelta(days=90)
    stale_text = stale.replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    bundle['source_snapshots'][0]['review_status'] = 'machine_extracted'
    bundle['environment_evidence'][0]['collected_at_utc'] = stale_text

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['overall_status'] == 'blocked'
    assert 'EVIDENCE_NOT_REVIEWED' in codes
    assert 'EVIDENCE_STALE' in codes


def test_missing_blocking_claim_or_non_prove_outcome_blocks() -> None:
    module = _load_script_module()
    bundle = _valid_bundle(module)
    removed = bundle['solver_reports'].pop()
    bundle['solver_reports'][0]['outcome'] = 'unknown'

    report = module.validate_bundle(bundle, repo_root=REPO_ROOT)

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['overall_status'] == 'blocked'
    assert 'BLOCKING_CLAIM_NOT_COVERED' in codes
    assert 'BLOCKING_CLAIM_NOT_PROVED' in codes
    assert removed['claim_id']


def test_cli_writes_example_bundle(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'example.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--write-example',
            out_path.as_posix(),
            '--example-task-id',
            'PORTAL-CXTP-078',
        ]
    )

    bundle = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert bundle['schema_version'] == 'production-evidence-bundle/v1'
    assert bundle['task_id'] == 'PORTAL-CXTP-078'
    assert bundle['solver_reports']


def test_document_covers_fail_closed_policy_and_commands() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-085' in doc
    assert 'production-evidence-bundle/v1' in doc
    assert 'validate_production_evidence_bundle.py' in doc
    assert 'PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED' in doc
    assert 'does not prove production is secure' in doc
