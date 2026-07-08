#!/usr/bin/env python3
"""Fetch and pin a reproducible Xaman-App source corpus manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 'xaman-corpus-source-manifest/v1'
TARGET_REPO = 'https://github.com/XRPL-Labs/Xaman-App'
TARGET_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'

DEFAULT_SPARSE_PATHS = (
    'src',
    'android',
    'ios',
    'e2e',
    'scripts',
    'patches',
    'typings',
    'docs',
    '.github',
    '.buckconfig',
    '.detoxrc.js',
    '.eslintrc',
    '.prettierrc',
    '.ruby-version',
    '.watchmanconfig',
    'Gemfile',
    'Gemfile.lock',
    'LICENSE',
    'Makefile',
    'README.md',
    'RESPONSIBLE-DISCLOSURE.md',
    'Xaman.xctestplan',
    'babel.config.js',
    'debug.ts',
    'global.ts',
    'index.js',
    'jest.config.js',
    'jest.setup.js',
    'metro.config.js',
    'package-lock.json',
    'package.json',
    'tsconfig.jest.json',
    'tsconfig.json',
)

DEFAULT_REQUIRED_LOCKFILES = ('package-lock.json',)
DEFAULT_REQUIRED_LICENSE_FILES = ('LICENSE',)
DEFAULT_REQUIRED_SECURITY_FILES = ('RESPONSIBLE-DISCLOSURE.md',)

LOCKFILE_NAMES = {
    'Gemfile.lock',
    'Cargo.lock',
    'Package.resolved',
    'Podfile.lock',
    'composer.lock',
    'flake.lock',
    'go.sum',
    'gradle.lockfile',
    'npm-shrinkwrap.json',
    'package-lock.json',
    'pnpm-lock.yaml',
    'poetry.lock',
    'requirements.txt',
    'yarn.lock',
}
LOCKFILE_SUFFIXES = (
    '.lock',
    '.lockfile',
)
LICENSE_FILE_RE = re.compile(r'(^|/)(copying|licen[cs]e)(\.[^.\/]+)?$', re.IGNORECASE)
SECURITY_FILE_RE = re.compile(
    r'(^|/)(security|responsible[-_ ]?disclosure)(\.[^.\/]+)?$',
    re.IGNORECASE,
)
COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')


class CorpusReproducibilityError(RuntimeError):
    """Raised when the requested corpus cannot be reproduced exactly."""


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
) -> str:
    try:
        completed = subprocess.run(
            ['git', *args],
            cwd=str(cwd) if cwd else None,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
        )
    except FileNotFoundError as exc:
        raise CorpusReproducibilityError('git executable is required') from exc
    if completed.returncode != 0:
        command = 'git ' + ' '.join(args)
        stderr = completed.stderr.strip()
        raise CorpusReproducibilityError(
            f'{command} failed with exit code {completed.returncode}: {stderr}'
        )
    return completed.stdout.strip()


def _normalize_repo_url(repo: str) -> str:
    return repo.rstrip('/')


def _validate_commit_ref(ref: str) -> str:
    normalized = ref.strip()
    if not COMMIT_RE.fullmatch(normalized):
        raise CorpusReproducibilityError(
            f'--ref must be an exact 40-character lowercase commit SHA, got {ref!r}'
        )
    return normalized


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().strip('/')
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _path_exists(repo_dir: Path, relative_path: str) -> bool:
    return (repo_dir / relative_path).exists()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _git_tracked_files(repo_dir: Path) -> list[str]:
    output = _run_git(['ls-files', '-z'], cwd=repo_dir)
    return sorted(
        path
        for path in output.split('\0')
        if path and (repo_dir / path).is_file()
    )


def _git_index_entries(repo_dir: Path) -> dict[str, dict[str, str]]:
    output = _run_git(['ls-files', '-s', '-z'], cwd=repo_dir)
    entries: dict[str, dict[str, str]] = {}
    for item in output.split('\0'):
        if not item:
            continue
        metadata, path = item.split('\t', 1)
        mode, blob_sha, stage = metadata.split()
        entries[path] = {
            'git_mode': mode,
            'git_blob_sha1': blob_sha,
            'git_stage': stage,
        }
    return entries


def _is_lockfile(path: str) -> bool:
    name = Path(path).name
    if name in LOCKFILE_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in LOCKFILE_SUFFIXES)


def _is_license_file(path: str) -> bool:
    return bool(LICENSE_FILE_RE.search(path))


def _is_security_file(path: str) -> bool:
    return bool(SECURITY_FILE_RE.search(path))


def _file_entry(repo_dir: Path, path: str, index_entries: dict[str, dict[str, str]]) -> dict[str, Any]:
    full_path = repo_dir / path
    stat = full_path.stat()
    entry = {
        'path': path,
        'size_bytes': stat.st_size,
        'sha256': _sha256_file(full_path),
    }
    entry.update(index_entries.get(path, {}))
    return entry


def _matching_entries(files: list[dict[str, Any]], predicate) -> list[dict[str, Any]]:
    return [
        {
            'path': str(entry['path']),
            'size_bytes': int(entry['size_bytes']),
            'sha256': str(entry['sha256']),
            'git_blob_sha1': str(entry.get('git_blob_sha1', '')),
        }
        for entry in files
        if predicate(str(entry['path']))
    ]


def _ensure_required_paths(
    *,
    label: str,
    required_paths: Iterable[str],
    present_paths: set[str],
) -> None:
    missing = [
        path for path in _dedupe_preserving_order(required_paths)
        if path not in present_paths
    ]
    if missing:
        raise CorpusReproducibilityError(
            f'missing required {label}: {", ".join(missing)}'
        )


def _fetch_sparse_checkout(
    *,
    repo_url: str,
    commit_sha: str,
    sparse_paths: list[str],
    work_dir: Path,
) -> Path:
    repo_dir = work_dir / 'xaman-app'
    _run_git([
        'clone',
        '--filter=blob:none',
        '--sparse',
        '--no-checkout',
        repo_url,
        str(repo_dir),
    ])
    _run_git(['sparse-checkout', 'set', *sparse_paths], cwd=repo_dir)
    _run_git(['checkout', '--detach', commit_sha], cwd=repo_dir)
    resolved = _run_git(['rev-parse', 'HEAD'], cwd=repo_dir)
    if resolved != commit_sha:
        raise CorpusReproducibilityError(
            f'checked out commit {resolved}, expected {commit_sha}'
        )
    status = _run_git(['status', '--porcelain'], cwd=repo_dir)
    if status:
        raise CorpusReproducibilityError(
            f'sparse checkout is not clean after checkout: {status}'
        )
    missing_sparse_paths = [
        path for path in sparse_paths
        if not _path_exists(repo_dir, path)
    ]
    if missing_sparse_paths:
        raise CorpusReproducibilityError(
            'sparse checkout did not reproduce required paths: '
            + ', '.join(missing_sparse_paths)
        )
    return repo_dir


def build_manifest_from_checkout(
    *,
    repo_url: str,
    commit_sha: str,
    requested_ref: str,
    sparse_paths: Iterable[str],
    checkout_dir: Path,
    required_lockfiles: Iterable[str] = DEFAULT_REQUIRED_LOCKFILES,
    required_license_files: Iterable[str] = DEFAULT_REQUIRED_LICENSE_FILES,
    required_security_files: Iterable[str] = DEFAULT_REQUIRED_SECURITY_FILES,
) -> dict[str, Any]:
    sparse_path_list = _dedupe_preserving_order(sparse_paths)
    tracked_paths = _git_tracked_files(checkout_dir)
    if not tracked_paths:
        raise CorpusReproducibilityError('sparse checkout did not produce tracked files')
    index_entries = _git_index_entries(checkout_dir)
    files = [
        _file_entry(checkout_dir, path, index_entries)
        for path in tracked_paths
    ]
    present_paths = {str(entry['path']) for entry in files}

    dependency_lockfiles = _matching_entries(files, _is_lockfile)
    license_files = _matching_entries(files, _is_license_file)
    security_disclosure_files = _matching_entries(files, _is_security_file)

    _ensure_required_paths(
        label='dependency lockfiles',
        required_paths=required_lockfiles,
        present_paths=present_paths,
    )
    _ensure_required_paths(
        label='license files',
        required_paths=required_license_files,
        present_paths=present_paths,
    )
    _ensure_required_paths(
        label='security disclosure files',
        required_paths=required_security_files,
        present_paths=present_paths,
    )

    total_size = sum(int(entry['size_bytes']) for entry in files)
    aggregate_digest = hashlib.sha256(
        ''.join(
            f"{entry['path']}\0{entry['size_bytes']}\0{entry['sha256']}\n"
            for entry in files
        ).encode('utf-8')
    ).hexdigest()

    return {
        'schema_version': SCHEMA_VERSION,
        'corpus': 'xaman-app',
        'source': {
            'repo_url': repo_url,
            'requested_ref': requested_ref,
            'commit_sha': commit_sha,
        },
        'sparse_checkout': {
            'mode': 'git sparse-checkout cone',
            'paths': sparse_path_list,
        },
        'reproducibility': {
            'exact_commit_required': True,
            'fail_closed': True,
            'file_count': len(files),
            'total_size_bytes': total_size,
            'aggregate_sha256': aggregate_digest,
            'required_dependency_lockfiles': _dedupe_preserving_order(required_lockfiles),
            'required_license_files': _dedupe_preserving_order(required_license_files),
            'required_security_disclosure_files': _dedupe_preserving_order(required_security_files),
        },
        'dependency_lockfiles': dependency_lockfiles,
        'license_files': license_files,
        'security_disclosure_files': security_disclosure_files,
        'files': files,
    }


def fetch_xaman_manifest(
    *,
    repo_url: str,
    ref: str,
    sparse_paths: Iterable[str] = DEFAULT_SPARSE_PATHS,
    required_lockfiles: Iterable[str] = DEFAULT_REQUIRED_LOCKFILES,
    required_license_files: Iterable[str] = DEFAULT_REQUIRED_LICENSE_FILES,
    required_security_files: Iterable[str] = DEFAULT_REQUIRED_SECURITY_FILES,
) -> dict[str, Any]:
    normalized_repo_url = _normalize_repo_url(repo_url)
    commit_sha = _validate_commit_ref(ref)
    sparse_path_list = _dedupe_preserving_order(sparse_paths)
    if not sparse_path_list:
        raise CorpusReproducibilityError('at least one sparse checkout path is required')
    with tempfile.TemporaryDirectory(prefix='xaman-corpus-') as temp_dir_name:
        checkout_dir = _fetch_sparse_checkout(
            repo_url=normalized_repo_url,
            commit_sha=commit_sha,
            sparse_paths=sparse_path_list,
            work_dir=Path(temp_dir_name),
        )
        return build_manifest_from_checkout(
            repo_url=normalized_repo_url,
            commit_sha=commit_sha,
            requested_ref=ref,
            sparse_paths=sparse_path_list,
            checkout_dir=checkout_dir,
            required_lockfiles=required_lockfiles,
            required_license_files=required_license_files,
            required_security_files=required_security_files,
        )


def write_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _split_csv(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(part for part in value.split(',') if part.strip())
    return _dedupe_preserving_order(result)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=TARGET_REPO, help='Xaman-App git repository URL')
    parser.add_argument('--ref', default=TARGET_COMMIT, help='Exact 40-character commit SHA to pin')
    parser.add_argument(
        '--out',
        default='security_ir_artifacts/corpora/xaman-app/source-manifest.json',
        help='Path to write the source manifest JSON',
    )
    parser.add_argument(
        '--sparse-path',
        action='append',
        default=[],
        help='Sparse checkout path. May be repeated or comma-separated. Defaults to the reviewed Xaman paths.',
    )
    parser.add_argument(
        '--required-lockfile',
        action='append',
        default=[],
        help='Dependency lockfile path that must be present. May be repeated or comma-separated.',
    )
    parser.add_argument(
        '--required-license-file',
        action='append',
        default=[],
        help='License file path that must be present. May be repeated or comma-separated.',
    )
    parser.add_argument(
        '--required-security-file',
        action='append',
        default=[],
        help='Security disclosure file path that must be present. May be repeated or comma-separated.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    sparse_paths = _split_csv(args.sparse_path) or list(DEFAULT_SPARSE_PATHS)
    required_lockfiles = (
        _split_csv(args.required_lockfile) or list(DEFAULT_REQUIRED_LOCKFILES)
    )
    required_license_files = (
        _split_csv(args.required_license_file) or list(DEFAULT_REQUIRED_LICENSE_FILES)
    )
    required_security_files = (
        _split_csv(args.required_security_file) or list(DEFAULT_REQUIRED_SECURITY_FILES)
    )
    try:
        manifest = fetch_xaman_manifest(
            repo_url=args.repo,
            ref=args.ref,
            sparse_paths=sparse_paths,
            required_lockfiles=required_lockfiles,
            required_license_files=required_license_files,
            required_security_files=required_security_files,
        )
        write_manifest(manifest, Path(args.out))
    except CorpusReproducibilityError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(f'error: failed to reproduce Xaman corpus: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
