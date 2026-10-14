"""One reviewed attributes correction and the five uncreated release chunks.

The interrupted V02 publisher, payload, specification and receipts stay intact.
Checkpoints are opaque bytes. Final forced Hub downloads establish retrieval,
not automatic Git LFS clone materialization or an isolated numerical reload.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261014-actor-refinement-v1'
BASE_HELPER = 'archive_actor_refinement_hf_v02.py'
BASE_HELPER_BYTES = 28426
BASE_HELPER_SHA256 = '89a01553f09ea1f228ea50ad8dd1c3d289d1dd89ddda5d2d2598e429393f53a5'
BASELINE_REVISION = '0228887c8e33cb23e9679889a9496f87140021e6'
FIRST_REVISION = '5bd19a067cd014288591b12bfc118046f8d978a2'
PARTIAL_REVISION = '1c5d3103e73895c250b84261d7ab4c4341da9a0f'
OLD_ATTRIBUTES = dict(size=2230, blob_id='1cf99f89f95ce8f39b630d8df37126fc628047de', lfs=None)
PARTIAL_ATTRIBUTES = dict(size=2359, blob_id='a2a2c85690269e3dc9a72f8d3729ee785b2587e1', lfs=None)
OLD_ATTRIBUTES_SHA256 = '88ff4d857c849ce3e11fea7c2f70d648550968cf546ab9cbc4d690e1b6543036'
PARTIAL_ATTRIBUTES_SHA256 = 'f0ad1ecaa2d81a65bb4dba0fb29222339fd93034de8729fed21b1f5c1c2de71a'
CHECKPOINT_NAME = PREFIX + '/cells/actor-refinement-ce/results/cell-checkpoint.json'
CHECKPOINT_BYTES = 12230969
CHECKPOINT_SHA256 = 'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4'
REMAINING_INDICES = [3, 4, 5, 6, 7]


def require(value, message):
    if not value:
        raise ValueError(message)


def revision(value):
    require(type(value) is str and len(value) == 40 and all(c in '0123456789abcdef' for c in value),
            'Exact returned immutable revision required')
    return value


def byte_identity(identity, raw):
    if identity['lfs'] is not None:
        return (identity['size'] == len(raw) and identity['lfs']['size'] == len(raw)
                and identity['lfs']['sha256'] == hashlib.sha256(raw).hexdigest())
    return (identity['size'] == len(raw)
            and identity['blob_id'] == hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())


def qualify_partial(original, snapshot, payload, groups, first, second, verified):
    require(type(groups) is list and len(groups) == 7 and all(type(g) is list and g for g in groups),
            'The unchanged original seven chunks are required')
    flat = [name for group in groups for name in group]
    require(len(flat) == len(set(flat)) == len(payload) == 198 and set(flat) == set(payload)
            and len(groups[0]) == 18 and len(groups[1]) == 8, 'Exact198-file original chunk geometry required')
    require(type(original) is dict and len(original) == 5448 and original.get('.gitattributes') == OLD_ATTRIBUTES,
            'Exact5448 original identities including baseline attributes required')
    require(first == dict(parent_revision=BASELINE_REVISION, revision=FIRST_REVISION, names=groups[0])
            and second == dict(parent_revision=FIRST_REVISION, revision=PARTIAL_REVISION, names=groups[1]),
            'Exact two original created-chunk receipts required')
    require(verified == dict(parent_revision=BASELINE_REVISION, revision=FIRST_REVISION,
            new_files=18, old_identities_exact=True, new_byte_identities_exact=True),
            'Original chunk1 verification must remain intact')
    require(type(snapshot) is dict and set(snapshot) == {'schema', 'repository', 'requested_revision',
            'returned_revision', 'metadata_queries', 'files'}
            and snapshot['schema'] == 'actor-refinement-Hub-partial-immutable-snapshot/v1'
            and snapshot['repository'] == REPO and snapshot['requested_revision'] == PARTIAL_REVISION
            and snapshot['returned_revision'] == PARTIAL_REVISION and type(snapshot['metadata_queries']) is int
            and snapshot['metadata_queries'] == 1, 'Exact independently observed immutable partial snapshot required')
    current = snapshot['files']; done_names = groups[0] + groups[1]
    require(type(current) is dict and len(current) == 5474 and set(current) == set(original) | set(done_names)
            and not (set(original) & set(done_names)), 'Exactly5448 original plus26 created paths required')
    require({name for name in original if current.get(name) != original[name]} == {'.gitattributes'}
            and current['.gitattributes'] == PARTIAL_ATTRIBUTES,
            'Only the authenticated attributes difference is permitted before correction')
    require(all(byte_identity(current[name], payload[name]) for name in done_names),
            'All26 previously created payload byte identities must match')
    return {name: current[name] for name in done_names}


def qualify_attributes(receipt, baseline_raw, partial_raw, original, partial):
    require(receipt['schema'] == 'actor-refinement-Hub-attributes-immutable-readback/v1'
            and receipt['repository'] == REPO and set(receipt['files']) == {'baseline', 'chunk02'}
            and receipt['raw_download_calls'] == 2 and receipt['remote_mutations'] == 0,
            'Two immutable attributes readbacks without mutations required')
    for key, raw, expected, sha, rev in [('baseline', baseline_raw, OLD_ATTRIBUTES, OLD_ATTRIBUTES_SHA256, BASELINE_REVISION),
                                       ('chunk02', partial_raw, PARTIAL_ATTRIBUTES, PARTIAL_ATTRIBUTES_SHA256, PARTIAL_REVISION)]:
        d = receipt['files'][key]
        require(d['revision'] == rev and d['remote_identity'] == expected and d['git_blob_id'] == expected['blob_id']
                and d['bytes'] == len(raw) == expected['size'] and d['sha256'] == sha == hashlib.sha256(raw).hexdigest()
                and d['immutable_download_byte_identity_matches'] is True and byte_identity(expected, raw),
                'Exact original and partial attributes raw bytes and Git identities required')
    line = (CHECKPOINT_NAME + ' filter=lfs diff=lfs merge=lfs -text\n').encode()
    require(original.get('.gitattributes') == OLD_ATTRIBUTES and partial.get('.gitattributes') == PARTIAL_ATTRIBUTES
            and partial_raw == baseline_raw + line and receipt['byte_delta'] == len(line) == 129
            and receipt['removed_lines'] == [] and receipt['added_lines'] == [line.decode().rstrip('\n')],
            'Only the exact129-byte checkpoint LFS line may explain the interruption')
    return baseline_raw


def qualify_restored(after, original, additions):
    require(type(after) is dict and after == {**original, **additions},
            'After correction every original and created payload identity must be exact')


def qualify_chunk(after, previous, names, payload):
    require(type(names) is list and names and len(names) == len(set(names))
            and all(name in payload and name not in previous for name in names),
            'Only the uncreated names in the next original chunk may be added')
    require(type(after) is dict and set(after) == set(previous) | set(names)
            and all(after.get(name) == value for name, value in previous.items())
            and all(byte_identity(after[name], payload[name]) for name in names),
            'Every old identity and every new raw byte identity must match after each chunk')
    return {name: after[name] for name in names}


def helper():
    path = F / BASE_HELPER
    require(path.is_file() and not path.is_symlink() and path.resolve() == path, 'Physical retained helper required')
    raw = path.read_bytes()
    require(len(raw) == BASE_HELPER_BYTES and hashlib.sha256(raw).hexdigest() == BASE_HELPER_SHA256,
            'The original sealed V02 helper must remain byte-identical')
    spec = importlib.util.spec_from_file_location('_retained_actor_refinement_Hub_v02', path)
    value = importlib.util.module_from_spec(spec); exec(compile(raw, str(path), 'exec'), value.__dict__)
    require(value.F == F and value.REPO == REPO and value.PREFIX == PREFIX, 'Exact retained helper phase required')
    return value


def main():
    h = helper(); own = h.pin(Path(__file__).resolve())
    source_path = F / 'hf-resume-helper-source-independent-review-v01.json'
    gate_path = F / 'hf-publication-resume-independent-review-v01.json'
    source = h.read(source_path); gate = h.read(gate_path)
    h.clean(source, 'actor-refinement-Hub-resume-helper-source-independent-review/v1')
    h.clean(gate, 'actor-refinement-Hub-publication-resume-independent-review/v1')
    allowed = {}
    def admit(value):
        for path, d in h.approved(value).items():
            require(path not in allowed or allowed[path] == d, 'Conflicting independent raw artifact identity')
            allowed[path] = d
    admit(source); admit(gate)
    require(source['producer'] == gate['producer'] == own and allowed.get(own['path']) == h.brief(own)
            and gate['source_qualification'] == h.pin(source_path)
            and allowed.get(str(source_path)) == h.brief(h.pin(source_path)), 'Exact source and concrete reconciliation gates required')
    require(gate['repository'] == REPO and gate['release_prefix'] == PREFIX
            and gate['expected_parent_revision'] == PARTIAL_REVISION and gate['corrective_path'] == '.gitattributes'
            and gate['remaining_chunk_indices'] == REMAINING_INDICES and gate['default_promotion'] is False,
            'One exact attributes correction and only original chunks3through7 are qualified')
    expected = dict(original_publication_review='hf-publication-independent-review-v01.json',
        preparation='hf-preparation-receipt-v01.json', interruption='hf-publication-interruption-v01.json',
        discrepancy='hf-publication-partial-discrepancy-independent-v01.json',
        snapshot='hf-chunk-02-immutable-independent-v01.json', attributes_readback='hf-attributes-immutable-readback-independent-v01.json')
    records = {}
    for key, filename in expected.items():
        d = gate[key]; require(d['path'] == str(F / filename) and allowed.get(d['path']) == h.brief(d),
                              'Exact concrete corrective provenance descriptor required')
        records[key] = h.read(d['path'], d)
    review = records['original_publication_review']; h.clean(review, 'actor-refinement-Hub-publication-independent-review/v1'); admit(review)
    receipt = records['preparation']; root = F / 'hf-upload-v01'; entries = receipt['entries']
    require(receipt['schema'] == 'actor-refinement-Hub-preparation/v1' and receipt['repository'] == REPO
            and receipt['release_prefix'] == PREFIX and receipt['upload_root'] == str(root)
            and receipt['additions_only'] is True and receipt['default_promotion'] is False
            and receipt['source_archive'] == h.pin(F / BASE_HELPER)
            and receipt['payload_files'] == len(entries) == 198 and receipt['payload_bytes'] == 77331365
            and receipt['algorithm_source_count'] == len(receipt['algorithm_sources']) == 40,
            'The unchanged concrete198-file preparation from sealed V02 is required')
    for key, path in [('source_spec', F / 'hf-release-spec-v01.json'), ('source_archive', F / BASE_HELPER),
                      ('source_review', F / 'hf-helper-source-independent-review-v01.json')]:
        d = receipt[key]; require(d['path'] == str(path) and allowed.get(str(path)) == h.brief(d) and h.pin(path) == d,
                                  'Original specification, helper and qualification must remain exact')
    helper_review = h.read(receipt['source_review']['path'], receipt['source_review'])
    h.clean(helper_review, 'actor-refinement-Hub-helper-source-independent-review/v1'); admit(helper_review)
    spec = h.read(receipt['source_spec']['path'], receipt['source_spec'])
    require(spec['repository'] == REPO and spec['release_prefix'] == PREFIX and spec['baseline'] == receipt['baseline']
            and review['repository'] == REPO and review['release_prefix'] == PREFIX
            and review['expected_parent_revision'] == receipt['expected_parent_revision'] == BASELINE_REVISION
            and review['payload_files'] == receipt['payload_files'] and review['payload_bytes'] == receipt['payload_bytes'],
            'Original payload, baseline, repository and parent custody must match')
    require({row['destination']: h.brief(row['source']) for row in spec['files']}
            == {name: h.brief(d) for name, d in entries.items()} and len(spec['files']) == 198,
            'Every unchanged original specification row must match its prepared payload bytes')
    before = h.qualify_hf_baseline(h.read(receipt['baseline']['path'], receipt['baseline']))
    require(allowed.get(receipt['baseline']['path']) == h.brief(receipt['baseline']) and before['revision'] == BASELINE_REVISION,
            'Exact immutable original baseline must remain reviewed')
    actual = list(root.rglob('*'))
    require(not any(p.is_symlink() for p in actual)
            and {p.relative_to(root).as_posix() for p in actual if p.is_file()} == set(entries), 'Exact unchanged physical payload inventory required')
    payload = {}
    for name, d in entries.items():
        h.destination(name); require(h.pin(root / name) == d and allowed.get(str(root / name)) == h.brief(d), 'Every original payload byte must remain reviewed')
        payload[name] = (root / name).read_bytes()
        require(h.brief(d) == dict(bytes=len(payload[name]), sha256=hashlib.sha256(payload[name]).hexdigest()), 'Consumed payload drift')
    require(sum(len(raw) for raw in payload.values()) == 77331365 and all(name in entries and h.brief(entries[name]) == h.brief(d)
            for name, d in receipt['algorithm_sources'].items()), 'Exact bounded payload with all40 source files required')
    groups = h.chunks(entries)
    require([len(group) for group in groups[2:]] == [12, 23, 48, 48, 41]
            and sum(len(payload[name]) for group in groups[2:] for name in group) == 47107394,
            'Only the original five remaining groups with172files/47107394bytes may resume')
    def bound_read(filename):
        path = F / filename; require(allowed.get(str(path)) == h.brief(h.pin(path)), 'Additional original receipt not independently bound')
        return h.read(path)
    first = bound_read('hf-chunk-01-created-v01.json'); second = bound_read('hf-chunk-02-created-v01.json')
    verified = bound_read('hf-chunk-01-verified-v01.json')
    original = before['files']; snapshot = records['snapshot']
    additions = qualify_partial(original, snapshot, payload, groups, first, second, verified)
    interruption = records['interruption']; discrepancy = records['discrepancy']
    require(interruption['schema'] == 'actor-refinement-Hub-publication-interruption/v1'
            and interruption['created_revision'] == PARTIAL_REVISION and interruption['last_verified_chunk'] == 1
            and interruption['created_but_unverified_chunk'] == 2 and interruption['automatic_retry_performed'] is False
            and interruption['final_publication_complete'] is False and interruption['exit_code'] == 1,
            'The interrupted original publication must remain recorded as failed and incomplete')
    require(discrepancy['schema'] == 'actor-refinement-Hub-partial-publication-independent-review/v1'
            and discrepancy['passed'] is False and discrepancy['reconciliation_completed'] is True
            and discrepancy['repository'] == REPO and discrepancy['baseline_revision'] == BASELINE_REVISION
            and discrepancy['created_but_unverified_revision'] == PARTIAL_REVISION
            and discrepancy['immutable_snapshot'] == gate['snapshot'] and discrepancy['interruption'] == gate['interruption']
            and discrepancy['immutable_attributes_readback'] == gate['attributes_readback']
            and discrepancy['original_identity_differences'] == {'.gitattributes': dict(before=OLD_ATTRIBUTES, after=PARTIAL_ATTRIBUTES)}
            and len(discrepancy['findings']) == 1 and discrepancy['findings'][0]['path'] == '.gitattributes',
            'The failed invariant remains failed; a distinct corrective qualification is required')
    attrs = records['attributes_readback']; raw_attrs = {}
    for key, sub in [('baseline', 'baseline'), ('chunk02', 'chunk02')]:
        d = attrs['files'][key]; path = F / 'hf-reconciliation-attrs-readback-v01' / sub / '.gitattributes'
        full = {k: d[k] for k in ('path', 'bytes', 'sha256')}
        require(d['path'] == str(path) and allowed.get(str(path)) == h.brief(full) and h.pin(path) == full,
                'Exact independently downloaded public attributes file required')
        raw_attrs[key] = path.read_bytes()
    correction = qualify_attributes(attrs, raw_attrs['baseline'], raw_attrs['chunk02'], original, snapshot['files'])
    output_names = ['hf-resume-correction-' + s + '-v01.json' for s in ['preupload', 'created', 'verified', 'unknown-outcome']]
    output_names += [f'hf-resume-chunk-{i:02d}-{s}-v01.json' for i in REMAINING_INDICES for s in ['preupload', 'created', 'verified', 'unknown-outcome']]
    output_names += ['hf-resume-commit-created-v01.json', 'hf-resume-final-file-identities-v01.json',
                     'hf-resume-download-verification-v01.log', 'hf-publication-verification-v02.json', 'hf-verified-download-v02']
    require(all(not os.path.lexists(F / name) for name in output_names), 'Exclusive one-shot recovery outputs required; no automatic restart')
    def close():
        h.fence(allowed)
        for name, d in entries.items(): require(h.pin(root / name) == d, 'Original concrete payload drift')
    close()
    require(os.environ.get('HF_ENDPOINT', 'https://huggingface.co') == 'https://huggingface.co', 'Exact public Hub endpoint required')
    import huggingface_hub
    require(huggingface_hub.__version__ == '0.36.2', 'Reviewed SDK version required')
    from huggingface_hub import HfApi, CommitOperationAdd
    api = HfApi(endpoint='https://huggingface.co'); current = PARTIAL_REVISION
    live = api.model_info(REPO, files_metadata=True)
    require(live.sha == current and h.identities(live) == snapshot['files'], 'Exact current partial parent and all5474 identities required')
    h.write_json(F / 'hf-resume-correction-preupload-v01.json', dict(parent_revision=current,
        paths=['.gitattributes'], baseline_attributes=attrs['files']['baseline'], sole_prior_file_correction=True))
    try:
        result = api.create_commit(repo_id=REPO, repo_type='model', revision='main', parent_commit=current, num_threads=2,
            operations=[CommitOperationAdd(path_in_repo='.gitattributes', path_or_fileobj=correction)],
            commit_message='Restore exact pre-release attributes after interrupted actor refinement publication',
            commit_description='Reviewed sole correction: restore original attributes bytes; keep every prior and26 payload identities. No payload retry or default promotion.')
    except Exception as error:
        h.write_json(F / 'hf-resume-correction-unknown-outcome-v01.json', dict(parent_revision=current,
            paths=['.gitattributes'], error_type=type(error).__name__, automatic_retry_performed=False,
            reconciliation_required_before_resume=True)); raise
    corrected = revision(result.oid)
    corrective = dict(parent_revision=current, revision=corrected, paths=['.gitattributes'],
                      attributes_restored_to_baseline=True, original_files=5448, preserved_payload_files=26)
    h.write_json(F / 'hf-resume-correction-created-v01.json', dict(parent_revision=current, revision=corrected, paths=['.gitattributes']))
    info = api.model_info(REPO, revision=corrected, files_metadata=True); after = h.identities(info)
    require(info.sha == corrected, 'Exact immutable corrective revision required'); qualify_restored(after, original, additions)
    close(); h.write_json(F / 'hf-resume-correction-verified-v01.json', corrective); current = corrected; commits = []
    for index, names in enumerate(groups[2:], 3):
        close(); previous = {**original, **additions}; live = api.model_info(REPO, files_metadata=True)
        require(live.sha == current and h.identities(live) == previous and all(n not in previous for n in names),
                'Exact corrected parent and all previous identities required; chunks1and2 cannot be repeated')
        h.write_json(F / f'hf-resume-chunk-{index:02d}-preupload-v01.json', dict(parent_revision=current, names=names, additions_only=True))
        try:
            result = api.create_commit(repo_id=REPO, repo_type='model', revision='main', parent_commit=current, num_threads=2,
                operations=[CommitOperationAdd(path_in_repo=n, path_or_fileobj=payload[n]) for n in names],
                commit_message=f'Archive actor refinement remaining part {index}/{len(groups)} after reviewed reconciliation',
                commit_description='Original sealed198-file payload and five remaining chunks only; all original identities preserved. Negative scientific result; no default promotion.')
        except Exception as error:
            h.write_json(F / f'hf-resume-chunk-{index:02d}-unknown-outcome-v01.json', dict(parent_revision=current, names=names,
                error_type=type(error).__name__, automatic_retry_performed=False, reconciliation_required_before_resume=True)); raise
        created = revision(result.oid)
        h.write_json(F / f'hf-resume-chunk-{index:02d}-created-v01.json', dict(parent_revision=current, revision=created, names=names))
        info = api.model_info(REPO, revision=created, files_metadata=True); after = h.identities(info)
        require(info.sha == created, 'Exact returned immutable remaining-chunk revision required')
        additions.update(qualify_chunk(after, previous, names, payload)); close()
        item = dict(chunk=index, parent_revision=current, revision=created, new_files=len(names),
                    old_identities_exact=True, new_byte_identities_exact=True)
        commits.append(item); current = created; h.write_json(F / f'hf-resume-chunk-{index:02d}-verified-v01.json', item)
    require(set(additions) == set(entries) and len(commits) == 5, 'All198 additions and exactly five resumed chunks required')
    qualify_restored(after, original, additions); close()
    h.write_json(F / 'hf-resume-final-file-identities-v01.json', dict(repo=REPO, revision=current, files=after))
    h.write_json(F / 'hf-resume-commit-created-v01.json', dict(repo=REPO, revision=current, parent_revision=BASELINE_REVISION,
        release_prefix=PREFIX, new_files=198, old_files_preserved=5448, interrupted_parent=PARTIAL_REVISION,
        corrective_commit=corrective, resumed_chunks=commits, default_promotion=False))
    target = F / 'hf-verified-download-v02'; require(not os.path.lexists(target), 'Fresh exact immutable forced-readback target required')
    with (F / 'hf-resume-download-verification-v01.log').open('x') as stream:
        done = subprocess.run(['hf', 'download', REPO, '--revision', current, '--include', PREFIX + '/*',
            '--local-dir', str(target), '--max-workers', '2', '--force-download'], stdout=stream, stderr=subprocess.STDOUT)
        stream.flush(); os.fsync(stream.fileno())
    require(done.returncode == 0, 'Forced immutable CLI readback failed')
    downloads = {}
    for name, d in entries.items():
        downloads[name] = h.pin(target / name); require(h.brief(downloads[name]) == h.brief(d), 'Forced immutable download bytes differ')
    require(len(downloads) == 198 and h.brief(downloads[CHECKPOINT_NAME]) == dict(bytes=CHECKPOINT_BYTES, sha256=CHECKPOINT_SHA256),
            'All198 raw downloads including the exact opaque checkpoint are required')
    close()
    print(h.write_json(F / 'hf-publication-verification-v02.json', dict(schema='actor-refinement-Hub-verification/v1', passed=True, findings=[],
        repo=REPO, revision=current, parent_revision=BASELINE_REVISION, release_prefix=PREFIX, new_files=198, old_files_preserved=5448,
        all_old_identities_exact=True, all_downloads_byte_exact=True, forced_download=True, downloads=downloads,
        publication_protocol='interrupted-attributes-correction-and-five-chunk-resume', original_interruption=gate['interruption'],
        original_failed_discrepancy=gate['discrepancy'], reconciliation_qualification=h.pin(gate_path), source_qualification=h.pin(source_path),
        original_created_chunks=[first, second], original_chunk1_verification=verified, chunk2_original_prior_identity_invariant_failed=True,
        corrective_commit=corrective, resumed_chunks=commits, original_chunks_reuploaded=False, additional_corrective_commits=0,
        overall_protocol_additions_only=False, all_payload_operations_additions_only=True, no_delete_operations=True,
        Git_clone_LFS_automatic_materialization_qualified=False, portable_numerical_reload_qualified=False,
        checkpoint_JSON_parses=0, model_calls=0, default_promotion=False, semantic_accuracy=None)))


if __name__ == '__main__':
    main()
