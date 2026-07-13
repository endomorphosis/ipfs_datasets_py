#!/usr/bin/env python3
"""Build provenance-bound parsed coverage from a pinned local Xaman checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_source_extractor import (
    XamanSourceExtractor,
)


ROOT_DIR = Path(__file__).resolve().parents[3]
CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
MANIFEST_PATH = CORPUS_DIR / 'source-manifest.json'
DEFAULT_OUT = CORPUS_DIR / 'source-coverage-hydrated.json'


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _git(corpus_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ['git', *args],
        cwd=corpus_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
    )
    if completed.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed: {completed.stderr.strip()}')
    return completed.stdout.strip()


def build_hydrated_coverage(repo_root: Path, corpus_root: Path) -> dict[str, Any]:
    manifest = json.loads((repo_root / MANIFEST_PATH).read_text(encoding='utf-8'))
    source = manifest['source']
    expected_commit = str(source['commit_sha'])
    expected_repo = str(source['repo_url']).rstrip('/')
    if _git(corpus_root, 'rev-parse', 'HEAD') != expected_commit:
        raise ValueError('local checkout commit does not match the frozen Xaman manifest')
    if _git(corpus_root, 'status', '--porcelain'):
        raise ValueError('local Xaman checkout must be clean before hydration')
    remote_url = _git(corpus_root, 'remote', 'get-url', 'origin').rstrip('/')
    if remote_url != expected_repo and remote_url != f'{expected_repo}.git':
        raise ValueError('local checkout origin does not match the frozen Xaman manifest')

    coverage = XamanSourceExtractor().extract_coverage(
        corpus_root=corpus_root,
        manifest_path=repo_root / MANIFEST_PATH,
    )
    payload: dict[str, Any] = {
        **coverage,
        'hydration': {
            'task_id': 'PORTAL-CXTP-154',
            'source_commit_verified': expected_commit,
            'source_repository_verified': expected_repo,
            'checkout_clean': True,
            'checkout_kind': 'local_verified_public_checkout',
            'absolute_checkout_path_recorded': False,
            'frozen_manifest_path': str(MANIFEST_PATH),
            'replaces_frozen_baseline': False,
        },
    }
    payload['artifact_cid'] = _canonical_sha256(payload)
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR))
    parser.add_argument('--corpus-root', required=True)
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    corpus_root = Path(args.corpus_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    payload = build_hydrated_coverage(repo_root, corpus_root)
    write_json(out, payload)
    print(
        json.dumps(
            {
                'analysis_mode': payload['analysis_mode'],
                'artifact_cid': payload['artifact_cid'],
                'parsed_files': payload['coverage_summary']['parsed_files'],
                'out': str(out.relative_to(repo_root)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
