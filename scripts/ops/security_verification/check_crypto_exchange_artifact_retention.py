#!/usr/bin/env python3
"""Fail-closed retention check for crypto_exchange theorem-prover artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable


SCHEMA_VERSION = 'crypto-exchange-artifact-retention/v1'
TASK_ID = 'PORTAL-CXTP-057'
DEFAULT_BASELINE = Path('security_ir_artifacts/recovery/artifact-retention-baseline.json')

PACKAGE_ROOT = Path('ipfs_datasets_py/logic/security_models/crypto_exchange')
TEST_ROOT = Path('tests/logic/security_models/crypto_exchange')
IMPLEMENTATION_LOG_ROOT = Path('data/crypto_exchange_theorem_prover/state')

STATIC_GROUP_PATHS: dict[str, tuple[str, tuple[str, ...]]] = {
    'taskboard': (
        'sha256',
        (
            'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
        ),
    ),
    'plans_and_release_policy': (
        'sha256',
        (
            'docs/security_verification/crypto_exchange_theorem_prover_security_plan.todo.md',
            'docs/security_verification/crypto_exchange_verification_plan.md',
            'docs/security_verification/production_release_decision_policy.md',
            'docs/security_verification/proof_receipt_consumer_policy.md',
            'docs/security_verification/release_gate_runbook.md',
            'docs/security_verification/security_ir_spec.md',
            'docs/security_verification/threat_model.md',
        ),
    ),
    'retention_controls': (
        'sha256',
        (
            'docs/security_verification/taskboard_artifact_retention_policy.md',
            'scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py',
        ),
    ),
    'xaman_manifests': (
        'sha256',
        (
            'docs/security_verification/xaman_corpus_profile.md',
            'security_ir_artifacts/corpora/xaman-app/source-manifest.json',
            'security_ir_artifacts/corpora/xaman-app/source-coverage.json',
        ),
    ),
    'model_facts': (
        'sha256',
        (
            'docs/security_verification/code_to_ir_evidence_matrix.md',
            'docs/security_verification/production_environment_profile.md',
            'docs/security_verification/xaman_payload_lifecycle_model.md',
            'docs/security_verification/xaman_wallet_auth_model.md',
            'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',
            'security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json',
            'security_ir_artifacts/production/assumption-evidence.json',
        ),
    ),
    'assurance_packets': (
        'sha256',
        (
            'docs/security_verification/evidence_promotion_workflow.md',
            'docs/security_verification/independent_prover_backend_promotion.md',
            'docs/security_verification/prover_matrix.md',
            'security_ir_artifacts/assurance-baseline.md',
            'security_ir_artifacts/assurance-run/assurance-baseline.md',
            'security_ir_artifacts/assurance-run/code-to-ir-coverage.json',
            'security_ir_artifacts/assurance-run/evidence-review-template.json',
            'security_ir_artifacts/proof-baseline.json',
            'security_ir_artifacts/disproof-baseline.json',
            'security_ir_artifacts/test-proof-report.json',
            'security_ir_artifacts/test-disproof-report.json',
        ),
    ),
    'recovery_artifacts': (
        'sha256',
        (
            'docs/security_verification/crypto_exchange_recovery_report.md',
            'security_ir_artifacts/recovery/crypto-exchange-source-audit.json',
            'scripts/ops/security_verification/audit_crypto_exchange_source_tree.py',
        ),
    ),
}


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


def _file_entry(path: Path, root: Path, validation: str) -> dict[str, Any]:
    stat = path.stat()
    entry: dict[str, Any] = {
        'path': _relative(path, root),
        'size_bytes': stat.st_size,
    }
    if validation == 'sha256':
        entry['sha256'] = _sha256(path)
    return entry


def _files(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob(pattern) if path.is_file())


def _existing(paths: Iterable[str], root: Path) -> list[Path]:
    return sorted(root / path for path in paths if (root / path).is_file())


def _group(name: str, validation: str, paths: Iterable[Path], root: Path) -> dict[str, Any]:
    entries = [_file_entry(path, root, validation) for path in sorted(paths)]
    return {
        'name': name,
        'validation': validation,
        'required_count': len(entries),
        'entries': entries,
    }


def build_baseline(repo_root: Path | str | None = None) -> dict[str, Any]:
    """Build a retention baseline from the current reviewed checkout."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    groups: list[dict[str, Any]] = []

    for name, (validation, paths) in STATIC_GROUP_PATHS.items():
        groups.append(_group(name, validation, _existing(paths, root), root))

    retention_entries = groups[[group['name'] for group in groups].index('retention_controls')]['entries']
    if not any(entry['path'] == DEFAULT_BASELINE.as_posix() for entry in retention_entries):
        retention_entries.append(
            {
                'path': DEFAULT_BASELINE.as_posix(),
                'content_policy': 'presence_only_self_reference',
            }
        )
        retention_entries.sort(key=lambda entry: entry['path'])
        groups[[group['name'] for group in groups].index('retention_controls')]['required_count'] = len(
            retention_entries
        )

    groups.append(_group('source_files', 'sha256', _files(root / PACKAGE_ROOT, '*.py'), root))
    groups.append(_group('tests', 'sha256', _files(root / TEST_ROOT, 'test_*.py'), root))

    solver_paths = (
        _files(root / 'security_ir_artifacts/assurance-run/smtlib', '*.smt2')
        + _files(root / 'security_ir_artifacts/assurance-run/smtlib', 'manifest.json')
        + _existing(
            (
                'security_ir_artifacts/assurance-run/proof-baseline.json',
                'security_ir_artifacts/assurance-run/disproof-baseline.json',
                'security_ir_artifacts/assurance-run/cvc5-differential.json',
                'scripts/ops/security_verification/run_security_ir_assurance_baseline.py',
                'scripts/ops/security_verification/run_security_ir_disproof_suite.py',
                'scripts/ops/security_verification/run_security_ir_proof_suite.py',
                'scripts/ops/security_verification/audit_security_ir_coverage.py',
                'scripts/ops/security_verification/fetch_xaman_corpus.py',
            ),
            root,
        )
    )
    groups.append(_group('solver_artifacts', 'sha256', solver_paths, root))

    implementation_log_paths = (
        _files(root / IMPLEMENTATION_LOG_ROOT / 'implementation_logs', '*.log')
        + _existing(
            (
                'data/crypto_exchange_theorem_prover/state/cxtp_events.jsonl',
                'data/crypto_exchange_theorem_prover/state/cxtp_strategy.json',
                'data/crypto_exchange_theorem_prover/state/cxtp_task_state.json',
                'data/crypto_exchange_theorem_prover/state/cxtp_supervisor_events.jsonl',
                'data/crypto_exchange_theorem_prover/state/cxtp_supervisor_status.json',
            ),
            root,
        )
    )
    groups.append(_group('implementation_logs', 'presence', implementation_log_paths, root))

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': _utc_now(),
        'policy_path': 'docs/security_verification/taskboard_artifact_retention_policy.md',
        'security_decision_when_blocked': 'BLOCK_PROOF_ACCEPTANCE_ARTIFACT_RETENTION',
        'restoration_runbook': {
            'summary': 'Restore missing paths before accepting any theorem-prover result.',
            'document': 'docs/security_verification/taskboard_artifact_retention_policy.md',
            'source_tree_gate': 'scripts/ops/security_verification/audit_crypto_exchange_source_tree.py',
            'recovery_artifact': 'security_ir_artifacts/recovery/crypto-exchange-source-audit.json',
        },
        'groups': groups,
    }


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def load_baseline(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as handle:
        return json.load(handle)


def _baseline_schema_blockers(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if baseline.get('schema_version') != SCHEMA_VERSION:
        blockers.append(
            {
                'code': 'BASELINE_SCHEMA_VERSION_MISMATCH',
                'expected': SCHEMA_VERSION,
                'actual': baseline.get('schema_version'),
            }
        )
    if baseline.get('task_id') != TASK_ID:
        blockers.append(
            {
                'code': 'BASELINE_TASK_ID_MISMATCH',
                'expected': TASK_ID,
                'actual': baseline.get('task_id'),
            }
        )
    if not isinstance(baseline.get('groups'), list) or not baseline.get('groups'):
        blockers.append({'code': 'BASELINE_GROUPS_MISSING'})
    return blockers


def check_retention(
    baseline: dict[str, Any],
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Check the current checkout against a retention baseline."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    blockers = _baseline_schema_blockers(baseline)
    group_results: list[dict[str, Any]] = []
    total_required = 0
    total_present = 0

    for group in baseline.get('groups', []):
        name = group.get('name', '<unnamed>')
        validation = group.get('validation', 'sha256')
        missing: list[str] = []
        changed: list[dict[str, Any]] = []
        malformed: list[dict[str, Any]] = []
        present = 0

        entries = group.get('entries')
        if not isinstance(entries, list):
            blockers.append({'code': 'BASELINE_GROUP_ENTRIES_MALFORMED', 'group': name})
            entries = []

        for entry in entries:
            path_text = entry.get('path') if isinstance(entry, dict) else None
            if not path_text:
                malformed.append({'entry': entry})
                continue
            path = root / path_text
            if not path.is_file():
                missing.append(path_text)
                continue
            present += 1
            if validation == 'sha256' and entry.get('content_policy') != 'presence_only_self_reference':
                expected_sha = entry.get('sha256')
                actual_sha = _sha256(path)
                if expected_sha != actual_sha:
                    changed.append(
                        {
                            'path': path_text,
                            'expected_sha256': expected_sha,
                            'actual_sha256': actual_sha,
                        }
                    )

        required_count = group.get('required_count', len(entries))
        if required_count != len(entries):
            blockers.append(
                {
                    'code': 'BASELINE_GROUP_COUNT_MISMATCH',
                    'group': name,
                    'declared_count': required_count,
                    'entry_count': len(entries),
                }
            )

        total_required += len(entries)
        total_present += present

        if missing:
            blockers.append(
                {
                    'code': 'REQUIRED_ARTIFACT_MISSING',
                    'group': name,
                    'count': len(missing),
                    'paths': missing,
                }
            )
        if changed:
            blockers.append(
                {
                    'code': 'REQUIRED_ARTIFACT_DIGEST_CHANGED',
                    'group': name,
                    'count': len(changed),
                    'paths': changed,
                }
            )
        if malformed:
            blockers.append(
                {
                    'code': 'BASELINE_ENTRY_MALFORMED',
                    'group': name,
                    'count': len(malformed),
                    'entries': malformed,
                }
            )

        group_results.append(
            {
                'name': name,
                'validation': validation,
                'required_count': len(entries),
                'present_count': present,
                'missing_count': len(missing),
                'changed_count': len(changed),
                'malformed_count': len(malformed),
                'status': 'blocked' if missing or changed or malformed else 'pass',
            }
        )

    blocked = bool(blockers)
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'overall_status': 'blocked' if blocked else 'pass',
        'proof_acceptance_blocked': blocked,
        'security_decision': (
            'BLOCK_PROOF_ACCEPTANCE_ARTIFACT_RETENTION'
            if blocked
            else 'ARTIFACT_RETENTION_BASELINE_INTACT'
        ),
        'summary': {
            'group_count': len(group_results),
            'required_artifact_count': total_required,
            'present_artifact_count': total_present,
            'blocker_count': len(blockers),
        },
        'groups': group_results,
        'blockers': blockers,
        'restoration_runbook': baseline.get('restoration_runbook', {}),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Check crypto_exchange theorem-prover taskboard and artifact retention.'
    )
    parser.add_argument('--repo-root', default=str(_repo_root()), help='repository root to inspect')
    parser.add_argument(
        '--baseline',
        default=DEFAULT_BASELINE.as_posix(),
        help='retention baseline JSON to validate against',
    )
    parser.add_argument('--out', help='optional path for the retention check report JSON')
    parser.add_argument(
        '--write-baseline',
        action='store_true',
        help='write a new baseline from the current checkout instead of validating',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = repo_root / baseline_path

    if args.write_baseline:
        baseline = build_baseline(repo_root)
        write_json(baseline, baseline_path)
        print(json.dumps({'baseline_written': baseline_path.as_posix(), 'schema_version': SCHEMA_VERSION}))
        return 0

    if not baseline_path.is_file():
        result = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'proof_acceptance_blocked': True,
            'security_decision': 'BLOCK_PROOF_ACCEPTANCE_ARTIFACT_RETENTION',
            'summary': {'blocker_count': 1},
            'blockers': [
                {
                    'code': 'RETENTION_BASELINE_MISSING',
                    'path': _relative(baseline_path, repo_root),
                }
            ],
        }
    else:
        result = check_retention(load_baseline(baseline_path), repo_root)

    if args.out:
        write_json(result, Path(args.out))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))

    return 2 if result['proof_acceptance_blocked'] else 0


if __name__ == '__main__':
    sys.exit(main())
