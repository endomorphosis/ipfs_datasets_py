"""Synthetic pure receipt guards; no model/resource imports or actual private reads."""
import ast
import copy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path

F=Path(__file__).resolve().parent
SOURCE=F/'conditions_balanced_resource_protocol_v01.py'
EXPECTED=(22010,'09cfe98e31aecb9be4f24781c6f6d51b0b082402ab1bdd24861c5a7187bbd01a')
BASELINE=Path('/home/barberb/lift_coding/artifacts/legal-conditions-recall-20261014-01/resource-baseline-v01.json')
OUTPUT=F/'resource-predicate-author-controls-v01.json'


def main():
    raw=SOURCE.read_bytes();assert (len(raw),hashlib.sha256(raw).hexdigest())==EXPECTED
    tree=ast.parse(raw);roots=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='HISTORICAL_ROOTS'))
    def require(value,message):
        if not value:raise ValueError(message)
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    names={'full_descriptor','current_root_metadata','check_receipt_custody','qualify_execution_baseline','qualify_capacity_clearance'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names];assert len(nodes)==5
    scope=dict(F=F,CONTRACT=F/'resource-protocol-contract-v01.json',Path=Path,require=require,digest=digest,HISTORICAL_ROOTS=roots)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'exact_f14_pure_resource_receipt_guards','exec'),scope)
    old_raw=BASELINE.read_bytes();assert len(old_raw)==77889 and hashlib.sha256(old_raw).hexdigest()=='9fd03480b85fb3b9a9164a4b4e87b4807bf8c65419a1037edccbb1b04723775f'
    ledger=json.loads(old_raw)['baseline_ledger'];current=copy.deepcopy(roots);current[3]['inode']=99999
    def desc(name):return dict(path=str(F/name),bytes=1,sha256='a'*64)
    proof=desc('root-identity-reconciliation-v01.json')
    summary=dict(root_identity_changed=True,atomic_native_ledger_writes=1,native_strict_read_after_passed=True,all538_record_bodies_unchanged=True,
        record_body_hash_map_sha256='b3c68c6a50aa564532be42134e3d803a2ee25ecf48ff1f55034dcaa6ce032df3',
        full_nonreleased_claim_bytes=44381777216,roots_after=current,cap_bytes=145000000000,cap_changed=False)
    shared=dict(resource_contract=desc('resource-protocol-contract-v01.json'),fresh_metadata_check=desc('guardian-check-v02.json'),
        sampler_source_qualification=desc('sampler-source-independent-review-v01.json'),resource_bridge_source_qualification=desc('resource-bridge-source-independent-review-v01.json'),
        root_identity_reconciliation=proof,root_identity_reconciliation_summary=summary,artifacts={proof['path']:proof})
    baseline=dict(shared,schema='conditions-balanced-resource-baseline/v1',passed=True,findings=[],observer=desc('review_conditions_balanced_resource_baseline_v01.py'),
        source_qualification=desc('resource-observer-source-independent-review-v01.json'),baseline_ledger=ledger,counted_root_metadata=current,
        preadmission_full_claim_census=dict(observed_apparent_bytes=100000000000,outstanding_full_reservations_bytes=44381777216,additional_requested_bytes=200000000,
            charged_bytes=144581777216,minimum_filesystem_free_bytes=140000000000,limit_bytes=145000000000),
        global_endpoint_body_reads=0,resource_API_calls=0,model_calls=0,checkpoint_JSON_parses=0,claim_reconciliations=0,shared_state_modified=False)
    def clearance(observed,free=140000000000):
        native=observed+44381777216+200000000;full=native+200000000;required=44781777216;fits=full<=145000000000 and free>=required
        return dict(shared,schema='conditions-balanced-capacity-clearance/v1',passed=fits,findings=[] if fits else ['synthetic capacity refusal'],
            observer=desc('review_conditions_balanced_capacity_clearance_v01.py'),source_qualification=desc('capacity-clearance-source-independent-review-v01.json'),
            baseline=desc('resource-baseline-v01.json'),input_manifest=desc('capacity-clearance-inputs-v01.json'),ledger_record_count=538,
            record_status_counts={'released':437,'retained':101},prior_record_body_hash_map_sha256=summary['record_body_hash_map_sha256'],all538_prior_record_bodies_unchanged=True,
            observed_apparent_bytes=observed,outstanding_full_reservations_bytes=44381777216,additional_requested_bytes=200000000,future_own_output_bound_bytes=200000000,
            native_charged_bytes=native,full_run_charged_bound_bytes=full,required_filesystem_free_bound_bytes=required,minimum_filesystem_free_bytes=free,limit_bytes=145000000000,
            full_run_apparent_headroom_bytes=145000000000-full,full_run_physical_headroom_bytes=free-required,full_run_capacity_fits=fits,
            native_capacity_fits=native<=145000000000 and free>=44581777216,
            model_started=False,reservation_acquired=False,shared_state_modified=False,admission_guaranteed=False,future_output_bound_is_an_additional_claim=False,
            cap_or_claim_budget_changed=False,resource_API_calls=0,global_endpoint_body_reads=0,checkpoint_JSON_parses=0)
    cases=[]
    def positive(name,fn):fn();cases.append(dict(name=name,passed=True))
    def negative(name,fn):
        try:fn()
        except (ValueError,KeyError,TypeError):cases.append(dict(name=name,passed=True));return
        raise AssertionError(name+' accepted')
    positive('qualified root-proof baseline returns exact538 mapping',lambda:scope['qualify_execution_baseline'](baseline))
    positive('fresh conservative capacity pass authorizes runtime guard only',lambda:scope['qualify_capacity_clearance'](clearance(100000000000),for_training=True))
    positive('truthful capacity refusal may prepare a reviewable plan',lambda:scope['qualify_capacity_clearance'](clearance(101000000000),for_training=False))
    negative('truthful capacity refusal blocks training',lambda:scope['qualify_capacity_clearance'](clearance(101000000000),for_training=True))
    negative('insufficient physical free blocks training',lambda:scope['qualify_capacity_clearance'](clearance(100000000000,44781777215),for_training=True))
    bad=copy.deepcopy(baseline);bad['baseline_ledger']['record_body_hashes'][next(iter(bad['baseline_ledger']['record_body_hashes']))]='b'*64
    negative('changed historical body hash refuses',lambda:scope['qualify_execution_baseline'](bad))
    bad=copy.deepcopy(baseline);bad['counted_root_metadata'][0]['inode']+=1
    negative('changed persistent physical root refuses',lambda:scope['qualify_execution_baseline'](bad))
    bad=copy.deepcopy(baseline);bad['artifacts']={}
    negative('unbound roots reconciliation proof refuses',lambda:scope['qualify_execution_baseline'](bad))
    bad=copy.deepcopy(baseline);bad['source_qualification']=desc('wrong-gate.json')
    negative('wrong concrete baseline source gate path refuses',lambda:scope['qualify_execution_baseline'](bad))
    bad=clearance(100000000000);bad['full_run_charged_bound_bytes']-=1
    negative('arithmetic undercharge refuses',lambda:scope['qualify_capacity_clearance'](bad,for_training=True))
    bad=clearance(100000000000);bad['future_own_output_bound_bytes']=0
    negative('future output bound removal refuses',lambda:scope['qualify_capacity_clearance'](bad,for_training=True))
    bad=clearance(100000000000);bad['model_started']=True
    negative('preexisting model execution claim refuses',lambda:scope['qualify_capacity_clearance'](bad,for_training=True))
    value=dict(schema='conditions-balanced-resource-predicate-author-controls/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        control_count=len(cases),cases=cases,protocol=dict(path=str(SOURCE),bytes=len(raw),sha256=EXPECTED[1]),
        actual_model_calls=0,actual_censuses=0,private_body_reads=0,resource_API_calls=0,shared_mutations=0)
    with OUTPUT.open('x') as out:json.dump(value,out,indent=2,sort_keys=True);out.write('\n');out.flush();os.fsync(out.fileno())
    OUTPUT.chmod(0o444);raw=OUTPUT.read_bytes();print(json.dumps(dict(path=str(OUTPUT),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())))

if __name__=='__main__':main()
