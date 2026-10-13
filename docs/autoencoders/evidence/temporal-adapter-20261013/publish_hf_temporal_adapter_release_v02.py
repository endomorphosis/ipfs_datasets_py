"""Publish an independently reviewed prefix-only temporal-adapter archive.

No model/checkpoint parser or private global-body read. All commits require
unchanged parent CAS and are followed by immutable revision CLI readback.
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261013-temporal-adapter-v1'
MAX_PAYLOAD_BYTES, MAX_FILE_BYTES = 200000000, 10000000
CELLS = ('temporal-ce-control','temporal-anchor-margin')
PANELS = ('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law')
READ_PINS, PRIVATE_REFERENCE_PINS, RUNTIME_PRIVATE_AUTHORITY = {}, {}, {}
CONTRACT = dict(max_files=48,max_raw_bytes=16000000,parent_CAS_every_chunk=True,additions_only=True)
PUBLIC_RUNTIME = ('pre-admission.json','scheduler-adoption.json','lease-binding.json','command.json',
    'child-identity.json','resource-observations.json','child-exit.json','group-rss-summary.json',
    'owned-group-final.json','guardian-exit.json','lease-observations.jsonl','group-rss-observations.jsonl','child.log')
SOURCE_SHA = '95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035'
SOURCE_STATE_SHA = 'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5'

def private(path):
    path=Path(path)
    return ('private-runtime-snapshots' in path.parts or path.name in
        {'resources-start.json','resources-final.json','disk-reservations.json'}
        or path.name.startswith('ipfs-datasets-resource-scheduler-'))

def require(condition, message):
    if not condition:
        raise ValueError(message)

def brief(record):
    require(type(record) is dict and set(record) in ({'bytes', 'sha256'}, {'path', 'bytes', 'sha256'}),
            'closed raw identity required')
    require(type(record['bytes']) is int and 0 <= record['bytes'] <= MAX_PAYLOAD_BYTES
            and type(record['sha256']) is str and len(record['sha256']) == 64
            and all(c in '0123456789abcdef' for c in record['sha256']), 'bounded raw identity required')
    return {k: record[k] for k in ('bytes', 'sha256')}

def pin(path):
    path = Path(path)
    require(not private(path), 'private global bodies remain unopened')
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            'exact physical absolute file required')
    before = path.stat()
    require(before.st_size <= MAX_PAYLOAD_BYTES, 'raw input byte cap exceeded')
    raw = path.read_bytes(); after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) and len(raw) == before.st_size,
            'file changed during raw pin')
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def read(path, expected=None):
    path = Path(path)
    require('checkpoint' not in path.name and 'reference-packet' not in path.name,
            'checkpoint/reference JSON parsing prohibited')
    captured = pin(path)
    require(expected is None or captured == expected, 'consumed metadata differs from required descriptor')
    raw = path.read_bytes()
    require(brief(captured) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) and pin(path) == captured,
            'consumed metadata bytes differ from opening pin')
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == captured, 'previous parsed identity changed')
    READ_PINS[str(path)] = captured
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key'); result[key] = value
        return result
    def finite(raw):
        result = float(raw); require(math.isfinite(result), 'nonfinite JSON number'); return result
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def write(path, raw):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return pin(path)

def write_json(path, value):
    return write(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())

def clean(review, schema):
    require(type(review) is dict and review.get('schema') == schema and review.get('findings') == []
            and (review.get('passed') is True or review.get('status') == 'PASS')
            and ('passed' not in review or review['passed'] is True)
            and ('status' not in review or review['status'] == 'PASS'), 'clean exact qualification required')

def approved_map(review):
    require((review.get('passed') is True or review.get('status') == 'PASS') and review.get('findings') == [],
            'clean independent review required')
    require(type(review.get('artifacts')) is dict and review['artifacts'], 'raw review artifact map required')
    result = {}
    for path, expected in review['artifacts'].items():
        require(type(path) is str and ('path' not in expected or expected['path'] == path), 'review path identity differs')
        expected = brief(expected)
        if private(path):
            require(RUNTIME_PRIVATE_AUTHORITY.get(path) == expected,
                    'private identity reference must join qualified runtime metadata')
            require(path not in PRIVATE_REFERENCE_PINS or PRIVATE_REFERENCE_PINS[path] == expected,
                    'conflicting qualified private identity reference')
            PRIVATE_REFERENCE_PINS[path] = expected
            continue
        result[path] = expected
        require(brief(pin(path)) == expected, 'independently reviewed public bytes changed')
    return result

def checked_review(path, schema):
    captured = pin(path); review = read(path, captured)
    clean(review, schema)
    approved = approved_map(review)
    require(pin(path) == captured, 'independent review changed while checking')
    return review, captured, approved

def fence(approved):
    for path, expected in approved.items():
        require(brief(pin(path)) == expected, 'closing approved source identity changed')
    for path, expected in READ_PINS.items():
        require(pin(path) == expected, 'closing consumed metadata identity changed')

def identities(info):
    result = {}
    for item in info.siblings:
        require(item.rfilename not in result, 'duplicate Hub sibling path')
        result[item.rfilename] = dict(size=item.size, blob_id=item.blob_id,
            lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size))
    return result

def chunks(entries):
    result=[]; current=[]; size=0
    for name in sorted(entries):
        amount=entries[name]['bytes']
        require(type(amount) is int and 0 <= amount < MAX_FILE_BYTES, 'bounded single public artifact required')
        if current and (len(current)==CONTRACT['max_files'] or size+amount>CONTRACT['max_raw_bytes']):
            result.append(current); current=[]; size=0
        current.append(name); size+=amount
    if current: result.append(current)
    require(result and all(len(group)<=CONTRACT['max_files'] and
            sum(entries[name]['bytes'] for name in group)<=CONTRACT['max_raw_bytes'] for group in result), 'closed bounded chunks required')
    return result

def byte_identity(record, raw):
    if record['lfs'] is not None:
        return record['size']==len(raw) and record['lfs']['size']==len(raw) and record['lfs']['sha256']==hashlib.sha256(raw).hexdigest()
    return record['size']==len(raw) and record['blob_id']==hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def close_payload(root, entries, approved, review_path, review_pin):
    require(pin(review_path)==review_pin, 'concrete publication review changed')
    fence(approved)
    for name, expected in entries.items():
        require(pin(root/name)==expected, 'reviewed local payload identity changed')


def owned(descriptor, pattern):
    require(set(descriptor)=={'path','bytes','sha256'}, 'closed owned source descriptor required')
    path=Path(descriptor['path'])
    require(path.parent==F and re.fullmatch(pattern,path.name) and pin(path)==descriptor,
        'exact owned producer descriptor required')
    return path


def main(args):
    review_path=Path(args.review);review_pin=pin(review_path);review=read(review_path,review_pin)
    clean(review,'temporal-adapter-Hub-publication-independent-review/v1')
    require(set(review)=={'schema','passed','findings','repository','release_prefix','expected_parent_revision',
        'payload_files','payload_bytes','artifacts','scope','limitations'},'closed concrete publication review required')
    # Read the concrete-bound receipt first, then authenticate private references
    # against its exact already-qualified runtime metadata, never their bodies.
    receipt_path=F/'hf-preparation-receipt-v02.json';receipt_pin=pin(receipt_path)
    require(brief(review['artifacts'][str(receipt_path)])==brief(receipt_pin),'concrete review must bind exact receipt')
    receipt=read(receipt_path,receipt_pin)
    require(set(receipt)=={'schema','repository','release_prefix','expected_parent_revision','upload_root','complete_upload_files',
        'payload_files','payload_bytes','baseline_pin','freeze_manifest','result_review','runtime_review','helper_review',
        'release_spec','source_preparer','source_publisher','approved_source_artifacts','qualified_runtime_private_identity_references',
        'default_promotion','additive_only'} and receipt['schema']=='temporal-adapter-Hub-preparation/v1'
        and receipt['default_promotion'] is False and receipt['additive_only'] is True,'closed additive preparation receipt required')
    runtime_descriptor=receipt['runtime_review'];require(brief(review['artifacts'][runtime_descriptor['path']])==brief(runtime_descriptor),
        'actual runtime review descriptor needs concrete raw provenance')
    runtime=read(runtime_descriptor['path'],runtime_descriptor);clean(runtime,'temporal-adapter-runtime-independent-review/v1')
    RUNTIME_PRIVATE_AUTHORITY.update({path:brief(value) for path,value in runtime['artifacts'].items() if private(path)})
    approved=approved_map(review)
    def read_approved(descriptor):
        require(approved.get(descriptor['path'])==brief(descriptor),'parsed source needs exact concrete provenance')
        return read(descriptor['path'],descriptor)
    owned(receipt['source_preparer'],r'prepare_hf_temporal_adapter_release_v[0-9]{2}\.py')
    require(owned(receipt['source_publisher'],r'publish_hf_temporal_adapter_release_v[0-9]{2}\.py')==Path(__file__).resolve(),
        'actual publisher must equal qualified source descriptor')
    for descriptor in (receipt['source_preparer'],receipt['source_publisher'],receipt['release_spec'],receipt['baseline_pin'],receipt['freeze_manifest']):
        require(approved.get(descriptor['path'])==brief(descriptor),'required actual input not independently bound')
    baseline=read_approved(receipt['baseline_pin'])
    require(receipt['repository']==baseline['repo']==review['repository']==REPO and receipt['release_prefix']==review['release_prefix']==PREFIX
        and receipt['expected_parent_revision']==review['expected_parent_revision']==baseline['revision'],'one exact repository/prefix/parent required')
    for key,schema in (('result_review','temporal-adapter-result-independent-review/v1'),
        ('runtime_review','temporal-adapter-runtime-independent-review/v1'),('helper_review','temporal-adapter-Hub-helper-source-independent-review/v1')):
        value=read_approved(receipt[key]);clean(value,schema)
        for path,expected in approved_map(value).items():
            require(receipt['approved_source_artifacts'].get(path)==expected,'prepared qualification source map differs')
    for path,expected in receipt['approved_source_artifacts'].items():
        require(not private(path) and approved.get(path)==brief(expected) and brief(pin(path))==brief(expected),
            'entire prepared public provenance must remain concrete-bound')
    require(receipt['qualified_runtime_private_identity_references']==PRIVATE_REFERENCE_PINS,
        'prepared private identity references differ from qualified metadata only joins')
    entries=receipt['complete_upload_files']; root=Path(receipt['upload_root'])
    require(root==F/'hf-upload-v02' and root.is_absolute() and root.resolve()==root and root.is_dir() and not root.is_symlink(), 'exact owned upload root required')
    require(type(entries) is dict and type(receipt['payload_files']) is int and review['payload_files']==receipt['payload_files']==len(entries)
            and 0<len(entries)<=1000 and type(receipt['payload_bytes']) is int
            and review['payload_bytes']==receipt['payload_bytes']==sum(brief(value)['bytes'] for value in entries.values())
            and 0<receipt['payload_bytes']<=MAX_PAYLOAD_BYTES, 'closed bounded concrete payload required')
    files=list(root.rglob('*'))
    require(not any(path.is_symlink() for path in files) and set(path.relative_to(root).as_posix() for path in files if path.is_file())==set(entries),
            'exact symlink-free physical payload tree required')
    for name, expected in entries.items():
        require(type(name) is str and name.startswith(PREFIX+'/') and '..' not in Path(name).parts and not Path(name).is_absolute()
                and set(expected)=={'path','bytes','sha256'} and expected['bytes']<MAX_FILE_BYTES and pin(root/name)==expected
                and approved.get(str(root/name))==brief(expected), 'every bounded prefix addition needs concrete raw approval')
    require(not any(name.startswith(PREFIX+'/') for name in baseline['files']), 'release prefix must be absent in original tree')
    payload={name:(root/name).read_bytes() for name in sorted(entries)}
    require(all(brief(entries[name])==dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for name,raw in payload.items()),
            'immutable consumed upload bytes differ from approved payload')
    close_payload(root,entries,approved,review_path,review_pin)
    planned=chunks(entries)
    from huggingface_hub import HfApi, CommitOperationAdd
    api=HfApi(); before=api.model_info(REPO,files_metadata=True)
    require(before.sha==baseline['revision'] and identities(before)==baseline['files'], 'all original Hub identities and root attributes must match baseline')
    write_json(F/'hf-preupload-custody-v01.json',dict(repo=REPO,parent_revision=before.sha,old_files=len(baseline['files']),
        review=review_pin,receipt=READ_PINS[str(receipt_path)],chunks=planned,chunk_contract=CONTRACT,additive_only=True))
    current=baseline['revision']; published_identities={}; commits=[]
    for index,names in enumerate(planned,1):
        close_payload(root,entries,approved,review_path,review_pin)
        opening=api.model_info(REPO,files_metadata=True); opening_files=identities(opening)
        require(opening.sha==current and opening_files=={**baseline['files'],**published_identities}, 'exact old/prior identities and parent required before each chunk')
        require(all(name not in opening_files for name in names), 'every commit operation must add an absent prefix path')
        write_json(F/f'hf-chunk-{index:02d}-preupload-v01.json',dict(parent_revision=current,names=names,
            raw_bytes=sum(entries[name]['bytes'] for name in names),additions_only=True))
        try:
            result=api.create_commit(repo_id=REPO,repo_type='model',revision='main',parent_commit=current,
                operations=[CommitOperationAdd(path_in_repo=name,path_or_fileobj=payload[name]) for name in names],num_threads=2,
                commit_message=f'Archive temporal adapter part {index}/{len(planned)}',
                commit_description='Two opt-in source-only temporal adapter candidates;32 fresh Adam updates each. Exposed authored engineering measurements; no default promotion or legal-semantic qualification.')
        except Exception as error:
            write_json(F/f'hf-chunk-{index:02d}-unknown-outcome-v01.json',dict(parent_revision=current,names=names,
                error_type=type(error).__name__,message=str(error),automatic_retry_performed=False,reconciliation_required_before_resume=True))
            raise
        revision=result.oid
        write_json(F/f'hf-chunk-{index:02d}-created-v01.json',dict(parent_revision=current,revision=revision,commit_url=result.commit_url,names=names))
        info=api.model_info(REPO,revision=revision,files_metadata=True); after=identities(info)
        require(info.sha==revision and all(after.get(name)==record for name,record in {**baseline['files'],**published_identities}.items()),
                'old/root-attributes/previous-owned identities changed')
        require(set(after)==set(baseline['files'])|set(published_identities)|set(names), 'unexpected chunk additions or deletions')
        require(all(byte_identity(after[name],payload[name]) for name in names), 'new immutable byte identities differ')
        published_identities.update({name:after[name] for name in names}); current=revision
        record=dict(parent_revision=opening.sha,revision=current,new_files=len(names),all_old_and_prior_owned_identities_exact=True,new_byte_identities_exact=True)
        write_json(F/f'hf-chunk-{index:02d}-verified-v01.json',record); commits.append(record)
        print(json.dumps(dict(status='chunk_committed_and_identity_verified',chunk=index,chunks=len(planned),files=len(published_identities),revision=current)),flush=True)
    close_payload(root,entries,approved,review_path,review_pin)
    require(set(published_identities)==set(entries), 'complete additive release required')
    revision=current
    write_json(F/'hf-commit-created-v01.json',dict(repo=REPO,revision=revision,parent_revision=before.sha,
        commit_url=f'https://huggingface.co/{REPO}/commit/{revision}',release_prefix=PREFIX,additions=len(entries),chunks=commits,default_promotion=False))
    write_json(F/'hf-after-file-identities-v01.json',dict(repo=REPO,revision=revision,files={**baseline['files'],**published_identities}))
    destination=F/'hf-verified-download-v01'; require(not os.path.lexists(destination), 'exclusive immutable CLI readback destination required')
    with (F/'hf-download-verification-v01.log').open('x') as output:
        completed=subprocess.run(['hf','download',REPO,'--revision',revision,'--include',PREFIX+'/*','--local-dir',str(destination),'--max-workers','2'],
            stdout=output,stderr=subprocess.STDOUT)
        output.flush(); os.fsync(output.fileno())
    require(completed.returncode==0, 'immutable CLI readback failed')
    downloads={}
    for name,expected in entries.items():
        actual=pin(destination/name)
        require(brief(actual)==brief(expected) and pin(root/name)==expected, 'immutable downloaded bytes differ from reviewed upload')
        downloads[name]=actual
    close_payload(root,entries,approved,review_path,review_pin)
    write_json(F/'hf-publication-verification-v01.json',dict(schema='temporal-adapter-Hub-verification/v1',passed=True,findings=[],repo=REPO,
        revision=revision,parent_revision=before.sha,commit_url=f'https://huggingface.co/{REPO}/commit/{revision}',release_prefix=PREFIX,
        new_files=len(entries),old_files_preserved=len(baseline['files']),all_old_identities_exact=True,all_downloads_byte_exact=True,
        downloads=downloads,chunks=commits,default_promotion=False,semantic_accuracy=None))
    print(json.dumps(dict(status='published_and_verified',revision=revision,new_files=len(entries))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--review',required=True)
    main(parser.parse_args())
