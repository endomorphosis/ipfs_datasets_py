"""Read-only completion after the Hub appended a release-local LFS rule.

The existing commit is not replayed or changed. All old payload identities and
103 downloaded new files must match. The sole metadata change is authenticated
as the exact old attributes bytes plus one rule for the new authored-data file.
"""
from pathlib import Path
import json
import hashlib
import subprocess
from huggingface_hub import HfApi, hf_hub_download

F=Path(__file__).resolve().parent

def pin(path):
    path=Path(path);assert path.is_absolute() and path.resolve()==path and path.is_file() and not path.is_symlink()
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def write(name,value):
    with (F/name).open('x') as s:json.dump(value,s,indent=2,sort_keys=True);s.write('\n')

def main():
    created=json.loads((F/'hf-commit-created.json').read_bytes())
    receipt=json.loads((F/'hf-preparation-receipt-v01.json').read_bytes())
    baseline=json.loads((F/'hf-before-file-identities.local.json').read_bytes())
    repo,oid,prefix=created['repo'],created['revision'],created['release_prefix']
    assert repo=='Publicus/legal-ir-autoencoder' and created['parent_revision']==baseline['revision']==receipt['expected_parent_revision']
    entries=receipt['complete_upload_files'];root=Path(receipt['upload_root']);assert len(entries)==103
    for relative,expected in entries.items():assert pin(root/relative)==expected
    info=HfApi().model_info(repo,revision=oid,files_metadata=True)
    actual={s.rfilename:dict(size=s.size,blob_id=s.blob_id,lfs=None if s.lfs is None else
        dict(sha256=s.lfs.sha256,size=s.lfs.size,pointer_size=s.lfs.pointer_size)) for s in info.siblings}
    changed=[name for name,value in baseline['files'].items() if actual.get(name)!=value]
    assert changed==['.gitattributes'] and set(actual)-set(baseline['files'])==set(entries)
    attrs=[];attrs_pins=[]
    for label,rev in [('before',baseline['revision']),('after',oid)]:
        path=Path(hf_hub_download(repo,filename='.gitattributes',revision=rev,local_dir=str(F/'hf-attributes-readback'/label)))
        attrs.append(path.read_bytes());attrs_pins.append(pin(path))
    expected_addition=(prefix+'/data/authored-train-tune-only.json filter=lfs diff=lfs merge=lfs -text\n').encode()
    assert attrs[1]==attrs[0]+expected_addition
    write('hf-attributes-append-only-verification.json',dict(schema='hub-automatic-release-LFS-attributes-append/v1',passed=True,findings=[],
        parent_revision=baseline['revision'],revision=oid,original_bytes_preserved_as_prefix=True,
        exact_added_rule=expected_addition.decode(),readback_pins=attrs_pins,
        original_payload_file_count=3207,all3207_original_payload_identities_preserved=True,
        original_root_model_card_and_all_retained_weight_paths_unchanged=True,
        provider_automatic_metadata_change=True,no_second_commit_or_rollback=True))
    dest=F/'hf-verified-download';assert not dest.exists()
    argv=['hf','download',repo,'--revision',oid,'--include',prefix+'/*','--local-dir',str(dest),'--max-workers','2']
    with (F/'hf-download-verification.log').open('x') as out:result=subprocess.run(argv,stdout=out,stderr=subprocess.STDOUT)
    assert result.returncode==0
    downloads={}
    for relative,expected in entries.items():
        downloaded=pin(dest/relative)
        assert {k:downloaded[k] for k in ('bytes','sha256')}=={k:expected[k] for k in ('bytes','sha256')}
        assert pin(root/relative)==expected;downloads[relative]=downloaded
    write('hf-publication-verification.json',dict(schema='structured-span-hf-publication-verification/v2',passed=True,findings=[],
        repo=repo,revision=oid,parent_revision=baseline['revision'],commit_url=created['commit_url'],release_prefix=prefix,
        old_file_count=3208,old_payload_file_count=3207,all_old_payload_file_identities_preserved=True,
        old_metadata_changes=['.gitattributes'],automatic_attributes_change_exact_release_local_append=True,
        all_old_attributes_rules_preserved=True,new_file_count=103,all103_downloaded_files_byte_exact=True,
        downloads=downloads,prepared_receipt=pin(F/'hf-preparation-receipt-v01.json'),
        independent_prepared_review=pin(F/'hf-prepared-publication-independent-review-v02.json'),
        initial_publisher_failure_preserved=pin(F/'hf-publication.log'),
        verifier=pin(Path(__file__).resolve()),no_additional_remote_mutations=True,
        default_promotion=False,semantic_accuracy=None,
        weight_scope='four actual experimental32-update continuations; original retained weight bytes unchanged'))
    print(json.dumps(dict(status='published_and_download_verified',revision=oid,new_files=103,old_payloads_preserved=3207,attributes_rule_append_only=True)),flush=True)

if __name__=='__main__':main()
