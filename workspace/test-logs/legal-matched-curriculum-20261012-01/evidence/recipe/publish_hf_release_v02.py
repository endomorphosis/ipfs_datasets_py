"""Publish reviewed immutable additions in bounded, individually CAS commits.

The v01 request failed without changing the sampled remote endpoint. This
recovery uses <=48 files and <=16MB raw per request; source guidance is at
https://huggingface.co/docs/hub/storage-limits. Every successful chunk is durably
recorded and compared with all old identities and the prior owned additions.
Unknown outcomes stop with a durable reconciliation requirement, never a blind
retry. No model imports, checkpoint parsing, deletion, replacement or promotion.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import publish_hf_release_v01 as old

F=Path(__file__).resolve().parent
CONTRACT=dict(max_files=48,max_raw_bytes=16000000,parent_CAS_every_chunk=True,additions_only=True)

def chunks(entries):
    result=[];current=[];size=0
    for name in sorted(entries):
        record=entries[name]
        old.require(type(record['bytes']) is int and 0<=record['bytes']<=CONTRACT['max_raw_bytes'],'bounded single artifact required')
        if current and (len(current)==CONTRACT['max_files'] or size+record['bytes']>CONTRACT['max_raw_bytes']):
            result.append(current);current=[];size=0
        current.append(name);size+=record['bytes']
    if current:result.append(current)
    old.require(bool(result),'nonempty chunks required')
    return result

def byte_identity(record,raw):
    if record['lfs'] is not None:
        return record['size']==len(raw) and record['lfs']['size']==len(raw) and record['lfs']['sha256']==hashlib.sha256(raw).hexdigest()
    return record['size']==len(raw) and record['blob_id']==hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def main():
    review_path=Path(sys.argv[1]).resolve();review=old.read(review_path)
    old.require(set(review)=={'schema','passed','findings','repository','release_prefix','expected_parent_revision','payload_files','payload_bytes','artifacts','scope','limitations'} and review['schema']=='matched-curriculum-Hub-publication-independent-review/v2' and review['passed'] is True and review['findings']==[],'closed clean recovery review required')
    receipt_path=F/'hf-preparation-receipt-v02.json';receipt=old.read(receipt_path)
    original=old.read(F/'hf-preparation-receipt-v01.json');baseline=old.read(F/'hf-before-file-identities-v01.json')
    expected_keys=set(original)|{'original_preparation','original_publication_review','reconciliation','recovery_source_review','chunk_contract'}
    old.require(set(receipt)==expected_keys and receipt['schema']=='matched-curriculum-Hub-preparation/v2' and receipt['chunk_contract']==CONTRACT,'closed reviewed recovery recipe required')
    old.require(review['repository']==receipt['repository']==baseline['repo']==old.REPO and review['release_prefix']==receipt['release_prefix']==old.PREFIX,'exact repo/prefix required')
    old.require(review['expected_parent_revision']==receipt['expected_parent_revision']==baseline['revision'],'same baseline required')
    old.require(receipt['default_promotion'] is False and receipt['additive_only'] is True,'no promotion and additions only required')
    entries=receipt['complete_upload_files'];root=Path(receipt['upload_root'])
    old.require(root==F/'hf-upload-v02' and root.resolve()==root and not root.is_symlink(),'physical recovery root required')
    old.require(review['payload_files']==receipt['payload_files']==len(entries) and 0<len(entries)<=1000,'bounded closed file count required')
    old.require(review['payload_bytes']==receipt['payload_bytes']==sum(x['bytes'] for x in entries.values())<=old.MAX_PAYLOAD_BYTES,'bounded exact payload bytes required')
    old.require({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}==set(entries) and not any(p.is_symlink() for p in root.rglob('*')),'closed recovery tree required')
    for name,record in original['complete_upload_files'].items():
        old.require(name in entries and {key:entries[name][key] for key in ('bytes','sha256')}=={key:record[key] for key in ('bytes','sha256')},'original reviewed bytes must remain identical')
    required=[Path(__file__).resolve(),F/'prepare_hf_release_v02.py',receipt_path,F/'hf-before-file-identities-v01.json',F/'hf-failed-attempt-reconciliation-v01.json',F/'hf-recovery-helper-source-independent-review-v01.json',F/'hf-publication-independent-review-v01.json',F/'hf-preparation-receipt-v01.json',F/'result-independent-review-v01.json',F/'runtime-independent-review-v01.json',F/'eight-cell-output-freeze-v01.json',*[root/name for name in entries]]
    for path in required:old.require(review['artifacts'].get(str(path))=={key:old.pin(path)[key] for key in ('bytes','sha256')},'complete recovery artifact review required')
    def fence():
        for path,expected in review['artifacts'].items():old.require({key:old.pin(path)[key] for key in ('bytes','sha256')}==expected,'reviewed bytes changed')
    fence()
    for name,record in entries.items():
        old.require(name.startswith(old.PREFIX+'/') and '..' not in Path(name).parts and old.pin(root/name)==record,'bounded approved addition required')
    for key in ('baseline_pin','result_review','runtime_review','helper_review','freeze_manifest','original_preparation','original_publication_review','reconciliation','recovery_source_review'):
        old.require(old.pin(receipt[key]['path'])==receipt[key],'bound recovery input changed')
    payload={name:(root/name).read_bytes() for name in entries}
    old.require(all(len(raw)==entries[name]['bytes'] and hashlib.sha256(raw).hexdigest()==entries[name]['sha256'] for name,raw in payload.items()),'immutable input buffers differ')
    planned=chunks(entries);api=old.HfApi();before=api.model_info(old.REPO,files_metadata=True)
    old.require(before.sha==baseline['revision'] and old.identities(before)==baseline['files'] and not any(n.startswith(old.PREFIX+'/') for n in baseline['files']),'fresh unchanged remote baseline required')
    old.write('hf-preupload-custody-v02.json',dict(repo=old.REPO,parent_revision=before.sha,review=old.pin(review_path),receipt=old.pin(receipt_path),chunks=planned,chunk_contract=CONTRACT,old_files=len(baseline['files']),additive_only=True))
    current=baseline['revision'];owned={};commits=[]
    for index,names in enumerate(planned,1):
        fence();opening=api.model_info(old.REPO,files_metadata=True);opening_files=old.identities(opening)
        old.require(opening.sha==current and opening_files=={**baseline['files'],**owned},'current parent or prior identities changed before chunk')
        old.require(all(name not in opening_files for name in names),'every new operation must add an absent path')
        old.write(f'hf-chunk-{index:02d}-preupload-v02.json',dict(parent_revision=current,names=names,raw_bytes=sum(entries[name]['bytes'] for name in names),additions_only=True))
        try:
            result=api.create_commit(repo_id=old.REPO,repo_type='model',revision='main',parent_commit=current,operations=[old.CommitOperationAdd(path_in_repo=name,path_or_fileobj=payload[name]) for name in names],num_threads=2,commit_message=f'Archive matched curriculum part {index}/{len(planned)}',commit_description='Reviewed prefix-only additions. All eight checkpoints retained; no default promotion. Complete release is qualified by final immutable readback.')
        except Exception as error:
            old.write(f'hf-chunk-{index:02d}-unknown-outcome-v02.json',dict(parent_revision=current,names=names,error_type=type(error).__name__,message=str(error),automatic_retry_performed=False,reconciliation_required_before_resume=True))
            raise
        revision=result.oid
        old.write(f'hf-chunk-{index:02d}-created-v02.json',dict(parent_revision=current,revision=revision,commit_url=result.commit_url,names=names))
        after=old.identities(api.model_info(old.REPO,revision=revision,files_metadata=True))
        old.require(all(after.get(name)==record for name,record in {**baseline['files'],**owned}.items()),'old or previously owned identity changed')
        old.require(set(after)==set(baseline['files'])|set(owned)|set(names),'unexpected chunk additions')
        old.require(all(byte_identity(after[name],payload[name]) for name in names),'new immutable tree identity differs from reviewed bytes')
        owned.update({name:after[name] for name in names});current=revision
        record=dict(parent_revision=opening.sha,revision=revision,new_files=len(names),all_old_and_prior_owned_identities_exact=True,new_byte_identities_exact=True)
        old.write(f'hf-chunk-{index:02d}-verified-v02.json',record);commits.append(record)
        print(json.dumps(dict(status='chunk_committed_and_identity_verified',chunk=index,chunks=len(planned),files=len(owned),revision=revision)),flush=True)
    fence();old.require(set(owned)==set(entries),'complete release additions required')
    old.write('hf-commit-created-v02.json',dict(repo=old.REPO,revision=current,parent_revision=baseline['revision'],commit_url=f'https://huggingface.co/{old.REPO}/commit/{current}',release_prefix=old.PREFIX,additions=len(entries),default_promotion=False,chunks=commits))
    old.write('hf-after-file-identities-v02.json',dict(repo=old.REPO,revision=current,files={**baseline['files'],**owned}))
    destination=F/'hf-verified-download-v02';old.require(not destination.exists(),'new immutable download directory required')
    with (F/'hf-download-verification-v02.log').open('x') as output:
        downloaded=subprocess.run(['hf','download',old.REPO,'--revision',current,'--include',old.PREFIX+'/*','--local-dir',str(destination),'--max-workers','2'],stdout=output,stderr=subprocess.STDOUT)
    old.require(downloaded.returncode==0,'immutable readback failed')
    downloads={}
    for name,expected in entries.items():
        actual=old.pin(destination/name)
        old.require({key:actual[key] for key in ('bytes','sha256')}=={key:expected[key] for key in ('bytes','sha256')},'downloaded bytes differ')
        downloads[name]=actual
    fence()
    old.write('hf-publication-verification-v02.json',dict(schema='matched-curriculum-Hub-verification/v2',passed=True,findings=[],repo=old.REPO,revision=current,parent_revision=baseline['revision'],commit_url=f'https://huggingface.co/{old.REPO}/commit/{current}',release_prefix=old.PREFIX,new_files=len(entries),old_files_preserved=len(baseline['files']),all_old_identities_exact=True,all_downloads_byte_exact=True,downloads=downloads,chunks=commits,default_promotion=False,semantic_accuracy=None))
    print(json.dumps(dict(status='published_and_verified',revision=current,new_files=len(entries))),flush=True)

if __name__=='__main__':main()
