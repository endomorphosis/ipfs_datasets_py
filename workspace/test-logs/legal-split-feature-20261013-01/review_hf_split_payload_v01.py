"""Independent finite local custody review of the prepared Hub payload.

No SDK imports, requests, model restoration, checkpoint JSON or reference JSON.
"""
import hashlib
import json
import math
import os
from pathlib import Path

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261013-split-feature-v1'
OUTPUT = F/'hf-publication-independent-review-v01.json'
PRIOR = F.parent/'legal-permission-retention-20261012-01'
PRIOR_PREFIX = 'releases/20261012-permission-retention-v1'
RUNTIME = ('pre-admission.json','scheduler-adoption.json','lease-binding.json','command.json','child-identity.json','resource-observations.json','child-exit.json','group-rss-summary.json','owned-group-final.json','guardian-exit.json','lease-observations.jsonl','group-rss-observations.jsonl','child.log')
EVIDENCE = ('split-feature-output-freeze-v01.json','split-feature-result-analysis-v01.json',
 'result-independent-review-v01.json','runtime-independent-review-v01.json','registration-v01.json',
 'training-export-v01.json','root-science-source-independent-review-v01.json',
 'trainer-source-independent-review-v01.json','terminal-copy-freeze-source-independent-review-v02.json',
 'combined-pure-tests-v01.xml','combined-pure-tests-v01.log','combined-pure-tests-observation-v01.json',
 'split-feature-evaluation-contract-v01.json','saved-score-hybrid-source-independent-review-v02.json',
 'split-feature-gaps-v01.md','hf-helper-source-independent-review-v02.json')
RECIPES = ('run_split_features.py','prepare_split_features.py','run_scope_guardian.py',
 'review_split_cell_v03.py','capture_split_terminal_v01.py','freeze_split_outputs_v02.py',
 'audit_split_terminal_v01.py','analyze_saved_score_hybrid_v02.py',
 'prepare_hf_split_feature_release_v04.py','publish_hf_split_feature_release_v04.py')
SOURCE = ('ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_split_features.py',
 'tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_split_features_contracts.py')

def require(condition, message):
    if not condition: raise ValueError(message)

READ_PINS = {}
PRIVATE_REFERENCES = {}

def private(path):
    path=Path(path)
    return 'private-runtime-snapshots' in path.parts or path.name in ('resources-start.json','resources-final.json','disk-reservations.json')

def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and path.is_file() and not path.is_symlink(),'physical ordinary byte source required')
    require('private-runtime-snapshots' not in path.parts and path.name not in ('resources-start.json','resources-final.json','disk-reservations.json'),'private bodies excluded')
    before=path.stat();require(before.st_size<=128*1024*1024,'bounded byte source required before allocation');raw=path.read_bytes();after=path.stat()
    identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    require(identity(before)==identity(after) and len(raw)==before.st_size<=128*1024*1024,'source changed during read or oversized')
    result=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    return dict(path=str(path),**result)

def brief(value):
    require(type(value) is dict and set(value) in ({'bytes','sha256'},{'path','bytes','sha256'})
        and type(value['bytes']) is int and 0<=value['bytes']<=200000000
        and type(value['sha256']) is str and len(value['sha256'])==64
        and all(c in '0123456789abcdef' for c in value['sha256']),'closed bounded raw identity required')
    return {key:value[key] for key in ('bytes','sha256')}

def captured_raw(path):
    path=Path(path);before=pin(path);raw=path.read_bytes()
    require(dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())==brief(before) and pin(path)==before,'consumed raw bytes differ from captured identity')
    return raw,brief(before)

def read(path):
    path=Path(path)
    require('checkpoint' not in path.name and 'reference-packet' not in path.name,'opaque checkpoint/reference JSON parsing forbidden')
    raw,record=captured_raw(path);key=str(path)
    require(key not in READ_PINS or READ_PINS[key]==record,'previous parsed metadata changed')
    READ_PINS[key]=record
    def unique(pairs):
        value={}
        for key,item in pairs:require(key not in value,'duplicate JSON key');value[key]=item
        return value
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'nonfinite JSON number');return value
    return json.loads(raw,object_pairs_hook=unique,parse_float=finite,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))

def fence_reads(artifacts):
    for path,record in READ_PINS.items():
        require(path not in artifacts or artifacts[path]==record,'parsed metadata artifact conflict')
        artifacts[path]=record
    for path,record in artifacts.items():
        if private(path):
            require(PRIVATE_REFERENCES.get(path)==record,'private identity reference lost qualified runtime join')
        else:require(brief(pin(path))==record,'closing exact parsed/source artifact drift')


def install_guard():
    import sys
    sys.dont_write_bytecode=True
    def audit(event,args):
        if event=='import' and args[0].split('.')[0] in {'torch','numpy','ipfs_datasets_py','transformers','sentence_transformers','huggingface_hub'}:
            raise ValueError('model/production/SDK imports forbidden')
        require(not event.startswith(('socket.','subprocess.','os.exec','os.spawn')) and event not in {
            'os.system','os.fork','os.kill','os.killpg','fcntl.flock','os.remove','os.unlink','os.rename','os.replace','os.mkdir','os.rmdir'},
            'process/network/resource/mutation forbidden')
        if event=='open':
            path,mode,flags=args
            target=Path(os.fsdecode(path)).absolute() if isinstance(path,(str,bytes,os.PathLike)) else None
            writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
            writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC))
            require(not writing or target==OUTPUT,'only exclusive owned payload review may be written')
        if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
            require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'only owned review freeze allowed')
    sys.addaudithook(audit)


def main():
    require(not os.path.lexists(OUTPUT),'exclusive fresh concrete payload review required')
    artifacts={}
    def bind(path,expected=None):
        path=Path(path);key=str(path)
        if private(path):
            require(expected is not None and PRIVATE_REFERENCES.get(key)==brief(expected),'private identity reference requires exact qualified runtime join')
            require(key not in artifacts or artifacts[key]==brief(expected),'private metadata reference identity changed')
            artifacts[key]=brief(expected);return dict(path=key,**brief(expected))
        value=pin(path)
        require(expected is None or brief(value)==brief(expected),'required source raw identity differs')
        require(key not in READ_PINS or READ_PINS[key]==brief(value),'bound bytes differ from consumed metadata')
        require(key not in artifacts or artifacts[key]==brief(value),'first public source identity changed')
        artifacts[key]=brief(value);return value
    own=bind(Path(__file__).resolve())
    approval_path=F/'hf-payload-observer-source-independent-review-v01.json'
    bind(approval_path);own_review=read(approval_path)
    require(own_review['schema']=='split-feature-Hub-payload-observer-source-independent-review/v1'
        and own_review['passed'] is True and own_review['findings']==[] and own_review['observer']==own,
        'exact clean independent concrete-observer source qualification required')
    receipt_path=F/'hf-preparation-receipt-v01.json';bind(receipt_path);receipt=read(receipt_path)
    require(set(receipt)=={'schema','repository','release_prefix','expected_parent_revision','upload_root','complete_upload_files',
        'payload_files','payload_bytes','baseline_pin','result_review','runtime_review','helper_review','freeze_manifest',
        'approved_source_artifacts','default_promotion','additive_only'}
        and receipt['schema']=='split-feature-Hub-preparation/v1','closed exact preparation schema required')
    require(receipt['repository']==REPO and receipt['release_prefix']==PREFIX and receipt['default_promotion'] is False
        and receipt['additive_only'] is True,'closed additive experiment required')
    root=Path(receipt['upload_root'])
    require(root==F/'hf-upload-v01' and root.resolve()==root and root.is_dir() and not root.is_symlink(),'exact upload root required')
    for key,name in [('baseline_pin','hf-before-file-identities-v01.json'),('result_review','result-independent-review-v01.json'),
        ('runtime_review','runtime-independent-review-v01.json'),('helper_review','hf-helper-source-independent-review-v02.json'),
        ('freeze_manifest','split-feature-output-freeze-v01.json')]:
        require(bind(F/name)==receipt[key],'preparation source descriptor changed')
    baseline=read(F/'hf-before-file-identities-v01.json')
    require(baseline['repo']==REPO and baseline['revision']==receipt['expected_parent_revision']
        and type(baseline['revision']) is str and len(baseline['revision'])==40
        and all(c in '0123456789abcdef' for c in baseline['revision'])
        and len(baseline['files'])>=4244 and '.gitattributes' in baseline['files'],'complete current Hub baseline required')
    require(not any(name.startswith(PREFIX+'/') for name in baseline['files']),'new release prefix must be absent')
    prior_path=PRIOR/'hf-actual-publication-independent-review-v01.json'
    bind(prior_path,dict(bytes=141473,sha256='26596f61ff1af63c1d77757bfb221747d672f75ef26d2476ece61c99f718b4e4'))
    prior=read(prior_path)
    require(prior['schema']=='permission-retention-Hub-actual-publication-independent-review/v1'
        and prior['passed'] is True and prior['findings']==[],'qualified immutable prior archive required')
    prior_after_path=PRIOR/'hf-after-file-identities-v01.json'
    bind(prior_after_path,prior['artifacts'][str(prior_after_path)]);prior_after=read(prior_after_path)
    previous={name:value for name,value in prior_after['files'].items() if name.startswith(PRIOR_PREFIX+'/')}
    require(prior_after['revision']==prior['revision'] and len(previous)==prior['checks']['new_files']==142
        and all(baseline['files'].get(name)==value for name,value in previous.items()),'all142 prior N3 release identities must remain exact')
    runtime=read(F/'runtime-independent-review-v01.json')
    require(runtime['schema']=='split-feature-runtime-independent-review/v1' and runtime['passed'] is True and runtime['findings']==[]
        and runtime['total_actual_returned_optimizer_updates']==32 and runtime['result_file_count']==53,
        'exact completed source-qualified runtime identity authority required')
    require(READ_PINS[str(F/'runtime-independent-review-v01.json')]==dict(bytes=92760,
        sha256='455b0962c661d38c53ef6866940a9633d2aafdc6e6e9ef23da0cf2dc454b85f7'),'exact actual runtime qualification required')
    references={path:brief(value) for path,value in runtime['artifacts'].items() if private(path)}
    require(len(references)==2 and {Path(path).name for path in references}=={'resources-start.json','resources-final.json'}
        and len({str(Path(path).parent) for path in references})==1,'closed own two private endpoint identity references required')
    PRIVATE_REFERENCES.update(references)
    approved={}
    for name,schema in [('result-independent-review-v01.json','split-feature-result-independent-review/v1'),
        ('runtime-independent-review-v01.json','split-feature-runtime-independent-review/v1'),
        ('hf-helper-source-independent-review-v02.json','split-feature-Hub-helper-source-independent-review/v1')]:
        review=read(F/name)
        require(review['schema']==schema and review['passed'] is True and review['findings']==[],'clean exact source/result/runtime review required')
        for path,expected in review['artifacts'].items():
            require('path' not in expected or expected['path']==path,'review artifact path differs')
            expected=brief(expected)
            require(path not in approved or approved[path]==expected,'conflicting independent review artifact identity')
            bind(path,expected);approved[path]=expected
        approved[str(F/name)]=READ_PINS[str(F/name)]
    require(receipt['approved_source_artifacts']==approved,'entire prepared source closure must equal qualified review union')
    frozen=read(F/'split-feature-output-freeze-v01.json')
    require(frozen['schema']=='split-feature-output-freeze/v1' and frozen['all_outputs_frozen'] is True
        and frozen['new_trained_outputs_scored_before_freeze'] is False and frozen['reference_packet_previously_scored'] is True
        and frozen['independent_blinding'] is False and len(frozen['cells'])==1,'single new53-output freeze with exposed references required')
    mapping={}
    def add(source,relative):
        source=Path(source);remote=PREFIX+'/'+relative
        require(remote not in mapping and '..' not in Path(remote).parts and not Path(remote).is_absolute(),'unique closed payload path required')
        require('private-runtime-snapshots' not in source.parts and source.name not in {
            'resources-start.json','resources-final.json','disk-reservations.json','saved-score-hybrid-analysis-v01.json'},'private/full hybrid bodies excluded')
        original=bind(source)
        require(approved.get(str(source))==brief(original),'explicit qualified source provenance required')
        copied=bind(root/remote)
        require(brief(original)==brief(copied) and copied['path']==str(root/remote),'prepared copy differs from reviewed original')
        require(0<=copied['bytes']<10000000 and Path(remote).suffix in {'.json','.jsonl','.py','.md','.xml','.log'},'bounded reviewed text artifact required')
        mapping[remote]=copied
    row=frozen['cells'][0]
    require(row['cell']==dict(id='split-features',trainable_parameter_policy='split-features',actor_ranking_enabled=False,
        presence_ce_weight=1,modality_loss_weight=2),'exact sole split-feature cell required')
    for role in ('plan','summary','guardian_terminal','pre_admission'):
        require(bind(row[role]['path'])==row[role] and approved.get(row[role]['path'])==brief(row[role]),'frozen descriptor lacks raw provenance')
    plan=read(row['plan']['path']);summary=read(row['summary']['path']);terminal=read(row['guardian_terminal']['path']);pre=read(row['pre_admission']['path'])
    require(plan['cell']==summary['cell']==row['cell'] and plan['attempt_name']==summary['attempt_name']
        =='split-feature-20261013-split-features-01','exact cell/attempt identities required')
    require(summary['status']=='completed' and summary['actual_new_updates']==32 and summary['actual_encoder_calls']==0
        and summary['latent_enabled'] is False and summary['initial_parent_head_parity']['total_source_rows']==392
        and summary['initial_parent_head_parity']['all_four_heads_and_tokens_exact'] is True
        and summary['initial_parent_head_parity']['checked_before_training'] is True,'completed source-only32 and initial392 parent parity required')
    require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
        and terminal['returncode']==terminal['child_returncode']==0 and terminal['artifacts_durable'] is True
        and terminal['resource_reservation_released'] is True,'successful durable released terminal required')
    require(len(row['results'])==53,'all53 outputs including one opaque checkpoint required')
    for source,expected in row['results'].items():
        bind(source,expected);add(source,'cells/split-features/results/'+Path(source).name)
    add(row['plan']['path'],'cells/split-features/plan.json')
    require(bind(pre['review']['path'])==pre['review'] and approved.get(pre['review']['path'])==brief(pre['review']),'actual protocol review raw join differs')
    add(pre['review']['path'],'cells/split-features/training-protocol-review.json')
    attempt=Path(row['guardian_terminal']['path']).parent
    require(Path(row['summary']['path']).parent==attempt/'results'
        and set(PRIVATE_REFERENCES)=={str(attempt/name) for name in ('resources-start.json','resources-final.json')},
        'exact physical attempt result and qualified private identity roots required')
    for name in RUNTIME:add(attempt/name,'cells/split-features/runtime/'+name)
    analysis_path=F/'split-feature-result-analysis-v01.json';analysis=read(analysis_path)
    producer=analysis['analyzer'];qualification=analysis['independent_source_review']
    require(analysis['schema']=='split-feature-exposed-result-analysis/v1' and analysis['passed'] is True and analysis['findings']==[],
        'qualified actual analysis required')
    import re
    for descriptor,pattern in ((producer,r'analyze_split_feature_results_v[0-9]{2}\.py'),
        (qualification,r'split-feature-analyzer-source-independent-review-v[0-9]{2}\.json')):
        path=Path(descriptor['path'])
        require(path.parent==F and re.fullmatch(pattern,path.name) and bind(path)==descriptor
            and approved.get(str(path))==brief(descriptor),'exact qualified actual analyzer producer/approval required')
    producer_review=read(qualification['path'])
    require(producer_review['schema']=='split-feature-analyzer-source-independent-review/v1' and producer_review['passed'] is True
        and producer_review['findings']==[] and producer_review['analyzer']==producer,'actual analyzer source qualification inner join differs')
    for path,expected in producer_review['artifacts'].items():
        require(approved.get(path)==brief(expected),'analyzer qualification closure lacks concrete provenance');bind(path,expected)
    card_review_path=F/'model-card-gap-independent-review-v01.json';bind(card_review_path);card_review=read(card_review_path)
    require(card_review['schema']=='split-feature-model-card-gap-independent-review/v1' and card_review['passed'] is True
        and card_review['findings']==[],'qualified model-card/gap review required')
    for name in ('split-feature-model-card-v01.md','split-feature-gaps-v01.md'):
        require(brief(bind(F/name))==brief(card_review['artifacts'][str(F/name)]) and approved.get(str(F/name))==brief(card_review['artifacts'][str(F/name)]),
            'independently qualified card/gap bytes differ')
    for name in EVIDENCE:add(F/name,'evidence/'+name)
    for name in RECIPES:add(F/name,'recipe/'+name)
    add(producer['path'],'recipe/'+Path(producer['path']).name)
    add(qualification['path'],'evidence/'+Path(qualification['path']).name)
    for relative in SOURCE:add(F/'datasets'/relative,'source/'+relative)
    add(F/'split-feature-model-card-v01.md','README.md')
    release_path=root/PREFIX/'release-manifest.json';release=read(release_path)
    require(release==dict(schema='split-feature-Hub-release-manifest/v1',repository=REPO,release_prefix=PREFIX,cells=['split-features'],
        actual_new_updates=32,dimension=384,latent_enabled=False,actual_external_latent_encoder_calls=0,feature_paths_per_source_model_forward=2,
        same_original_parent_model_sha256=summary['same_original_parent_model_sha256'],fresh_Adam=True,inherited_optimizer_moments=False,
        model_tensors=34,trainable_tensors=17,frozen_tensors=17,initial_parent_head_score_rows=392,
        equal_compute_budget_claimed=False,independent_statutory_gold=False,semantic_accuracy=None,default_promotion=False,Lake_executed=False,
        full_hybrid_analysis_uploaded=False,private_global_bodies_uploaded=False,actual_analyzer=producer,
        actual_analyzer_source_review=qualification,sources=mapping),'release manifest must exactly describe actual copies and scope')
    mapping[PREFIX+'/release-manifest.json']=bind(release_path)
    require(mapping==receipt['complete_upload_files'],'closed complete preparation inventory required')
    paths=list(root.rglob('*'))
    require(not any(path.is_symlink() for path in paths) and {path.relative_to(root).as_posix() for path in paths if path.is_file()}==set(mapping),
        'exact ordinary payload tree without unlisted files required')
    total=sum(record['bytes'] for record in mapping.values())
    expected_count=53+1+1+len(RUNTIME)+len(EVIDENCE)+len(RECIPES)+2+len(SOURCE)+1+1
    require(type(receipt['payload_files']) is int and receipt['payload_files']==len(mapping)==expected_count
        and type(receipt['payload_bytes']) is int and receipt['payload_bytes']==total and 0<total<=200000000
        and max(record['bytes'] for record in mapping.values())<10000000,'finite independently derived capped payload required')
    chunks=[];current=[];size=0
    for name in sorted(mapping):
        if current and (len(current)==48 or size+mapping[name]['bytes']>16000000):chunks.append(current);current=[];size=0
        current.append(name);size+=mapping[name]['bytes']
    if current:chunks.append(current)
    require(all(0<len(c)<=48 and sum(mapping[n]['bytes'] for n in c)<=16000000 for c in chunks),'independent48-file/16MB chunk bounds required')
    fence_reads(artifacts)
    review=dict(schema='split-feature-Hub-publication-independent-review/v1',passed=True,findings=[],repository=REPO,release_prefix=PREFIX,
        expected_parent_revision=baseline['revision'],payload_files=len(mapping),payload_bytes=total,artifacts=artifacts,
        scope=dict(reviewer='/root/permission_protocol_review',concrete_payload_authorized=True,prepared_copies_checked_against_exact_originals=True,
            single_opaque_split_checkpoint_retained=True,raw_result_files=53,source_only_dimension=384,external_latent_encoder_calls=0,new_updates=32,
            qualified_private_identity_references=PRIVATE_REFERENCES.copy(),private_bodies_opened=False,
            complete_prior_file_count=len(baseline['files']),prior_N3_release_files_preserved=142,prior_root_attributes=baseline['files']['.gitattributes'],
            payload_max_single_bytes=max(record['bytes'] for record in mapping.values()),
            chunks=[dict(files=len(c),bytes=sum(mapping[n]['bytes'] for n in c),names=c) for c in chunks],no_root_attributes_operation=True,
            SDK_imported=False,network_requests=False,model_or_resource_APIs=False,checkpoint_or_reference_JSON_parsed=False),
        limitations=['Authorization covers the exact local additive payload; actual remote revisions and immutable downloaded bytes require final verification.',
            'Previously exposed authored engineering measurements establish no independent statutory gold, genuine latent semantics, broader logic-family or Lake qualification.',
            'The candidate fails the old96 complete-IR gate. No automatic selection or default promotion. The full16MB hybrid analysis and private resource bodies are excluded.'])
    with OUTPUT.open('x') as stream:json.dump(review,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=True,output=str(OUTPUT),payload_files=len(mapping),payload_bytes=total,chunks=len(chunks),artifacts=len(artifacts))))


if __name__=='__main__':
    install_guard();main()
