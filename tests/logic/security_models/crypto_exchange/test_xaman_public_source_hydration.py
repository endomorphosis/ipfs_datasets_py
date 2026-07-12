from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from scripts.ops.security_verification.hydrate_xaman_public_source import (
    build_hydrated_coverage,
)


def _canonical_sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def test_hydration_requires_a_clean_checkout_at_the_frozen_manifest_commit(tmp_path: Path) -> None:
    repo_root = tmp_path / 'repo'
    corpus_root = tmp_path / 'xaman'
    corpus_root.mkdir(parents=True)
    (corpus_root / 'tsconfig.json').write_text(
        '{"$schema":"https://json.schemastore.org/tsconfig","compilerOptions":{"paths":{}}}',
        encoding='utf-8',
    )
    source_file = corpus_root / 'src/services/AuthenticationService.ts'
    source_file.parent.mkdir(parents=True)
    source_file.write_text('export const authenticate = () => true;\n', encoding='utf-8')
    manifest_path = repo_root / 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                'schema_version': 'xaman-corpus-source-manifest/v1',
                'corpus': 'xaman-app',
                'source': {
                    'repo_url': 'https://github.com/XRPL-Labs/Xaman-App',
                    'commit_sha': 'a' * 40,
                },
                'reproducibility': {'aggregate_sha256': 'b' * 64},
                'files': [
                    {'path': 'tsconfig.json', 'size_bytes': 1, 'sha256': 'c' * 64},
                    {
                        'path': 'src/services/AuthenticationService.ts',
                        'size_bytes': 1,
                        'sha256': 'd' * 64,
                    },
                ],
            }
        ),
        encoding='utf-8',
    )

    responses = {
        ('rev-parse', 'HEAD'): 'a' * 40,
        ('status', '--porcelain'): '',
        ('remote', 'get-url', 'origin'): 'https://github.com/XRPL-Labs/Xaman-App.git',
    }

    def fake_git(_root: Path, *args: str) -> str:
        return responses[args]

    with patch('scripts.ops.security_verification.hydrate_xaman_public_source._git', fake_git):
        payload = build_hydrated_coverage(repo_root, corpus_root)

    artifact_cid = payload.pop('artifact_cid')
    assert artifact_cid == _canonical_sha256(payload)
    assert payload['hydration']['source_commit_verified'] == 'a' * 40
    assert payload['hydration']['absolute_checkout_path_recorded'] is False
    assert payload['analysis_mode'] == 'source'
    assert payload['coverage_summary']['parsed_files'] == 1
