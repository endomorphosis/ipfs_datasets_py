"""Tests for PORTAL-CXTP-056 crypto_exchange source tree recovery evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'audit_crypto_exchange_source_tree.py'
)
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'recovery' / 'crypto-exchange-source-audit.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'crypto_exchange_recovery_report.md'


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location('audit_crypto_exchange_source_tree', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load source-tree audit script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_source_tree_audit_passes() -> None:
    module = _load_module()

    report = module.build_audit(REPO_ROOT)

    assert report['schema_version'] == 'crypto-exchange-source-tree-audit/v1'
    assert report['task_id'] == 'PORTAL-CXTP-056'
    assert report['overall_status'] == 'pass'
    assert report['proof_acceptance_blocked'] is False
    assert report['blockers'] == []
    assert report['summary']['present_required_source_count'] == report['summary']['required_source_count']
    assert report['summary']['present_required_test_count'] == report['summary']['required_test_count']


def test_checked_in_audit_report_matches_policy() -> None:
    assert REPORT_PATH.is_file()
    data = json.loads(REPORT_PATH.read_text(encoding='utf-8'))

    assert data['overall_status'] == 'pass'
    assert data['security_decision'] == 'CRYPTO_EXCHANGE_SOURCE_TREE_PRESENT'
    assert data['summary']['blocker_count'] == 0


def test_audit_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / 'source-audit.json'

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            '--repo-root',
            str(REPO_ROOT),
            '--out',
            str(out),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['overall_status'] == 'pass'


def test_recovery_report_links_audit_and_validation() -> None:
    text = DOC_PATH.read_text(encoding='utf-8')

    assert 'audit_crypto_exchange_source_tree.py' in text
    assert 'crypto-exchange-source-audit.json' in text
    assert 'test_crypto_exchange_source_tree_recovery.py' in text
