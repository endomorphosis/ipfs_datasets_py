#!/usr/bin/env python3
"""Audit the crypto_exchange source tree recovered for theorem-prover work."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCHEMA_VERSION = 'crypto-exchange-source-tree-audit/v1'
TASK_ID = 'PORTAL-CXTP-056'
DEFAULT_OUT = Path('security_ir_artifacts/recovery/crypto-exchange-source-audit.json')
PACKAGE_ROOT = Path('ipfs_datasets_py/logic/security_models/crypto_exchange')

REQUIRED_SOURCE_FILES = (
    '__init__.py',
    'assumption_registry.py',
    'prove_all.py',
    'release_policy.py',
    'claims/base.py',
    'claims/withdrawal.py',
    'claims/deposit.py',
    'claims/ledger.py',
    'claims/capability.py',
    'compilers/to_smtlib.py',
    'compilers/to_z3.py',
    'extractors/source_code_extractor.py',
    'extractors/xaman_source_extractor.py',
    'ir/schema.py',
    'ir/canonicalize.py',
    'ir/cid.py',
    'reports/proof_report.py',
    'runners/z3_runner.py',
    'runners/cvc5_runner.py',
)

REQUIRED_TEST_FILES = (
    'tests/logic/security_models/crypto_exchange/test_crypto_exchange_artifact_retention.py',
    'tests/logic/security_models/crypto_exchange/test_solver_dependency_probe.py',
    'tests/logic/security_models/crypto_exchange/test_ir_schema.py',
    'tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py',
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _source_entry(root: Path, rel_path: str) -> dict[str, Any]:
    path = root / PACKAGE_ROOT / rel_path
    present = path.is_file()
    entry: dict[str, Any] = {
        'path': _relative(path, root),
        'present': present,
        'required': True,
    }
    if present:
        text = path.read_text(encoding='utf-8', errors='replace')
        entry.update(
            {
                'size_bytes': path.stat().st_size,
                'sha256': _sha256(path),
                'line_count': text.count('\n') + (0 if text.endswith('\n') or not text else 1),
                'pycache_only': False,
            }
        )
    return entry


def build_audit(repo_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    package_root = root / PACKAGE_ROOT
    source_files = [_source_entry(root, rel_path) for rel_path in REQUIRED_SOURCE_FILES]
    test_entries = [
        {
            'path': path,
            'present': (root / path).is_file(),
            'required': True,
        }
        for path in REQUIRED_TEST_FILES
    ]

    discovered_sources = sorted(
        _relative(path, root)
        for path in package_root.rglob('*.py')
        if path.is_file()
    ) if package_root.is_dir() else []
    discovered_pyc = sorted(
        _relative(path, root)
        for path in package_root.rglob('*.pyc')
        if path.is_file()
    ) if package_root.is_dir() else []

    missing_sources = [entry['path'] for entry in source_files if not entry['present']]
    missing_tests = [entry['path'] for entry in test_entries if not entry['present']]
    source_only_missing = bool(missing_sources) and bool(discovered_pyc) and not discovered_sources
    blockers: list[dict[str, Any]] = []
    if not package_root.is_dir():
        blockers.append({'code': 'PACKAGE_ROOT_MISSING', 'path': PACKAGE_ROOT.as_posix()})
    if missing_sources:
        blockers.append({'code': 'REQUIRED_SOURCE_FILES_MISSING', 'paths': missing_sources})
    if missing_tests:
        blockers.append({'code': 'REQUIRED_TEST_FILES_MISSING', 'paths': missing_tests})
    if source_only_missing:
        blockers.append({'code': 'BYTECODE_ONLY_TREE', 'path': PACKAGE_ROOT.as_posix()})

    blocked = bool(blockers)
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'package_root': PACKAGE_ROOT.as_posix(),
        'overall_status': 'blocked' if blocked else 'pass',
        'proof_acceptance_blocked': blocked,
        'security_decision': 'BLOCK_CRYPTO_EXCHANGE_SOURCE_TREE' if blocked else 'CRYPTO_EXCHANGE_SOURCE_TREE_PRESENT',
        'summary': {
            'required_source_count': len(source_files),
            'present_required_source_count': sum(1 for entry in source_files if entry['present']),
            'required_test_count': len(test_entries),
            'present_required_test_count': sum(1 for entry in test_entries if entry['present']),
            'discovered_source_count': len(discovered_sources),
            'discovered_pyc_count': len(discovered_pyc),
            'blocker_count': len(blockers),
        },
        'required_sources': source_files,
        'required_tests': test_entries,
        'discovered_sources': discovered_sources,
        'discovered_pyc': discovered_pyc,
        'blockers': blockers,
    }


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Audit crypto_exchange source tree recovery evidence.')
    parser.add_argument('--repo-root', default=_repo_root().as_posix())
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    report = build_audit(root)
    write_json(report, out_path)
    print(json.dumps({'report': _relative(out_path, root), 'status': report['overall_status']}))
    return 2 if report['proof_acceptance_blocked'] else 0


if __name__ == '__main__':
    sys.exit(main())
