"""Publish a verified recovery archive additively, then verify immutable downloads."""
from datetime import datetime, timezone
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import stat
import sys

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'archives/20261014-owned-released-results-v1'
PREPARED = F / 'owned-results-archive-prepared-v01.json'
PREPARED_PIN = dict(path=str(PREPARED), bytes=801434,
    sha256='5be5dfc877425e0fcc94ce00a2a5416b07d638133f3eeeaee791e326a18e39b3')
REVIEW = F / 'owned-results-archive-prepared-independent-review-v02.json'
GATE = F / 'owned-results-archive-hf-source-independent-review-v01.json'
OUTPUT = F / 'owned-results-archive-hf-publication-v01.json'
COMMIT = F / 'owned-results-archive-hf-commit-v01.json'
BEFORE = F / 'owned-results-archive-hf-before-v01.json'
AFTER = F / 'owned-results-archive-hf-after-v01.json'
FAILURE = F / 'owned-results-archive-hf-failure-v01.json'
CARD = F / 'owned-results-archive-README-v01.txt'
DOWNLOAD = F / 'owned-results-archive-hf-readback-v01'
STATE = dict(stage='source_gate', revision=None, commit_calls=0)
sys.dont_write_bytecode = True
os.environ['HF_HUB_DISABLE_XET'] = '1'


def require(value, message):
    if not value:
        raise ValueError(message)


class NoModel(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        require(fullname.split('.')[0] not in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'ipfs_datasets_py'},
                'Model/numerical imports prohibited in archive publication')
        return None


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), 'Physical local artifact required')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 1200000000, 'Bounded ordinary artifact required')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576), b''):
            sha.update(chunk)
    after = path.stat()
    identity = lambda s:(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), 'Artifact changed while hashing')
    return dict(path=str(path), bytes=before.st_size, sha256=sha.hexdigest())


def read(path, expected=None):
    path = Path(path)
    require('checkpoint' not in path.name and 'private-runtime-snapshots' not in path.parts,
            'Checkpoint/private bodies prohibited')
    item = pin(path)
    require(item['bytes'] <= 16 * 1024 * 1024 and (expected is None or item == expected), 'Exact public metadata required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite public JSON')))
    require(pin(path) == item, 'Consumed public metadata drift')
    return value


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)
    return pin(path)


def remote_map(info):
    require(type(info.sha) is str and len(info.sha) == 40 and all(c in '0123456789abcdef' for c in info.sha)
            and 0 < len(info.siblings) <= 12000,
            'Bounded immutable repository listing required')
    result = {}
    for item in info.siblings:
        require(type(item.rfilename) is str and item.rfilename not in result
                and type(item.size) is int and item.size >= 0
                and type(item.blob_id) is str and len(item.blob_id) == 40
                and all(c in '0123456789abcdef' for c in item.blob_id), 'Complete unique remote file identity required')
        lfs = item.lfs
        require(lfs is None or type(lfs.size) is int and lfs.size == item.size
                and type(lfs.sha256) is str and len(lfs.sha256) == 64
                and all(c in '0123456789abcdef' for c in lfs.sha256)
                and type(lfs.pointer_size) is int and lfs.pointer_size > 0, 'Typed exact LFS metadata required')
        result[item.rfilename] = dict(bytes=item.size, blob_id=item.blob_id,
            lfs=None if lfs is None else dict(sha256=lfs.sha256, size=lfs.size, pointer_size=lfs.pointer_size))
    return result


def git_blob(path, size):
    digest = hashlib.sha1(('blob ' + str(size) + '\0').encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    require(sys.argv[1:] == [] and not any(os.path.lexists(p) for p in (OUTPUT, COMMIT, BEFORE, AFTER, FAILURE, CARD, DOWNLOAD)),
            'Exclusive argument-free publication required')
    sys.meta_path.insert(0, NoModel())
    own = pin(Path(__file__).resolve())
    gate = read(GATE)
    require(gate['schema'] == 'actor-refinement-owned-results-archive-hf-source-independent-review/v1'
            and gate['passed'] is True and gate['findings'] == [] and gate['producer'] == own
            and gate['prepared'] == PREPARED_PIN, 'Exact independent publisher qualification required')
    for path, item in gate['artifacts'].items():
        require(pin(path) == dict(path=path, **{k:item[k] for k in ('bytes', 'sha256')}), 'Qualified source closure drift')
    prepared = read(PREPARED, PREPARED_PIN)
    archive = prepared['archive']
    require(prepared['schema'] == 'actor-refinement-owned-results-archive-prepared/v1' and prepared['passed'] is True
            and prepared['findings'] == [] and prepared['file_count'] == 1162 and prepared['raw_bytes'] == 934325529
            and prepared['projected_net_apparent_savings_lower_bound_bytes'] >= 750000000
            and prepared['verification']['every_member_restored_fsynced_and_readback_byte_exact'] is True
            and pin(archive['path']) == archive, 'Actual complete byte-restorable archive required')
    review_pin = pin(REVIEW); review = read(REVIEW, review_pin)
    require(review['schema'] == 'actor-refinement-owned-results-archive-prepared-independent-review/v1'
            and review['passed'] is True and review['findings'] == []
            and review['prepared'] == PREPARED_PIN and review['archive'] == archive,
            'Independent concrete prepared proof required')
    with CARD.open('x') as stream:
        stream.write('''# Recovery archive for completed LegalIR runs

This lossless archive contains 1,162 original result files from 27 successful,
released experiments: 934,325,529 uncompressed bytes. Every member was restored
to a physical probe and verified by SHA-256 before publication. The accompanying
manifest records the original paths, modes and exact byte identities.

The archive includes historical checkpoints and exposed engineering diagnostics.
It does not establish new training accuracy, statutory semantic correctness,
active 8D/384D/768D latent behavior, logic-family qualification or a Lean build.
No default model is promoted. The N11 donor and latest balanced experiment remain
uncompressed locally. Restoring original counted paths requires fresh headroom.
''')
        stream.flush(); os.fsync(stream.fileno())
    CARD.chmod(0o444)
    uploads = {'owned-released-results.tar.gz':Path(archive['path']), 'restoration-manifest.json':PREPARED, 'README.md':CARD}
    local = {PREFIX + '/' + name:pin(path) for name, path in uploads.items()}
    STATE['stage'] = 'remote_intake'
    import huggingface_hub
    from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
    require(huggingface_hub.__version__ == '0.36.2', 'Reviewed installed SDK version required')
    api = HfApi(endpoint='https://huggingface.co')
    before_info = api.model_info(REPO, revision='main', files_metadata=True, timeout=60)
    before = remote_map(before_info); parent = before_info.sha
    require(not any(path.startswith(PREFIX + '/') for path in before), 'Fresh additive archive prefix required')
    before_pin = write(BEFORE, dict(repository=REPO, revision=parent, files=before))
    operations = [CommitOperationAdd(path_in_repo=remote, path_or_fileobj=item['path']) for remote, item in local.items()]
    for item in local.values():
        require(pin(item['path']) == item, 'Pre-upload local payload drift')
    STATE.update(stage='commit', commit_calls=1)
    commit = api.create_commit(REPO, operations=operations, repo_type='model', revision='main', parent_commit=parent,
        commit_message='Archive exact completed LegalIR results before local compression', num_threads=1)
    revision = commit.oid
    require(type(revision) is str and len(revision) == 40, 'Actual immutable publication commit required')
    STATE.update(stage='immutable_readback', revision=revision)
    commit_pin = write(COMMIT, dict(repository=REPO, revision=revision, parent=parent, prefix=PREFIX, files=local))
    after_info = api.model_info(REPO, revision=revision, files_metadata=True, timeout=60)
    require(after_info.sha == revision, 'Returned repository listing must match the exact publication commit')
    after = remote_map(after_info)
    require(set(after) == set(before) | set(local) and all(after[path] == item for path,item in before.items()),
            'Every prior remote file must retain its exact identity')
    for remote, item in local.items():
        identity = after[remote]
        require(identity['bytes'] == item['bytes'], 'Remote payload length differs')
        require(identity['lfs']['sha256'] == item['sha256'] if identity['lfs'] is not None
                else identity['blob_id'] == git_blob(Path(item['path']), item['bytes']), 'Remote Git/LFS payload identity differs')
    after_pin = write(AFTER, dict(repository=REPO, revision=revision, files=after))
    downloads = {}
    for remote, item in local.items():
        path = Path(hf_hub_download(REPO, remote, repo_type='model', revision=revision,
            local_dir=DOWNLOAD, force_download=True, endpoint='https://huggingface.co'))
        require(path == DOWNLOAD / remote and path.resolve(strict=True) == path,
                'SDK readback must be the exact fresh immutable-download destination')
        downloaded = pin(path)
        require(all(downloaded[k] == item[k] for k in ('bytes', 'sha256')), 'Immutable downloaded payload bytes differ')
        downloads[remote] = downloaded
    for path, item in gate['artifacts'].items():
        require(pin(path) == dict(path=path, **{k:item[k] for k in ('bytes', 'sha256')}), 'Closing source closure drift')
    for item in local.values():
        require(pin(item['path']) == item, 'Closing local payload drift')
    value = dict(schema='actor-refinement-owned-results-archive-hf-publication/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), producer=own, source_qualification=pin(GATE),
        prepared_review=review_pin, archive=archive, manifest=PREPARED_PIN, repo=REPO, revision=revision, parent_revision=parent,
        prefix=PREFIX, commit=commit_pin, before=before_pin, after=after_pin,
        downloaded_archive=downloads[PREFIX + '/owned-released-results.tar.gz'],
        downloaded_manifest=downloads[PREFIX + '/restoration-manifest.json'], downloads=downloads,
        prior_file_count=len(before), new_file_count=3, final_file_count=len(after),
        all_prior_file_identities_preserved=True, all_new_remote_identities_verified=True,
        immutable_downloads_byte_exact=True, commit_calls=1, original_unlinks=0, resource_API_calls=0,
        default_promotion=False, model_calls=0, numerical_imports=0, checkpoint_JSON_parses=0,
        training_authorized=False, native_capacity_PASS_claimed=False)
    print(json.dumps(write(OUTPUT, value), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if not FAILURE.exists():
            write(FAILURE, dict(schema='actor-refinement-owned-results-archive-hf-failure/v1',
                error_type=type(error).__name__, **STATE, retry_performed=False, original_unlinks=0))
        raise
