"""Append exactly one independently reviewed prefix at a pinned Hub parent.

Uses the installed Hub API for parent_commit compare-and-swap, which the CLI
does not expose, then the hf CLI for immutable download verification. No model
loads, training, deletions, model-card changes or default promotion.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
from huggingface_hub import HfApi, CommitOperationAdd

F=Path(__file__).resolve().parent
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261011-structured-span-probability-v1'

def pin(path):
    path=Path(path);assert path.is_absolute() and path.resolve()==path and path.is_file() and not path.is_symlink()
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def write(name,value):
    with (F/name).open('x') as s:json.dump(value,s,indent=2,sort_keys=True);s.write('\n')

def identities(info):
    return {s.rfilename:dict(size=s.size,blob_id=s.blob_id,lfs=None if s.lfs is None else
        dict(sha256=s.lfs.sha256,size=s.lfs.size,pointer_size=s.lfs.pointer_size)) for s in info.siblings}

def main():
    review_path=Path(sys.argv[1]).resolve();review=json.loads(review_path.read_bytes())
    assert review['passed'] is True and review['findings']==[]
    receipt_path=F/'hf-preparation-receipt-v01.json';receipt=json.loads(receipt_path.read_bytes())
    baseline=json.loads((F/'hf-before-file-identities.local.json').read_bytes())
    assert receipt['repository']==REPO and receipt['release_prefix']==PREFIX
    assert receipt['expected_parent_revision']==baseline['revision']=='8279ea69452c0c72560211a1eda505ff1b1b5713'
    entries=receipt['complete_upload_files'];root=Path(receipt['upload_root'])
    assert len(entries)==103 and sum(v['bytes'] for v in entries.values())==47834763
    assert set(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())==set(entries)
    assert all(not p.is_symlink() for p in root.rglob('*'))
    for relative,expected in entries.items():
        assert relative.startswith(PREFIX+'/') and '..' not in Path(relative).parts
        assert pin(root/relative)==expected
    # Bind the reviewed prepared-tree receipt and every payload file by bytes.
    # Review schema need not reuse historical numerical-admission metadata.
    review_raw=json.dumps(review,sort_keys=True)
    assert pin(receipt_path)['sha256'] in review_raw
    assert all(v['sha256'] in review_raw for v in entries.values())
    api=HfApi();before=api.model_info(REPO,files_metadata=True)
    assert before.sha==baseline['revision'] and identities(before)==baseline['files']
    assert not any(name.startswith(PREFIX+'/') for name in baseline['files'])
    write('hf-preupload-custody.json',dict(repo=REPO,parent_revision=before.sha,old_file_count=len(before.siblings),
        prepared_receipt=pin(receipt_path),independent_review=pin(review_path),file_count=len(entries),
        payload_bytes=sum(v['bytes'] for v in entries.values()),operations='prefix-only additions; parent_commit compare-and-swap'))
    operations=[CommitOperationAdd(path_in_repo=relative,path_or_fileobj=str(root/relative)) for relative in sorted(entries)]
    result=api.create_commit(repo_id=REPO,repo_type='model',revision='main',parent_commit=before.sha,
        operations=operations,num_threads=2,commit_message='Archive four experimental structured span continuations',
        commit_description='Equal32-step CE0/probability0.1 paired raw384/source-only continuations. Authored tuning96/96 remains unchanged; real-law proposal counts unchanged, no semantic accuracy or default promotion.')
    oid=result.oid
    write('hf-commit-created.json',dict(repo=REPO,revision=oid,parent_revision=before.sha,
        commit_url=result.commit_url,release_prefix=PREFIX,requested_additions=len(entries),default_promotion=False))
    after=api.model_info(REPO,revision=oid,files_metadata=True);actual=identities(after)
    assert all(actual.get(name)==value for name,value in baseline['files'].items())
    assert set(actual)-set(baseline['files'])==set(entries)
    dest=F/'hf-verified-download';assert not dest.exists()
    argv=['hf','download',REPO,'--revision',oid,'--include',PREFIX+'/*','--local-dir',str(dest),'--max-workers','2']
    with (F/'hf-download-verification.log').open('x') as out:completed=subprocess.run(argv,stdout=out,stderr=subprocess.STDOUT)
    assert completed.returncode==0,'immutable download failed; preserve created commit receipt'
    downloads={}
    for relative,expected in entries.items():
        actual_file=pin(dest/relative)
        assert {k:actual_file[k] for k in ('bytes','sha256')}=={k:expected[k] for k in ('bytes','sha256')}
        assert pin(root/relative)==expected
        downloads[relative]=actual_file
    write('hf-publication-verification.json',dict(schema='structured-span-hf-publication-verification/v1',passed=True,findings=[],
        repo=REPO,revision=oid,parent_revision=before.sha,commit_url=result.commit_url,release_prefix=PREFIX,
        old_file_count=len(baseline['files']),all_old_file_identities_preserved=True,new_file_count=len(entries),
        all103_downloaded_files_byte_exact=True,downloads=downloads,prepared_receipt=pin(receipt_path),
        independent_review=pin(review_path),default_promotion=False,semantic_accuracy=None,
        weight_scope='four actual experimental32-update continuations; original retained checkpoints unchanged'))
    print(json.dumps(dict(status='published_and_download_verified',revision=oid,new_files=103,old_files_preserved=3208)),flush=True)

if __name__=='__main__':main()
