"""Independently replay captured immutable Hub metadata and downloaded bytes.

No second network request, model/compiler/resource API, checkpoint parser or
private-global-body read. Authoritative private identity references are joined
only to the already qualified runtime review. Run after actual publication.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

F=Path(__file__).resolve().parent
N3=F.parent/'legal-permission-retention-20261012-01'
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261013-split-feature-v1'
PRIOR_PREFIX='releases/20261012-permission-retention-v1'
MAX_BYTES=200000000
READ_PINS={}
PRIOR_REVIEW_PIN=dict(bytes=141473,sha256='26596f61ff1af63c1d77757bfb221747d672f75ef26d2476ece61c99f718b4e4')
OUTPUT=F/'hf-actual-publication-independent-review-v01.json'


def require(value,message):
    if not value:raise ValueError(message)


def brief(record):
    require(type(record) is dict and type(record.get('bytes')) is int and 0<=record['bytes']<=MAX_BYTES
            and type(record.get('sha256')) is str and re.fullmatch(r'[0-9a-f]{64}',record['sha256']), 'bounded exact raw identity required')
    return {key:record[key] for key in ('bytes','sha256')}


def private(path):
    path=Path(path)
    return 'private-runtime-snapshots' in path.parts or path.name in {'resources-start.json','resources-final.json','disk-reservations.json'}


def pin(path):
    path=Path(path)
    require(not private(path), 'private global bodies must remain unopened')
    require(path.is_absolute() and path.resolve(strict=True)==path and path.is_file() and not path.is_symlink(), 'ordinary physical public byte source required')
    before=path.stat();require(before.st_size<=MAX_BYTES, 'bounded raw source required before allocation')
    raw=path.read_bytes();after=path.stat()
    identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    require(identity(before)==identity(after) and len(raw)==before.st_size, 'public input changed during raw pin')
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def captured_raw(path):
    path=Path(path);captured=pin(path);raw=path.read_bytes()
    require(brief(captured)==dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) and pin(path)==captured,
            'consumed public bytes differ from opening pin')
    return raw,captured


def read(path,expected=None):
    path=Path(path)
    require('checkpoint' not in path.name and 'reference-packet' not in path.name and not private(path), 'opaque checkpoint/reference/private JSON parsing prohibited')
    raw,captured=captured_raw(path)
    require(expected is None or captured==brief(expected), 'parsed metadata differs from required raw identity')
    require(str(path) not in READ_PINS or READ_PINS[str(path)]==captured, 'previous consumed metadata identity changed')
    READ_PINS[str(path)]=captured
    def unique(pairs):
        result={}
        for key,value in pairs:require(key not in result,'duplicate JSON key');result[key]=value
        return result
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'nonfinite JSON number');return value
    return json.loads(raw,object_pairs_hook=unique,parse_float=finite,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))


def identity(record,raw):
    if record['lfs'] is not None:
        return record['size']==len(raw) and record['lfs']['size']==len(raw) and record['lfs']['sha256']==hashlib.sha256(raw).hexdigest()
    return record['size']==len(raw) and record['blob_id']==hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def fence(artifacts):
    for path,captured in READ_PINS.items():
        require(path not in artifacts or artifacts[path]==captured,'parsed metadata differs from bound public artifact')
        artifacts[path]=captured
    for path,expected in artifacts.items():require(pin(path)==expected,'closing public source/captured-metadata identity changed')


def clean(value,schema):
    require(value['schema']==schema and (value.get('passed') is True or value.get('status')=='PASS') and value['findings']==[], 'exact clean independent qualification required')


def main():
    require(not os.path.lexists(OUTPUT), 'exclusive actual-publication observation required')
    artifacts={};private_references={}
    runtime=read(F/'runtime-independent-review-v01.json')
    clean(runtime,'split-feature-runtime-independent-review/v1')
    def bind(path,expected=None):
        path=Path(path);key=str(path)
        if private(path):
            require(expected is not None and key in runtime['artifacts'] and brief(runtime['artifacts'][key])==brief(expected),
                    'private identity reference must join already qualified runtime metadata')
            require(key not in private_references or private_references[key]==brief(expected),'conflicting private metadata identity reference')
            private_references[key]=brief(expected);return brief(expected)
        actual=pin(path)
        require(expected is None or actual==brief(expected), 'independently approved public bytes differ')
        require(key not in READ_PINS or READ_PINS[key]==actual,'bound public identity differs from parsed payload')
        require(key not in artifacts or artifacts[key]==actual,'conflicting public raw identity')
        artifacts[key]=actual;return actual
    receipt=read(F/'hf-preparation-receipt-v01.json')
    helper_descriptor=receipt['helper_review'];helper_path=Path(helper_descriptor['path'])
    require(set(helper_descriptor)=={'path','bytes','sha256'} and helper_path.parent==F
            and re.fullmatch(r'hf-helper-source-independent-review-v[0-9]{2}\.json',helper_path.name),
            'exact receipt-derived owned helper qualification path required')
    source=read(helper_path,helper_descriptor)
    concrete=read(F/'hf-publication-independent-review-v01.json')
    proof=read(F/'hf-publication-verification-v01.json')
    baseline=read(F/'hf-before-file-identities-v01.json')
    after=read(F/'hf-after-file-identities-v01.json')
    created=read(F/'hf-commit-created-v01.json')
    preupload=read(F/'hf-preupload-custody-v01.json')
    clean(source,'split-feature-Hub-helper-source-independent-review/v1')
    clean(concrete,'split-feature-Hub-publication-independent-review/v1')
    clean(proof,'split-feature-Hub-verification/v1')
    require(receipt['schema']=='split-feature-Hub-preparation/v1','exact prepared-payload schema required')
    require(proof['repo']==receipt['repository']==baseline['repo']==after['repo']==created['repo']==concrete['repository']==REPO
            and proof['release_prefix']==receipt['release_prefix']==created['release_prefix']==concrete['release_prefix']==PREFIX,
            'exact public repository and additive prefix required')
    parent=baseline['revision'];revision=proof['revision']
    require(re.fullmatch(r'[0-9a-f]{40}',parent) and re.fullmatch(r'[0-9a-f]{40}',revision)
            and proof['parent_revision']==receipt['expected_parent_revision']==concrete['expected_parent_revision']==created['parent_revision']==preupload['parent_revision']==parent
            and revision==after['revision']==created['revision'], 'one complete immutable parent and result revision chain required')
    require(receipt['additive_only'] is True and preupload['additive_only'] is True and preupload['repo']==REPO
            and proof['default_promotion'] is False and receipt['default_promotion'] is False and created['default_promotion'] is False
            and proof['semantic_accuracy'] is None, 'additive opt-in archive only')
    entries=receipt['complete_upload_files'];count=len(entries);old_count=len(baseline['files'])
    require(type(entries) is dict and 0<count<=1000 and proof['new_files']==receipt['payload_files']==concrete['payload_files']==created['additions']==count
            and proof['old_files_preserved']==preupload['old_files']==old_count and old_count>0
            and proof['all_old_identities_exact'] is True and proof['all_downloads_byte_exact'] is True,
            'exact current baseline and complete new payload counts required')
    require(not any(name.startswith(PREFIX+'/') for name in baseline['files']) and set(after['files'])==set(baseline['files'])|set(entries), 'closed absent-prefix additions required')
    require(all(after['files'][name]==record for name,record in baseline['files'].items())
            and '.gitattributes' in baseline['files'] and after['files']['.gitattributes']==baseline['files']['.gitattributes'], 'all current baseline identities and root attributes must remain exact')
    for path,expected in concrete['artifacts'].items():bind(path,expected)
    for path,expected in source['artifacts'].items():bind(path,expected)
    for path,expected in receipt['approved_source_artifacts'].items():
        require(path in concrete['artifacts'] and brief(concrete['artifacts'][path])==brief(expected), 'entire prepared source closure needs concrete raw provenance')
        bind(path,expected)
    for key,name in [('baseline_pin','hf-before-file-identities-v01.json'),('result_review','result-independent-review-v01.json'),
                     ('runtime_review','runtime-independent-review-v01.json'),
                     ('freeze_manifest','split-feature-output-freeze-v01.json')]:
        require(bind(F/name)==brief(receipt[key]), 'prepared actual source receipt differs')
    require(bind(helper_path,helper_descriptor)==brief(receipt['helper_review'])
            and brief(concrete['artifacts'][str(helper_path)])==brief(helper_descriptor),
            'receipt-derived helper qualification needs concrete raw provenance')
    require(bind(F/'hf-publication-independent-review-v01.json')==brief(preupload['review'])
            and bind(F/'hf-preparation-receipt-v01.json')==brief(preupload['receipt']), 'durable publication authorization identities differ')
    require(receipt['payload_bytes']==concrete['payload_bytes']==sum(brief(value)['bytes'] for value in entries.values())
            and 0<receipt['payload_bytes']<=MAX_BYTES and all(value['bytes']<10000000 for value in entries.values()), 'exact200M/10M public payload caps required')
    root=Path(receipt['upload_root']);require(root==F/'hf-upload-v01','exact owned upload root required')
    require(set(proof['downloads'])==set(entries),'every prepared addition needs immutable CLI download')
    require(set(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())==set(entries)
            and not any(path.is_symlink() for path in root.rglob('*')), 'exact ordinary complete local payload required')
    for name,expected in entries.items():
        require(name.startswith(PREFIX+'/') and '..' not in Path(name).parts and not Path(name).is_absolute()
                and Path(expected['path'])==root/name and not private(Path(name)), 'exact public prefix payload source required')
        bind(expected['path'],expected)
        downloaded=proof['downloads'][name]
        require(Path(downloaded['path'])==F/'hf-verified-download-v01'/name,'exact immutable readback path required')
        require(bind(downloaded['path'],downloaded)==brief(expected),'downloaded byte identity differs from concrete payload')
        raw,captured=captured_raw(expected['path'])
        require(captured==brief(expected) and identity(after['files'][name],raw),'new immutable remote blob differs from concrete raw payload')
    plans=concrete['scope']['chunks']
    require(preupload['chunks']==[row['names'] for row in plans] and preupload['chunk_contract']==dict(max_files=48,max_raw_bytes=16000000,parent_CAS_every_chunk=True,additions_only=True), 'exact independently reviewed chunk plan required')
    require(plans and [name for row in plans for name in row['names']]==sorted(entries),'chunks must partition every addition exactly once')
    current=parent;chain=[]
    for index,plan in enumerate(plans,1):
        names=plan['names']
        require(0<len(names)==plan['files']<=48 and plan['bytes']==sum(entries[name]['bytes'] for name in names)<=16000000,'exact48-file/16M chunk bounds required')
        stem='hf-chunk-'+str(index).zfill(2)
        a=read(F/(stem+'-preupload-v01.json'));b=read(F/(stem+'-created-v01.json'));c=read(F/(stem+'-verified-v01.json'))
        require(a==dict(parent_revision=current,names=names,raw_bytes=plan['bytes'],additions_only=True),'durable exact chunk opening required')
        require(b['parent_revision']==current and b['names']==names and re.fullmatch(r'[0-9a-f]{40}',b['revision']),'returned exact chunk revision required')
        require(c==dict(parent_revision=current,revision=b['revision'],new_files=len(names),all_old_and_prior_owned_identities_exact=True,new_byte_identities_exact=True),'successful exact chunk byte verification required')
        require(not os.path.lexists(F/(stem+'-unknown-outcome-v01.json')),'unknown commit outcome remains unqualified')
        for suffix in ('preupload','created','verified'):bind(F/(stem+'-'+suffix+'-v01.json'))
        chain.append(c);current=b['revision']
    require(current==revision and chain==proof['chunks']==created['chunks'],'complete serial parent-CAS chain required')
    result=read(F/'result-independent-review-v01.json');clean(result,'split-feature-result-independent-review/v1')
    analysis=read(F/'split-feature-result-analysis-v01.json')
    require(analysis['schema']=='split-feature-exposed-result-analysis/v1' and analysis['passed'] is True and analysis['findings']==[]
            and brief(result['artifacts'][str(F/'split-feature-result-analysis-v01.json')])==bind(F/'split-feature-result-analysis-v01.json'), 'actual independently reviewed analysis required')
    producer=analysis['analyzer'];approval=analysis['independent_source_review']
    require(Path(producer['path']).parent==F and re.fullmatch(r'analyze_split_feature_results_v[0-9]{2}\.py',Path(producer['path']).name)
            and Path(approval['path']).parent==F and re.fullmatch(r'split-feature-analyzer-source-independent-review-v[0-9]{2}\.json',Path(approval['path']).name), 'exact actual analyzer producer/approval source paths required')
    for descriptor in (producer,approval):
        require(brief(result['artifacts'][descriptor['path']])==bind(descriptor['path'],descriptor),'actual analyzer/source approval lacks result provenance')
    producer_review=read(approval['path'],approval)
    clean(producer_review,'split-feature-analyzer-source-independent-review/v1')
    require(producer_review['analyzer']==producer,'actual source qualification inner analyzer descriptor differs')
    for path,expected in producer_review['artifacts'].items():
        require(path in concrete['artifacts'] and brief(concrete['artifacts'][path])==brief(expected),'actual analyzer qualification closure lacks concrete raw provenance')
        bind(path,expected)
    release_path=root/PREFIX/'release-manifest.json';release=read(release_path,entries[PREFIX+'/release-manifest.json'])
    require(release['schema']=='split-feature-Hub-release-manifest/v1' and release['cells']==['split-features']
            and release['actual_new_updates']==32 and release['model_tensors']==34 and release['trainable_tensors']==release['frozen_tensors']==17
            and release['actual_analyzer']==producer and release['actual_analyzer_source_review']==approval
            and release['default_promotion'] is False and release['semantic_accuracy'] is None
            and release['full_hybrid_analysis_uploaded'] is False and release['private_global_bodies_uploaded'] is False,
            'actual34/17/17 source-only release limitations/producers differ')
    require(set(release['sources'])==set(entries)-{PREFIX+'/release-manifest.json'}
            and all(release['sources'][name]==entries[name] for name in release['sources']), 'release manifest sources differ from exact concrete payload')
    weights=PREFIX+'/cells/split-features/results/cell-checkpoint.json'
    require(weights in entries and len([name for name in entries if name.endswith('/cell-checkpoint.json')])==1,'exact one opaque split checkpoint required')
    card_review_path=F/'model-card-gap-independent-review-v01.json';card_review=read(card_review_path)
    clean(card_review,'split-feature-model-card-gap-independent-review/v1')
    for name,target in [('split-feature-model-card-v01.md','README.md'),('split-feature-gaps-v01.md','evidence/split-feature-gaps-v01.md')]:
        expected=bind(F/name,card_review['artifacts'][str(F/name)])
        require(brief(entries[PREFIX+'/'+target])==expected,'qualified model card/gap bytes differ from published payload')
    # Anchor prior immutable N3 release identities, while current baseline counts
    # can grow with other additive work before this release begins.
    prior=read(N3/'hf-actual-publication-independent-review-v01.json',PRIOR_REVIEW_PIN)
    clean(prior,'permission-retention-Hub-actual-publication-independent-review/v1')
    prior_after_path=N3/'hf-after-file-identities-v01.json'
    previous=read(prior_after_path,prior['artifacts'][str(prior_after_path)])
    prior_files={name:record for name,record in previous['files'].items() if name.startswith(PRIOR_PREFIX+'/')}
    require(previous['revision']==prior['revision'] and len(prior_files)==prior['checks']['new_files']==142
            and all(baseline['files'].get(name)==record==after['files'].get(name) for name,record in prior_files.items()), 'all142 previously qualified N3 release identities must remain exact')
    for name in ('hf-publication-independent-review-v01.json','hf-preparation-receipt-v01.json',
                 'hf-publication-verification-v01.json','hf-before-file-identities-v01.json','hf-after-file-identities-v01.json',
                 'hf-commit-created-v01.json','hf-preupload-custody-v01.json','hf-download-verification-v01.log',
                 'result-independent-review-v01.json','runtime-independent-review-v01.json','model-card-gap-independent-review-v01.json'):
        bind(F/name)
    bind(Path(__file__).resolve());fence(artifacts)
    observation=dict(schema='split-feature-Hub-actual-publication-independent-review/v1',passed=True,findings=[],reviewer='/root/permission_training_design',
        observed_at_utc=datetime.now(timezone.utc).isoformat(),repository=REPO,release_prefix=PREFIX,revision=revision,parent_revision=parent,
        artifacts=artifacts,qualified_runtime_private_identity_references=private_references,
        checks=dict(new_files=count,payload_bytes=receipt['payload_bytes'],old_files_preserved=old_count,all_current_baseline_identities_exact=True,
            root_attributes_unchanged=True,prior_N3_release_files_preserved=142,all_new_immutable_remote_blob_identities_exact=True,
            all_downloads_byte_exact=True,single_opaque_split_checkpoint_retained=True,serial_parent_CAS_chunks=len(plans),bounded_chunks=True,
            no_unknown_outcomes=True,default_promotion=False,actual_analyzer_source_and_approval_bound=True,qualified_cards_byte_exact=True,
            all_public_copied_source_provenance_exact=True,full_private_global_bodies_excluded=True),
        scope=dict(actual_receipt_and_byte_audit=True,checkpoint_or_reference_JSON_parsed=False,shared_global_bodies_read=False,
            private_identity_refs_joined_to_qualified_runtime_metadata_only=True,network_requests_by_this_replay=False,model_compiler_resource_APIs=False,
            Git_mutations=False,independent_new_training_or_semantic_validation=False),
        limitations=['This independently replays captured immutable remote metadata, returned commit receipts and every CLI-downloaded payload byte; no second remote request is made.',
            'Private resource-start/final body references are metadata-only joins to qualified runtime evidence; those bodies are neither opened nor uploaded by this observer.',
            'The split run fails its old96 full-IR gate. Exposed authored results establish no independent statutory accuracy, genuine latent conditioning, broader-family support or Lake compilation.'])
    with OUTPUT.open('x') as stream:
        json.dump(observation,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=True,path=str(OUTPUT),revision=revision,new_files=count,bytes=OUTPUT.stat().st_size,sha256=pin(OUTPUT)['sha256'])))


def install_read_only_guard():
    def audit(event,args):
        if event=='import' and args[0].split('.')[0] in {'torch','numpy','ipfs_datasets_py','transformers','sentence_transformers','huggingface_hub'}:
            raise ValueError('Actual public replay forbids model/production/SDK imports')
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn')) or event in {'os.system','os.fork','os.kill','os.killpg','fcntl.flock'}:
            raise ValueError('Actual public replay forbids process/network/resource operations')
        if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink','os.mkdir','os.remove','os.rename','os.replace','os.rmdir','os.unlink'}:
            require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'Only exclusive output freezing permitted')
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).absolute()
            require(not private(path),'Private global bodies must remain unopened')
            writing=isinstance(args[1],str) and any(c in args[1] for c in 'wax+')
            writing|=isinstance(args[2],int) and bool(args[2]&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            require(not writing or path==OUTPUT,'Only exclusive new actual-review receipt may be written')
    sys.dont_write_bytecode=True;sys.addaudithook(audit)

if __name__=='__main__':
    install_read_only_guard()
    main()
