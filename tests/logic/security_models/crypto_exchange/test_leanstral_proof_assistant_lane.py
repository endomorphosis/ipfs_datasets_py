"""Tests for PORTAL-CXTP-097 Leanstral proof-assistant lane."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'probe_leanstral_proof_assistant.py'
)
ARTIFACT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'environment' / 'leanstral-proof-assistant-report.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'leanstral_proof_assistant_lane.md'


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'probe_leanstral_proof_assistant',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Leanstral proof assistant probe')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _lean_report(status: str = 'ready', checked: bool = True) -> dict:
    return {
        'overall_status': status,
        'security_decision': 'OPTIONAL_SOLVER_LANE_READY' if status == 'ready' else 'BLOCK_OPTIONAL_SOLVER_LANE',
        'summary': {
            'proof_kernel_checked': checked,
            'lean_present': True,
            'lake_present': True,
        },
        'proof_kernel_check': {'status': 'checked' if checked else 'blocked'},
    }


def test_checked_in_artifact_is_advisory_and_offline_safe() -> None:
    payload = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert payload['schema_version'] == 'crypto-exchange-leanstral-proof-assistant-report/v1'
    assert payload['task_id'] == 'PORTAL-CXTP-097'
    assert payload['default_mode'] == 'probe-only-no-network'
    assert payload['acceptance_policy']['leanstral_is_proof_authority'] is False
    assert payload['acceptance_policy']['network_calls_by_default'] is False
    assert payload['summary']['prompt_count'] >= 3
    assert 'labs-leanstral-1-5' in payload['configuration']['approved_model_routes']
    assert 'labs-leanstral-2603' in payload['configuration']['approved_model_routes']


def test_unconfigured_model_degrades_but_generates_prompts(tmp_path: Path) -> None:
    module = _load_script_module()
    lean_report_path = tmp_path / 'lean.json'
    _write_json(lean_report_path, _lean_report())

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={},
        lean_report_path=lean_report_path,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'degraded'
    assert report['security_decision'] == 'DEGRADE_LEANSTRAL_ASSISTANT_UNCONFIGURED'
    assert report['summary']['configured'] is False
    assert report['summary']['lean_lane_ready'] is True
    assert report['proof_attempt_prompts']
    assert {blocker['code'] for blocker in report['blockers']} == {'LEANSTRAL_MODEL_NOT_CONFIGURED'}


def test_approved_route_with_ready_lean_lane_is_ready_advisory(tmp_path: Path) -> None:
    module = _load_script_module()
    lean_report_path = tmp_path / 'lean.json'
    _write_json(lean_report_path, _lean_report())

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={
            'IPFS_DATASETS_PY_LEANSTRAL_MODEL': 'labs-leanstral-1-5',
            'IPFS_DATASETS_PY_LLM_PROVIDER': 'openai',
        },
        lean_report_path=lean_report_path,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'ready-advisory'
    assert report['security_decision'] == 'LEANSTRAL_ASSISTANT_READY_ADVISORY'
    assert report['configuration']['configured_by_route'] is True
    assert report['summary']['prompt_count'] >= 3
    assert report['blockers'] == []


def test_configured_route_blocks_when_lean_verifier_is_not_ready(tmp_path: Path) -> None:
    module = _load_script_module()
    lean_report_path = tmp_path / 'lean.json'
    _write_json(lean_report_path, _lean_report(status='blocked', checked=False))

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'IPFS_DATASETS_PY_OPENAI_MODEL': 'labs-leanstral-2603'},
        lean_report_path=lean_report_path,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {blocker['code'] for blocker in report['blockers']} == {
        'LEAN_VERIFIER_NOT_READY_FOR_LEANSTRAL_OUTPUT'
    }


def test_local_weights_path_counts_as_configuration(tmp_path: Path) -> None:
    module = _load_script_module()
    weights = tmp_path / 'leanstral.weights'
    weights.write_text('fixture weights marker\n', encoding='utf-8')
    lean_report_path = tmp_path / 'lean.json'
    _write_json(lean_report_path, _lean_report())

    report = module.build_report(
        repo_root=tmp_path,
        environ={'IPFS_DATASETS_PY_LEANSTRAL_WEIGHTS': weights.as_posix()},
        lean_report_path=lean_report_path,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'ready-advisory'
    assert report['configuration']['configured_by_weights'] is True
    assert report['configuration']['local_weights']['sha256']


def test_cli_writes_report_with_ignore_env(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'leanstral.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--ignore-env',
            '--out',
            out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['overall_status'] in {'degraded', 'blocked'}
    assert report['default_mode'] == 'probe-only-no-network'


def test_document_names_routes_and_proof_authority_boundary() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-097' in doc
    assert 'labs-leanstral-1-5' in doc
    assert 'labs-leanstral-2603' in doc
    assert 'not the proof authority' in doc
    assert 'probe-only-no-network' in doc
