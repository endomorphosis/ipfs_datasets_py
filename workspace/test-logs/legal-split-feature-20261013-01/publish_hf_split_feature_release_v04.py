"""Publish a concrete independently reviewed additive split-feature payload.

No import-time SDK operation or model restoration. Immutable raw bytes, exact
original file identities and parent CAS on every chunk precede CLI readback.
Unknown commit outcomes are preserved without automatic retry.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261013-split-feature-v1'
MAX_PAYLOAD_BYTES = 200000000
MAX_FILE_BYTES = 10000000
READ_PINS = {}
CONTRACT = dict(max_files=48,max_raw_bytes=16000000,parent_CAS_every_chunk=True,additions_only=True)

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
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            'exact physical absolute file required')
    before = path.stat()
    require(before.st_size <= MAX_PAYLOAD_BYTES, 'raw input byte cap exceeded')
    raw = path.read_bytes(); after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
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

def approved_map(review):
    require((review.get('passed') is True or review.get('status') == 'PASS') and review.get('findings') == [],
            'clean independent review required')
    require(type(review.get('artifacts')) is dict and review['artifacts'], 'raw review artifact map required')
    result = {}
    for path, expected in review['artifacts'].items():
        require(type(path) is str and ('path' not in expected or expected['path'] == path), 'review path identity differs')
        result[path] = brief(expected)
        require(brief(pin(path)) == result[path], 'independently reviewed source bytes changed')
    return result

def checked_review(path, schema):
    captured = pin(path); review = read(path, captured)
    require(review['schema'] == schema, 'independent review schema differs')
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

def main(args):
    review_path=Path(args.review)
    review_pin=pin(review_path); review=read(review_path,review_pin)
    require(set(review)=={'schema','passed','findings','repository','release_prefix','expected_parent_revision',
            'payload_files','payload_bytes','artifacts','scope','limitations'} and review['passed'] is True
            and review['findings']==[] and review['schema']=='split-feature-Hub-publication-independent-review/v1',
            'clean exact concrete publication review required')
    approved=approved_map(review)
    required=[Path(__file__).resolve(),F/'prepare_hf_split_feature_release_v04.py',F/'hf-preparation-receipt-v01.json',
        F/'hf-before-file-identities-v01.json',F/'result-independent-review-v01.json',F/'runtime-independent-review-v01.json',
        F/'hf-helper-source-independent-review-v02.json',F/'split-feature-output-freeze-v01.json']
    for path in required: require(approved.get(str(path))==brief(pin(path)), 'required publication input not independently bound')
    def read_approved(path, expected=None):
        captured=pin(path)
        require(approved.get(str(path))==brief(captured) and (expected is None or captured==expected), 'parsed publication metadata not approved')
        return read(path,captured)
    receipt_path=F/'hf-preparation-receipt-v01.json'; receipt=read_approved(receipt_path)
    require(set(receipt)=={'schema','repository','release_prefix','expected_parent_revision','upload_root','complete_upload_files',
            'payload_files','payload_bytes','baseline_pin','result_review','runtime_review','helper_review','freeze_manifest',
            'approved_source_artifacts','default_promotion','additive_only'} and receipt['schema']=='split-feature-Hub-preparation/v1'
            and receipt['default_promotion'] is False and receipt['additive_only'] is True, 'closed additive preparation receipt required')
    baseline_path=F/'hf-before-file-identities-v01.json'; baseline=read_approved(baseline_path,receipt['baseline_pin'])
    require(receipt['repository']==baseline['repo']==review['repository']==REPO and receipt['release_prefix']==review['release_prefix']==PREFIX
            and receipt['expected_parent_revision']==review['expected_parent_revision']==baseline['revision'], 'same repository/prefix/parent required')
    schemas={'result_review':'split-feature-result-independent-review/v1','runtime_review':'split-feature-runtime-independent-review/v1',
             'helper_review':'split-feature-Hub-helper-source-independent-review/v1'}
    for key,name in [('result_review','result-independent-review-v01.json'),('runtime_review','runtime-independent-review-v01.json'),
                     ('helper_review','hf-helper-source-independent-review-v02.json'),('freeze_manifest','split-feature-output-freeze-v01.json')]:
        value=read_approved(F/name,receipt[key])
        if key in schemas:
            require(value['schema']==schemas[key], 'prepared review schema differs')
            for path, expected in approved_map(value).items():
                require(receipt['approved_source_artifacts'].get(path)==expected, 'prepared source review map differs')
    for path,expected in receipt['approved_source_artifacts'].items():
        require(approved.get(path)==brief(expected) and brief(pin(path))==brief(expected), 'concrete review must bind entire prepared source closure')
    entries=receipt['complete_upload_files']; root=Path(receipt['upload_root'])
    require(root==F/'hf-upload-v01' and root.is_absolute() and root.resolve()==root and root.is_dir() and not root.is_symlink(), 'exact owned upload root required')
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
    current=baseline['revision']; owned={}; commits=[]
    for index,names in enumerate(planned,1):
        close_payload(root,entries,approved,review_path,review_pin)
        opening=api.model_info(REPO,files_metadata=True); opening_files=identities(opening)
        require(opening.sha==current and opening_files=={**baseline['files'],**owned}, 'exact old/prior identities and parent required before each chunk')
        require(all(name not in opening_files for name in names), 'every commit operation must add an absent prefix path')
        write_json(F/f'hf-chunk-{index:02d}-preupload-v01.json',dict(parent_revision=current,names=names,
            raw_bytes=sum(entries[name]['bytes'] for name in names),additions_only=True))
        try:
            result=api.create_commit(repo_id=REPO,repo_type='model',revision='main',parent_commit=current,
                operations=[CommitOperationAdd(path_in_repo=name,path_or_fileobj=payload[name]) for name in names],num_threads=2,
                commit_message=f'Archive split features part {index}/{len(planned)}',
                commit_description='One opt-in source-only split-feature candidate;32 fresh Adam updates. Exposed authored engineering measurements; no default promotion or legal-semantic qualification.')
        except Exception as error:
            write_json(F/f'hf-chunk-{index:02d}-unknown-outcome-v01.json',dict(parent_revision=current,names=names,
                error_type=type(error).__name__,message=str(error),automatic_retry_performed=False,reconciliation_required_before_resume=True))
            raise
        revision=result.oid
        write_json(F/f'hf-chunk-{index:02d}-created-v01.json',dict(parent_revision=current,revision=revision,commit_url=result.commit_url,names=names))
        info=api.model_info(REPO,revision=revision,files_metadata=True); after=identities(info)
        require(info.sha==revision and all(after.get(name)==record for name,record in {**baseline['files'],**owned}.items()),
                'old/root-attributes/previous-owned identities changed')
        require(set(after)==set(baseline['files'])|set(owned)|set(names), 'unexpected chunk additions or deletions')
        require(all(byte_identity(after[name],payload[name]) for name in names), 'new immutable byte identities differ')
        owned.update({name:after[name] for name in names}); current=revision
        record=dict(parent_revision=opening.sha,revision=current,new_files=len(names),all_old_and_prior_owned_identities_exact=True,new_byte_identities_exact=True)
        write_json(F/f'hf-chunk-{index:02d}-verified-v01.json',record); commits.append(record)
        print(json.dumps(dict(status='chunk_committed_and_identity_verified',chunk=index,chunks=len(planned),files=len(owned),revision=current)),flush=True)
    close_payload(root,entries,approved,review_path,review_pin)
    require(set(owned)==set(entries), 'complete additive release required')
    revision=current
    write_json(F/'hf-commit-created-v01.json',dict(repo=REPO,revision=revision,parent_revision=before.sha,
        commit_url=f'https://huggingface.co/{REPO}/commit/{revision}',release_prefix=PREFIX,additions=len(entries),chunks=commits,default_promotion=False))
    write_json(F/'hf-after-file-identities-v01.json',dict(repo=REPO,revision=revision,files={**baseline['files'],**owned}))
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
    write_json(F/'hf-publication-verification-v01.json',dict(schema='split-feature-Hub-verification/v1',passed=True,findings=[],repo=REPO,
        revision=revision,parent_revision=before.sha,commit_url=f'https://huggingface.co/{REPO}/commit/{revision}',release_prefix=PREFIX,
        new_files=len(entries),old_files_preserved=len(baseline['files']),all_old_identities_exact=True,all_downloads_byte_exact=True,
        downloads=downloads,chunks=commits,default_promotion=False,semantic_accuracy=None))
    print(json.dumps(dict(status='published_and_verified',revision=revision,new_files=len(entries))))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--review',required=True)
    main(parser.parse_args())
