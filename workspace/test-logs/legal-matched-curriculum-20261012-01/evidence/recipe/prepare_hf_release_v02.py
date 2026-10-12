"""Rebind unchanged reviewed payload plus finite transport-recovery evidence.

Preserves every v01 payload byte and receipt. No API call or model parsing.
"""
from pathlib import Path
import json
import os
import shutil

import prepare_hf_release_v01 as old

F=Path(__file__).resolve().parent
CONTRACT=dict(max_files=48,max_raw_bytes=16000000,parent_CAS_every_chunk=True,additions_only=True)

def main():
    original=F/'hf-preparation-receipt-v01.json';receipt=old.read(original)
    review=F/'hf-publication-independent-review-v01.json';old.checked_review(review)
    recovery_review=F/'hf-recovery-helper-source-independent-review-v01.json';old.checked_review(recovery_review)
    reconciliation=F/'hf-failed-attempt-reconciliation-v01.json';reconciled=old.read(reconciliation)
    old.require(reconciled['passed'] is True and reconciled['all_old_identities_exact'] is True and reconciled['release_prefix_absent'] is True,'failed request must be reconciled before retry')
    old.require(reconciled['revision']==receipt['expected_parent_revision'],'unchanged baseline required')
    root=F/'hf-upload-v02';old.require(not root.exists(),'new immutable recovery root required');root.mkdir()
    entries={}
    def copy(source,name,expected):
        source=Path(source);old.require(old.pin(source)==expected,'reviewed recovery source changed')
        target=root/name;old.require(target.resolve().is_relative_to(root.resolve()) and not target.exists(),'bounded exclusive target required')
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:
            stream.write(source.read_bytes());stream.flush();os.fsync(stream.fileno())
        target.chmod(0o444);actual=old.pin(target)
        old.require({key:actual[key] for key in ('bytes','sha256')}=={key:expected[key] for key in ('bytes','sha256')},'copy changed source bytes')
        entries[name]=actual
    for name,expected in receipt['complete_upload_files'].items():copy(expected['path'],name,expected)
    source_review=old.read(recovery_review)
    for name,relative in (
        ('prepare_hf_release_v02.py','recipe/prepare_hf_release_v02.py'),
        ('publish_hf_release_v02.py','recipe/publish_hf_release_v02.py'),
        ('hf-recovery-helper-source-independent-review-v01.json','evidence/hf-recovery-helper-source-independent-review-v01.json'),
        ('hf-failed-attempt-reconciliation-v01.json','evidence/hf-failed-attempt-reconciliation-v01.json'),
        ('hf-publication-execution-v01.log','evidence/failed-publication-execution-v01.log')):
        path=F/name;expected=old.pin(path)
        if path!=recovery_review:old.require(source_review['artifacts'].get(str(path))=={key:expected[key] for key in ('bytes','sha256')},'recovery additions need source approval')
        copy(path,old.PREFIX+'/'+relative,expected)
    manifest=dict(schema='matched-curriculum-Hub-transport-recovery-manifest/v1',original_preparation=old.pin(original),failed_request_reconciliation=old.pin(reconciliation),original_payload_bytes_unchanged=True,original_files=receipt['payload_files'],chunk_contract=CONTRACT,source_review=old.pin(recovery_review),source_guidance='https://huggingface.co/docs/hub/storage-limits',all_eight_retained=True,default_promotion=False,sources=entries.copy())
    manifest_path=root/old.PREFIX/'recovery-manifest.json';old.write_json(manifest_path,manifest)
    entries[old.PREFIX+'/recovery-manifest.json']=old.pin(manifest_path)
    total=sum(item['bytes'] for item in entries.values());old.require(total<=old.MAX_PAYLOAD_BYTES and len(entries)<=1000,'same total payload limits required')
    result={**receipt,'schema':'matched-curriculum-Hub-preparation/v2','upload_root':str(root),'complete_upload_files':entries,'payload_files':len(entries),'payload_bytes':total,'original_preparation':old.pin(original),'original_publication_review':old.pin(review),'reconciliation':old.pin(reconciliation),'recovery_source_review':old.pin(recovery_review),'chunk_contract':CONTRACT}
    old.write_json(F/'hf-preparation-receipt-v02.json',result)
    print(json.dumps(dict(status='recovery_prepared_only',files=len(entries),bytes=total)))

if __name__=='__main__':main()
