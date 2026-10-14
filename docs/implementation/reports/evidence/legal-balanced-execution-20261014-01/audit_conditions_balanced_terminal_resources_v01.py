"""Authenticate copied resource closure for exactly one conditions-balanced attempt; no live endpoints or APIs."""
import ast
from collections import Counter
from datetime import datetime,timezone
import importlib.util
import json,math,os
from pathlib import Path
import sys

F=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('conditions_terminal_protocol',F/'conditions_balanced_resource_protocol_v01.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
INPUTS=F/'conditions-balanced-terminal-resource-inputs-v01.json'
OUTPUT=F/'conditions-balanced-ce-terminal-resource-audit-v01.json'
APPROVAL=F/'conditions-balanced-terminal-resource-source-independent-review-v01.json'
OLD_HELPERS=dict(path=str(F.parent/'legal-actor-features-20261013-01/audit_actor_features_terminal_resources_v03.py'),bytes=48261,sha256='3ac3a0b15434562fbb50e35f8883daad2bc674342d259269643bc9ee2cc0d22f')
WRAPPERS=('child-identity.json','child-exit.json','command.json','guardian-exit.json','pre-admission.json','resource-observations.json',
    'resources-start.json','resources-final.json','lease-binding.json','scheduler-adoption.json','lease-observations.jsonl','owned-group-final.json','group-rss-observations.jsonl','group-rss-summary.json')


def retained_helpers(m,contract):
    path=Path(OLD_HELPERS['path']);m.pin(path,OLD_HELPERS)
    tree=ast.parse(path.read_bytes());names={'qualify_own','qualify_lease','qualify_rss'}
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    p.require(len(nodes)==3,'exact three inherited pure ownclaim/lease/RSS predicates required')
    ns=dict(require=p.require,digest=p.digest,math=math,Counter=Counter,RESOURCES={k:contract['resources'][k] for k in ('storage_bytes','memory_mb','cpu_slots','child_process_slots')},SCHEDULER=p.SCHEDULER)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
    return ns


def qualify_public_custody(contract,plan,review,plan_pin,review_pin,producers,wrappers=None):
    p.require(plan['schema']=='conditions-balanced-cell-plan/v1' and plan['cell']==contract['cell']
        and plan['attempt_name']==contract['attempt_name'] and plan['package_root']==str(F/'datasets')
        and plan['runner_path']==str(F/'run_conditions_balanced_v01.py') and plan['guardian_path']==contract['guardian']['path'],'exact owned plan custody required')
    p.require(review['schema']==contract['review_schema']=='conditions-balanced-concrete-training-independent-review/v1'
        and review['passed'] is True and review['findings']==[] and review['phase']=='training'
        and review['plan_sha256']==plan_pin['sha256'] and review['package_root']==plan['package_root']
        and review['run_root']==contract['run_root'],'exact concrete training review required')
    p.require(review['artifacts'].get(plan_pin['path']) in (plan_pin,{k:plan_pin[k] for k in ('bytes','sha256')}),'review artifacts must authenticate actual plan bytes')
    for label in ('runner','guardian'):
        item=producers[label]
        p.require(item['path']==plan[label+'_path'] and review[label+'_sha256']==item['sha256']
            and plan['artifacts'][item['path']]=={k:item[k] for k in ('bytes','sha256')},'qualified runtime source custody differs')
    if wrappers is None:return
    pre,command=wrappers['pre-admission.json'],wrappers['command.json']
    p.require(pre['plan']==plan_pin and pre['review']==review_pin and pre['runner']==producers['runner'] and pre['guardian']==producers['guardian'],'actual admission custody differs')
    attempt=Path(contract['run_root'])/contract['attempt_name'];argv=command['argv']
    p.require(type(argv) is list and len(argv)==6 and type(argv[0]) is str and Path(argv[0]).is_absolute()
        and argv[1:]==[str(F/'run_conditions_balanced_v01.py'),'--plan',plan_pin['path'],'--output',str(attempt/'results')]
        and command['cwd']==command['candidate_pythonpath']==plan['package_root'] and command['resources']==contract['resources']
        and command['no_cuda'] is True and command['no_proof_workers'] is True and command['model_authority'] is False,'exact guarded child command/envelope required')


def main():
    p.require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free terminal receipt required')
    m=p.Metadata(OUTPUT);sys.addaudithook(m.audit);own=m.pin(Path(__file__).resolve())
    approval=m.read(APPROVAL)
    p.require(approval['schema']=='conditions-balanced-terminal-resource-source-independent-review/v1' and approval['passed'] is True
        and approval['findings']==[] and approval['observer']==own,'exact terminal source qualification required')
    for path,expected in approval['artifacts'].items():m.pin(path,dict(path=path,**{k:expected[k] for k in ('bytes','sha256')}))
    inputs=m.read(INPUTS);baseline_pin=inputs['baseline']
    p.require(p.full_descriptor(baseline_pin,F/'resource-baseline-v01.json'),'actual F14 baseline full descriptor required')
    baseline=m.read(baseline_pin['path'],baseline_pin);p.qualify_execution_baseline(baseline)
    contract_pin=baseline['resource_contract'];contract=p.qualify_contract(m.read(p.CONTRACT,contract_pin))
    rebind,rebind_summary=p.qualify_rebind(m,contract)
    p.require(set(inputs)=={'schema','passed','findings','cell','attempt_name','baseline','plan','training_review','opening_snapshot','terminal_snapshot','metadata_check','runtime_artifacts'}
        and inputs['schema']=='conditions-balanced-terminal-resource-inputs/v1' and inputs['passed'] is True and inputs['findings']==[]
        and inputs['cell']==contract['cell'] and inputs['attempt_name']==contract['attempt_name'] and inputs['baseline']==baseline_pin,'closed root-approved terminal inputs required')
    hashes=baseline['baseline_ledger']['record_body_hashes']
    p.require(baseline['schema']=='conditions-balanced-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and len(hashes)==538 and p.digest(hashes)==contract['prior_record_body_hash_map_sha256']
        and baseline['private_sample_receipt']==inputs['opening_snapshot'] and baseline['fresh_metadata_check']==inputs['metadata_check'],'exact actual opening baseline custody required')
    for path,descriptor in baseline['artifacts'].items():m.pin(path,descriptor)
    plan_pin=inputs['plan'];review_pin=inputs['training_review']
    p.require(plan_pin['path']==str(F/'conditions-balanced-ce-plan-v01.json') and review_pin['path']==str(F/'conditions-balanced-ce-training-review-v01.json'),'exact owned plan/review paths required')
    plan=m.read(plan_pin['path'],plan_pin);review=m.read(review_pin['path'],review_pin)
    producers={}
    for label in ('runner','guardian'):
        path=plan[label+'_path'];producers[label]=m.pin(path,dict(path=path,**plan['artifacts'][path]))
    qualify_public_custody(contract,plan,review,plan_pin,review_pin,producers)
    p.require(plan['artifacts'].get(baseline_pin['path'])=={key:baseline_pin[key] for key in ('bytes','sha256')}
        and plan['artifacts'].get(contract_pin['path'])=={key:contract_pin[key] for key in ('bytes','sha256')},'exact actual baseline and reconciled contract must join admitted plan')
    opening_receipt,opening,opening_scheduler=p.snapshot(m,inputs['opening_snapshot'],'opening',contract)
    p.qualify_ledger(contract,opening,hashes)
    check=m.read(inputs['metadata_check']['path'],inputs['metadata_check']);p.qualify_check(contract,check,opening_receipt,opening_scheduler)
    closing_receipt,closing,closing_scheduler=p.snapshot(m,inputs['terminal_snapshot'],'terminal',contract)
    p.require(type(closing_scheduler['leases']) is dict and type(closing_scheduler['waiters']) is dict
        and closing_scheduler['config']==opening_scheduler['config']==contract['scheduler_config']
        and closing_scheduler['schema_version']==opening_scheduler['schema_version'],'same scheduler/config with typed coexistence occupancy required')
    for path,brief in contract['resource_producer_pins'].items():m.pin(path,dict(path=path,**brief))
    p.require(set(inputs['runtime_artifacts'])==set(WRAPPERS),'exact fourteen own wrappers required')
    attempt=Path(contract['run_root'])/contract['attempt_name'];wrappers={}
    for name in WRAPPERS:
        descriptor=inputs['runtime_artifacts'][name];p.require(descriptor['path']==str(attempt/name),'own saved wrapper path required')
        m.pin(descriptor['path'],descriptor)
        if not name.endswith('.jsonl'):wrappers[name]=m.read(descriptor['path'],descriptor)
    def lines(name):
        descriptor=inputs['runtime_artifacts'][name];path=Path(descriptor['path']);m.pin(path,descriptor)
        def pairs(items):
            result={}
            for key,value in items:p.require(key not in result,'duplicate observation key');result[key]=value
            return result
        def finite(raw):
            value=float(raw);p.require(math.isfinite(value),'nonfinite observation');return value
        values=[json.loads(raw,object_pairs_hook=pairs,parse_float=finite,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite observation'))) for raw in path.read_bytes().splitlines()]
        p.require(0<len(values)<=1024 and all(type(row) is dict for row in values),'bounded saved observation log required');m.pin(path,descriptor);return values
    qualify_public_custody(contract,plan,review,plan_pin,review_pin,producers,wrappers)
    own_id=wrappers['resources-final.json']['owner']['reservation_id'];status=p.qualify_ledger(contract,closing,hashes,own_id=own_id)
    helpers=p.census_helpers(m,contract)
    for row in contract['counted_root_metadata']+[contract['run_root_identity']]:p.require(helpers['_root_identity'](Path(row['path']))==row,'physical resource root identity changed')
    retained=retained_helpers(m,contract);record=closing['reservations'][own_id]
    own_claim=retained['qualify_own'](record,wrappers,helpers['_root_identity'](attempt))
    p.require(own_claim['record_body_sha256']==status['record_body_hashes'][own_id] and closing_receipt['plan']==plan_pin
        and closing_receipt['terminal']==inputs['runtime_artifacts']['guardian-exit.json'],'closing sampler/ownclaim custody differs')
    lease_count=retained['qualify_lease'](record,wrappers,closing_scheduler,lines('lease-observations.jsonl'))
    final=wrappers['resources-final.json'];p.require(final['lease_events']==inputs['runtime_artifacts']['lease-observations.jsonl']
        and final['group_rss_summary']==inputs['runtime_artifacts']['group-rss-summary.json'],'saved final sample pins differ')
    rss=retained['qualify_rss'](wrappers,lines('group-rss-observations.jsonl'),inputs['runtime_artifacts']['group-rss-observations.jsonl'])
    artifacts={path:descriptor for path,descriptor in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts and Path(path).name not in ('resources-start.json','resources-final.json')}
    value=dict(schema='conditions-balanced-terminal-resource-audit/v1',passed=True,findings=[],observer=own,source_qualification=m.pin(APPROVAL),input_manifest=m.pin(INPUTS),
        observed_at_utc=datetime.now(timezone.utc).isoformat(),phase='terminal',cell=contract['cell'],baseline=baseline_pin,resource_contract=contract_pin,
        root_identity_reconciliation=contract['root_identity_reconciliation'],root_identity_reconciliation_summary=rebind_summary,plan=plan_pin,training_review=review_pin,metadata_check=inputs['metadata_check'],
        only_new_own_claim=own_claim,opening_record_count=538,closing_record_count=539,preserved_prior_record_count=538,all_prior_record_bodies_unchanged=True,
        prior_record_body_hash_map_sha256=p.digest(hashes),closing_record_body_hash_map_sha256=status['record_body_hash_map_sha256'],
        closing_record_status_counts=status['record_status_counts'],closing_full_nonreleased_claim_bytes=status['full_nonreleased_claim_bytes'],
        failed_N7_claim_retained_and_fully_charged=True,failed_N8_claim_explicitly_reconciled=True,global_cap_bytes=contract['global_cap_bytes'],
        counted_root_metadata=contract['counted_root_metadata'],run_root_identity=contract['run_root_identity'],scheduler_config_sha256=contract['scheduler_config_sha256'],
        scheduler_lease_count=len(closing_scheduler['leases']),scheduler_waiter_count=len(closing_scheduler['waiters']),
        opening_scheduler_lease_count=len(opening_scheduler['leases']),opening_scheduler_waiter_count=len(opening_scheduler['waiters']),own_scheduler_lease_absent=True,sampled_coexistence=True,
        all_ten_resource_producer_pins_unchanged=True,saved_lease_observations=lease_count,private_sample_receipts=dict(opening=inputs['opening_snapshot'],terminal=inputs['terminal_snapshot']),
        private_endpoint_pin_descriptors=[opening_receipt['ledger'],opening_receipt['scheduler'],closing_receipt['ledger'],closing_receipt['scheduler']],
        private_owned_resource_wrapper_pin_descriptors={name:inputs['runtime_artifacts'][name] for name in ('resources-start.json','resources-final.json')},
        private_record_bodies_published=False,individual_prior_records_published=False,sampled_coverage_only=True,continuous_coverage_claimed=False,absolute_peak_measured=False,kernel_hard_memory_cap=False,
        model_or_encoder_calls_by_reviewer=0,checkpoint_JSON_parses_by_reviewer=0,reference_packet_reads_by_reviewer=0,resource_API_calls_by_reviewer=0,global_endpoint_body_reads_by_reviewer=0,
        shared_state_modified_by_reviewer=False,shared_tree_censuses_by_reviewer=0,semantic_qualification=False,artifacts=artifacts,retained_pure_helpers=OLD_HELPERS,**rss)
    print(m.write(value))

if __name__=='__main__':main()
