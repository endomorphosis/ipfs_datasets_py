import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from publication_descendant_support import validate_descendant,validate_supplement,TESTED_PARENT

PACKAGE = Path('/home/barberb/lift_coding/external/ipfs_datasets')
WORKSPACE = PACKAGE.parent.parent
RUN = PACKAGE / 'workspace/test-logs/decoder-modality-gap-r2-20261004'
BASE = json.loads((RUN / 'before.json').read_text())['package']['origin_main']
RECEIPT = RUN / 'publication-v2.json'

def git(root, *args, env=None, input=None):
    return subprocess.check_output(['git', *args], cwd=root, env=env, input=input).decode().strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def local_state(root):
    index = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    return {'head': git(root, 'rev-parse', 'HEAD'), 'index_sha256': sha(index)}

def alternate(root, name, base):
    path = RUN / (name + '-v2.index')
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
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', BASE, base], cwd=PACKAGE)
    compatibility = json.loads((RUN / 'publication-compatibility-v2.json').read_text())
    assert base == compatibility['publication_parent'], ('new_remote_revision_requires_review', base)
    advance=validate_descendant(base);supplement=validate_supplement()
    assert compatibility['tested_parent']==TESTED_PARENT and compatibility['source_advance']==advance
    assert compatibility['publication_supplement']==supplement
    assert not compatibility['producer_overlap'] and not compatibility['owned_overlap']
    assert compatibility['passed'] is True and compatibility['historical_sources_verified_against_validated_base'] is True
    assert compatibility['integration_review_passed'] is True
    integration_path = RUN / 'publication-integration-review.json'
    integration_bytes = integration_path.read_bytes()
    integration_review = json.loads(integration_bytes)
    assert hashlib.sha256(integration_bytes).hexdigest() == compatibility['integration_review_sha256']
    assert integration_review['passed'] is True and integration_review['findings'] == []
    assert integration_review['schema'] == 'source-modality-publication-integration/v1'
    assert integration_review['publication_parent'] == TESTED_PARENT and integration_review['validated_base'] == BASE
    assert integration_review['scoped_tests_passed'] is True and integration_review['semantic_gates_passed'] is True
    assert integration_review['owned_sources_unchanged'] is True and integration_review['frozen_six_fit_reexecuted'] is False
    for name, expected in integration_review['artifacts'].items():
        content = Path(name).read_bytes()
        assert dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest()) == expected
    before = local_state(PACKAGE)
    owned = json.loads((RUN / 'owned-files-v2.json').read_text())
    results_path = 'docs/implementation/reports/evidence/decoder-modality-gap-r2-20261004/results.json'
    results = json.loads((PACKAGE / results_path).read_text())
    assert sha(PACKAGE / results_path) == compatibility['results_sha256']
    assert sha(RUN / 'owned-files-v2.json') == compatibility['owned_files_sha256']
    assert sha(RUN / 'code-files.json') == compatibility['code_files_sha256']
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
    assert sha(PACKAGE / results_path.replace('results.json', 'manifest.json')) == compatibility['manifest_sha256']
    assert compatibility['producer_overrides'] == manifest['publication_producer_overrides']
    allowed_overrides = {'ipfs_datasets_py/logic/deontic/formula_builder.py',
        'ipfs_datasets_py/logic/deontic/utils/deontic_parser.py',
        'ipfs_datasets_py/logic/legal_ir/canonical_compiler.py',
        'ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py'}
    assert set(manifest['publication_producer_overrides']) == allowed_overrides
    assert not allowed_overrides & set(owned)
    assert integration_review['producer_overrides'] == manifest['publication_producer_overrides']
    expected_publication = dict(manifest['validated_producer_source_sha256'])
    for relative, override in integration_review['producer_overrides'].items():
        assert set(override) == {'historical_sha256', 'publication_sha256'}
        assert expected_publication[relative] == override['historical_sha256']
        assert override['historical_sha256'] != override['publication_sha256']
        parent_blob = subprocess.check_output(['git', 'show', base + ':' + relative], cwd=PACKAGE)
        assert hashlib.sha256(parent_blob).hexdigest() == override['publication_sha256']
        expected_publication[relative] = override['publication_sha256']
    assert expected_publication == manifest['publication_producer_source_sha256']
    assert integration_review['owned_candidate_sha256'] == {rel:digest for rel,digest in results['candidate_sha256'].items() if rel.endswith('.py')}
    integration = manifest['publication_integration']
    assert integration['review_member'] == 'validation/publication-integration-review.json'
    assert {k:integration[k] for k in ('bytes','sha256')} == dict(bytes=len(integration_bytes),sha256=hashlib.sha256(integration_bytes).hexdigest())
    assert integration['publication_parent'] == TESTED_PARENT and integration['validated_base'] == BASE
    assert integration['historical_training_sources_preserved'] is True
    assert integration['owned_candidate_sources_unchanged'] is True
    assert integration['numerical_study_reexecuted_on_publication_sources'] is False
    assert integration['source_members'] == {rel:'publication-source/'+rel for rel in allowed_overrides}
    assert compatibility['historical_producer_sources'] == manifest['historical_producer_sources']
    historical = {value['archive_member']: (scoped, value) for scoped, value in manifest['historical_producer_sources'].items()}
    assert len(historical) == len(manifest['historical_producer_sources'])
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
        assert set(historical) <= set(manifest['members'])
        assert integration['review_member'] in manifest['members']
        assert set(integration['source_members'].values()) <= set(manifest['members'])
        archived_review = bundle.extractfile(integration['review_member']).read()
        assert archived_review == integration_bytes
        for scoped, value in manifest['scoped_validated_producer_sources'].items():
            scope, relative = scoped.split(':', 1)
            assert scope in ('dependency', 'parent_extension', 'extension')
            assert manifest['members'][value['archive_member']]['sha256'] == value['sha256']
            if scoped in manifest['historical_producer_sources']:
                assert value == manifest['historical_producer_sources'][scoped]
            else:
                assert value['archive_member'] == 'source/' + relative
                assert manifest['validated_producer_source_sha256'][relative] == value['sha256']
        for entry in entries:
            assert entry.isfile() and not Path(entry.name).is_absolute() and '..' not in Path(entry.name).parts
            content = bundle.extractfile(entry).read()
            assert {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)} == manifest['members'][entry.name]
            if entry.name.startswith('publication-source/'):
                relative = entry.name[len('publication-source/'):]
                assert relative in allowed_overrides and integration['source_members'][relative] == entry.name
                assert hashlib.sha256(content).hexdigest() == integration_review['producer_overrides'][relative]['publication_sha256']
                staged_source = subprocess.check_output(['git','show',':'+relative],cwd=PACKAGE,env=env)
                assert staged_source == content, ('reviewed_publication_source_not_in_staged_tree',entry.name)
            if entry.name.startswith('historical-source/'):
                assert entry.name in historical, ('undeclared_historical_source', entry.name)
                scoped, descriptor = historical[entry.name]
                scope, relative = scoped.split(':', 1)
                assert scope == 'parent_extension'
                assert relative == 'ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py'
                assert entry.name == 'historical-source/' + scope + '/' + relative
                assert hashlib.sha256(content).hexdigest() == descriptor['sha256']
                parent_source = subprocess.check_output(['git', 'show', BASE + ':' + relative], cwd=PACKAGE)
                assert parent_source == content, ('historical_source_differs_from_published_parent', entry.name)
            if entry.name.startswith('source/'):
                relative = entry.name[len('source/'):]
                staged_source = subprocess.check_output(['git', 'show', ':' + relative], cwd=PACKAGE, env=env)
                override = manifest['publication_producer_overrides'].get(relative)
                if override is None:
                    assert staged_source == content, ('archived_source_not_in_staged_tree', entry.name)
                else:
                    assert hashlib.sha256(content).hexdigest() == override['historical_sha256']
                    assert hashlib.sha256(staged_source).hexdigest() == override['publication_sha256']
                    assert relative not in owned
            if entry.name == 'validation/independent-audit.json':
                assert hashlib.sha256(content).hexdigest() == results['independent_audit_sha256']
    for rel, digest in manifest['publication_producer_source_sha256'].items():
        staged = subprocess.check_output(['git', 'show', ':' + rel], cwd=PACKAGE, env=env)
        assert hashlib.sha256(staged).hexdigest() == digest, ('producer_not_in_publication_tree', rel)
    for rel in owned:
        staged = subprocess.check_output(['git', 'show', ':' + rel], cwd=PACKAGE, env=env)
        assert staged == (PACKAGE / rel).read_bytes(), ('staged_mismatch', rel)
    tree = git(PACKAGE, 'write-tree', env=env)
    message = (RUN / 'commit-message.txt').read_text()
    commit = git(PACKAGE, 'commit-tree', tree, '-p', base, input=message.encode())
    assert local_state(PACKAGE) == before
    data = {'validated_code_base': BASE, 'tested_parent': TESTED_PARENT, 'source_advance':advance, 'publication_supplement':supplement, 'package_parent': base, 'package_commit': commit,
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
                 input=b'Update datasets for balanced source-modality training and exposed reconstruction evidence\n')
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
