"""Pure synthetic complete-run capacity boundaries; never run the observer or inspect resources."""
import ast
from copy import deepcopy
import hashlib,json,os
from pathlib import Path

F=Path(__file__).resolve().parent
OUTPUT=F/'capacity-clearance-author-controls-v01.json'
SOURCE=F/'run_conditions_balanced_v01.py'
OBSERVER=F/'review_conditions_balanced_capacity_clearance_v01.py'

def pin(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def require(value,message):
    if not value:raise ValueError(message)

def main():
    tree=ast.parse(SOURCE.read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_capacity_clearance')
    ns=dict(F=F,CELL='conditions-balanced-ce',ATTEMPT='conditions-balanced-20261014-conditions-balanced-ce-01',require=require)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(SOURCE),'exec'),ns);check=ns['qualify_capacity_clearance']
    cap=145000000000;claims=44381777216;request=200000000
    def fixture(*,delta=0,physical_delta=0):
        observed=cap-claims-2*request+delta;free=claims+2*request+physical_delta
        fits=delta<=0 and physical_delta>=0
        d=dict(schema='conditions-balanced-capacity-clearance/v1',cell=ns['CELL'],attempt_name=ns['ATTEMPT'],passed=fits,
            findings=[] if fits else ['conservative full-run storage headroom refused before any claim or model'],
            ledger_record_count=538,record_status_counts=dict(released=437,retained=101),
            prior_record_body_hash_map_sha256='b3c68c6a50aa564532be42134e3d803a2ee25ecf48ff1f55034dcaa6ce032df3',
            all538_prior_record_bodies_unchanged=True,all_ten_resource_producer_pins_unchanged=True,
            observed_apparent_bytes=observed,outstanding_full_reservations_bytes=claims,additional_requested_bytes=request,
            future_own_output_bound_bytes=request,native_charged_bytes=observed+claims+request,full_run_charged_bound_bytes=observed+claims+2*request,
            limit_bytes=cap,minimum_filesystem_free_bytes=free,required_filesystem_free_bound_bytes=claims+2*request,
            full_run_apparent_headroom_bytes=-delta,full_run_physical_headroom_bytes=physical_delta,
            native_capacity_fits=delta<=request and physical_delta>=-request,full_run_capacity_fits=fits,
            resource_API_calls=0,global_endpoint_body_reads=0,checkpoint_JSON_parses=0)
        for k in ('existing_baseline_modified','new_baseline_created','model_started','reservation_acquired','shared_state_modified','private_record_bodies_published',
            'continuous_coverage_claimed','admission_guaranteed','future_output_bound_is_an_additional_claim','cap_or_claim_budget_changed'):d[k]=False
        for k,name in {'observer':OBSERVER.name,'source_qualification':'capacity-clearance-source-independent-review-v01.json','input_manifest':'capacity-clearance-inputs-v01.json',
            'resource_contract':'resource-protocol-contract-v01.json','baseline':'resource-baseline-v01.json'}.items():d[k]=dict(path=str(F/name),bytes=1,sha256='0'*64)
        d['baseline']=dict(path=str(F/'resource-baseline-v01.json'),bytes=77889,sha256='9fd03480b85fb3b9a9164a4b4e87b4807bf8c65419a1037edccbb1b04723775f')
        return d
    results=[]
    def accept(name,value,training,expected):
        assert check(value,for_training=training) is expected;results.append(dict(name=name,passed=True))
    def reject(name,value,training=True):
        try:check(value,for_training=training)
        except (ValueError,KeyError,TypeError):results.append(dict(name=name,passed=True))
        else:raise AssertionError(name+' accepted')
    accept('exact apparent and physical full-run boundaries pass',fixture(),True,True)
    accept('one byte apparent shortfall preserved as prepared-only refusal',fixture(delta=1),False,False)
    reject('one byte apparent shortfall blocks model',fixture(delta=1))
    accept('one byte physical shortfall preserved as prepared-only refusal',fixture(physical_delta=-1),False,False)
    reject('one byte physical shortfall blocks model',fixture(physical_delta=-1))
    accept('native admission fit does not imply full-run fit',fixture(delta=request),False,False)
    accept('native refusal remains publishable metadata',fixture(delta=request+1),False,False)
    mutations=[('invented passed flag','passed',True,fixture(delta=1)),('smaller claim','additional_requested_bytes',request-1,fixture()),
        ('smaller future bound','future_own_output_bound_bytes',request-1,fixture()),('changed cap','limit_bytes',cap+1,fixture()),
        ('old record count','ledger_record_count',537,fixture()),('wrong fullclaims','outstanding_full_reservations_bytes',claims-1,fixture()),
        ('future bound is never a claim','future_output_bound_is_an_additional_claim',True,fixture()),('shared mutation','shared_state_modified',True,fixture()),
        ('numeric truth refused','native_capacity_fits',1,fixture()),('boolean API count refused','resource_API_calls',False,fixture()),
        ('model already started refused','model_started',True,fixture()),('wrong refusal findings','findings',[],fixture(delta=1)),
        ('fake headroom','full_run_apparent_headroom_bytes',1,fixture()),('foreign prior drift','all538_prior_record_bodies_unchanged',False,fixture())]
    for name,key,value,data in mutations:data[key]=value;reject(name,data,False)
    d=fixture();d['baseline']['sha256']='0'*64;reject('original baseline raw pin conserved',d,False)
    d=fixture();d['observer']['path']=str(F/'unqualified.py');reject('observer path closed',d,False)
    reject('training selector must be boolean',fixture(),1)
    observer=ast.parse(OBSERVER.read_bytes());text=ast.unparse(observer)
    assert 'full_run_charged = native_charged + future_bound' in text and 'required_free = claims + requested + future_bound' in text
    assert "receipt['index'] == 2" in text and "original['private_sample_receipt']" in text
    results.append(dict(name='observer applies future bound and fresh opening2 source guards',passed=True))
    value=dict(schema='conditions-balanced-capacity-clearance-author-controls/v1',passed=True,findings=[],controls=results,control_count=len(results),
        controls_source=pin(Path(__file__).resolve()),runner=pin(SOURCE),observer=pin(OBSERVER),
        actual_resource_or_observer_mains=0,actual_private_or_live_body_reads=0,actual_tree_censuses=0,model_or_encoder_calls=0,checkpoint_JSON_parses=0,resource_API_calls=0)
    assert not OUTPUT.exists()
    with OUTPUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
    OUTPUT.chmod(0o444);print(json.dumps(dict(passed=True,control_count=len(results),receipt=pin(OUTPUT))))

if __name__=='__main__':main()
