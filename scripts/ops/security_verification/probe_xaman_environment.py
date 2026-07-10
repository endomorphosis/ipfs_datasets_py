#!/usr/bin/env python3
"""Build a Xaman corpus dependency and build-environment probe."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'xaman-environment-probe/v1'
TASK_ID = 'PORTAL-CXTP-061'
DEFAULT_CORPUS_MANIFEST = Path('security_ir_artifacts/corpora/xaman-app/source-manifest.json')
DEFAULT_SOLVER_PROBE = Path('security_ir_artifacts/environment/solver-dependency-probe.json')
DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/environment-probe.json')
POLICY_DOCUMENT = 'docs/security_verification/xaman_environment_assumptions.md'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    return 'sha256:' + _sha256_json({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _file_paths(manifest: Mapping[str, Any] | None) -> set[str]:
    files = manifest.get('files') if isinstance(manifest, Mapping) else None
    if not isinstance(files, list):
        return set()
    return {
        str(item.get('path'))
        for item in files
        if isinstance(item, Mapping) and isinstance(item.get('path'), str)
    }


def _category_paths(manifest: Mapping[str, Any] | None, key: str) -> list[str]:
    values = manifest.get(key) if isinstance(manifest, Mapping) else None
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        if isinstance(item, Mapping) and isinstance(item.get('path'), str):
            result.append(str(item['path']))
        elif isinstance(item, str):
            result.append(item)
    return sorted(result)


def _dependency_by_name(solver_probe: Mapping[str, Any] | None) -> dict[str, Any]:
    deps = solver_probe.get('dependencies') if isinstance(solver_probe, Mapping) else None
    if not isinstance(deps, list):
        return {}
    return {
        str(dep.get('name')): dep
        for dep in deps
        if isinstance(dep, Mapping) and isinstance(dep.get('name'), str)
    }


def _run_version(command: Sequence[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status': 'error', 'command': list(command), 'error': exc.__class__.__name__}
    line = next(
        (
            text.strip()
            for value in (completed.stdout, completed.stderr)
            for text in value.splitlines()
            if text.strip()
        ),
        None,
    )
    return {
        'status': 'present' if completed.returncode == 0 else 'error',
        'command': list(command),
        'exit_code': completed.returncode,
        'version_raw': line,
    }


def _has_any(paths: set[str], *candidates: str) -> bool:
    return any(candidate in paths for candidate in candidates)


def _has_prefix(paths: set[str], prefix: str) -> bool:
    return any(path.startswith(prefix) for path in paths)


def build_report(
    *,
    repo_root: Path | str | None = None,
    corpus_manifest_path: Path | str = DEFAULT_CORPUS_MANIFEST,
    solver_probe_path: Path | str = DEFAULT_SOLVER_PROBE,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    manifest_abs = Path(corpus_manifest_path)
    solver_abs = Path(solver_probe_path)
    if not manifest_abs.is_absolute():
        manifest_abs = root / manifest_abs
    if not solver_abs.is_absolute():
        solver_abs = root / solver_abs
    manifest = _load_json(manifest_abs)
    solver_probe = _load_json(solver_abs)
    paths = _file_paths(manifest)
    deps = _dependency_by_name(solver_probe)

    source = manifest.get('source') if isinstance(manifest, Mapping) else {}
    source = source if isinstance(source, Mapping) else {}
    commit = source.get('commit_sha') or source.get('commit')
    lockfiles = _category_paths(manifest, 'dependency_lockfiles')
    assumptions = {
        'node_runtime': {
            'status': deps.get('node', {}).get('status') or _run_version(['node', '--version'])['status'],
            'executable': deps.get('node', {}).get('executable'),
            'version': deps.get('node', {}).get('version'),
            'required_for': 'React Native package and proof-consumer schema tooling',
        },
        'npm_runtime': {
            'status': deps.get('npm', {}).get('status') or _run_version(['npm', '--version'])['status'],
            'executable': deps.get('npm', {}).get('executable'),
            'version': deps.get('npm', {}).get('version'),
            'required_for': 'package-lock based dependency resolution',
        },
        'typescript_compiler': {
            'status': deps.get('typescript', {}).get('status'),
            'executable': deps.get('typescript', {}).get('executable'),
            'version': deps.get('typescript', {}).get('version'),
            'required_for': 'TypeScript/TSX source parsing and proof-consumer schema checks',
        },
        'react_native_config': {
            'metro_config': 'metro.config.js' in paths,
            'babel_config': 'babel.config.js' in paths,
            'package_json': 'package.json' in paths,
            'package_lock': 'package-lock.json' in paths,
        },
        'typescript_config': {
            'tsconfig': 'tsconfig.json' in paths,
            'tsconfig_jest': 'tsconfig.jest.json' in paths,
        },
        'native_android': {
            'present': _has_prefix(paths, 'android/'),
            'build_gradle': _has_any(paths, 'android/app/build.gradle', 'android/build.gradle'),
            'security_native_sources': len([p for p in paths if p.startswith('android/') and '/security/' in p]),
        },
        'native_ios': {
            'present': _has_prefix(paths, 'ios/'),
            'podfile_lock': 'ios/Podfile.lock' in paths,
            'xctest_plan': 'Xaman.xctestplan' in paths,
        },
        'detox_e2e': {
            'detox_config': '.detoxrc.js' in paths,
            'e2e_directory': _has_prefix(paths, 'e2e/'),
            'workflow': '.github/workflows/e2e.yml' in paths,
        },
        'solver_paths': {
            name: {
                'status': deps.get(name, {}).get('status'),
                'executable': deps.get(name, {}).get('executable'),
                'version': deps.get(name, {}).get('version'),
                'required': deps.get(name, {}).get('required'),
            }
            for name in ('z3', 'cvc5', 'apalache', 'tamarin', 'proverif', 'lean', 'coq')
        },
    }

    blockers: list[dict[str, Any]] = []
    if manifest is None:
        blockers.append({'code': 'XAMAN_SOURCE_MANIFEST_MISSING', 'path': _relative(manifest_abs, root)})
    if commit != PINNED_XAMAN_COMMIT:
        blockers.append({'code': 'XAMAN_COMMIT_MISMATCH', 'expected': PINNED_XAMAN_COMMIT, 'actual': commit})
    for required_path in ('package.json', 'package-lock.json', 'tsconfig.json'):
        if required_path not in paths:
            blockers.append({'code': 'XAMAN_REQUIRED_BUILD_FILE_MISSING', 'path': required_path})
    if not lockfiles:
        blockers.append({'code': 'XAMAN_DEPENDENCY_LOCKFILES_MISSING'})
    if assumptions['typescript_compiler']['status'] != 'present':
        blockers.append({'code': 'TYPESCRIPT_COMPILER_UNAVAILABLE'})
    if solver_probe is None:
        blockers.append({'code': 'SOLVER_DEPENDENCY_PROBE_MISSING', 'path': _relative(solver_abs, root)})
    elif solver_probe.get('proof_acceptance_blocked'):
        blockers.append({'code': 'SOLVER_DEPENDENCY_PROBE_BLOCKED'})

    warnings: list[dict[str, Any]] = []
    for solver in ('apalache', 'tamarin', 'proverif', 'coq'):
        if deps.get(solver, {}).get('status') != 'present':
            warnings.append({'code': 'OPTIONAL_SOLVER_CAPABILITY_GAP', 'solver': solver})
    if not assumptions['native_ios']['podfile_lock']:
        warnings.append({'code': 'IOS_PODFILE_LOCK_NOT_IN_MANIFEST'})
    if not assumptions['detox_e2e']['detox_config']:
        warnings.append({'code': 'DETOX_CONFIG_NOT_IN_MANIFEST'})

    blocked = bool(blockers)
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'corpus_manifest': {
            'path': _relative(manifest_abs, root),
            'exists': manifest_abs.is_file(),
            'schema_version': manifest.get('schema_version') if isinstance(manifest, Mapping) else None,
            'repository_url': source.get('repo_url') or source.get('repository_url'),
            'commit_sha': commit,
            'file_count': len(paths),
            'dependency_lockfiles': lockfiles,
            'license_files': _category_paths(manifest, 'license_files'),
            'security_disclosure_files': _category_paths(manifest, 'security_disclosure_files'),
        },
        'solver_probe': {
            'path': _relative(solver_abs, root),
            'exists': solver_abs.is_file(),
            'overall_status': solver_probe.get('overall_status') if isinstance(solver_probe, Mapping) else None,
            'proof_acceptance_blocked': solver_probe.get('proof_acceptance_blocked') if isinstance(solver_probe, Mapping) else None,
        },
        'overall_status': 'blocked' if blocked else 'ready',
        'security_decision': 'BLOCK_XAMAN_ENVIRONMENT_PROBE' if blocked else 'XAMAN_ENVIRONMENT_PROBE_READY',
        'assumptions': assumptions,
        'blockers': blockers,
        'warnings': warnings,
        'summary': {
            'file_count': len(paths),
            'lockfile_count': len(lockfiles),
            'native_android_present': assumptions['native_android']['present'],
            'native_ios_present': assumptions['native_ios']['present'],
            'detox_e2e_present': assumptions['detox_e2e']['detox_config'] and assumptions['detox_e2e']['e2e_directory'],
            'typescript_ready': assumptions['typescript_compiler']['status'] == 'present',
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Probe Xaman corpus build environment assumptions.')
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument('--corpus-manifest', default=DEFAULT_CORPUS_MANIFEST.as_posix())
    parser.add_argument('--solver-probe', default=DEFAULT_SOLVER_PROBE.as_posix())
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    report = build_report(
        repo_root=root,
        corpus_manifest_path=args.corpus_manifest,
        solver_probe_path=args.solver_probe,
    )
    _write_json(report, out)
    print(
        json.dumps(
            {
                'report': _relative(out, root),
                'overall_status': report['overall_status'],
                'blocker_count': report['summary']['blocker_count'],
                'warning_count': report['summary']['warning_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
