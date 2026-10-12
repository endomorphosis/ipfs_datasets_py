"""Publish only a concrete reviewed 20261012 payload; no import-time API call.

Inputs are copied into immutable bytes before SDK operations; parent CAS and
prefix-only additions protect all old files. Durable preupload/commit/identity
receipts precede immutable CLI readback. A helper source review alone never
authorizes publication. Require checks remain active under python -O.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys
from huggingface_hub import HfApi, CommitOperationAdd
F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261012-targeted-loss-v1'
MAX_PAYLOAD_BYTES = 200000000

def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    require(len(raw) <= MAX_PAYLOAD_BYTES, 'publication custody precondition failed')

    def finite_number(raw):
        value = float(raw)
        require(math.isfinite(value), 'nonfinite JSON number')
        return value
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite_number, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and (not path.is_symlink()), 'publication custody precondition failed')
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def write(name, value):
    with (F / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def identities(info):
    return {item.rfilename: dict(size=item.size, blob_id=item.blob_id, lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size)) for item in info.siblings}

CONTRACT=dict(max_files=48,max_raw_bytes=16000000,parent_CAS_every_chunk=True,additions_only=True)

def chunks(entries):
    result=[];current=[];size=0
    for name in sorted(entries):
        record=entries[name]
        require(type(record['bytes']) is int and 0<=record['bytes']<=CONTRACT['max_raw_bytes'],'bounded single artifact required')
        if current and (len(current)==CONTRACT['max_files'] or size+record['bytes']>CONTRACT['max_raw_bytes']):
            result.append(current);current=[];size=0
        current.append(name);size+=record['bytes']
    if current:result.append(current)
    require(bool(result),'nonempty chunks required')
    return result

def byte_identity(record,raw):
    if record['lfs'] is not None:
        return record['size']==len(raw) and record['lfs']['size']==len(raw) and record['lfs']['sha256']==hashlib.sha256(raw).hexdigest()
    return record['size']==len(raw) and record['blob_id']==hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def main():
    review_path = Path(sys.argv[1]).resolve()
    review_pin = pin(review_path)
    review = read(review_path)
    require(pin(review_path) == review_pin, 'publication review changed while reading')
    require(set(review) == {'schema', 'passed', 'findings', 'repository', 'release_prefix', 'expected_parent_revision', 'payload_files', 'payload_bytes', 'artifacts', 'scope', 'limitations'}, 'publication custody precondition failed')
    require(review['passed'] is True and review['findings'] == [], 'publication custody precondition failed')
    require(review['schema'] == 'targeted-loss-curriculum-Hub-publication-independent-review/v1', 'publication custody precondition failed')
    receipt_path = F / 'hf-preparation-receipt-v01.json'
    receipt = read(receipt_path)
    require(set(receipt) == {'schema', 'repository', 'release_prefix', 'expected_parent_revision', 'upload_root', 'complete_upload_files', 'payload_files', 'payload_bytes', 'baseline_pin', 'result_review', 'runtime_review', 'helper_review', 'freeze_manifest', 'default_promotion', 'additive_only'}, 'publication custody precondition failed')
    require(receipt['schema'] == 'targeted-loss-curriculum-Hub-preparation/v1', 'publication custody precondition failed')
    require(receipt['default_promotion'] is False and receipt['additive_only'] is True, 'publication custody precondition failed')
    baseline = read(F / 'hf-before-file-identities-v01.json')
    require(receipt['repository'] == baseline['repo'] == REPO and receipt['release_prefix'] == PREFIX, 'publication custody precondition failed')
    require(review['repository'] == REPO and review['release_prefix'] == PREFIX, 'publication custody precondition failed')
    require(review['expected_parent_revision'] == receipt['expected_parent_revision'] == baseline['revision'], 'publication custody precondition failed')
    entries = receipt['complete_upload_files']
    root = Path(receipt['upload_root'])
    require(root == F/'hf-upload-v01', 'exact owned upload root required')
    require(root.is_absolute() and root.resolve() == root and root.is_dir() and (not root.is_symlink()), 'publication custody precondition failed')
    require(review['payload_files'] == receipt['payload_files'] == len(entries), 'publication custody precondition failed')
    require(type(receipt['payload_files']) is int and 0 < len(entries) <= 1000, 'publication custody precondition failed')
    require(type(receipt['payload_bytes']) is int and 0 < receipt['payload_bytes'] <= MAX_PAYLOAD_BYTES, 'publication custody precondition failed')
    require(review['payload_bytes'] == receipt['payload_bytes'] == sum((value['bytes'] for value in entries.values())), 'publication custody precondition failed')
    require(set((path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())) == set(entries), 'publication custody precondition failed')
    require(all((not path.is_symlink() for path in root.rglob('*'))), 'publication custody precondition failed')
    for path, expected in review['artifacts'].items():
        require({key: pin(path)[key] for key in ('bytes', 'sha256')} == expected, 'publication custody precondition failed')
    for path in [Path(__file__), F / 'prepare_hf_targeted_release_v01.py', receipt_path, F / 'hf-before-file-identities-v01.json', F / 'result-independent-review-v01.json', F / 'runtime-independent-review-v01.json', F / 'hf-helper-source-independent-review-v01.json', F / 'four-cell-output-freeze-v01.json', *[root / name for name in entries]]:
        require(review['artifacts'][str(path)] == {key: pin(path)[key] for key in ('bytes', 'sha256')}, 'publication custody precondition failed')
    for name, expected in entries.items():
        require(set(expected) == {'path', 'bytes', 'sha256'} and type(expected['bytes']) is int and 0 <= expected['bytes'] < 10000000, 'publication custody precondition failed')
        require(name.startswith(PREFIX + '/') and '..' not in Path(name).parts and (pin(root / name) == expected), 'publication custody precondition failed')
    require(pin(F / 'hf-before-file-identities-v01.json') == receipt['baseline_pin'], 'publication custody precondition failed')
    require(pin(F / 'result-independent-review-v01.json') == receipt['result_review'], 'publication custody precondition failed')
    for key, name in [('runtime_review', 'runtime-independent-review-v01.json'), ('helper_review', 'hf-helper-source-independent-review-v01.json'), ('freeze_manifest', 'four-cell-output-freeze-v01.json')]:
        require(pin(F / name) == receipt[key], 'reviewed preparation evidence changed')
    payload = {name: (root / name).read_bytes() for name in sorted(entries)}
    require(all((len(raw) == entries[name]['bytes'] and hashlib.sha256(raw).hexdigest() == entries[name]['sha256'] for name, raw in payload.items())), 'publication custody precondition failed')
    api = HfApi()
    before = api.model_info(REPO, files_metadata=True)
    require(before.sha == baseline['revision'] and identities(before) == baseline['files'], 'publication custody precondition failed')
    require(not any((name.startswith(PREFIX + '/') for name in baseline['files'])), 'publication custody precondition failed')
    def fence():
        require(pin(review_path) == review_pin, 'publication review changed')
        for path, expected in review['artifacts'].items():
            require({key: pin(path)[key] for key in ('bytes', 'sha256')} == expected, 'reviewed bytes changed')
    planned = chunks(entries)
    write('hf-preupload-custody-v01.json', dict(repo=REPO, parent_revision=before.sha,
        old_files=len(baseline['files']), review=review_pin, receipt=pin(receipt_path),
        chunks=planned, chunk_contract=CONTRACT, additive_only=True))
    current, owned, commits = baseline['revision'], {}, []
    for index, names in enumerate(planned, 1):
        fence()
        opening = api.model_info(REPO, files_metadata=True)
        opening_files = identities(opening)
        require(opening.sha == current and opening_files == {**baseline['files'], **owned},
                'parent or prior identities changed before chunk')
        require(all(name not in opening_files for name in names), 'every operation must add an absent path')
        write(f'hf-chunk-{index:02d}-preupload-v01.json', dict(parent_revision=current, names=names,
            raw_bytes=sum(entries[name]['bytes'] for name in names), additions_only=True))
        try:
            result = api.create_commit(repo_id=REPO, repo_type='model', revision='main', parent_commit=current,
                operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=payload[name]) for name in names],
                num_threads=2, commit_message=f'Archive targeted loss part {index}/{len(planned)}',
                commit_description='Four retained matched32-update source-only candidates. Authored engineering measurements; no default promotion. Final immutable readback qualifies the complete release.')
        except Exception as error:
            write(f'hf-chunk-{index:02d}-unknown-outcome-v01.json', dict(parent_revision=current, names=names,
                error_type=type(error).__name__, message=str(error), automatic_retry_performed=False,
                reconciliation_required_before_resume=True))
            raise
        revision = result.oid
        write(f'hf-chunk-{index:02d}-created-v01.json', dict(parent_revision=current, revision=revision,
            commit_url=result.commit_url, names=names))
        after = identities(api.model_info(REPO, revision=revision, files_metadata=True))
        require(all(after.get(name) == record for name, record in {**baseline['files'], **owned}.items()),
                'old or previously owned identities changed')
        require(set(after) == set(baseline['files']) | set(owned) | set(names), 'unexpected chunk additions')
        require(all(byte_identity(after[name], payload[name]) for name in names), 'new immutable identities differ')
        owned.update({name: after[name] for name in names})
        current = revision
        record = dict(parent_revision=opening.sha, revision=current, new_files=len(names),
            all_old_and_prior_owned_identities_exact=True, new_byte_identities_exact=True)
        write(f'hf-chunk-{index:02d}-verified-v01.json', record)
        commits.append(record)
        print(json.dumps(dict(status='chunk_committed_and_identity_verified', chunk=index,
            chunks=len(planned), files=len(owned), revision=current)), flush=True)
    fence()
    require(set(owned) == set(entries), 'complete prefix additions required')
    revision = current
    write('hf-commit-created-v01.json', dict(repo=REPO, revision=revision, parent_revision=before.sha,
        commit_url=f'https://huggingface.co/{REPO}/commit/{revision}', release_prefix=PREFIX,
        additions=len(entries), default_promotion=False, chunks=commits))
    write('hf-after-file-identities-v01.json', dict(repo=REPO, revision=revision, files={**baseline['files'], **owned}))
    destination = F / 'hf-verified-download-v01'
    require(not destination.exists(), 'publication custody precondition failed')
    with (F / 'hf-download-verification-v01.log').open('x') as output:
        completed = subprocess.run(['hf', 'download', REPO, '--revision', revision, '--include', PREFIX + '/*', '--local-dir', str(destination), '--max-workers', '2'], stdout=output, stderr=subprocess.STDOUT)
    require(completed.returncode == 0, 'publication custody precondition failed')
    downloads = {}
    for name, expected in entries.items():
        actual = pin(destination / name)
        require({key: actual[key] for key in ('bytes', 'sha256')} == {key: expected[key] for key in ('bytes', 'sha256')}, 'publication custody precondition failed')
        require(pin(root / name) == expected, 'publication custody precondition failed')
        downloads[name] = actual
    fence()
    write('hf-publication-verification-v01.json', dict(schema='targeted-loss-curriculum-Hub-verification/v1', passed=True, findings=[], repo=REPO, revision=revision, parent_revision=before.sha, commit_url=result.commit_url, release_prefix=PREFIX, new_files=len(entries), old_files_preserved=len(baseline['files']), all_old_identities_exact=True, all_downloads_byte_exact=True, downloads=downloads, chunks=commits, default_promotion=False, semantic_accuracy=None))
    print(json.dumps(dict(status='published_and_verified', revision=revision, new_files=len(entries))))
if __name__ == '__main__':
    main()
