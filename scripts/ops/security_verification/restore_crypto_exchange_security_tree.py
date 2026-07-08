#!/usr/bin/env python3
"""Restore and verify the crypto_exchange security verification tree.

This is the supervisor preflight for PORTAL-CXTP-088.  It repairs missing
taskboard/source artifacts from durable git objects when possible and otherwise
fails closed before downstream theorem-prover tasks can run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = 'crypto-exchange-supervisor-recovery-stability/v1'
TASK_ID = 'PORTAL-CXTP-088'
SOURCE_RECOVERY_REF = '5a9ce484a'
XAMAN_REPO_URL = 'https://github.com/XRPL-Labs/Xaman-App'
XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'

DEFAULT_REPORT = Path('security_ir_artifacts/recovery/supervisor-stability-report.json')
PACKAGE_ROOT = Path('ipfs_datasets_py/logic/security_models/crypto_exchange')
TEST_ROOT = Path('tests/logic/security_models/crypto_exchange')

STATIC_REQUIRED_PATHS: dict[str, tuple[str, ...]] = {
    'taskboard': (
        'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
    ),
    'stability_controls': (
        'docs/security_verification/supervisor_recovery_stability_runbook.md',
        'scripts/ops/security_verification/restore_crypto_exchange_security_tree.py',
    ),
    'retention_baseline': (
        'docs/security_verification/taskboard_artifact_retention_policy.md',
        'scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py',
        'security_ir_artifacts/recovery/artifact-retention-baseline.json',
    ),
    'solver_probe': (
        'docs/security_verification/solver_dependency_bootstrap.md',
        'scripts/ops/security_verification/probe_theorem_prover_environment.py',
        'security_ir_artifacts/environment/solver-dependency-probe.json',
    ),
    'xaman_artifacts': (
        'docs/security_verification/xaman_corpus_profile.md',
        'security_ir_artifacts/corpora/xaman-app/source-manifest.json',
        'security_ir_artifacts/corpora/xaman-app/source-coverage.json',
        'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',
        'security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json',
    ),
}

ESSENTIAL_SOURCE_PATHS = (
    'ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/assumption_registry.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/ir/cid.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/ir/canonicalize.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/claims/base.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/claims/withdrawal.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/claims/deposit.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/claims/ledger.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/claims/capability.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_smtlib.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_z3.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/xaman_source_extractor.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/prove_all.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/release_policy.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/runners/z3_runner.py',
    'ipfs_datasets_py/logic/security_models/crypto_exchange/runners/cvc5_runner.py',
)

ESSENTIAL_TEST_PATHS = (
    'tests/logic/security_models/crypto_exchange/test_crypto_exchange_artifact_retention.py',
    'tests/logic/security_models/crypto_exchange/test_solver_dependency_probe.py',
    'tests/logic/security_models/crypto_exchange/test_xaman_corpus_manifest.py',
)


@dataclass(frozen=True)
class RequiredPath:
    group: str
    path: str
    semantic: str = 'presence'


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


def _run_git(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', *args],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _ref_exists(repo_root: Path, ref: str) -> bool:
    result = _run_git(repo_root, ['cat-file', '-e', f'{ref}^{{commit}}'])
    return result.returncode == 0


def _git_paths(repo_root: Path, ref: str, prefix: Path, suffix: str | None = None) -> list[str]:
    result = _run_git(repo_root, ['ls-tree', '-r', '--name-only', ref, '--', prefix.as_posix()])
    if result.returncode != 0:
        return []
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if suffix is not None:
        paths = [path for path in paths if path.endswith(suffix)]
    return sorted(paths)


def _current_paths(repo_root: Path, prefix: Path, pattern: str) -> list[str]:
    root = repo_root / prefix
    if not root.exists():
        return []
    return sorted(_relative(path, repo_root) for path in root.rglob(pattern) if path.is_file())


def _path_in_ref(repo_root: Path, ref: str, path: str) -> bool:
    result = _run_git(repo_root, ['cat-file', '-e', f'{ref}:{path}'])
    return result.returncode == 0


def _restore_from_ref(repo_root: Path, ref: str, path: str) -> tuple[bool, str | None]:
    result = _run_git(repo_root, ['show', f'{ref}:{path}'])
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip() or 'git show failed'
    target = repo_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.stdout.encode('utf-8'))
    return True, None


def _json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open('r', encoding='utf-8') as handle:
            value = json.load(handle)
    except Exception as exc:  # pragma: no cover - exact decoder text is platform-specific
        return None, str(exc)
    if not isinstance(value, dict):
        return None, 'JSON document is not an object'
    return value, None


def _semantic_kind(group: str, path: str) -> str:
    if group == 'taskboard':
        return 'taskboard'
    if path.endswith('.json'):
        if path.endswith('source-manifest.json'):
            return 'xaman_manifest'
        if path.endswith('source-coverage.json'):
            return 'xaman_coverage'
        if path.endswith('payload-lifecycle-facts.json') or path.endswith('wallet-auth-facts.json'):
            return 'xaman_facts'
        if path.endswith('artifact-retention-baseline.json'):
            return 'retention_baseline'
        if path.endswith('solver-dependency-probe.json'):
            return 'solver_probe'
    return 'presence'


def _build_required_paths(repo_root: Path, durable_refs: Sequence[str]) -> list[RequiredPath]:
    grouped_paths: dict[str, set[str]] = {
        group: set(paths)
        for group, paths in STATIC_REQUIRED_PATHS.items()
    }

    source_paths = set(_current_paths(repo_root, PACKAGE_ROOT, '*.py'))
    test_paths = set(_current_paths(repo_root, TEST_ROOT, 'test_*.py'))
    for ref in durable_refs:
        source_paths.update(_git_paths(repo_root, ref, PACKAGE_ROOT, '.py'))
        test_paths.update(_git_paths(repo_root, ref, TEST_ROOT, '.py'))

    grouped_paths['source_files'] = source_paths or set(ESSENTIAL_SOURCE_PATHS)
    grouped_paths['downstream_tests'] = test_paths or set(ESSENTIAL_TEST_PATHS)

    required: list[RequiredPath] = []
    for group in sorted(grouped_paths):
        for path in sorted(grouped_paths[group]):
            required.append(RequiredPath(group=group, path=path, semantic=_semantic_kind(group, path)))
    return required


def _check_taskboard(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8')
    required_fragments = (
        '## PORTAL-CXTP-088 Stabilize recovered tree across supervisor commit cleanup',
        'Depends on: PORTAL-CXTP-056, PORTAL-CXTP-057, PORTAL-CXTP-058',
        'restore_crypto_exchange_security_tree.py',
        'supervisor-stability-report.json',
    )
    return [
        {'code': 'TASKBOARD_REQUIRED_FRAGMENT_MISSING', 'fragment': fragment}
        for fragment in required_fragments
        if fragment not in text
    ]


def _check_xaman_manifest(path: Path) -> list[dict[str, Any]]:
    data, error = _json(path)
    if data is None:
        return [{'code': 'JSON_ARTIFACT_MALFORMED', 'error': error}]
    source = data.get('source') if isinstance(data.get('source'), dict) else {}
    reproducibility = (
        data.get('reproducibility') if isinstance(data.get('reproducibility'), dict) else {}
    )
    errors: list[dict[str, Any]] = []
    if data.get('schema_version') != 'xaman-corpus-source-manifest/v1':
        errors.append({'code': 'XAMAN_MANIFEST_SCHEMA_MISMATCH'})
    if data.get('corpus') != 'xaman-app':
        errors.append({'code': 'XAMAN_CORPUS_MISMATCH'})
    if source.get('repo_url') != XAMAN_REPO_URL:
        errors.append({'code': 'XAMAN_REPO_URL_MISMATCH', 'expected': XAMAN_REPO_URL})
    if source.get('commit_sha') != XAMAN_COMMIT:
        errors.append({'code': 'XAMAN_COMMIT_MISMATCH', 'expected': XAMAN_COMMIT})
    if reproducibility.get('fail_closed') is not True:
        errors.append({'code': 'XAMAN_REPRODUCIBILITY_NOT_FAIL_CLOSED'})
    if not data.get('dependency_lockfiles'):
        errors.append({'code': 'XAMAN_LOCKFILES_MISSING'})
    return errors


def _check_xaman_coverage(path: Path) -> list[dict[str, Any]]:
    data, error = _json(path)
    if data is None:
        return [{'code': 'JSON_ARTIFACT_MALFORMED', 'error': error}]
    errors: list[dict[str, Any]] = []
    if data.get('schema_version') != 'xaman-source-coverage/v1':
        errors.append({'code': 'XAMAN_COVERAGE_SCHEMA_MISMATCH'})
    if data.get('corpus') != 'xaman-app':
        errors.append({'code': 'XAMAN_CORPUS_MISMATCH'})
    if not data.get('security_relevant_modules'):
        errors.append({'code': 'XAMAN_SECURITY_MODULES_MISSING'})
    return errors


def _check_xaman_facts(path: Path) -> list[dict[str, Any]]:
    data, error = _json(path)
    if data is None:
        return [{'code': 'JSON_ARTIFACT_MALFORMED', 'error': error}]
    errors: list[dict[str, Any]] = []
    if data.get('corpus') != 'xaman-app':
        errors.append({'code': 'XAMAN_CORPUS_MISMATCH'})
    if not str(data.get('schema_version', '')).startswith('xaman-'):
        errors.append({'code': 'XAMAN_FACT_SCHEMA_MISMATCH'})
    if not data.get('modeled_facts'):
        errors.append({'code': 'XAMAN_MODELED_FACTS_MISSING'})
    return errors


def _check_retention_baseline(path: Path) -> list[dict[str, Any]]:
    data, error = _json(path)
    if data is None:
        return [{'code': 'JSON_ARTIFACT_MALFORMED', 'error': error}]
    errors: list[dict[str, Any]] = []
    if data.get('schema_version') != 'crypto-exchange-artifact-retention/v1':
        errors.append({'code': 'RETENTION_BASELINE_SCHEMA_MISMATCH'})
    if data.get('task_id') != 'PORTAL-CXTP-057':
        errors.append({'code': 'RETENTION_BASELINE_TASK_MISMATCH'})
    groups = data.get('groups') if isinstance(data.get('groups'), list) else []
    group_names = {group.get('name') for group in groups if isinstance(group, dict)}
    required_groups = {
        'taskboard',
        'source_files',
        'xaman_manifests',
        'retention_controls',
        'solver_artifacts',
    }
    missing = sorted(required_groups - group_names)
    if missing:
        errors.append({'code': 'RETENTION_BASELINE_REQUIRED_GROUPS_MISSING', 'groups': missing})
    return errors


def _check_solver_probe(path: Path) -> list[dict[str, Any]]:
    data, error = _json(path)
    if data is None:
        return [{'code': 'JSON_ARTIFACT_MALFORMED', 'error': error}]
    errors: list[dict[str, Any]] = []
    if data.get('schema_version') != 'crypto-exchange-solver-dependency-probe/v1':
        errors.append({'code': 'SOLVER_PROBE_SCHEMA_MISMATCH'})
    if data.get('task_id') != 'PORTAL-CXTP-058':
        errors.append({'code': 'SOLVER_PROBE_TASK_MISMATCH'})
    dependencies = data.get('dependencies') if isinstance(data.get('dependencies'), list) else []
    dependency_names = {dep.get('name') for dep in dependencies if isinstance(dep, dict)}
    required = {'python', 'node', 'npm', 'typescript', 'z3', 'cvc5'}
    missing = sorted(required - dependency_names)
    if missing:
        errors.append({'code': 'SOLVER_PROBE_REQUIRED_DEPENDENCIES_MISSING', 'dependencies': missing})
    if 'proof_acceptance_blocked' not in data:
        errors.append({'code': 'SOLVER_PROBE_BLOCKING_FIELD_MISSING'})
    return errors


def _semantic_errors(item: RequiredPath, repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / item.path
    try:
        if item.semantic == 'taskboard':
            return _check_taskboard(path)
        if item.semantic == 'xaman_manifest':
            return _check_xaman_manifest(path)
        if item.semantic == 'xaman_coverage':
            return _check_xaman_coverage(path)
        if item.semantic == 'xaman_facts':
            return _check_xaman_facts(path)
        if item.semantic == 'retention_baseline':
            return _check_retention_baseline(path)
        if item.semantic == 'solver_probe':
            return _check_solver_probe(path)
    except UnicodeDecodeError as exc:
        return [{'code': 'ARTIFACT_NOT_UTF8', 'error': str(exc)}]
    return []


def _restoration_instructions(paths: Iterable[str], durable_refs: Sequence[str]) -> list[str]:
    refs = ' '.join(durable_refs)
    instructions = [
        'Do not run downstream crypto_exchange theorem-prover tasks while this report is blocked.',
        (
            'Restore missing files from durable history with: '
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python '
            'scripts/ops/security_verification/restore_crypto_exchange_security_tree.py '
            f'--durable-ref {refs}'
        ),
        (
            'If git history cannot provide the missing paths, recover the supervisor worktree '
            'archive or rerun PORTAL-CXTP-056, PORTAL-CXTP-057, and PORTAL-CXTP-058 before '
            'continuing.'
        ),
        'Rerun this script with --verify-only after restoration succeeds.',
    ]
    for path in sorted(paths):
        instructions.append(f'Missing or invalid protected path: {path}')
    return instructions


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def verify_or_restore(
    repo_root: Path | str | None = None,
    *,
    verify_only: bool = False,
    durable_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    refs = tuple(dict.fromkeys(durable_refs or ('HEAD', SOURCE_RECOVERY_REF)))
    ref_status = [{'ref': ref, 'available': _ref_exists(root, ref)} for ref in refs]
    required = _build_required_paths(root, refs)

    restored: list[dict[str, Any]] = []
    restore_failures: list[dict[str, Any]] = []

    if not verify_only:
        for item in required:
            target = root / item.path
            if target.is_file():
                continue
            attempts: list[dict[str, Any]] = []
            for ref in refs:
                if not _path_in_ref(root, ref, item.path):
                    attempts.append({'ref': ref, 'status': 'missing_from_ref'})
                    continue
                ok, error = _restore_from_ref(root, ref, item.path)
                attempts.append({'ref': ref, 'status': 'restored' if ok else 'restore_failed', 'error': error})
                if ok:
                    restored.append({'path': item.path, 'group': item.group, 'ref': ref})
                    break
            if not target.is_file():
                restore_failures.append({'path': item.path, 'group': item.group, 'attempts': attempts})

    group_counts: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    missing_paths: list[str] = []
    invalid_paths: list[str] = []

    for item in required:
        counts = group_counts.setdefault(
            item.group,
            {
                'name': item.group,
                'required_count': 0,
                'present_count': 0,
                'missing_count': 0,
                'invalid_count': 0,
                'restored_count': 0,
                'status': 'pass',
            },
        )
        counts['required_count'] += 1
        path = root / item.path
        if not path.is_file():
            counts['missing_count'] += 1
            counts['status'] = 'blocked'
            missing_paths.append(item.path)
            blockers.append(
                {
                    'code': 'REQUIRED_STABILITY_ARTIFACT_MISSING',
                    'group': item.group,
                    'path': item.path,
                    'durable_recovery_available': any(_path_in_ref(root, ref, item.path) for ref in refs),
                }
            )
            continue

        counts['present_count'] += 1
        if any(entry['path'] == item.path for entry in restored):
            counts['restored_count'] += 1
        semantic_errors = _semantic_errors(item, root)
        if semantic_errors:
            counts['invalid_count'] += 1
            counts['status'] = 'blocked'
            invalid_paths.append(item.path)
            blockers.append(
                {
                    'code': 'REQUIRED_STABILITY_ARTIFACT_INVALID',
                    'group': item.group,
                    'path': item.path,
                    'errors': semantic_errors,
                }
            )

    for failure in restore_failures:
        if not any(blocker.get('path') == failure['path'] for blocker in blockers):
            blockers.append(
                {
                    'code': 'DURABLE_RECOVERY_UNAVAILABLE',
                    'group': failure['group'],
                    'path': failure['path'],
                    'attempts': failure['attempts'],
                }
            )

    blocked = bool(blockers)
    required_count = len(required)
    present_count = required_count - len(set(missing_paths))
    groups = sorted(group_counts.values(), key=lambda group: group['name'])
    sample_paths = sorted({*missing_paths, *invalid_paths})

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'repo_root': root.resolve().as_posix(),
        'mode': 'verify_only' if verify_only else 'restore_then_verify',
        'durable_refs': list(refs),
        'durable_ref_status': ref_status,
        'source_recovery_ref': SOURCE_RECOVERY_REF,
        'overall_status': 'blocked' if blocked else 'pass',
        'downstream_task_gate': 'blocked' if blocked else 'allowed',
        'proof_acceptance_blocked': blocked,
        'security_decision': (
            'BLOCK_DOWNSTREAM_CRYPTO_EXCHANGE_SECURITY_TREE_UNSTABLE'
            if blocked
            else 'CRYPTO_EXCHANGE_SECURITY_TREE_STABLE'
        ),
        'summary': {
            'required_artifact_count': required_count,
            'present_artifact_count': present_count,
            'restored_artifact_count': len(restored),
            'blocker_count': len(blockers),
            'group_count': len(groups),
        },
        'groups': groups,
        'restored_artifacts': restored,
        'blockers': blockers,
        'restoration_instructions': _restoration_instructions(sample_paths, refs) if blocked else [],
        'downstream_preflight_contract': {
            'required_before_any_downstream_task': [
                'taskboard',
                'source_files',
                'xaman_artifacts',
                'retention_baseline',
                'solver_probe',
            ],
            'failure_mode': 'fail_closed',
            'runbook': 'docs/security_verification/supervisor_recovery_stability_runbook.md',
        },
        'artifact_fingerprints': [
            {
                'group': item.group,
                'path': item.path,
                'sha256': _sha256(root / item.path),
                'size_bytes': (root / item.path).stat().st_size,
            }
            for item in required
            if (root / item.path).is_file()
        ],
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Restore and verify crypto_exchange security verification artifacts.'
    )
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root to inspect')
    parser.add_argument(
        '--report',
        default=DEFAULT_REPORT.as_posix(),
        help='JSON report path to write',
    )
    parser.add_argument(
        '--verify-only',
        action='store_true',
        help='do not restore missing files; only verify the current checkout',
    )
    parser.add_argument(
        '--durable-ref',
        action='append',
        dest='durable_refs',
        help='git commit/ref to use as a durable restoration source; may be repeated',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    refs = tuple(args.durable_refs) if args.durable_refs else ('HEAD', SOURCE_RECOVERY_REF)
    report = verify_or_restore(repo_root, verify_only=args.verify_only, durable_refs=refs)
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = repo_root / report_path
    write_json(report, report_path)
    if args.verify_only:
        print(json.dumps({'report': _relative(report_path, repo_root), 'status': report['overall_status']}))
    else:
        print(
            json.dumps(
                {
                    'report': _relative(report_path, repo_root),
                    'status': report['overall_status'],
                    'restored_artifact_count': report['summary']['restored_artifact_count'],
                }
            )
        )
    return 2 if report['proof_acceptance_blocked'] else 0


if __name__ == '__main__':
    sys.exit(main())
