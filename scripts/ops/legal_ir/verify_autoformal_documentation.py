#!/usr/bin/env python3
"""Verify the finite LegalIR documentation migration with the standard library.

This reads bounded saved files only. It neither imports product packages nor
loads checkpoints, executes proposals, or changes supervisor state.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile


MANIFEST = Path('docs/autoformalization/evidence/documentation-migration.json')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def verify(root, *, overlay=None, snapshot=False):
    def read(value):
        path = Path(value)
        need(not path.is_absolute() and '..' not in path.parts, f'Unsafe relative path: {path}')
        selected = overlay / path if overlay is not None and (overlay / path).exists() else root / path
        need(selected.is_file() and not selected.is_symlink(), f'Missing or aliased file: {path}')
        need(selected.stat().st_size <= 8 * 1024**2, f'Oversized file: {path}')
        return selected.read_bytes()

    manifest = json.loads(read(MANIFEST))
    need(manifest['schema'] == 'autoformal-documentation-migration/v1', 'Unknown migration schema')
    rows = manifest['new_relocations']
    existing = manifest['existing_relocations_preserved']
    need(len({r['source'] for r in rows + existing}) == len(rows + existing), 'Repeated source guide')
    need(len({r['destination'] for r in rows + existing}) == len(rows + existing), 'Repeated maintained guide')
    archive = manifest['originals_archive']
    archive_raw = read(archive['path'])
    need(digest(archive_raw) == archive['sha256'], 'Original archive hash differs')
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as originals:
        names = originals.namelist()
        need(len(names) == len(set(names)) == archive['members'] == len(rows), 'Archive member count differs')
        need(set(names) == {r['source'] for r in rows}, 'Archive membership differs')
        need(sum(i.file_size for i in originals.infolist()) <= 16 * 1024**2, 'Archive expansion exceeds bound')
        for row in rows:
            raw = originals.read(row['source'])
            need(len(raw) == row['original_bytes'] and digest(raw) == row['original_sha256'],
                 'Original guide commitment differs: ' + row['source'])
            if snapshot:
                need(digest(read(row['destination'])) == row['migrated_sha256'],
                     'Maintained guide changed since migration: ' + row['destination'])
                need(digest(read(row['source'])) == row['redirect_sha256'],
                     'Redirect changed since migration: ' + row['source'])
    for row in rows + existing:
        source, dest = Path(row['source']), Path(row['destination'])
        stub, body = read(source).decode(), read(dest).decode()
        need('This guide moved to' in stub, 'Old path is no longer a compatibility page: ' + str(source))
        expected = os.path.relpath(dest, source.parent)
        need('](' + expected + ')' in stub, 'Redirect points away from owner: ' + str(source))
        need('This guide moved to' not in body, 'Maintained body redirects again: ' + str(dest))
    for row in manifest['proposals']:
        need(digest(read(row['path'])) == row['sha256'], 'Preserved proposal differs: ' + row['path'])
    proposal_root = Path('docs/autoformalization/proposals')
    sources = json.loads(read(proposal_root / 'source-proposals.json'))
    for proposal in sources['proposals']:
        patch = read(proposal_root / proposal['patch']['path'])
        need(digest(patch) == proposal['patch']['sha256'], 'Decoder patch commitment differs')
        lines = patch.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.startswith(b'@@ '))
        hunk = lines[start + 1:]
        need(all(line.startswith(b'+') for line in hunk), 'Decoder proposal is not a single addition hunk')
        original = b''.join(line[1:] for line in hunk)
        need(digest(original) == proposal['source']['sha256'] and
             len(original) == proposal['source']['bytes'], 'Decoder source reconstruction differs')
    native = json.loads(read(proposal_root / 'parent-native-adapter/provenance.json'))
    native_patch = read(proposal_root / 'parent-native-adapter' / native['patch']['path'])
    need(digest(native_patch) == native['patch']['sha256'], 'Native proposal commitment differs')
    recovered = manifest.get('recovered_historical_guides', [])
    for row in recovered:
        source, dest = Path(row['source']), Path(row['destination'])
        need(digest(read(dest)) == row['sha256'], 'Recovered historical bytes differ: ' + str(dest))
        need('](' + os.path.relpath(dest, source.parent) + ')' in read(source).decode(),
             'Recovered guide redirect differs: ' + str(source))
    # Check the entrypoints without traversing historical workspaces or raw archives.
    for path in ('README.md', 'CURRENT_STATE.md', 'MIGRATION.md', 'CATALOG.md', 'proposals/README.md'):
        need(bool(read(Path('docs/autoformalization') / path)), 'Empty navigation page: ' + path)
    return {
        'status': 'passed', 'snapshot_hashes_required': snapshot,
        'new_guide_moves': len(rows), 'prior_guide_moves': len(existing),
        'redirects_checked': len(rows) + len(existing),
        'recovered_historical_guides': len(recovered),
        'exact_decoder_source_reconstructions': len(sources['proposals']),
        'native_proposal_hash_checked': True,
        'product_imports': False, 'numerical_or_lean_execution': False,
        'scope': 'Finite ownership map, preserved originals and proposals; not runtime qualification or an exhaustive link crawl.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--overlay', type=Path, help='Read staged files here before falling back to the repository')
    parser.add_argument('--snapshot', action='store_true', help='Require exact migration-time maintained guide hashes')
    args = parser.parse_args()
    try:
        result = verify(args.repo_root.resolve(), overlay=args.overlay.resolve() if args.overlay else None,
                        snapshot=args.snapshot)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, StopIteration) as exc:
        parser.exit(1, f'Documentation verification failed: {exc}\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
