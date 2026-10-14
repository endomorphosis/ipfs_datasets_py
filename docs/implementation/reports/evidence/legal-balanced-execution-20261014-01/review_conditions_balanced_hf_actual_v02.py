"""Independent immutable Hub metadata and downloaded opaque-byte review; no uploads."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,sys
from huggingface_hub import HfApi
F=Path(__file__).resolve().parent
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261014-conditions-balanced-v1'
REVISION='77e33d1c07b09a421b272e3ccb0af229933a7f82'
OUTPUT=F/'hf-publication-actual-independent-review-v01.json'
ARTIFACTS={}
sys.dont_write_bytecode=True

def require(value,message):
    if not value:raise ValueError(message)

def private(path):
    p=Path(path)
    return 'private-runtime-snapshots' in p.parts or 'private-root-identity-rebind-v01' in p.parts or p.name in {'resources-start.json','resources-final.json','resources-final-failure.json','disk-reservations.json'} or p.name.startswith('ipfs-datasets-resource-scheduler-')

def pin(path,expected=None):
    p=Path(path);require(p.is_absolute() and p.resolve()==p and p.is_file() and not p.is_symlink() and not private(p),'Public ordinary physical input required')
    before=p.stat();sha=hashlib.sha256();gitsha=hashlib.sha1(b'blob '+str(before.st_size).encode()+b'\0');size=0
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):sha.update(block);gitsha.update(block);size+=len(block)
    after=p.stat();stable=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    require(stable(before)==stable(after) and size==before.st_size,'Raw evidence changed')
    value=dict(path=str(p),bytes=size,sha256=sha.hexdigest())
    require(expected is None or all(value[k]==expected[k] for k in ('bytes','sha256')) and ('path' not in expected or value['path']==expected['path']),'Exact byte identity differs')
    brief={k:value[k] for k in ('bytes','sha256')};require(str(p) not in ARTIFACTS or ARTIFACTS[str(p)]==brief,'Closing identity drift');ARTIFACTS[str(p)]=brief
    return value,gitsha.hexdigest()

def read(name):
    p=F/name;require('checkpoint' not in p.name and 'reference-packet' not in p.name and 'results' not in p.parts,'Checkpoint/reference/head JSON parse denied')
    value,_=pin(p)
    result=json.loads(p.read_bytes());pin(p,value);return result

def identities(info):
    result={}
    for item in info.siblings:
        require(item.rfilename not in result,'Duplicate immutable Hub path')
        result[item.rfilename]=dict(size=item.size,blob_id=item.blob_id,lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256,size=item.lfs.size,pointer_size=item.lfs.pointer_size))
    return result

def main():
    require(not OUTPUT.exists(),'Exclusive new independent actual review required')
    verification=read('hf-publication-verification-v01.json');receipt=read('hf-preparation-receipt-v01.json');spec=read('hf-release-spec-v01.json');before=read('hf-before-file-identities-v01.json');created=read('hf-commit-created-v01.json')
    sourcegate=read('hf-helper-source-independent-review-v01.json');payloadreview=read('hf-publication-independent-review-v01.json');plan=read('conditions-balanced-ce-plan-v01.json');relocation=read('trainer-relocation-source-independent-review-v01.json');result=read('conditions-balanced-result-independent-review-v01.json');summary=read('public-result-summary-v01.json')
    require(verification['passed'] is True and verification['findings']==[] and verification['schema']=='conditions-balanced-Hub-verification/v1','Actual completed verification required')
    require(verification['repo']==receipt['repository']==REPO and verification['revision']==created['revision']==REVISION and verification['release_prefix']==receipt['release_prefix']==PREFIX,'Actual repo/prefix/revision joins')
    require(verification['parent_revision']==receipt['expected_parent_revision']==before['revision']==before['prior_release_revision']=='702caba2da183f9d98a0ffd12f1240243167aab2','Exact prior immutable release association')
    require(len(before['prior_release_files'])==len(before['files'])==5269 and all(before['files'].get(n)==d for n,d in before['prior_release_files'].items()),'Full prior5269 identity map')
    require(sourcegate['passed'] is payloadreview['passed'] is True and sourcegate['findings']==payloadreview['findings']==[],'Qualified exact helper/payload reviews')
    for key in ('source_spec','source_archive','source_review','baseline'):pin(receipt[key]['path'],receipt[key])
    for key in ('freeze','runtime_review','result_review'):pin(spec[key]['path'],spec[key])
    current=before['revision'];covered=set();require(verification['chunks']==created['chunks'] and len(created['chunks'])==7,'Exact seven recordedchunks')
    for index,entry in enumerate(created['chunks'],1):
        pre=read(f'hf-chunk-{index:02d}-preupload-v01.json');commit=read(f'hf-chunk-{index:02d}-created-v01.json');checked=read(f'hf-chunk-{index:02d}-verified-v01.json')
        require(pre['parent_revision']==commit['parent_revision']==entry['parent_revision']==checked['parent_revision']==current and checked==entry,'All seven parents link in order')
        require(commit['revision']==entry['revision'] and pre['names']==commit['names'] and pre['additions_only'] is True and entry['old_identities_exact'] is entry['new_byte_identities_exact'] is True,'Actual additive created/verified chunk association')
        names=pre['names'];require(len(names)==len(set(names))==entry['new_files'] and not covered.intersection(names) and all(n not in before['files'] for n in names),'Unique new paths perchunk')
        covered.update(names);current=entry['revision']
    sources={r['destination']:r['source'] for r in spec['files']}
    require(current==REVISION and covered==set(receipt['entries'])==set(verification['downloads'])==set(sources) and len(sources)==len(spec['files'])==176,'Exact complete176 additions acrosssevenchunks')
    require(receipt['payload_files']==verification['new_files']==176 and receipt['payload_bytes']==74081975 and verification['old_files_preserved']==5269,'Actual finite176/74MB/old5269 scope')
    algorithm={PREFIX+'/source/'+Path(d['path']).relative_to(F/'datasets').as_posix():d for d in [*plan['source_owner_pins'].values(),*relocation['supplemental_source_pins'].values()]}
    require(len(plan['source_owner_pins'])==39 and len(algorithm)==40 and receipt['algorithm_sources']==algorithm and receipt['algorithm_source_count']==40,'Exact39modules+supplemental40map')
    require({n for n in sources if n.startswith(PREFIX+'/source/ipfs_datasets_py/')}==set(algorithm) and all(sources[n]==d for n,d in algorithm.items()),'All40sources package-relative/provenance exact')
    require(result['scientific_success'] is summary['scientific_success'] is False and result['technical_result_qualification_passed'] is summary['technical_pass'] is True and result['default_promotion'] is summary['default_promotion'] is False,'Actual scientificnegative/technicalPASS join')
    api=HfApi();info=api.model_info(REPO,revision=REVISION,files_metadata=True);require(info.sha==REVISION,'Exact independent immutable model revision')
    remote=identities(info);require(len(remote)==len(before['files'])+len(sources)==5445 and set(remote)==set(before['files'])|set(sources) and all(remote[n]==d for n,d in before['files'].items()),'Independent SDK exactold5269+new176 union5445 required')
    for name,payload in receipt['entries'].items():
        p,_=pin(payload['path'],payload);download,gitoid=pin(verification['downloads'][name]['path'],verification['downloads'][name]);original,_=pin(sources[name]['path'],sources[name])
        require(len({(v['bytes'],v['sha256']) for v in [p,download,original]})==1,'Every original/payload/immutable-download byte agrees')
        identity=remote[name];require(identity['size']==download['bytes'],'Remote bytecount differs')
        if identity['lfs'] is None:require(identity['blob_id']==gitoid,'Remote Git blob identity differs')
        else:require(identity['lfs']['sha256']==download['sha256'] and identity['lfs']['size']==download['bytes'],'Remote LFS identity differs')
    card=(F/'MODEL_CARD_v01.md').read_text();require('failed its preregistered scientific' in card and 'not promoted' in card and 'unscored' in card,'Negative model card retained')
    require(sources[PREFIX+'/README.md']==pin(F/'MODEL_CARD_v01.md')[0],'Actual negative card publishedexact')
    pin(Path(__file__).resolve())
    for path,expected in list(ARTIFACTS.items()):pin(path,expected)
    live=api.model_info(REPO)
    require(not any(n.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'} for n in sys.modules),'No production/numerical import')
    value=dict(schema='conditions-balanced-Hub-actual-independent-review/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),repository=REPO,revision=REVISION,parent_revision=before['revision'],release_prefix=PREFIX,new_files=176,old_files_preserved=5269,immutable_remote_files=len(remote),payload_bytes=74081975,chunks=created['chunks'],all_seven_recorded_chunk_parents_join=True,all_old_identities_exact=True,all_remote_new_identities_exact=True,all_downloads_payload_and_original_sources_byte_exact=True,algorithm_source_count=40,source_owner_count=39,all40_package_relative_sources_byte_exact=True,independent_immutable_SDK_model_info=True,observed_main_revision=live.sha,observed_main_matches_publication=live.sha==REVISION,scientific_success=False,technical_result_passed=True,model_card_negative_verified=True,default_promotion=False,semantic_accuracy=None,statutory8_unscored=True,portable_reload_qualified=False,checkpoint_parsing=False,model_execution=False,private_resource_reads=False,resource_API_calls=0,publication_or_upload_calls=0,SDK_readonly_metadata_calls=2,artifacts=ARTIFACTS)
    with OUTPUT.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(dict(path=str(OUTPUT),bytes=OUTPUT.stat().st_size,sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),revision=REVISION,new_files=176,old_files_preserved=5269,remote_files=len(remote)),sort_keys=True))

if __name__=='__main__':main()
