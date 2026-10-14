"""Build a finite public N10 release spec after full freeze and independent result review.

No payload copying, model/reference parsing, resource API, Git, SDK or network.
The existing reviewed archive helper owns later preparation/publication/readback.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
ATTEMPT=RUN/'actor-features-20261013-actor-features-ce-02'
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261013-actor-features-v1'
SPEC=F/'hf-release-spec-v01.json'
MANIFEST=F/'release-manifest-v01.json'
FREEZE=F/'actor-features-output-freeze-v01.json'
RUNTIME=F/'actor-features-ce-runtime-review-v01.json'
RESULT_REVIEW=F/'result-independent-review-v01.json'
FREEZE_PASSED=False
READS={}
PUBLIC_RUNTIME=('pre-admission.json','scheduler-adoption.json','lease-binding.json','command.json',
    'child-identity.json','resource-observations.json','child-exit.json','group-rss-summary.json',
    'owned-group-final.json','guardian-exit.json','lease-observations.jsonl','group-rss-observations.jsonl','child.log')
RECIPES=('run_actor_features_v02.py','prepare_actor_features_v02.py','actor_features_bootstrap_smoke_controls_v02.py',
    'run_scope_guardian_v02.py','adopt_shared_scheduler_actor_ranking_v02.py','owned_lease_watchdog_actor_ranking_v02.py',
    'sample_actor_features_private_resources_v02.py','review_actor_features_resource_baseline_v02.py',
    'diagnose_actor_features_storage_v01.py','review_actor_features_retained_claim_preflight_v02.py',
    'reconcile_actor_features_retained_claim_v01.py','audit_actor_features_terminal_resources_v03.py',
    'freeze_actor_features_outputs_v03.py','analyze_actor_features_v04.py','review_actor_features_result_recount_v02.py',
    'archive_actor_features_hf_v03.py','build_actor_features_release_spec_v03.py')
EVIDENCE=('phase-intake-v01.json','evaluation-contract-v01.json','evaluation-contract-root-review-v01.json',
    'training-design-v02.json','trainer-source-independent-review-v01.json','runner-preparer-source-independent-review-v02.json',
    'actor-features-bootstrap-smoke-controls-v02.json','resource-bridge-source-independent-review-v02.json',
    'sampler-source-independent-review-v02.json','resource-observer-source-independent-review-v02.json',
    'resource-baseline-inputs-v02.json','resource-baseline-v02.json','actor-features-storage-diagnostic-v01.json',
    'storage-diagnostic-source-independent-review-v01.json','actor-features-retained-claim-preflight-v01.json',
    'retained-claim-preflight-source-independent-review-v02.json','actor-features-retained-claim-reconciliation-v01.json',
    'retained-claim-reconciliation-source-independent-review-v01.json','retained-claim-reconciliation-execution-approval-v01.json',
    'actor-features-ce-plan-v02.json','actor-features-ce-training-review-v02.json',
    'actor-features-terminal-resource-source-independent-review-v03.json','actor-features-terminal-resource-inputs-v02.json',
    'actor-features-ce-terminal-resource-audit-v02.json','runtime-freeze-source-independent-review-v03.json',
    'actor-features-ce-runtime-review-v01.json','actor-features-output-freeze-v01.json',
    'analyzer-source-independent-review-v04.json','actor-features-result-analysis-v01.json',
    'result-recount-source-independent-review-v02.json','result-recount-inputs-v02.json','actor-features-independent-recount-v01.json',
    'result-independent-review-v01.json','public-result-summary-v01.json','next-experiment-gaps-v01.json',
    'history-preintegration-independent-review-v01.json','terminal-compatibility-port-derivation-v03.json',
    'retry-producer-port-derivation-v02.json','hf-helper-commit-label-port-derivation-v03.json')
sys.dont_write_bytecode=True


def require(value,message):
    if not value:raise ValueError(message)


def private(path):
    path=Path(path)
    return 'private-runtime-snapshots' in path.parts or path.name in {'resources-start.json','resources-final.json',
        'resources-final-failure.json','disk-reservations.json'} or path.name.startswith('ipfs-datasets-resource-scheduler-')


def pin(path,expected=None):
    path=Path(path);require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink() and not private(path),'physical public artifact required')
    before=path.stat();require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=200000000,'bounded ordinary public artifact required')
    raw=path.read_bytes();after=path.stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after) and len(raw)==before.st_size,'raw public identity changed')
    value=dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    require(expected is None or value==dict(path=str(path),**{k:expected[k] for k in ('bytes','sha256')}),'expected public identity differs')
    require(str(path) not in READS or READS[str(path)]==value,'previous consumed raw identity differs');READS[str(path)]=value
    return value


def read(path,expected=None):
    path=Path(path)
    require(FREEZE_PASSED or path in {FREEZE,RUNTIME,F/'runtime-freeze-source-independent-review-v03.json'},'full authenticated freeze required before other metadata reads')
    require('checkpoint' not in path.name and 'reference-packet' not in path.name,'model/reference JSON parsing prohibited')
    captured=pin(path,expected);raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==captured['sha256'] and len(raw)==captured['bytes'],'consumed metadata differs')
    def unique(pairs):
        out={}
        for key,value in pairs:require(key not in out,'duplicate JSON key');out[key]=value
        return out
    result=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
    pin(path,captured);return result


def expected_names():
    panels=('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law','fresh_dev','fresh_test')
    names={'data-schedule-before-models.json','cell-checkpoint.json','cell-training.json','summary.json','initial-parent-head-parity.json','trained-frozen-head-retention.json'}
    for stage in ('baseline','trained'):names.update(f'{stage}-{panel}-{kind}.json' for panel in panels for kind in ('raw','joint'))
    for label in ('initial-training168','parent-training168','trained-training168','parent-fresh_dev','parent-fresh_test'):
        names.update(label+'-'+kind+'.json' for kind in ('raw','joint'))
    for stage in ('initial','trained'):
        names.add(stage+'-parity.json');names.update(stage+'-parity-'+control+'.json' for control in ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    require(len(names)==62,'exact62 expected result names required');return names


def main():
    global FREEZE_PASSED
    require(sys.argv[1:]==[] and not os.path.lexists(SPEC) and not os.path.lexists(MANIFEST),'exclusive argument-free spec/manifest writes required')
    freeze_pin=pin(FREEZE);freeze=read(FREEZE,freeze_pin);runtime_pin=pin(RUNTIME);runtime=read(RUNTIME,runtime_pin)
    require(freeze['schema']=='actor-features-output-freeze/v1' and freeze['all_outputs_frozen'] is True
        and freeze['authorizes_authored_eval_scoring'] is True and freeze['statutory_reference_scoring_authorized'] is False
        and freeze['runtime_review']==runtime_pin and runtime['schema']=='actor-features-runtime-independent-review/v1'
        and runtime['passed'] is True and runtime['findings']==[] and runtime['outputs']==freeze['results']
        and runtime['output_file_count']==62 and runtime['actual_returned_optimizer_updates']==32,'complete exact frozen science bundle required')
    require(runtime['observer']==pin(F/'freeze_actor_features_outputs_v03.py')
        and runtime['independent_source_review']==pin(F/'runtime-freeze-source-independent-review-v03.json'),'exact current qualified freezer required')
    review=read(F/'runtime-freeze-source-independent-review-v03.json')
    require(review['passed'] is True and review['findings']==[] and review['observer']==runtime['observer'],'independent current freezer source gate required')
    require(set(freeze['results'])=={str(ATTEMPT/'results'/name) for name in expected_names()},'exact current attempt62 inventory required')
    for path,brief in freeze['results'].items():
        pin(path,brief);require(stat.S_IMODE(Path(path).stat().st_mode)==0o444,'result must already be fully frozen')
    FREEZE_PASSED=True
    plan_pin=pin(F/'actor-features-ce-plan-v02.json');require(freeze['plan']==runtime['plan']==plan_pin,'exact attempt02 plan association required')
    plan=read(plan_pin['path'],plan_pin)
    require(plan['attempt_name']==ATTEMPT.name and plan['cell']=='actor-features-ce' and len(plan['source_owner_pins'])==37,'current37-owner CE-only plan required')
    result_pin=pin(RESULT_REVIEW);result_review=read(RESULT_REVIEW,result_pin)
    require(result_review['schema']=='actor-features-result-independent-review/v1' and result_review['passed'] is True
        and result_review['findings']==[] and result_review['freeze']==freeze_pin and result_review['runtime_review']==runtime_pin,
        'root independent completed result review must join the actual freeze/runtime')
    require(result_review['analysis']==pin(F/'actor-features-result-analysis-v01.json')
        and result_review['independent_recount']==pin(F/'actor-features-independent-recount-v01.json'),'actual scored analysis and independent recount must be bound')
    baseline_pin=pin(F/'hf-before-file-identities-v01.json');before=read(baseline_pin['path'],baseline_pin)
    require(before['repo']==REPO and before['revision']=='3c430bdb412a6bd0871f813a944dfec5b2f4c8e9'
        and len(before['files'])==4931 and not any(name.startswith(PREFIX+'/') for name in before['files']),'exact qualified absent-prefix Hub baseline required')
    files=[];destinations=set()
    def add(path,suffix,expected=None):
        source=pin(path,expected);destination=PREFIX+'/'+suffix
        require(destination not in destinations and source['bytes']<10000000 and '..' not in Path(suffix).parts,'unique bounded explicit public destination required')
        destinations.add(destination);files.append(dict(source=source,destination=destination))
    for path,brief in sorted(freeze['results'].items()):add(path,'cells/actor-features-ce/results/'+Path(path).name,brief)
    for name in PUBLIC_RUNTIME:add(ATTEMPT/name,'cells/actor-features-ce/runtime/'+name)
    candidate=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_features.py'
    tests=F/'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_features_contracts.py'
    add(candidate,'source/legal_span_actor_features.py');add(tests,'source/test_legal_span_actor_features_contracts.py')
    for descriptor in plan['source_owner_pins'].values():
        path=Path(descriptor['path'])
        if path==candidate:continue
        relative=path.relative_to(F/'datasets').as_posix();add(path,'source/datasets/'+relative,descriptor)
    for name in RECIPES:add(F/name,'recipes/'+name)
    for name in EVIDENCE:add(F/name,'evidence/'+name)
    for name in ('pre-admission.json','failure-primary.json','child-exit.json','guardian-exit.json'):
        add(RUN/'actor-features-20261013-actor-features-ce-01'/name,'failures/attempt01/'+name)
    add(F/'MODEL_CARD_v01.md','README.md')
    total=sum(row['source']['bytes'] for row in files)
    require(len(files)<=500 and total<=200000000,'bounded explicit release payload required')
    for path,expected in list(READS.items()):pin(path,expected)
    spec=dict(schema='actor-features-Hub-release-spec/v1',repository=REPO,release_prefix=PREFIX,baseline=baseline_pin,
        freeze=freeze_pin,runtime_review=runtime_pin,result_review=result_pin,files=files)
    manifest=dict(schema='actor-features-release-manifest/v1',file_count=len(files),payload_bytes=total,files=files,
        checkpoint=dict(path=str(ATTEMPT/'results/cell-checkpoint.json'),**freeze['results'][str(ATTEMPT/'results/cell-checkpoint.json')]),
        private_bodies_included=False,default_promotion=False)
    for path,value in ((SPEC,spec),(MANIFEST,manifest)):
        with path.open('x') as out:json.dump(value,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
        path.chmod(0o444)
    print(json.dumps(dict(spec=pin(SPEC),manifest=pin(MANIFEST),file_count=len(files),payload_bytes=total,payload_copies=0,network_calls=0)))

if __name__=='__main__':main()
