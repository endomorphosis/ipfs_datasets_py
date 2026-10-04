import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

PACKAGE = Path('/home/barberb/lift_coding/external/ipfs_datasets')
WORKSPACE = PACKAGE.parent.parent
RUN = PACKAGE / 'workspace/test-logs/decoder-action-binding-20261003'
BASE = json.loads((RUN / 'base.json').read_text())['base']
RECEIPT = RUN / 'publication.json'

def git(root, *args, env=None, input=None):
    return subprocess.check_output(['git', *args], cwd=root, env=env, input=input).decode().strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def local_state(root):
    index = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    return {'head': git(root, 'rev-parse', 'HEAD'), 'index_sha256': sha(index)}

def alternate(root, name, base):
    path = RUN / (name + '.index')
    assert not path.exists(), path
    env = dict(os.environ, GIT_INDEX_FILE=str(path))
    git(root, 'read-tree', base, env=env)
    return env

def save(data):
    RECEIPT.write_text(json.dumps(data, indent=2) + '\n')

action = sys.argv[1]
if action == 'prepare-package':
    assert not RECEIPT.exists()
    git(PACKAGE, 'fetch', 'origin', 'main')
    base = git(PACKAGE, 'rev-parse', 'origin/main')
    compatibility = json.loads((RUN / 'publication-compatibility.json').read_text())
    assert base == compatibility['publication_parent'], ('new_remote_revision_requires_review', base)
    assert not compatibility['producer_overlap'] and not compatibility['owned_overlap']
    before = local_state(PACKAGE)
    owned = json.loads((RUN / 'owned-files.json').read_text())
    results_path = 'docs/implementation/reports/evidence/decoder-action-binding-20261003/results.json'
    results = json.loads((PACKAGE / results_path).read_text())
    for rel, digest in results['candidate_sha256'].items():
        assert sha(PACKAGE / rel) == digest, rel
    env = alternate(PACKAGE, 'package', base)
    normal = [p for p in owned if not p.endswith(('.tar.gz', '.tar.xz'))]
    archives = [p for p in owned if '.tar.xz.part-' in p or p.endswith(('.tar.gz', '.tar.xz'))]
    normal = [p for p in owned if p not in archives]
    git(PACKAGE, 'add', '--', *normal, env=env)
    git(PACKAGE, 'add', '-f', '--', *archives, env=env)
    changed = git(PACKAGE, 'diff', '--cached', '--name-only', base, env=env).splitlines()
    assert set(changed) == set(owned), changed
    git(PACKAGE, 'diff', '--cached', '--check', base, env=env)
    manifest = json.loads((PACKAGE / results_path.replace('results.json', 'manifest.json')).read_text())
    archive_path = results_path.replace('results.json', manifest.get('archive_filename', 'evidence.tar.gz'))
    parts = manifest['archive_parts']
    assert parts and all(0 < item['bytes'] <= 48_000_000 for item in parts)
    chunks = []; offset = 0
    for index, item in enumerate(parts, 1):
        assert item['filename'] == 'evidence.tar.xz.part-' + str(index).zfill(3)
        assert item['offset_bytes'] == offset
        part_path = results_path.replace('results.json', item['filename'])
        block = subprocess.check_output(['git', 'show', ':' + part_path], cwd=PACKAGE, env=env)
        assert len(block) == item['bytes'] and hashlib.sha256(block).hexdigest() == item['sha256']
        chunks.append(block); offset += len(block)
    archived = b''.join(chunks)
    for name, expected in manifest['publication_support'].items():
        block = subprocess.check_output(['git', 'show', ':' + results_path.replace('results.json', name)], cwd=PACKAGE, env=env)
        assert {'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()} == expected
    artifact = {'sha256': hashlib.sha256(archived).hexdigest(), 'bytes': len(archived)}
    assert artifact == manifest['archive'] == results['archive'], 'staged_archive_mismatch'
    with tarfile.open(fileobj=io.BytesIO(archived), mode='r:*') as bundle:
        entries = bundle.getmembers()
        assert len(entries) == len(manifest['members'])
        assert {entry.name for entry in entries} == set(manifest['members'])
        for entry in entries:
            assert entry.isfile() and not Path(entry.name).is_absolute() and '..' not in Path(entry.name).parts
            content = bundle.extractfile(entry).read()
            assert {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)} == manifest['members'][entry.name]
            if entry.name.startswith('source/'):
                staged_source = subprocess.check_output(['git', 'show', ':' + entry.name[len('source/'):]], cwd=PACKAGE, env=env)
                assert staged_source == content, ('archived_source_not_in_staged_tree', entry.name)
            if entry.name == 'validation/independent-audit.json':
                assert hashlib.sha256(content).hexdigest() == results['independent_audit_sha256']
    for rel, digest in manifest['validated_producer_source_sha256'].items():
        staged = subprocess.check_output(['git', 'show', ':' + rel], cwd=PACKAGE, env=env)
        assert hashlib.sha256(staged).hexdigest() == digest, ('producer_not_in_publication_tree', rel)
    for rel in owned:
        staged = subprocess.check_output(['git', 'show', ':' + rel], cwd=PACKAGE, env=env)
        assert staged == (PACKAGE / rel).read_bytes(), ('staged_mismatch', rel)
    tree = git(PACKAGE, 'write-tree', env=env)
    message = (RUN / 'commit-message.txt').read_text()
    commit = git(PACKAGE, 'commit-tree', tree, '-p', base, input=message.encode())
    assert local_state(PACKAGE) == before
    data = {'validated_code_base': BASE, 'package_parent': base, 'package_commit': commit,
            'package_changed_files': changed, 'package_local_before': before,
            'package_local_preserved': True, 'package_pushed': False}
    save(data)
    print(json.dumps(data, indent=2))
elif action == 'push-package':
    data = json.loads(RECEIPT.read_text())
    assert local_state(PACKAGE) == data['package_local_before']
    git(PACKAGE, 'push', 'origin', data['package_commit'] + ':refs/heads/main')
    remote = git(PACKAGE, 'ls-remote', '--heads', 'origin', 'main').split()[0]
    assert remote == data['package_commit']
    assert local_state(PACKAGE) == data['package_local_before']
    data.update(package_pushed=True, package_remote_verified=remote)
    save(data)
    print('Package origin/main verified: ' + remote)
elif action == 'publish-parent':
    data = json.loads(RECEIPT.read_text())
    assert data['package_pushed']
    git(WORKSPACE, 'fetch', 'origin', 'main')
    base = git(WORKSPACE, 'rev-parse', 'origin/main')
    prior_link = git(WORKSPACE, 'rev-parse', base + ':external/ipfs_datasets')
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', prior_link, data['package_commit']], cwd=PACKAGE)
    before = local_state(WORKSPACE)
    env = alternate(WORKSPACE, 'workspace', base)
    git(WORKSPACE, 'update-index', '--add', '--cacheinfo', '160000', data['package_commit'], 'external/ipfs_datasets', env=env)
    changed = git(WORKSPACE, 'diff', '--cached', '--name-only', base, env=env).splitlines()
    assert changed == ['external/ipfs_datasets'], changed
    git(WORKSPACE, 'diff', '--cached', '--check', base, env=env)
    tree = git(WORKSPACE, 'write-tree', env=env)
    commit = git(WORKSPACE, 'commit-tree', tree, '-p', base,
                 input=b'Update datasets for action-binding decoder comparison across three widths\n')
    assert local_state(WORKSPACE) == before
    data.update(workspace_parent=base, prior_package_gitlink=prior_link, workspace_commit=commit, workspace_local_before=before,
                workspace_local_preserved=True, workspace_pushed=False)
    save(data)
    git(WORKSPACE, 'push', 'origin', commit + ':refs/heads/main')
    remote = git(WORKSPACE, 'ls-remote', '--heads', 'origin', 'main').split()[0]
    assert remote == commit
    assert local_state(WORKSPACE) == before
    data.update(workspace_pushed=True, workspace_remote_verified=remote)
    save(data)
    print('Workspace origin/main verified: ' + remote)
else:
    raise ValueError(action)
