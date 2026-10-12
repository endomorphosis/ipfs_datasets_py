"""Complete the known partial release and restore the exact original root attributes.

Preparation is local and treats checkpoint bytes as opaque. Publication requires
a separate concrete review, performs one CAS commit, and never retries an unknown
outcome. The sole existing-path operation restores .gitattributes to its original
reviewed bytes; all other operations add absent release-prefix paths. A local
release .gitattributes carries the already known reference-packet LFS rule.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

import publish_hf_release_v01 as old

F = Path(__file__).resolve().parent
KNOWN_PARENT = '4602870f7fb6b85fbff0ad4dc92b5546ba803091'
SOURCE_REVIEW = F / 'hf-completion-helper-source-independent-review-v01.json'
RECONCILIATION = F / 'hf-partial-publication-reconciliation-v01.json'
RECEIPT = F / 'hf-preparation-receipt-v03.json'
CONTRACT = dict(max_files=48, max_raw_bytes=16000000, parent_CAS=True,
                existing_path_exception='.gitattributes', deletes=False)
REVIEW_KEYS = {'schema', 'passed', 'findings', 'repository', 'release_prefix',
              'expected_parent_revision', 'payload_files', 'payload_bytes',
              'artifacts', 'scope', 'limitations'}
RECEIPT_KEYS = {'schema', 'repository', 'release_prefix', 'expected_parent_revision',
                'payload_files', 'payload_bytes', 'complete_payload_files',
                'original_payload_files', 'existing_original_paths',
                'missing_original_paths', 'operations', 'root_repair',
                'baseline_pin', 'original_preparation', 'reconciliation',
                'helper_review', 'transport_contract', 'default_promotion'}


def byte_identity(record, raw):
    if record['lfs'] is not None:
        return (record['size'] == len(raw) and record['lfs']['size'] == len(raw)
                and record['lfs']['sha256'] == hashlib.sha256(raw).hexdigest())
    return (record['size'] == len(raw)
            and record['blob_id'] == hashlib.sha1(
                b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())


def reviewed(path, schema):
    review = old.read(path)
    old.require(review.get('schema') == schema and review.get('passed') is True
                and review.get('findings') == [], 'clean named independent review required')
    old.require(type(review.get('artifacts')) is dict and bool(review['artifacts']),
                'review artifact fence required')
    fence(review)
    return review


def fence(review):
    for path, expected in review['artifacts'].items():
        old.require({key: old.pin(path)[key] for key in ('bytes', 'sha256')} == expected,
                    'reviewed bytes changed')


def require_binding(review, path):
    old.require(review['artifacts'].get(str(path)) == {
        key: old.pin(path)[key] for key in ('bytes', 'sha256')},
        'mandatory source or payload is not independently bound')


def local_state():
    recon = old.read(RECONCILIATION)
    old.require(recon.get('passed') is True and recon.get('findings') == []
                and recon['repo'] == old.REPO and recon['release_prefix'] == old.PREFIX
                and recon['revision'] == KNOWN_PARENT, 'known partial endpoint required')
    for key in ('baseline_pin', 'preparation_pin', 'root_attributes_before',
                'root_attributes_after'):
        old.require(old.pin(recon[key]['path']) == recon[key], 'reconciliation pin changed')
    old.require(recon['baseline_pin']['path'] == str(F / 'hf-before-file-identities-v01.json')
                and recon['preparation_pin']['path'] == str(F / 'hf-preparation-receipt-v02.json'),
                'exact retained input identities required')
    baseline = old.read(recon['baseline_pin']['path'])
    original = old.read(recon['preparation_pin']['path'])
    old.require(baseline['repo'] == original['repository'] == old.REPO
                and original['release_prefix'] == old.PREFIX
                and original['expected_parent_revision'] == baseline['revision']
                and original['schema'] == 'matched-curriculum-Hub-preparation/v2'
                and original['default_promotion'] is False
                and original['additive_only'] is True, 'original publication recipe differs')
    entries = original['complete_upload_files']
    old.require(len(baseline['files']) == 3451 and len(entries) == 405
                and original['payload_files'] == 405
                and original['payload_bytes'] == sum(x['bytes'] for x in entries.values())
                <= old.MAX_PAYLOAD_BYTES, 'exact retained population required')
    current = recon['files']
    existing = sorted(set(entries) & set(current))
    missing = sorted(set(entries) - set(current))
    old.require(len(existing) == 384 and len(missing) == 21
                and set(current) == set(baseline['files']) | set(existing),
                'only the known partial additions may exist')
    old.require(all(current.get(name) == identity for name, identity in baseline['files'].items()
                    if name != '.gitattributes'), 'unrelated old Hub identity changed')
    before = Path(recon['root_attributes_before']['path']).read_bytes()
    after = Path(recon['root_attributes_after']['path']).read_bytes()
    old.require(len(before) == 2230 and len(after) == 2350
                and byte_identity(baseline['files']['.gitattributes'], before)
                and byte_identity(current['.gitattributes'], after)
                and current['.gitattributes'] != baseline['files']['.gitattributes'],
                'exact known root-attributes difference required')
    old.require(after == before + (
        old.PREFIX + '/evidence/authored-reference-packet-v01.json '
        'filter=lfs diff=lfs merge=lfs -text\n').encode(),
        'root attributes changed beyond the single known LFS rule')
    root = Path(original['upload_root'])
    old.require(root == F / 'hf-upload-v02' and root.resolve() == root
                and root.is_dir() and not root.is_symlink(), 'original physical root required')
    for name, record in entries.items():
        old.require(name.startswith(old.PREFIX + '/') and '..' not in Path(name).parts
                    and old.pin(root / name) == record, 'original payload pin changed')
        if name in current:
            old.require(byte_identity(current[name], (root / name).read_bytes()),
                        'existing addition differs from original reviewed bytes')
    return recon, baseline, original, existing, missing


def durable_payload(path, raw):
    old.require(not path.exists(), 'exclusive completion payload required')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare():
    review = reviewed(SOURCE_REVIEW,
                      'matched-curriculum-Hub-completion-helper-source-independent-review/v1')
    recon, baseline, original, existing, missing = local_state()
    for path in (Path(__file__).resolve(), F / 'publish_hf_release_v01.py',
                 RECONCILIATION, Path(recon['root_attributes_before']['path']),
                 Path(recon['root_attributes_after']['path'])):
        require_binding(review, path)
    root = F / 'hf-completion-extras-v03'
    old.require(not root.exists(), 'new exclusive completion extras root required')
    root.mkdir()
    extras = {}

    def add(name, raw):
        full_name = old.PREFIX + '/' + name
        old.require(full_name not in original['complete_upload_files']
                    and full_name not in recon['files'], 'completion extras must add absent paths')
        target = root / full_name
        old.require(target.resolve().is_relative_to(root), 'bounded completion extra required')
        durable_payload(target, raw)
        extras[full_name] = old.pin(target)

    for source, name in (
        (Path(__file__).resolve(), 'recipe/complete_hf_release_v03.py'),
        (SOURCE_REVIEW, 'evidence/hf-completion-helper-source-independent-review-v01.json'),
        (RECONCILIATION, 'evidence/hf-partial-publication-reconciliation-v01.json'),
        (Path(recon['root_attributes_before']['path']), 'evidence/root-gitattributes-before.txt'),
        (Path(recon['root_attributes_after']['path']), 'evidence/root-gitattributes-after.txt')):
        add(name, source.read_bytes())
    add('.gitattributes', b'evidence/authored-reference-packet-v01.json filter=lfs diff=lfs merge=lfs -text\n')
    manifest = dict(schema='matched-curriculum-Hub-completion-manifest/v1',
                    known_partial_parent=KNOWN_PARENT,
                    original_preparation=recon['preparation_pin'],
                    reconciliation=old.pin(RECONCILIATION),
                    original_payload_bytes_unchanged=True,
                    existing_original_paths=existing, missing_original_paths=missing,
                    root_attributes_restored_to_original=recon['root_attributes_before'],
                    existing_path_exception='.gitattributes',
                    added_local_attributes='evidence/authored-reference-packet-v01.json',
                    extras=extras.copy(), transport_contract=CONTRACT,
                    all_eight_retained=True, default_promotion=False)
    add('completion-manifest.json',
        (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
    complete = {**original['complete_upload_files'], **extras}
    operations = {name: complete[name] for name in sorted(set(missing) | set(extras))}
    operations['.gitattributes'] = recon['root_attributes_before']
    old.require(len(operations) <= CONTRACT['max_files']
                and sum(x['bytes'] for x in operations.values()) <= CONTRACT['max_raw_bytes'],
                'single bounded completion request required')
    total = sum(x['bytes'] for x in complete.values())
    old.require(0 < total <= old.MAX_PAYLOAD_BYTES and len(complete) <= 1000,
                'unchanged total payload cap required')
    fence(review)
    old.write(RECEIPT.name, dict(
        schema='matched-curriculum-Hub-preparation/v3', repository=old.REPO,
        release_prefix=old.PREFIX, expected_parent_revision=KNOWN_PARENT,
        payload_files=len(complete), payload_bytes=total,
        complete_payload_files=complete, original_payload_files=405,
        existing_original_paths=existing, missing_original_paths=missing,
        operations=operations, root_repair=recon['root_attributes_before'],
        baseline_pin=recon['baseline_pin'], original_preparation=recon['preparation_pin'],
        reconciliation=old.pin(RECONCILIATION), helper_review=old.pin(SOURCE_REVIEW),
        transport_contract=CONTRACT, default_promotion=False))
    print(json.dumps(dict(status='completion_prepared_only', files=len(complete),
                          bytes=total, operations=len(operations),
                          operation_bytes=sum(x['bytes'] for x in operations.values()))))


def publish(review_path):
    review = reviewed(review_path, 'matched-curriculum-Hub-publication-independent-review/v3')
    old.require(set(review) == REVIEW_KEYS, 'closed concrete completion review required')
    receipt = old.read(RECEIPT)
    old.require(set(receipt) == RECEIPT_KEYS
                and receipt['schema'] == 'matched-curriculum-Hub-preparation/v3'
                and receipt['transport_contract'] == CONTRACT
                and receipt['default_promotion'] is False, 'closed completion recipe required')
    recon, baseline, original, existing, missing = local_state()
    old.require(review['repository'] == receipt['repository'] == old.REPO
                and review['release_prefix'] == receipt['release_prefix'] == old.PREFIX
                and review['expected_parent_revision'] == receipt['expected_parent_revision'] == KNOWN_PARENT,
                'exact completion endpoint required')
    for key, expected in (('baseline_pin', recon['baseline_pin']),
                          ('original_preparation', recon['preparation_pin']),
                          ('reconciliation', old.pin(RECONCILIATION)),
                          ('helper_review', old.pin(SOURCE_REVIEW)),
                          ('root_repair', recon['root_attributes_before'])):
        old.require(receipt[key] == expected and old.pin(expected['path']) == expected,
                    'bound completion input changed')
    entries = receipt['complete_payload_files']
    old.require(receipt['original_payload_files'] == 405
                and receipt['existing_original_paths'] == existing
                and receipt['missing_original_paths'] == missing,
                'partial publication population changed')
    old.require(review['payload_files'] == receipt['payload_files'] == len(entries)
                and len(entries) == 412
                and review['payload_bytes'] == receipt['payload_bytes']
                == sum(x['bytes'] for x in entries.values()) <= old.MAX_PAYLOAD_BYTES,
                'complete payload count or total bytes differ')
    for name, record in original['complete_upload_files'].items():
        old.require(entries.get(name) == record, 'original opaque payload changed')
    extras = set(entries) - set(original['complete_upload_files'])
    old.require(extras == {old.PREFIX + '/' + name for name in (
        '.gitattributes', 'recipe/complete_hf_release_v03.py',
        'evidence/hf-completion-helper-source-independent-review-v01.json',
        'evidence/hf-partial-publication-reconciliation-v01.json',
        'evidence/root-gitattributes-before.txt', 'evidence/root-gitattributes-after.txt',
        'completion-manifest.json')}, 'closed finite completion extras required')
    root = F / 'hf-completion-extras-v03'
    old.require(root.is_dir() and root.resolve() == root and not root.is_symlink()
                and not any(p.is_symlink() for p in root.rglob('*'))
                and {old.PREFIX + '/' + p.relative_to(root / old.PREFIX).as_posix()
                     for p in root.rglob('*') if p.is_file()} == extras,
                'closed physical completion extras tree required')
    for name, record in entries.items():
        old.require(name.startswith(old.PREFIX + '/') and '..' not in Path(name).parts
                    and old.pin(record['path']) == record, 'reviewed prefix payload changed')
        if name in extras:
            old.require(Path(record['path']) == root / name, 'extra path escaped physical root')
    expected_operations = {name: entries[name] for name in sorted(set(missing) | extras)}
    expected_operations['.gitattributes'] = recon['root_attributes_before']
    old.require(receipt['operations'] == expected_operations
                and len(expected_operations) <= CONTRACT['max_files']
                and sum(x['bytes'] for x in expected_operations.values()) <= CONTRACT['max_raw_bytes'],
                'only absent prefix additions and exact original attributes repair allowed')
    required = [Path(__file__).resolve(), F / 'publish_hf_release_v01.py', RECEIPT,
                RECONCILIATION, SOURCE_REVIEW,
                Path(recon['baseline_pin']['path']), Path(recon['preparation_pin']['path']),
                Path(recon['root_attributes_before']['path']),
                Path(recon['root_attributes_after']['path']),
                *[Path(record['path']) for record in entries.values()]]
    for path in required:
        require_binding(review, path)
    payload = {name: Path(record['path']).read_bytes()
               for name, record in entries.items()}
    repair = Path(receipt['root_repair']['path']).read_bytes()
    old.require(all(len(raw) == entries[name]['bytes']
                    and hashlib.sha256(raw).hexdigest() == entries[name]['sha256']
                    for name, raw in payload.items()), 'immutable prefix buffers differ')
    operations = {name: payload[name] for name in sorted(set(missing) | extras)}
    operations['.gitattributes'] = repair
    fence(review)
    api = old.HfApi()
    before = api.model_info(old.REPO, files_metadata=True)
    old.require(before.sha == KNOWN_PARENT and old.identities(before) == recon['files'],
                'fresh partial endpoint changed before completion')
    old.write('hf-preupload-custody-v03.json', dict(
        repo=old.REPO, parent_revision=KNOWN_PARENT, review=old.pin(review_path),
        receipt=old.pin(RECEIPT), operations=receipt['operations'],
        transport_contract=CONTRACT, additions_only_except_exact_root_repair=True))
    fence(review)
    try:
        result = api.create_commit(
            repo_id=old.REPO, repo_type='model', revision='main', parent_commit=KNOWN_PARENT,
            operations=[old.CommitOperationAdd(path_in_repo=name, path_or_fileobj=raw)
                        for name, raw in sorted(operations.items())], num_threads=2,
            commit_message='Complete matched curriculum archive and restore original root attributes',
            commit_description='Exact old root attribute repair plus reviewed absent prefix additions. All eight checkpoints retained; no default promotion. Final qualification requires complete immutable readback.')
    except Exception as error:
        old.write('hf-completion-unknown-outcome-v03.json', dict(
            parent_revision=KNOWN_PARENT, names=sorted(operations),
            error_type=type(error).__name__, message=str(error),
            automatic_retry_performed=False, reconciliation_required_before_resume=True))
        raise
    revision = result.oid
    old.write('hf-commit-created-v03.json', dict(
        repo=old.REPO, parent_revision=KNOWN_PARENT, revision=revision,
        commit_url=result.commit_url, release_prefix=old.PREFIX,
        operations=len(operations), prefix_additions=len(operations) - 1,
        exact_original_root_repair=True, default_promotion=False))
    after = old.identities(api.model_info(old.REPO, revision=revision, files_metadata=True))
    old.write('hf-after-file-identities-v03.json', dict(repo=old.REPO, revision=revision, files=after))
    old.require(all(after.get(name) == identity for name, identity in baseline['files'].items()),
                'an old Hub identity, including original root attributes, differs')
    old.require(set(after) == set(baseline['files']) | set(entries), 'unexpected completion tree paths')
    old.require(all(byte_identity(after[name], raw) for name, raw in payload.items()),
                'complete original or extra prefix identity differs from reviewed bytes')
    old.require(byte_identity(after['.gitattributes'], repair), 'root repair differs from original bytes')
    old.write('hf-completion-identity-verification-v03.json', dict(
        repo=old.REPO, revision=revision, all_old_identities_exact=True,
        complete_prefix_identities_byte_exact=True, root_attributes_original_exact=True,
        original_files=405, complete_prefix_files=len(entries)))
    destination = F / 'hf-verified-download-v03'
    old.require(not destination.exists(), 'exclusive immutable download root required')
    with (F / 'hf-download-verification-v03.log').open('x') as output:
        completed = subprocess.run(
            ['hf', 'download', old.REPO, '--revision', revision, '--include',
             old.PREFIX + '/*', '.gitattributes', '--local-dir', str(destination),
             '--max-workers', '2'], stdout=output, stderr=subprocess.STDOUT)
    old.require(completed.returncode == 0, 'complete immutable readback failed')
    downloads = {}
    for name, expected in entries.items():
        actual = old.pin(destination / name)
        old.require({key: actual[key] for key in ('bytes', 'sha256')}
                    == {key: expected[key] for key in ('bytes', 'sha256')},
                    'complete downloaded prefix bytes differ')
        downloads[name] = actual
    downloaded_repair = old.pin(destination / '.gitattributes')
    old.require({key: downloaded_repair[key] for key in ('bytes', 'sha256')}
                == {key: receipt['root_repair'][key] for key in ('bytes', 'sha256')},
                'downloaded root attributes differ from exact original bytes')
    fence(review)
    old.write('hf-publication-verification-v03.json', dict(
        schema='matched-curriculum-Hub-verification/v3', passed=True, findings=[],
        repo=old.REPO, revision=revision, parent_revision=KNOWN_PARENT,
        commit_url=result.commit_url, release_prefix=old.PREFIX,
        original_prefix_files=405, new_files=len(entries),
        completion_prefix_additions=len(operations) - 1,
        old_files_preserved=len(baseline['files']), all_old_identities_exact=True,
        all_downloads_byte_exact=True, root_attributes_original_exact=True,
        downloads=downloads, root_attributes_download=downloaded_repair,
        default_promotion=False, semantic_accuracy=None))
    print(json.dumps(dict(status='completed_and_verified', revision=revision,
                          prefix_files=len(entries), all_old_identities_exact=True)), flush=True)


if __name__ == '__main__':
    old.require(len(sys.argv) == 2, '--prepare or one concrete review path required')
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        publish(Path(sys.argv[1]).resolve())
