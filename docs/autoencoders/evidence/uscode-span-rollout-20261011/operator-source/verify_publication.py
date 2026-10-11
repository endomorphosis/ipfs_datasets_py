"""Verify complete immutable evidence bytes and preservation on GitHub main."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import urllib.parse
import urllib.request

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_REPOSITORY_BYTES = 16 * 1024 * 1024
MAX_COMPARE_BYTES = 32 * 1024 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')
PREFIXES = {
    'endomorphosis/lift_coding': 'artifacts/uscode-span-rollout-20261011/',
    'endomorphosis/ipfs_datasets_py': 'docs/autoencoders/evidence/uscode-span-rollout-20261011/'}
DOCUMENTS = {
    'endomorphosis/lift_coding': 'implementation_plan/docs/72-uscode-archive-reconciliation-rollout-2026-10-11.md',
    'endomorphosis/ipfs_datasets_py': 'docs/autoencoders/uscode_archive_rollout_20261011.md'}
MAIN_REPOSITORIES = set(PREFIXES) | {'endomorphosis/ipfs_accelerate_py'}
REQUIRED_BODIES = {'STATUS.md', 'campaign-summary.json', 'review/final-status-review.json',
                   'review/clone-implementation-review.json', 'review/rollout-results-review.json'}
EXTRA_ROOTS = {
    'endomorphosis/lift_coding': ('implementation_plan/docs/', 'artifacts/uscode-span-continuation-20261011/'),
    'endomorphosis/ipfs_datasets_py': ('ipfs_datasets_py/', 'scripts/ops/legal_ir/', 'tests/unit/',
                                     'docs/autoencoders/', 'docs/implementation/')}


def witness(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_manifest(path):
    path = path.absolute()
    if path.resolve(strict=True) != path or path.is_symlink():
        raise ValueError('Publication manifest must be canonical without symlink aliases')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('Publication manifest must be a bounded regular file')
    with path.open('rb') as stream:
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Publication manifest changed before read')
        body = stream.read(MAX_FILE_BYTES + 1)
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Publication manifest changed during read')
    if len(body) != before.st_size or witness(path.stat()) != witness(before):
        raise ValueError('Publication manifest changed after read')
    return path, body, witness(before)


def require_commit(value):
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise ValueError('Complete immutable 40-hex commit required')


def safe_path(value):
    if (not isinstance(value, str) or not value or value.startswith('/')
            or '\\' in value or '\x00' in value or any(ord(c) < 32 for c in value)
            or any(p in ('', '.', '..') for p in value.split('/'))
            or PurePosixPath(value).as_posix() != value):
        raise ValueError('Canonical repository-relative publication path required')
    return value


def read_bounded(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'uscode-source-reconciliation-verifier/3'})
    with urllib.request.urlopen(request, timeout=40) as response:
        if response.status != 200:
            raise ValueError('Publication endpoint did not return HTTP200')
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError('Publication endpoint exceeded its byte bound')
    return body


def extra_entries(manifest):
    entries = manifest.get('extra_files', [])
    if not isinstance(entries, list):
        raise ValueError('Explicit expected extra publication files must be a list')
    expected = set()
    for entry in entries:
        repository = entry.get('repository')
        if repository not in EXTRA_ROOTS:
            raise ValueError('Unexpected extra-file repository')
        path = safe_path(entry.get('path'))
        if (not path.startswith(EXTRA_ROOTS[repository])
                or PurePosixPath(path).suffix not in {'.py', '.md'}
                or path.startswith(PREFIXES[repository]) or path == DOCUMENTS[repository]):
            raise ValueError('Extra file lies outside expected source/helper/older-document roots')
        if (repository, path) in expected:
            raise ValueError('Duplicate expected extra file')
        expected.add((repository, path))
    return expected


def file_entries(manifest, extras):
    entries = manifest.get('files')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Complete publication file manifest required')
    by_key, totals, commits = {}, {}, {}
    for entry in entries:
        repository = entry.get('repository')
        if repository not in PREFIXES:
            raise ValueError('Unexpected publication repository')
        require_commit(entry.get('commit'))
        path = safe_path(entry.get('path'))
        if not (path.startswith(PREFIXES[repository]) or path == DOCUMENTS[repository]
                or (repository, path) in extras):
            raise ValueError('Publication path lies outside expected package/document')
        if (type(entry.get('bytes')) is not int or not 0 <= entry['bytes'] <= MAX_FILE_BYTES
                or not isinstance(entry.get('sha256'), str) or not SHA256.fullmatch(entry['sha256'])):
            raise ValueError('Bounded file length and SHA-256 pin required')
        key = (repository, entry['commit'], path)
        if key in by_key:
            raise ValueError('Duplicate publication file entry')
        if repository in commits and commits[repository] != entry['commit']:
            raise ValueError('One immutable package/document generation per repository required')
        commits[repository] = entry['commit']
        totals[repository] = totals.get(repository, 0) + entry['bytes']
        if totals[repository] > MAX_REPOSITORY_BYTES:
            raise ValueError('Publication repository exceeds aggregate byte bound')
        by_key[key] = entry
    if set(commits) != set(PREFIXES):
        raise ValueError('Both root and datasets evidence packages are required')
    for repository, commit in commits.items():
        for path in (PREFIXES[repository] + 'index.json', DOCUMENTS[repository]):
            if (repository, commit, path) not in by_key:
                raise ValueError('Package index and standalone document are required')
    if any((repo, commits[repo], path) not in by_key for repo, path in extras):
        raise ValueError('Expected extra file missing from publication manifest')
    return by_key, commits


def verify(entry):
    url = ('https://raw.githubusercontent.com/' + entry['repository'] + '/' +
           entry['commit'] + '/' + urllib.parse.quote(entry['path'], safe='/'))
    body = read_bounded(url, entry['bytes'])
    if len(body) != entry['bytes'] or hashlib.sha256(body).hexdigest() != entry['sha256']:
        raise ValueError('Immutable publication file differs from expected bytes: ' + entry['path'])
    return dict(entry, url=url, verified=True), body


def package_closure(by_key, commits, bodies, extras):
    checks = []
    index_bodies = [bodies[(repo, commits[repo], prefix + 'index.json')]
                    for repo, prefix in PREFIXES.items()]
    if index_bodies[0] != index_bodies[1]:
        raise ValueError('Root and datasets evidence indexes differ')
    for repository, commit in commits.items():
        prefix = PREFIXES[repository]
        index = json.loads(bodies[(repository, commit, prefix + 'index.json')])
        if index.get('schema') != 'uscode-span-rollout-evidence-index/v1' or not isinstance(index.get('files'), dict):
            raise ValueError('Unexpected published evidence index')
        if not REQUIRED_BODIES.issubset(index['files']):
            raise ValueError('Published evidence index lacks required final bodies')
        expected = ({prefix + 'index.json', DOCUMENTS[repository]}
                    | {path for repo, path in extras if repo == repository})
        for relative, pin in index['files'].items():
            safe_path(relative)
            if relative == 'index.json':
                raise ValueError('Evidence index cannot list itself')
            key = (repository, commit, prefix + relative)
            if key not in by_key or not isinstance(pin, dict):
                raise ValueError('Indexed body missing from publication manifest: ' + relative)
            if (type(pin.get('bytes')) is not int or not 0 <= pin['bytes'] <= MAX_FILE_BYTES
                    or not isinstance(pin.get('sha256'), str) or not SHA256.fullmatch(pin['sha256'])):
                raise ValueError('Invalid indexed body byte/hash pin: ' + relative)
            entry, body = by_key[key], bodies[key]
            if (pin.get('bytes') != entry['bytes'] or pin.get('sha256') != entry['sha256']
                    or len(body) != pin['bytes'] or hashlib.sha256(body).hexdigest() != pin['sha256']):
                raise ValueError('Indexed body pin/commit bytes differ: ' + relative)
            expected.add(prefix + relative)
        actual = {path for repo, sha, path in by_key if repo == repository and sha == commit}
        if actual != expected:
            raise ValueError('Manifest has unindexed or missing package entries')
        review = json.loads(bodies[(repository, commit, prefix + 'review/final-status-review.json')])
        review_checks = review.get('checks')
        status_body = bodies[(repository, commit, prefix + 'STATUS.md')]
        if (review.get('status') != 'accepted' or review.get('findings') != []
                or not isinstance(review_checks, list) or not review_checks
                or any(not isinstance(c, dict) or c.get('passed') is not True for c in review_checks)
                or type(review.get('check_count')) is not int or review['check_count'] != len(review_checks)
                or review.get('document', {}).get('path') != '/home/barberb/lift_coding/artifacts/uscode-span-rollout-20261011/STATUS.md'
                or review.get('document', {}).get('bytes') != len(status_body)
                or review.get('document', {}).get('sha256') != hashlib.sha256(status_body).hexdigest()):
            raise ValueError('Published status is not bound to its accepted document review')
        summary = json.loads(bodies[(repository, commit, prefix + 'campaign-summary.json')])
        if (summary.get('all_completed_windows_independently_reviewed') is not True
                or summary != index.get('final_summary')):
            raise ValueError('Published summary/review acceptance differs from its index')
        document_prefix = ('../../artifacts/uscode-span-rollout-20261011/'
                           if repository == 'endomorphosis/lift_coding'
                           else 'evidence/uscode-span-rollout-20261011/')
        def rewrite(match):
            target = match.group(1)
            if target.startswith(('#', '/', 'https://', 'http://')):
                return match.group(0)
            return '](' + document_prefix + target + ')'
        status = bodies[(repository, commit, prefix + 'STATUS.md')].decode('utf-8')
        standalone = re.sub(r'\]\(([^)]+)\)', rewrite, status).encode('utf-8')
        if standalone != bodies[(repository, commit, DOCUMENTS[repository])]:
            raise ValueError('Standalone document differs from indexed status/link rewrite')
        checks.append({'repository': repository, 'commit': commit,
                       'index_path': prefix + 'index.json', 'indexed_body_count': len(index['files']),
                       'verified_extra_file_count': sum(repo == repository for repo, _ in extras),
                       'complete_indexed_body_coverage': True})
    return checks


def repository_for_tree(tree):
    origin = subprocess.check_output(['git', '-C', tree, 'remote', 'get-url', 'origin'], text=True).strip()
    match = re.fullmatch(r'(?:https://(?:[^/@]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?', origin)
    if not match or match.group(1) not in MAIN_REPOSITORIES:
        raise ValueError('An expected GitHub repository worktree is required')
    return match.group(1)


def ancestor(tree, repository, base, head):
    require_commit(base)
    require_commit(head)
    if base == head:
        return 'identical_commit'
    available = all(subprocess.run(['git', '-C', tree, 'cat-file', '-e', sha + '^{commit}'],
                                  capture_output=True).returncode == 0 for sha in (base, head))
    if available:
        result = subprocess.run(['git', '-C', tree, 'merge-base', '--is-ancestor', base, head], capture_output=True)
        if result.returncode:
            raise ValueError('Required publication ancestry is not preserved')
        return 'local_commit_graph_read_only'
    url = 'https://api.github.com/repos/' + repository + '/compare/' + base + '...' + head + '?per_page=1'
    comparison = json.loads(read_bounded(url, MAX_COMPARE_BYTES))
    if (comparison.get('status') not in ('ahead', 'identical')
            or comparison.get('base_commit', {}).get('sha') != base
            or comparison.get('merge_base_commit', {}).get('sha') != base):
        raise ValueError('GitHub comparison does not preserve required publication ancestry')
    return 'bounded_GitHub_compare_API_read_only'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    manifest_path, manifest_raw, manifest_witness = read_manifest(args.manifest)
    manifest = json.loads(manifest_raw)
    extras = extra_entries(manifest)
    by_key, commits = file_entries(manifest, extras)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(verify, by_key.values()))
    verified = [entry for entry, _ in results]
    bodies = {(entry['repository'], entry['commit'], entry['path']): body for entry, body in results}
    closure = package_closure(by_key, commits, bodies, extras)
    gitlinks = []
    for expected in manifest['gitlinks']:
        require_commit(expected['root_commit'])
        require_commit(expected['target_commit'])
        path = safe_path(expected['path'])
        if (repository_for_tree(expected['worktree']) != 'endomorphosis/lift_coding'
                or expected['root_commit'] != commits['endomorphosis/lift_coding']
                or path not in ('external/ipfs_datasets', 'external/ipfs_accelerate')):
            raise ValueError('Unexpected root publication gitlink binding')
        if path == 'external/ipfs_datasets' and expected['target_commit'] != commits['endomorphosis/ipfs_datasets_py']:
            raise ValueError('Root datasets gitlink differs from verified package commit')
        line = subprocess.check_output(['git', '-C', expected['worktree'], 'ls-tree',
                                        expected['root_commit'], path], text=True).strip()
        if line.split()[:3] != ['160000', 'commit', expected['target_commit']]:
            raise ValueError('Published root gitlink differs from expected target')
        gitlinks.append(dict(expected, verified=True))
    if {entry['path'] for entry in gitlinks} != {'external/ipfs_datasets', 'external/ipfs_accelerate'} or len(gitlinks) != 2:
        raise ValueError('Exactly both expected root gitlinks are required')
    main_checks = []
    seen = set()
    for expected in manifest['main_checks']:
        tree = expected['worktree']
        repository = repository_for_tree(tree)
        if repository in seen or expected.get('repository', repository) != repository:
            raise ValueError('Duplicate or mismatched publication main check')
        seen.add(repository)
        require_commit(expected['published_commit'])
        require_commit(expected['preserved_main_commit'])
        if repository in commits and expected['published_commit'] != commits[repository]:
            raise ValueError('Main check differs from verified package commit')
        if repository == 'endomorphosis/ipfs_accelerate_py':
            target = next(entry['target_commit'] for entry in gitlinks if entry['path'] == 'external/ipfs_accelerate')
            if expected['published_commit'] != target:
                raise ValueError('Accelerate main check differs from root gitlink')
        remote_lines = subprocess.check_output(['git', '-C', tree, 'ls-remote', 'origin',
                                                'refs/heads/main'], text=True).splitlines()
        if len(remote_lines) != 1 or remote_lines[0].split()[1] != 'refs/heads/main':
            raise ValueError('One exact remote main ref is required')
        remote = remote_lines[0].split()[0]
        published_method = ancestor(tree, repository, expected['published_commit'], remote)
        preserved_method = ancestor(tree, repository, expected['preserved_main_commit'], expected['published_commit'])
        main_checks.append(dict(expected, repository=repository, observed_main=remote,
                               published_on_main=True, previous_main_preserved=True,
                               ancestry_methods=[published_method, preserved_method]))
    if seen != MAIN_REPOSITORIES:
        raise ValueError('Root, datasets and accelerate preservation checks are required')
    if (manifest_path.resolve(strict=True) != manifest_path
            or witness(manifest_path.stat()) != manifest_witness):
        raise ValueError('Publication manifest changed before final receipt')
    receipt = dict(schema='uscode-span-rollout-publication-verification/v2', passed=True,
                   manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                   file_count=len(verified), files=verified, package_closure=closure,
                   gitlinks=gitlinks, main_checks=main_checks, git_mutations=False,
                   scope='Complete immutable GitHub evidence bytes, exact root gitlinks and main ancestry; no model publication')
    with args.receipt.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': True, 'file_count': len(verified),
                      'gitlink_count': len(gitlinks), 'main_check_count': len(main_checks),
                      'package_closure_count': len(closure)}))


if __name__ == '__main__':
    main()
