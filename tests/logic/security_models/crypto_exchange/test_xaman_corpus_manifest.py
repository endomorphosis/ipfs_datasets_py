import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'fetch_xaman_corpus.py'
)
CHECKED_IN_MANIFEST_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-manifest.json'
)
EXPECTED_XAMAN_REPO_URL = 'https://github.com/XRPL-Labs/Xaman-App'
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
GIT_COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'fetch_xaman_corpus',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Xaman corpus fetch script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _create_local_xaman_like_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'security-tests@example.invalid')
    _git(repo, 'config', 'user.name', 'Security Tests')
    _write(
        repo / 'app' / 'signing' / 'payload_signer.ts',
        'export const signingPolicy = "require-local-secret";\n',
    )
    _write(
        repo / 'app' / 'wallet' / 'key_store.ts',
        'export const keyStore = "device-secure-enclave";\n',
    )
    _write(repo / 'package.json', '{"name":"xaman-like","lockfileVersion":3}\n')
    _write(repo / 'yarn.lock', '# deterministic dependency lock fixture\n')
    _write(repo / 'LICENSE', 'MIT\n')
    _write(
        repo / 'SECURITY.md',
        'Report wallet security issues to security@example.invalid.\n',
    )
    _write(repo / 'docs' / 'ignored.md', 'must not be fetched by sparse checkout\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'seed reproducible xaman corpus fixture')
    return _git(repo, 'rev-parse', 'HEAD')


def _read_manifest(path: Path) -> dict[str, Any]:
    assert path.exists(), f'manifest does not exist: {path}'
    return json.loads(path.read_text(encoding='utf-8'))


def _manifest_source(manifest: dict[str, Any]) -> dict[str, Any]:
    source = manifest.get('source')
    assert isinstance(source, dict), 'manifest must contain a source object'
    return source


def _repo_url(manifest: dict[str, Any]) -> str:
    source = _manifest_source(manifest)
    value = source.get('repository_url') or source.get('repo_url')
    assert isinstance(value, str), 'manifest source must record repository_url'
    return value


def _commit_sha(manifest: dict[str, Any]) -> str:
    source = _manifest_source(manifest)
    value = source.get('commit_sha') or source.get('commit')
    assert isinstance(value, str), 'manifest source must record commit_sha'
    return value


def _sparse_checkout_paths(manifest: dict[str, Any]) -> list[str]:
    sparse_checkout = manifest.get('sparse_checkout')
    assert isinstance(sparse_checkout, dict), 'manifest must contain sparse_checkout'
    value = sparse_checkout.get('paths') or sparse_checkout.get('sparse_checkout_paths')
    assert isinstance(value, list), 'manifest source must record sparse checkout paths'
    assert all(isinstance(path, str) for path in value)
    return value


def _file_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    value = manifest.get('files') or manifest.get('file_digests')
    assert isinstance(value, list), 'manifest must contain file digest entries'
    assert value, 'manifest must not have an empty file digest list'
    assert all(isinstance(entry, dict) for entry in value)
    return value


def _entry_path(entry: dict[str, Any]) -> str:
    value = entry.get('path')
    assert isinstance(value, str), 'file digest entry must contain path'
    return value


def _entry_sha256(entry: dict[str, Any]) -> str:
    value = entry.get('sha256') or entry.get('digest')
    assert isinstance(value, str), 'file digest entry must contain sha256'
    return value


def _category_paths(manifest: dict[str, Any], key: str) -> set[str]:
    value = manifest.get(key)
    assert isinstance(value, list), f'manifest must contain {key}'
    assert value, f'manifest {key} must not be empty'
    paths = set()
    for item in value:
        if isinstance(item, str):
            paths.add(item)
        elif isinstance(item, dict):
            paths.add(_entry_path(item))
        else:  # pragma: no cover - assertion branch
            raise AssertionError(f'unexpected {key} entry: {item!r}')
    return paths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_checked_in_xaman_manifest_records_reproducible_source_metadata() -> None:
    manifest = _read_manifest(CHECKED_IN_MANIFEST_PATH)

    assert _repo_url(manifest) == EXPECTED_XAMAN_REPO_URL
    assert GIT_COMMIT_RE.match(_commit_sha(manifest))

    sparse_paths = _sparse_checkout_paths(manifest)
    assert sparse_paths
    assert all(
        path and not path.startswith('/') and '..' not in Path(path).parts
        for path in sparse_paths
    )

    file_entries = _file_entries(manifest)
    file_paths = {_entry_path(entry) for entry in file_entries}
    assert len(file_entries) == len(file_paths), 'manifest file entries must be unique by path'
    for entry in file_entries:
        path = _entry_path(entry)
        assert path and not path.startswith('/') and '..' not in Path(path).parts
        assert SHA256_RE.match(_entry_sha256(entry))
        if 'size_bytes' in entry:
            assert isinstance(entry['size_bytes'], int)
            assert entry['size_bytes'] >= 0

    dependency_lockfiles = _category_paths(manifest, 'dependency_lockfiles')
    license_files = _category_paths(manifest, 'license_files')
    security_disclosure_files = _category_paths(manifest, 'security_disclosure_files')

    assert dependency_lockfiles <= file_paths
    assert license_files <= file_paths
    assert security_disclosure_files <= file_paths
    assert any(
        Path(path).name in {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'Podfile.lock'}
        for path in dependency_lockfiles
    )
    assert any(Path(path).name.upper().startswith('LICENSE') for path in license_files)
    assert any(
        Path(path).name.upper() in {'SECURITY.MD', 'SECURITY', 'RESPONSIBLE-DISCLOSURE.MD'}
        for path in security_disclosure_files
    )


def test_fetch_xaman_corpus_writes_manifest_from_local_sparse_git_checkout(tmp_path: Path) -> None:
    module = _load_script_module()
    source_repo = tmp_path / 'source-repo'
    commit_sha = _create_local_xaman_like_repo(source_repo)
    manifest_path = tmp_path / 'source-manifest.json'
    sparse_paths = [
        'app',
        'package.json',
        'yarn.lock',
        'LICENSE',
        'SECURITY.md',
    ]

    assert (
        module.main(
            [
                '--repo',
                source_repo.as_posix(),
                '--ref',
                commit_sha,
                '--out',
                manifest_path.as_posix(),
                '--required-lockfile',
                'yarn.lock',
                '--required-license-file',
                'LICENSE',
                '--required-security-file',
                'SECURITY.md',
                *[
                    argument
                    for path in sparse_paths
                    for argument in ('--sparse-path', path)
                ],
            ]
        )
        == 0
    )

    manifest = _read_manifest(manifest_path)
    assert _repo_url(manifest) == source_repo.as_posix()
    assert _commit_sha(manifest) == commit_sha
    assert set(_sparse_checkout_paths(manifest)) == set(sparse_paths)

    expected_files = {
        'app/signing/payload_signer.ts',
        'app/wallet/key_store.ts',
        'package.json',
        'yarn.lock',
        'LICENSE',
        'SECURITY.md',
    }
    file_entries = _file_entries(manifest)
    assert {_entry_path(entry) for entry in file_entries} == expected_files
    for entry in file_entries:
        path = source_repo / _entry_path(entry)
        assert path.exists(), f'source file missing for manifest entry: {path}'
        assert _entry_sha256(entry) == _sha256(path)
        if 'size_bytes' in entry:
            assert entry['size_bytes'] == path.stat().st_size

    assert _category_paths(manifest, 'dependency_lockfiles') == {'yarn.lock'}
    assert _category_paths(manifest, 'license_files') == {'LICENSE'}
    assert _category_paths(manifest, 'security_disclosure_files') == {'SECURITY.md'}


def test_fetch_xaman_corpus_fails_closed_when_sparse_path_cannot_be_reproduced(tmp_path: Path) -> None:
    module = _load_script_module()
    source_repo = tmp_path / 'source-repo'
    commit_sha = _create_local_xaman_like_repo(source_repo)
    manifest_path = tmp_path / 'source-manifest.json'

    exit_code = module.main(
        [
            '--repo',
            source_repo.as_posix(),
            '--ref',
            commit_sha,
            '--out',
            manifest_path.as_posix(),
            '--sparse-path',
            'app',
            '--sparse-path',
            'missing-security-critical-path',
            '--required-lockfile',
            'yarn.lock',
            '--required-license-file',
            'LICENSE',
            '--required-security-file',
            'SECURITY.md',
        ]
    )

    assert exit_code != 0
    assert not manifest_path.exists()
