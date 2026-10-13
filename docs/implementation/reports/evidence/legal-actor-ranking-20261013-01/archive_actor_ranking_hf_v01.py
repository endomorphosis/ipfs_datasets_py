"""Additive, reviewed N9 archive with parent CAS and immutable byte readback.

Checkpoints are opaque bytes. Private resource bodies are never opened here.
The shared parent weights stay in their already verified release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261013-actor-ranking-v1'
MAX_BYTES = 200000000
PUBLIC_RUNTIME = ('pre-admission.json', 'scheduler-adoption.json', 'lease-binding.json', 'command.json',
    'child-identity.json', 'resource-observations.json', 'child-exit.json', 'group-rss-summary.json',
    'owned-group-final.json', 'guardian-exit.json', 'lease-observations.jsonl', 'group-rss-observations.jsonl', 'child.log')
READ_PINS = {}


def require(value, message):
    if not value:
        raise ValueError(message)


def private(path):
    p = Path(path)
    return ('private-runtime-snapshots' in p.parts or p.name in
        {'resources-start.json', 'resources-final.json', 'resources-final-failure.json', 'disk-reservations.json'}
        or p.name.startswith('ipfs-datasets-resource-scheduler-'))


def brief(v):
    require(type(v) is dict and set(v) in ({'bytes', 'sha256'}, {'path', 'bytes', 'sha256'}), 'Closed raw descriptor required')
    require(type(v['bytes']) is int and 0 <= v['bytes'] <= MAX_BYTES and type(v['sha256']) is str
            and len(v['sha256']) == 64 and all(c in '0123456789abcdef' for c in v['sha256']), 'Bounded SHA256 descriptor required')
    return {k: v[k] for k in ('bytes', 'sha256')}


def pin(path):
    p = Path(path)
    require(p.is_absolute() and p.resolve() == p and not p.is_symlink() and p.is_file() and not private(p), 'Public physical ordinary file required')
    a = p.stat(); require(a.st_size <= MAX_BYTES, 'Raw byte bound exceeded')
    raw = p.read_bytes(); b = p.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(a) == identity(b) and len(raw) == a.st_size, 'Source changed while hashing')
    return dict(path=str(p), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read(path, expected=None):
    p = Path(path)
    require('checkpoint' not in p.name and 'reference-packet' not in p.name, 'Model/reference parsing prohibited')
    before = pin(p); require(expected is None or before == expected, 'Required metadata identity differs')
    raw = p.read_bytes()
    require(brief(before) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) and pin(p) == before, 'Consumed metadata changed')
    require(str(p) not in READ_PINS or READ_PINS[str(p)] == before, 'Earlier consumed input drift')
    READ_PINS[str(p)] = before
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'Duplicate JSON key'); result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def write(path, raw):
    p = Path(path)
    require(p.is_absolute() and p.resolve() == p and not private(p), 'Owned physical public output required')
    with p.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    p.chmod(0o444)
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return pin(p)


def write_json(path, value):
    return write(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())


def identities(info):
    result = {}
    for item in info.siblings:
        require(item.rfilename not in result, 'Duplicate Hub path')
        result[item.rfilename] = dict(size=item.size, blob_id=item.blob_id,
            lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size))
    return result


def destination(name):
    p = Path(name)
    require(type(name) is str and name.startswith(PREFIX + '/') and not p.is_absolute()
            and '..' not in p.parts and p.as_posix() == name and not private(p), 'Exact prefix-only public destination required')
    return name


def clean(value, schema):
    require(value.get('schema') == schema and value.get('passed') is True and value.get('findings') == [], 'Clean exact independent review required')


def approved(review):
    require(type(review.get('artifacts')) is dict and review['artifacts'], 'Independent raw artifact map required')
    result = {}
    for path, descriptor in review['artifacts'].items():
        expected = brief(descriptor)
        if private(path):
            continue
        require(brief(pin(path)) == expected, 'Reviewed public artifact drift')
        result[path] = expected
    return result


def fence(mapping):
    for path, expected in mapping.items():
        require(brief(pin(path)) == brief(expected), 'Closing raw identity differs')
    for path, descriptor in READ_PINS.items():
        require(pin(path) == descriptor, 'Closing parsed metadata differs')


def baseline():
    from huggingface_hub import HfApi
    info = HfApi().model_info(REPO, files_metadata=True); files = identities(info)
    require(files and '.gitattributes' in files and not any(n.startswith(PREFIX + '/') for n in files), 'New release prefix must be absent')
    print(write_json(F / 'hf-before-file-identities-v01.json', dict(repo=REPO, revision=info.sha, files=files)))


def prepare():
    spec_path = F / 'hf-release-spec-v01.json'; source_review = F / 'hf-helper-source-independent-review-v01.json'
    spec = read(spec_path); review = read(source_review)
    clean(review, 'actor-ranking-Hub-helper-source-independent-review/v1'); allowed = approved(review)
    require(allowed.get(str(spec_path)) == brief(pin(spec_path))
            and allowed.get(str(Path(__file__).resolve())) == brief(pin(Path(__file__).resolve())), 'Actual spec and archive source must be independently bound')
    require(set(spec) == {'schema', 'repository', 'release_prefix', 'baseline', 'freeze', 'runtime_review', 'result_review', 'files'}
            and spec['schema'] == 'actor-ranking-Hub-release-spec/v1' and spec['repository'] == REPO and spec['release_prefix'] == PREFIX, 'Closed release spec required')
    for key, schema in (('runtime_review', 'actor-ranking-runtime-independent-review/v1'),
                        ('result_review', 'actor-ranking-result-independent-review/v1')):
        d = spec[key]; require(allowed.get(d['path']) == brief(d), 'Concrete science qualification not source-bound')
        value = read(d['path'], d); clean(value, schema)
        for path, expected in approved(value).items():
            require(path not in allowed or allowed[path] == expected, 'Conflicting independent provenance')
            allowed[path] = expected
    for key in ('baseline', 'freeze'):
        d = spec[key]; require(allowed.get(d['path']) == brief(d), 'Exact source descriptor not bound')
    before = read(spec['baseline']['path'], spec['baseline']); freeze = read(spec['freeze']['path'], spec['freeze'])
    require(before['repo'] == REPO and before['files'] and not any(n.startswith(PREFIX + '/') for n in before['files']), 'Absent-prefix baseline required')
    require(freeze['schema'] == 'actor-ranking-output-freeze/v1' and freeze['all_outputs_frozen'] is True
            and freeze['authorizes_authored_eval_scoring'] is True and freeze['actual_returned_optimizer_updates'] == 32
            and len(freeze['results']) == 62, 'One actual completed actor-only candidate required')
    root = F / 'hf-upload-v01'; require(not os.path.lexists(root), 'Exclusive new payload tree required')
    require(type(spec['files']) is list and 0 < len(spec['files']) <= 500, 'Finite explicit release inventory required')
    names, total = set(), 0
    for row in spec['files']:
        require(set(row) == {'source', 'destination'}, 'Closed public copy row required')
        d = row['source']; name = destination(row['destination'])
        require(name not in names and allowed.get(d['path']) == brief(d) and pin(d['path']) == d and d['bytes'] < 10000000, 'Unique independently reviewed bounded public source required')
        names.add(name); total += d['bytes']
    required = {PREFIX + '/cells/actor-ranking-hinge/results/' + Path(p).name for p in freeze['results']}
    require(len(freeze['results']) == len(required) == 62, 'Exact62 frozen candidate results required')
    actual_sources = {row['destination']: row['source'] for row in spec['files']}
    for path, descriptor in freeze['results'].items():
        name = PREFIX + '/cells/actor-ranking-hinge/results/' + Path(path).name
        require(actual_sources.get(name) == dict(path=path, **brief(descriptor)), 'Result destination must contain exactly its frozen original bytes')
    for name, path in [('legal_span_actor_ranking.py', F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_ranking.py'),
                       ('test_legal_span_actor_ranking_contracts.py', F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_ranking_contracts.py')]:
        require(actual_sources.get(PREFIX + '/source/' + name) == pin(path), 'Actual new trainer and contract tests must be archived exactly')
    require(required <= names and PREFIX + '/README.md' in names and PREFIX + '/source/legal_span_actor_ranking.py' in names
            and PREFIX + '/source/test_legal_span_actor_ranking_contracts.py' in names and total <= MAX_BYTES, 'Complete candidate results, new source, tests and model card required')
    fence(allowed); root.mkdir(mode=0o700); entries = {}
    for row in spec['files']:
        d, name = row['source'], row['destination']; raw = Path(d['path']).read_bytes()
        require(brief(d) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) and pin(d['path']) == d, 'Consumed public copy differs')
        target = root / name; target.parent.mkdir(parents=True, exist_ok=True); entries[name] = write(target, raw)
    fence(allowed)
    print(write_json(F / 'hf-preparation-receipt-v01.json', dict(schema='actor-ranking-Hub-preparation/v1', repository=REPO,
        release_prefix=PREFIX, expected_parent_revision=before['revision'], baseline=spec['baseline'], source_spec=pin(spec_path),
        source_archive=pin(Path(__file__).resolve()), source_review=pin(source_review), upload_root=str(root), entries=entries,
        payload_files=len(entries), payload_bytes=sum(d['bytes'] for d in entries.values()), default_promotion=False, additions_only=True)))


def chunks(entries):
    result, current, size = [], [], 0
    for name in sorted(entries):
        amount = brief(entries[name])['bytes']; require(amount < 10000000, 'Single-file bound exceeded')
        if current and (len(current) == 48 or size + amount > 16000000):
            result.append(current); current, size = [], 0
        current.append(name); size += amount
    if current: result.append(current)
    return result


def byte_identity(identity, raw):
    if identity['lfs'] is not None:
        return identity['size'] == len(raw) and identity['lfs']['size'] == len(raw) and identity['lfs']['sha256'] == hashlib.sha256(raw).hexdigest()
    return identity['size'] == len(raw) and identity['blob_id'] == hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def publish():
    review_path = F / 'hf-publication-independent-review-v01.json'; review_pin = pin(review_path); review = read(review_path, review_pin)
    clean(review, 'actor-ranking-Hub-publication-independent-review/v1'); allowed = approved(review)
    receipt_path = F / 'hf-preparation-receipt-v01.json'
    require(allowed.get(str(receipt_path)) == brief(pin(receipt_path)), 'Concrete preparation must be bound')
    receipt = read(receipt_path); root = F / 'hf-upload-v01'; entries = receipt['entries']
    require(receipt['schema'] == 'actor-ranking-Hub-preparation/v1' and receipt['repository'] == REPO and receipt['release_prefix'] == PREFIX
            and receipt['upload_root'] == str(root) and receipt['additions_only'] is True and receipt['default_promotion'] is False
            and receipt['source_archive'] == pin(Path(__file__).resolve()), 'Exact reviewed additive receipt required')
    for key, expected_path in [('source_spec', F / 'hf-release-spec-v01.json'),
                               ('source_archive', Path(__file__).resolve()),
                               ('source_review', F / 'hf-helper-source-independent-review-v01.json')]:
        d = receipt[key]
        require(d['path'] == str(expected_path) and allowed.get(d['path']) == brief(d) and pin(expected_path) == d,
                'Actual archive source, spec and helper qualification must be concrete-bound')
    helper_review = read(receipt['source_review']['path'], receipt['source_review'])
    clean(helper_review, 'actor-ranking-Hub-helper-source-independent-review/v1')
    source_spec = read(receipt['source_spec']['path'], receipt['source_spec'])
    require(source_spec['repository'] == REPO and source_spec['release_prefix'] == PREFIX
            and source_spec['baseline'] == receipt['baseline'], 'Actual source specification must join receipt')
    require(review['repository'] == REPO and review['release_prefix'] == PREFIX and review['expected_parent_revision'] == receipt['expected_parent_revision']
            and review['payload_files'] == receipt['payload_files'] == len(entries) and 0 < len(entries) <= 500
            and review['payload_bytes'] == receipt['payload_bytes'] == sum(brief(d)['bytes'] for d in entries.values()) <= MAX_BYTES, 'Concrete repository, parent and bounded payload required')
    actual = list(root.rglob('*'))
    require(not any(p.is_symlink() for p in actual) and {p.relative_to(root).as_posix() for p in actual if p.is_file()} == set(entries), 'Exact physical payload inventory required')
    for name, d in entries.items():
        destination(name); require(pin(root / name) == d and allowed.get(str(root / name)) == brief(d), 'Every prefix payload byte must be independently reviewed')
    before = read(receipt['baseline']['path'], receipt['baseline'])
    require(allowed.get(receipt['baseline']['path']) == brief(receipt['baseline']) and before['repo'] == REPO
            and before['revision'] == receipt['expected_parent_revision'] and not any(n.startswith(PREFIX + '/') for n in before['files']), 'Immutable absent-prefix baseline required')
    payload = {n: (root / n).read_bytes() for n in entries}
    require(all(brief(entries[n]) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) for n, raw in payload.items()), 'Consumed publication bytes differ')
    def close():
        require(pin(review_path) == review_pin, 'Concrete publication review drift'); fence(allowed)
        for n, d in entries.items(): require(pin(root / n) == d, 'Concrete payload drift')
    close()
    from huggingface_hub import HfApi, CommitOperationAdd
    api = HfApi(); current = before['revision']; original = before['files']; additions = {}; commits = []
    groups = chunks(entries)
    for index, names in enumerate(groups, 1):
        close(); live = api.model_info(REPO, files_metadata=True)
        require(live.sha == current and identities(live) == {**original, **additions} and all(n not in original and n not in additions for n in names), 'Exact current parent and all previous identities required')
        write_json(F / f'hf-chunk-{index:02d}-preupload-v01.json', dict(parent_revision=current, names=names, additions_only=True))
        try:
            result = api.create_commit(repo_id=REPO, repo_type='model', revision='main', parent_commit=current, num_threads=2,
                operations=[CommitOperationAdd(path_in_repo=n, path_or_fileobj=payload[n]) for n in names],
                commit_message=f'Archive actor ranking part {index}/{len(groups)}',
                commit_description='One source-only 32-update actor ranking candidate; frozen shared parent; exposed engineering diagnostics. No default promotion or statutory-semantic qualification.')
        except Exception as error:
            write_json(F / f'hf-chunk-{index:02d}-unknown-outcome-v01.json', dict(parent_revision=current, names=names, error_type=type(error).__name__,
                automatic_retry_performed=False, reconciliation_required_before_resume=True)); raise
        revision = result.oid
        write_json(F / f'hf-chunk-{index:02d}-created-v01.json', dict(parent_revision=current, revision=revision, names=names))
        info = api.model_info(REPO, revision=revision, files_metadata=True); after = identities(info)
        require(info.sha == revision and set(after) == set(original) | set(additions) | set(names)
                and all(after.get(n) == d for n, d in {**original, **additions}.items())
                and all(byte_identity(after[n], payload[n]) for n in names), 'All previous and newly added immutable identities must match')
        commits.append(dict(parent_revision=current, revision=revision, new_files=len(names), old_identities_exact=True, new_byte_identities_exact=True))
        additions.update({n: after[n] for n in names}); current = revision
        write_json(F / f'hf-chunk-{index:02d}-verified-v01.json', commits[-1]); print(json.dumps(commits[-1]), flush=True)
    close(); require(set(additions) == set(entries), 'Complete publication required')
    write_json(F / 'hf-commit-created-v01.json', dict(repo=REPO, revision=current, parent_revision=before['revision'], release_prefix=PREFIX,
        new_files=len(entries), old_files_preserved=len(original), chunks=commits, default_promotion=False))
    target = F / 'hf-verified-download-v01'; require(not os.path.lexists(target), 'Exclusive immutable CLI readback destination required')
    with (F / 'hf-download-verification-v01.log').open('x') as stream:
        done = subprocess.run(['hf', 'download', REPO, '--revision', current, '--include', PREFIX + '/*', '--local-dir', str(target), '--max-workers', '2'],
            stdout=stream, stderr=subprocess.STDOUT); stream.flush(); os.fsync(stream.fileno())
    require(done.returncode == 0, 'Immutable CLI readback failed')
    downloads = {}
    for name, d in entries.items():
        downloads[name] = pin(target / name); require(brief(downloads[name]) == brief(d), 'Downloaded bytes differ')
    close()
    print(write_json(F / 'hf-publication-verification-v01.json', dict(schema='actor-ranking-Hub-verification/v1', passed=True, findings=[],
        repo=REPO, revision=current, parent_revision=before['revision'], release_prefix=PREFIX, new_files=len(entries), old_files_preserved=len(original),
        all_old_identities_exact=True, all_downloads_byte_exact=True, downloads=downloads, chunks=commits, default_promotion=False, semantic_accuracy=None)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('action', choices=('baseline', 'prepare', 'publish'))
    args = parser.parse_args(); {'baseline': baseline, 'prepare': prepare, 'publish': publish}[args.action]()
