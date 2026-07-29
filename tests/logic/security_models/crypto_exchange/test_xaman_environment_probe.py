"""Tests for PORTAL-CXTP-061 Xaman environment probe."""

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
    / 'probe_xaman_environment.py'
)
MANIFEST_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'source-manifest.json'
SOLVER_PROBE_PATH = REPO_ROOT / 'security_ir_artifacts' / 'environment' / 'solver-dependency-probe.json'
ARTIFACT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'environment-probe.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_environment_assumptions.md'


def _load_script_module():
    spec = importlib.util.spec_from_file_location('probe_xaman_environment', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Xaman environment probe')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _fixture_manifest() -> dict:
    return {
        'schema_version': 'xaman-corpus-source-manifest/v1',
        'source': {
            'repo_url': 'https://github.com/XRPL-Labs/Xaman-App',
            'commit_sha': '942f43876265a7af44f233288ad2b1d00841d5fa',
        },
        'files': [
            {'path': 'package.json'},
            {'path': 'package-lock.json'},
            {'path': 'tsconfig.json'},
            {'path': 'tsconfig.jest.json'},
            {'path': 'metro.config.js'},
            {'path': 'babel.config.js'},
            {'path': '.detoxrc.js'},
            {'path': '.github/workflows/e2e.yml'},
            {'path': 'e2e/signing.e2e.ts'},
            {'path': 'android/app/build.gradle'},
            {'path': 'android/app/src/main/java/libs/security/vault/VaultManagerModule.java'},
            {'path': 'ios/Podfile.lock'},
            {'path': 'Xaman.xctestplan'},
            {'path': 'LICENSE'},
            {'path': 'RESPONSIBLE-DISCLOSURE.md'},
        ],
        'dependency_lockfiles': [{'path': 'package-lock.json'}, {'path': 'ios/Podfile.lock'}],
        'license_files': [{'path': 'LICENSE'}],
        'security_disclosure_files': [{'path': 'RESPONSIBLE-DISCLOSURE.md'}],
    }


def _solver_probe(blocked: bool = False) -> dict:
    return {
        'overall_status': 'blocked' if blocked else 'ready',
        'proof_acceptance_blocked': blocked,
        'dependencies': [
            {'name': 'node', 'status': 'present', 'executable': '/bin/node', 'version': '24.0.0', 'required': True},
            {'name': 'npm', 'status': 'present', 'executable': '/bin/npm', 'version': '11.0.0', 'required': True},
            {'name': 'typescript', 'status': 'present', 'executable': '/bin/tsc', 'version': '5.5.4', 'required': True},
            {'name': 'z3', 'status': 'present', 'executable': '/bin/z3', 'version': '4.16.0', 'required': True},
            {'name': 'cvc5', 'status': 'present', 'executable': '/bin/cvc5', 'version': '1.3.2', 'required': True},
            {'name': 'apalache', 'status': 'missing', 'required': False},
            {'name': 'tamarin', 'status': 'missing', 'required': False},
            {'name': 'proverif', 'status': 'missing', 'required': False},
            {'name': 'lean', 'status': 'present', 'executable': '/bin/lean', 'version': '4.31.0', 'required': False},
            {'name': 'coq', 'status': 'missing', 'required': False},
        ],
    }


def test_fixture_manifest_and_ready_solver_probe_produce_ready_report(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest = tmp_path / 'manifest.json'
    solver = tmp_path / 'solver.json'
    _write_json(manifest, _fixture_manifest())
    _write_json(solver, _solver_probe())

    report = module.build_report(
        repo_root=tmp_path,
        corpus_manifest_path=manifest,
        solver_probe_path=solver,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['schema_version'] == 'xaman-environment-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-061'
    assert report['overall_status'] == 'ready'
    assert report['summary']['native_android_present'] is True
    assert report['summary']['native_ios_present'] is True
    assert report['summary']['detox_e2e_present'] is True
    assert report['summary']['typescript_ready'] is True
    assert {warning['solver'] for warning in report['warnings']} == {
        'apalache',
        'tamarin',
        'proverif',
        'coq',
    }


def test_missing_required_build_files_block(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest = _fixture_manifest()
    manifest['files'] = [{'path': 'package.json'}]
    manifest_path = tmp_path / 'manifest.json'
    solver_path = tmp_path / 'solver.json'
    _write_json(manifest_path, manifest)
    _write_json(solver_path, _solver_probe())

    report = module.build_report(
        repo_root=tmp_path,
        corpus_manifest_path=manifest_path,
        solver_probe_path=solver_path,
    )

    assert report['overall_status'] == 'blocked'
    codes = {blocker['code'] for blocker in report['blockers']}
    assert 'XAMAN_REQUIRED_BUILD_FILE_MISSING' in codes


def test_checked_in_environment_probe_is_ready_for_pinned_xaman_manifest() -> None:
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'xaman-environment-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-061'
    assert report['overall_status'] == 'ready'
    assert report['corpus_manifest']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert report['summary']['native_android_present'] is True
    assert report['summary']['native_ios_present'] is True
    assert report['summary']['typescript_ready'] is True


def test_cli_writes_environment_probe(tmp_path: Path) -> None:
    module = _load_script_module()
    out = tmp_path / 'environment-probe.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--corpus-manifest',
            MANIFEST_PATH.as_posix(),
            '--solver-probe',
            SOLVER_PROBE_PATH.as_posix(),
            '--out',
            out.as_posix(),
        ]
    )

    report = json.loads(out.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['overall_status'] == 'ready'
    assert report['summary']['file_count'] > 100


def test_document_records_probe_inputs_and_validation_command() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-061' in doc
    assert 'source-manifest.json' in doc
    assert 'environment-probe.json' in doc
    assert 'probe_xaman_environment.py' in doc
