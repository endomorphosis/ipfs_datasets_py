"""Build a finite public F16 actor-context-ranking release spec after full freeze and independent result review.

No payload copying, model/reference parsing, resource API, Git, SDK or network.
The existing reviewed archive helper owns later preparation/publication/readback.
"""
import hashlib
import types
import json
import os
from pathlib import Path
import stat
import sys

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
ATTEMPT=RUN/'actor-context-ranking-20261014-actor-context-ranking-hinge-01'
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261014-actor-context-ranking-v1'
SPEC=F/'hf-release-spec-v01.json'
PORT_GATE=F/'hf-helper-port-source-independent-review-v01.json'
MAX_FILE_BYTES=32*1024*1024
MANIFEST=F/'release-manifest-v01.json'
FREEZE=F/'actor-context-ranking-output-freeze-v01.json'
RUNTIME=F/'actor-context-ranking-hinge-runtime-review-v01.json'
RESULT_REVIEW=F/'actor-context-ranking-result-independent-review-v01.json'
FREEZE_PASSED=False
READS={}
PUBLIC_RUNTIME=('pre-admission.json','scheduler-adoption.json','lease-binding.json','command.json',
    'child-identity.json','resource-observations.json','child-exit.json','group-rss-summary.json',
    'owned-group-final.json','guardian-exit.json','lease-observations.jsonl','group-rss-observations.jsonl','child.log')
RECIPES=('run_actor_context_ranking_v04.py', 'prepare_actor_context_ranking_v04.py', 'actor_context_ranking_bootstrap_smoke_controls_v04.py', 'review_actor_context_ranking_training_plan_v03.py', 'run_scope_guardian_v04.py', 'adopt_shared_scheduler_actor_ranking_v03.py', 'owned_lease_watchdog_actor_ranking_v03.py', 'bootstrap_actor_context_ranking_resources_v02.py', 'sample_actor_context_ranking_private_resources_v01.py', 'collect_actor_context_ranking_opening_v03.py', 'actor_context_ranking_resource_protocol_v03.py', 'review_actor_context_ranking_resource_baseline_v03.py', 'audit_actor_context_ranking_terminal_resources_v04.py', 'freeze_actor_context_ranking_outputs_v04.py', 'analyze_actor_context_ranking_v01.py', 'review_actor_context_ranking_result_recount_v01.py', 'archive_actor_context_ranking_hf_v01.py', 'build_actor_context_ranking_release_spec_v01.py', 'test_actor_context_ranking_hf_port_detached_v01.py', 'test_actor_context_ranking_release_builder_detached_v01.py')
EVIDENCE=('phase-intake-v01.json', 'retained-source-intake-v01.json', 'evaluation-contract-v01.json', 'training-design-v01.json', 'trainer-source-independent-review-v01.json', 'model-source-independent-review-v01.json', 'actor-context-ranking-model-contract-controls-v01.json', 'model-independent-source-controls-v01.json', 'runner-preparer-source-independent-review-v02.json', 'actor-context-ranking-bootstrap-smoke-controls-v04.json', 'bootstrap-source-independent-review-v02.json', 'actor-context-ranking-harness-author-controls-v02.json', 'actor-context-ranking-current-recipe-independent-controls-v02.json', 'concrete-training-reviewer-source-independent-review-v02.json', 'resource-observation-policy-v02.json', 'resource-bridge-source-independent-review-v02.json', 'sampler-source-independent-review-v01.json', 'resource-collection-source-independent-review-v03.json', 'resource-observer-source-independent-review-v03.json', 'resource-baseline-inputs-v02.json', 'resource-baseline-v01.json', 'resource-source-snapshot-v01.json', 'resource-bootstrap-source-independent-review-v02.json', 'adoption-watchdog-current-source-independent-review-v01.json', 'scheduler-current-source-independent-review-v01.json', 'resource-bootstrap-smoke-source-independent-review-v02.json', 'resource-bootstrap-import-smoke-v01.json', 'resource-bootstrap-import-smoke-v02.json', 'guardian-check-diagnostic-v01.json', 'guardian-config-inspection-v01.json', 'guardian-config-inspection-v02.json', 'resource-collection-v01.json', 'resource-collection-v02.json', 'resource-current-config-amendment-design-v01.json', 'actor-context-ranking-hinge-plan-v01.json', 'actor-context-ranking-hinge-training-review-v01.json', 'actor-context-ranking-terminal-resource-source-independent-review-v02.json', 'actor-context-ranking-terminal-resource-inputs-v01.json', 'actor-context-ranking-hinge-terminal-resource-audit-v01.json', 'runtime-freeze-source-independent-review-v02.json', 'actor-context-ranking-hinge-runtime-review-v01.json', 'actor-context-ranking-output-freeze-v01.json', 'analyzer-port-source-independent-review-v01.json', 'analyzer-source-independent-review-v01.json', 'actor-context-ranking-result-analysis-v01.json', 'result-recount-source-independent-review-v01.json', 'result-recount-inputs-v01.json', 'actor-context-ranking-independent-recount-v01.json', 'actor-context-ranking-result-independent-review-v01.json', 'actor-context-ranking-evaluation-author-controls-v01.json', 'actor-context-ranking-evaluation-author-controls-independent-replay-v01.json', 'hf-helper-port-source-independent-review-v01.json', 'hf-helper-port-derivation-v01.json', 'actor-context-ranking-hf-port-detached-controls-v01.json', 'actor-context-ranking-release-builder-detached-controls-v01.json', 'public-result-summary-v01.json')
sys.dont_write_bytecode=True


def require(value,message):
    if not value:raise ValueError(message)


def private(path):
    path=Path(path)
    return 'private-runtime-snapshots' in path.parts or 'private-root-identity-rebind-v01' in path.parts or 'private-resource-diagnostics' in path.parts or path.name in {'resources-start.json','resources-final.json',
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
    require(FREEZE_PASSED or path in {FREEZE,RUNTIME,PORT_GATE,F/'runtime-freeze-source-independent-review-v02.json'},'full authenticated freeze required before other metadata reads')
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
    own=pin(Path(__file__).resolve());port_pin=pin(PORT_GATE);port=read(PORT_GATE,port_pin)
    require(port['schema']=='actor-context-ranking-Hub-helper-port-source-independent-review/v1' and port['passed'] is True
        and port['findings']==[] and port['builder']==own and port['helper']==pin(F/'archive_actor_context_ranking_hf_v01.py'),
        'Exact independently qualified source-only builder/helper port required')
    for path,item in port['artifacts'].items():pin(path,item)
    freeze_pin=pin(FREEZE);freeze=read(FREEZE,freeze_pin);runtime_pin=pin(RUNTIME);runtime=read(RUNTIME,runtime_pin)
    require(freeze['schema']=='actor-context-ranking-output-freeze/v1' and freeze['all_outputs_frozen'] is True
        and freeze['authorizes_authored_eval_scoring'] is True and freeze['statutory_reference_scoring_authorized'] is False
        and freeze['runtime_review']==runtime_pin and runtime['schema']=='actor-context-ranking-runtime-independent-review/v1'
        and runtime['passed'] is True and runtime['findings']==[] and runtime['outputs']==freeze['results']
        and runtime['output_file_count']==62 and runtime['actual_returned_optimizer_updates']==32,'complete exact frozen science bundle required')
    require(runtime['observer']==pin(F/'freeze_actor_context_ranking_outputs_v04.py')
        and runtime['independent_source_review']==pin(F/'runtime-freeze-source-independent-review-v02.json'),'exact current qualified freezer required')
    review=read(F/'runtime-freeze-source-independent-review-v02.json')
    require(review['passed'] is True and review['findings']==[] and review['observer']==runtime['observer'],'independent current freezer source gate required')
    require(set(freeze['results'])=={str(ATTEMPT/'results'/name) for name in expected_names()},'exact current attempt62 inventory required')
    for path,brief in freeze['results'].items():
        pin(path,brief);require(stat.S_IMODE(Path(path).stat().st_mode)==0o444,'result must already be fully frozen')
    FREEZE_PASSED=True
    plan_pin=pin(F/'actor-context-ranking-hinge-plan-v01.json');require(freeze['plan']==runtime['plan']==plan_pin,'exact attempt01 plan association required')
    plan=read(plan_pin['path'],plan_pin)
    require(plan['attempt_name']==ATTEMPT.name and plan['cell']=='actor-context-ranking-hinge' and len(plan['source_owner_pins'])==40,'current40-module actor-context-ranking execution plan required')
    result_pin=pin(RESULT_REVIEW);result_review=read(RESULT_REVIEW,result_pin)
    require(result_review['schema']=='actor-context-ranking-result-independent-review/v1' and result_review['passed'] is True
        and result_review['findings']==[] and result_review['freeze']==freeze_pin and result_review['runtime_review']==runtime_pin,
        'independent completed result review must join actual freeze/runtime')
    require(type(result_review['scientific_success']) is bool and result_review['default_promotion'] is False,
        'Technical completion is separate from actual scientific success; no default promotion')
    require(result_review['analysis']==pin(F/'actor-context-ranking-result-analysis-v01.json')
        and result_review['independent_recount']==pin(F/'actor-context-ranking-independent-recount-v01.json'),'actual scored analysis and independent recount must be bound')
    analysis=read(result_review['analysis']['path'],result_review['analysis'])
    recount=read(result_review['independent_recount']['path'],result_review['independent_recount'])
    require(analysis['passed'] is True and analysis['findings']==[] and recount['passed'] is True and recount['findings']==[]
        and analysis['scientific_success'] is recount['scientific_success'] is result_review['scientific_success']
        and analysis['default_promotion'] is recount['default_promotion'] is False,
        'Actual analysis/recount scientific disposition must match independently reviewed result')
    baseline_pin=pin(F/'hf-before-file-identities-v01.json');before=read(baseline_pin['path'],baseline_pin)
    helper_path=F/'archive_actor_context_ranking_hf_v01.py';helper_pin=pin(helper_path)
    helper_raw=helper_path.read_bytes()
    require(len(helper_raw)==helper_pin['bytes'] and hashlib.sha256(helper_raw).hexdigest()==helper_pin['sha256'],
        'Exact independently qualified helper source buffer required before raw compilation')
    archive=types.ModuleType('source_only_actor_context_ranking_archive_manifest');archive.__file__=str(helper_path);archive.__package__=''
    exec(compile(helper_raw,str(helper_path),'exec',dont_inherit=True),archive.__dict__)
    archive.qualify_hf_baseline(before)
    trainer_pin=pin(F/'trainer-source-independent-review-v01.json');trainer=read(trainer_pin['path'],trainer_pin)
    require(plan['artifacts'].get(trainer_pin['path'])=={key:trainer_pin[key] for key in ('bytes','sha256')},'Actual trainer source qualification must join frozen plan')
    algorithm=archive.algorithm_sources(plan,trainer)
    require(len(algorithm)==41,'All41 actual admitted algorithm files must be archived')
    files=[];destinations=set()
    def add(path,suffix,expected=None):
        source=pin(path,expected);destination=PREFIX+'/'+suffix
        require(destination not in destinations and 0<source['bytes']<=MAX_FILE_BYTES and '..' not in Path(suffix).parts,'unique bounded explicit public destination required')
        destinations.add(destination);files.append(dict(source=source,destination=destination))
    for path,brief in sorted(freeze['results'].items()):add(path,'cells/actor-context-ranking-hinge/results/'+Path(path).name,brief)
    for name in PUBLIC_RUNTIME:add(ATTEMPT/name,'cells/actor-context-ranking-hinge/runtime/'+name)
    for destination,descriptor in sorted(algorithm.items()):
        require(destination.startswith(PREFIX+'/source/'),'Actual package-relative source hierarchy required')
        add(descriptor['path'],destination[len(PREFIX)+1:],descriptor)
    test_relative='tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_context_ranking_contracts.py'
    test_pin=pin(F/'datasets'/test_relative)
    require(plan['artifacts'].get(test_pin['path'])=={key:test_pin[key] for key in ('bytes','sha256')},'Exact admitted current contract test required')
    add(test_pin['path'],'source/'+test_relative,test_pin)
    for name in RECIPES:add(F/name,'recipes/'+name)
    # Resource snapshot bytes are separate from the41 model algorithm files.
    snapshot=read(F/'resource-source-snapshot-v01.json')
    require(snapshot['schema']=='actor-context-ranking-resource-source-snapshot/v1' and snapshot['file_count']==6
        and len(snapshot['files'])==6 and snapshot['initializers_executed'] is False,'Exact explicit resource snapshot inventory required')
    for relative,item in sorted(snapshot['files'].items()):
        descriptor=item['snapshot']
        require(descriptor['path']==str(F/'resource-source-v01'/relative)
            and plan['artifacts'].get(descriptor['path'])=={key:descriptor[key] for key in ('bytes','sha256')},
            'All six actual resource snapshot source files must be plan-admitted')
        add(descriptor['path'],'recipes/resource-source-v01/'+relative,descriptor)
    for name in EVIDENCE:add(F/name,'evidence/'+name)
    for descriptor in (runtime['training_review'],):
        require(any(row['source']==descriptor for row in files),'Actual concrete training review must be present')
    require(pin(helper_path)==helper_pin,'Archive helper source drift during explicit spec build')
    add(F/'MODEL_CARD_v01.md','README.md')
    total=sum(row['source']['bytes'] for row in files)
    require(len(files)<=500 and total<=200000000,'bounded explicit release payload required')
    for path,expected in list(READS.items()):pin(path,expected)
    manifest=dict(schema='actor-context-ranking-release-manifest/v1',file_count=len(files),payload_bytes=total,files=list(files),
        manifest_self_excluded=True,source_spec_is_complete_inventory_including_manifest=True,
        checkpoint=dict(path=str(ATTEMPT/'results/cell-checkpoint.json'),**freeze['results'][str(ATTEMPT/'results/cell-checkpoint.json')]),
        algorithm_source_count=41,source_owner_count=40,supplemental_raw_source_count=1,
        package_relative_algorithm_source_hierarchy=True,portable_reload_executed=False,portable_reload_qualified=False,
        private_bodies_included=False,scientific_success=result_review['scientific_success'],default_promotion=False,
        source_parent_checkpoint=plan['source_checkpoint'],source_parent_model_state_sha256=plan['source_model_state_sha256'],
        max_payload_file_bytes=MAX_FILE_BYTES,known_immutable_archive_anchor='1622817fd804ff5333fce7dc8d04433e4acef2e4')
    # Publish a self-excluded inventory; the authoritative spec includes its raw copy.
    with MANIFEST.open('x') as out:json.dump(manifest,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
    MANIFEST.chmod(0o444);add(MANIFEST,'release-manifest.json',pin(MANIFEST))
    total=sum(row['source']['bytes'] for row in files)
    require(len(files)<=500 and total<=200000000,'complete payload including manifest exceeds bounds')
    for path,expected in list(READS.items()):pin(path,expected)
    spec=dict(schema='actor-context-ranking-Hub-release-spec/v1',repository=REPO,release_prefix=PREFIX,baseline=baseline_pin,
        freeze=freeze_pin,runtime_review=runtime_pin,result_review=result_pin,files=files)
    with SPEC.open('x') as out:json.dump(spec,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
    SPEC.chmod(0o444)
    print(json.dumps(dict(spec=pin(SPEC),manifest=pin(MANIFEST),file_count=len(files),payload_bytes=total,payload_copies=0,network_calls=0)))

if __name__=='__main__':main()
