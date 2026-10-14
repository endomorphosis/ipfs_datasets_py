"""Build a finite public N11 release spec after full freeze and independent result review.

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
ATTEMPT=RUN/'conditions-presence-20261014-conditions-presence-ce-01'
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261014-conditions-presence-v1'
SPEC=F/'hf-release-spec-v01.json'
MANIFEST=F/'release-manifest-v01.json'
FREEZE=F/'conditions-presence-output-freeze-v01.json'
RUNTIME=F/'conditions-presence-ce-runtime-review-v01.json'
RESULT_REVIEW=F/'result-independent-review-v01.json'
FREEZE_PASSED=False
READS={}
PUBLIC_RUNTIME=('pre-admission.json','scheduler-adoption.json','lease-binding.json','command.json',
    'child-identity.json','resource-observations.json','child-exit.json','group-rss-summary.json',
    'owned-group-final.json','guardian-exit.json','lease-observations.jsonl','group-rss-observations.jsonl','child.log')
RECIPES=('run_conditions_presence_v01.py','prepare_conditions_presence_v01.py','conditions_presence_bootstrap_smoke_controls_v01.py',
    'run_scope_guardian_v02.py','adopt_shared_scheduler_actor_ranking_v02.py','owned_lease_watchdog_actor_ranking_v02.py',
    'sample_conditions_presence_private_resources_v01.py','conditions_presence_resource_protocol_v01.py',
    'review_conditions_presence_resource_baseline_v01.py','review_conditions_presence_resource_baseline_v02.py',
    'audit_conditions_presence_terminal_resources_v01.py','freeze_conditions_presence_outputs_v01.py',
    'analyze_conditions_presence_v01.py','review_conditions_presence_result_recount_v01.py',
    'archive_conditions_presence_hf_v02.py','build_conditions_presence_release_spec_v01.py')
EVIDENCE=('phase-intake-v01.json','retained-source-owners-v01.json','evaluation-contract-v01.json','evaluation-contract-root-review-v01.json',
    'training-design-v01.json','trainer-source-independent-review-v01.json','runner-preparer-source-independent-review-v01.json',
    'conditions-presence-bootstrap-smoke-controls-v01.json','resource-protocol-contract-v01.json','resource-bridge-source-independent-review-v01.json',
    'sampler-source-independent-review-v01.json','resource-observer-source-independent-review-v01.json','resource-observer-source-independent-review-v02.json',
    'resource-baseline-inputs-v01.json','resource-baseline-v01.json','capacity-refusal-observation-v01.json',
    'conditions-presence-ce-plan-v01.json','conditions-presence-ce-training-review-v01.json',
    'conditions-presence-terminal-resource-source-independent-review-v01.json','conditions-presence-terminal-resource-inputs-v01.json',
    'conditions-presence-ce-terminal-resource-audit-v01.json','runtime-freeze-source-independent-review-v01.json',
    'conditions-presence-ce-runtime-review-v01.json','conditions-presence-output-freeze-v01.json',
    'analyzer-source-independent-review-v01.json','conditions-presence-result-analysis-v01.json',
    'result-recount-source-independent-review-v01.json','result-recount-inputs-v01.json','conditions-presence-independent-recount-v01.json',
    'result-independent-review-v01.json','public-result-summary-v01.json','next-experiment-gaps-v01.json','hf-helper-port-derivation-v01.json')
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
    require(FREEZE_PASSED or path in {FREEZE,RUNTIME,F/'runtime-freeze-source-independent-review-v01.json'},'full authenticated freeze required before other metadata reads')
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
    require(freeze['schema']=='conditions-presence-output-freeze/v1' and freeze['all_outputs_frozen'] is True
        and freeze['authorizes_authored_eval_scoring'] is True and freeze['statutory_reference_scoring_authorized'] is False
        and freeze['runtime_review']==runtime_pin and runtime['schema']=='conditions-presence-runtime-independent-review/v1'
        and runtime['passed'] is True and runtime['findings']==[] and runtime['outputs']==freeze['results']
        and runtime['output_file_count']==62 and runtime['actual_returned_optimizer_updates']==32,'complete exact frozen science bundle required')
    require(runtime['observer']==pin(F/'freeze_conditions_presence_outputs_v01.py')
        and runtime['independent_source_review']==pin(F/'runtime-freeze-source-independent-review-v01.json'),'exact current qualified freezer required')
    review=read(F/'runtime-freeze-source-independent-review-v01.json')
    require(review['passed'] is True and review['findings']==[] and review['observer']==runtime['observer'],'independent current freezer source gate required')
    require(set(freeze['results'])=={str(ATTEMPT/'results'/name) for name in expected_names()},'exact current attempt62 inventory required')
    for path,brief in freeze['results'].items():
        pin(path,brief);require(stat.S_IMODE(Path(path).stat().st_mode)==0o444,'result must already be fully frozen')
    FREEZE_PASSED=True
    plan_pin=pin(F/'conditions-presence-ce-plan-v01.json');require(freeze['plan']==runtime['plan']==plan_pin,'exact attempt01 plan association required')
    plan=read(plan_pin['path'],plan_pin)
    require(plan['attempt_name']==ATTEMPT.name and plan['cell']=='conditions-presence-ce' and len(plan['source_owner_pins'])==38,'current38-owner conditions-CE plan required')
    result_pin=pin(RESULT_REVIEW);result_review=read(RESULT_REVIEW,result_pin)
    require(result_review['schema']=='conditions-presence-result-independent-review/v1' and result_review['passed'] is True
        and result_review['findings']==[] and result_review['freeze']==freeze_pin and result_review['runtime_review']==runtime_pin,
        'root independent completed result review must join the actual freeze/runtime')
    require(result_review['analysis']==pin(F/'conditions-presence-result-analysis-v01.json')
        and result_review['independent_recount']==pin(F/'conditions-presence-independent-recount-v01.json'),'actual scored analysis and independent recount must be bound')
    baseline_pin=pin(F/'hf-before-file-identities-v01.json');before=read(baseline_pin['path'],baseline_pin)
    require(before['repo']==REPO and before['revision']=='f91692a0a695d91b793a00936dd525fbe2bafcac'
        and len(before['files'])==5105 and not any(name.startswith(PREFIX+'/') for name in before['files']),'exact qualified absent-prefix Hub baseline required')
    files=[];destinations=set()
    def add(path,suffix,expected=None):
        source=pin(path,expected);destination=PREFIX+'/'+suffix
        require(destination not in destinations and source['bytes']<10000000 and '..' not in Path(suffix).parts,'unique bounded explicit public destination required')
        destinations.add(destination);files.append(dict(source=source,destination=destination))
    for path,brief in sorted(freeze['results'].items()):add(path,'cells/conditions-presence-ce/results/'+Path(path).name,brief)
    for name in PUBLIC_RUNTIME:add(ATTEMPT/name,'cells/conditions-presence-ce/runtime/'+name)
    candidate=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_presence.py'
    tests=F/'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_conditions_presence_contracts.py'
    add(candidate,'source/legal_span_conditions_presence.py');add(tests,'source/test_legal_span_conditions_presence_contracts.py')
    for descriptor in plan['source_owner_pins'].values():
        path=Path(descriptor['path'])
        if path==candidate:continue
        relative=path.relative_to(F/'datasets').as_posix();add(path,'source/datasets/'+relative,descriptor)
    for name in RECIPES:add(F/name,'recipes/'+name)
    for name in EVIDENCE:add(F/name,'evidence/'+name)
    add(F/'MODEL_CARD_v01.md','README.md')
    total=sum(row['source']['bytes'] for row in files)
    require(len(files)<=500 and total<=200000000,'bounded explicit release payload required')
    for path,expected in list(READS.items()):pin(path,expected)
    spec=dict(schema='conditions-presence-Hub-release-spec/v1',repository=REPO,release_prefix=PREFIX,baseline=baseline_pin,
        freeze=freeze_pin,runtime_review=runtime_pin,result_review=result_pin,files=files)
    manifest=dict(schema='conditions-presence-release-manifest/v1',file_count=len(files),payload_bytes=total,files=files,
        checkpoint=dict(path=str(ATTEMPT/'results/cell-checkpoint.json'),**freeze['results'][str(ATTEMPT/'results/cell-checkpoint.json')]),
        private_bodies_included=False,default_promotion=False)
    for path,value in ((SPEC,spec),(MANIFEST,manifest)):
        with path.open('x') as out:json.dump(value,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
        path.chmod(0o444)
    print(json.dumps(dict(spec=pin(SPEC),manifest=pin(MANIFEST),file_count=len(files),payload_bytes=total,payload_copies=0,network_calls=0)))

if __name__=='__main__':main()
