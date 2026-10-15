"""Review only a concrete F14 plan and actual capacity PASS; no model or resource execution."""
import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime,timezone

F=Path(__file__).resolve().parent
OUTPUT=F/'conditions-balanced-ce-training-review-v01.json'
PLAN=F/'conditions-balanced-ce-plan-v01.json'
RUN_ROOT=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
ATTEMPT='conditions-balanced-20261014-conditions-balanced-ce-01'
OBSERVED={}
sys.dont_write_bytecode=True

def require(value,message):
    if not value:raise ValueError(message)

def audit(event,args):
    if event=='import' and args[0].split('.')[0] in {'torch','numpy','ipfs_datasets_py','transformers','sentence_transformers','huggingface_hub'}:
        raise ValueError('Production/numerical/SDK imports prohibited')
    if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in {'os.system','os.fork','fcntl.flock','os.mkdir','os.remove','os.rmdir','os.rename','os.replace','os.unlink','os.kill','os.killpg'}:
        raise ValueError('Process/network/resource/shared operations prohibited')
    if event=='open' and isinstance(args[0],(str,bytes)):
        path=Path(os.fsdecode(args[0])).absolute();mode,flags=args[1:3]
        require('private-runtime-snapshots' not in path.parts and path.name not in {'disk-reservations.json','resources-start.json','resources-final.json','ipfs-datasets-resource-scheduler-1000.json'},'Private/global body reads prohibited')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        require(not writing or path==OUTPUT and bool(flags&os.O_EXCL),'Only exclusive concrete review write allowed')
    if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
        require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'Only own review freeze allowed')

def pin(path,expected=None):
    path=Path(path);require(path.is_absolute() and path.resolve()==path and path.is_file() and not path.is_symlink(),'Physical public file required')
    before=path.stat();size=0;sha=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):size+=len(block);sha.update(block)
    after=path.stat();require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) and size==before.st_size,'Raw input drift')
    value=dict(path=str(path),bytes=size,sha256=sha.hexdigest())
    require(expected is None or all(value[k]==expected[k] for k in ('bytes','sha256')) and ('path' not in expected or value['path']==expected['path']),'Exact expected descriptor differs')
    require(str(path) not in OBSERVED or OBSERVED[str(path)]==value,'Previously consumed raw input drift');OBSERVED[str(path)]=value
    return value

def read(path,expected=None):
    path=Path(path);require('checkpoint' not in path.name and 'reference-packet' not in path.name and 'results' not in path.parts,'Checkpoint/reference/result JSON parsing prohibited')
    captured=pin(path,expected);require(captured['bytes']<=16*1024*1024,'Bounded public metadata required')
    def pairs(items):
        result={}
        for k,v in items:require(k not in result,'Duplicate JSON key');result[k]=v
        return result
    value=json.loads(path.read_bytes(),object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON constant')))
    pin(path,captured);return value

def main(args):
    require(not os.path.lexists(OUTPUT),'Exclusive new concrete review required')
    sys.addaudithook(audit)
    plan_pin=pin(PLAN,dict(path=str(PLAN),bytes=args.plan_bytes,sha256=args.plan_sha256));plan=read(PLAN,plan_pin)
    for path,descriptor in plan['artifacts'].items():pin(path,descriptor)
    runner_pin=pin(F/'run_conditions_balanced_v01.py');guardian_pin=pin(F/'run_scope_guardian_v02.py');protocol_pin=pin(F/'conditions_balanced_resource_protocol_v01.py')
    require(all(plan['artifacts'].get(item['path'])=={k:item[k] for k in ('bytes','sha256')} for item in (runner_pin,guardian_pin,protocol_pin)),'Actual producers must join admitted plan')
    spec=importlib.util.spec_from_file_location('qualified_balanced_plan_runner',runner_pin['path']);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    runner.validate_plan(plan)
    clearance_pin=pin(F/'capacity-clearance-v01.json',plan['artifacts'][str(F/'capacity-clearance-v01.json')]);clearance=read(clearance_pin['path'],clearance_pin)
    baseline_pin=pin(clearance['baseline']['path'],clearance['baseline']);baseline=read(baseline_pin['path'],baseline_pin)
    runner.resource_protocol().qualify_execution_baseline(baseline);runner.qualify_capacity_clearance(clearance,for_training=True)
    require(plan['artifacts'][baseline_pin['path']]=={k:baseline_pin[k] for k in ('bytes','sha256')},'Actual baseline must join plan')
    for receipt,schema in ((baseline,'conditions-balanced-resource-observer-source-independent-review/v1'),(clearance,'conditions-balanced-capacity-clearance-source-independent-review/v1')):
        gate=read(receipt['source_qualification']['path'],receipt['source_qualification'])
        require(gate['schema']==schema and gate['passed'] is True and gate['findings']==[] and gate['observer']==receipt['observer'],'Actual qualified baseline/clearance observer custody required')
        for path,descriptor in receipt['artifacts'].items():require(plan['artifacts'].get(path)=={k:descriptor[k] for k in ('bytes','sha256')},'Full public resource proof must join plan')
    peer=read(F/'runner-preparer-source-independent-review-v01.json')
    require(peer['schema']=='conditions-balanced-runner-preparer-source-independent-review/v1' and peer['passed'] is True and peer['findings']==[],'Independent actual recipe qualification required')
    for name in ('run_conditions_balanced_v01.py','prepare_conditions_balanced_v02.py','conditions_balanced_bootstrap_smoke_controls_v01.py','conditions-balanced-bootstrap-smoke-controls-v01.json'):
        value=pin(F/name);require(peer['artifacts'].get(value['path']) in (value,{k:value[k] for k in ('bytes','sha256')}),'Recipe peer must bind actual sources/smoke')
    relocation=read(F/'trainer-relocation-source-independent-review-v01.json')
    require(relocation['schema']=='conditions-balanced-trainer-relocation-source-independent-review/v1' and relocation['passed'] is True and relocation['findings']==[] and relocation['source_owner_pins']==plan['source_owner_pins'],'Qualified exact39 relocated source modules required')
    supplemental=relocation['supplemental_source_pins'];relative='ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py'
    require(set(supplemental)=={relative} and supplemental[relative]['sha256']=='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731','Exact extra raw implementation source required')
    sources=list(plan['source_owner_pins'].values())+list(supplemental.values())
    require(len(sources)==len({v['path'] for v in sources})==40 and all(plan['artifacts'].get(v['path'])=={k:v[k] for k in ('bytes','sha256')} for v in sources),'All40 raw algorithm sources must be admitted')
    require(plan['training_manifest_sha256']=='afa0deeebf4052831883c046104a8808342b67a7c8dc2e58de2f9208a9287c34' and plan['evaluation_contract']['sha256']=='cdd58af7b0b0abbb5e8523e23682a53f26ef28bf30e4b0f9090c4a88aeacf837' and plan['proposal']['sha256']=='a64ba710a1f02dbad996eec355ef42e9368846b2b4ba9bdb735d1b5ae6f60f11','Fixed training/science contract differs')
    require(not os.path.lexists(RUN_ROOT/ATTEMPT),'Never-used attempt directory must remain absent')
    pin(Path(__file__).resolve())
    for path,descriptor in list(OBSERVED.items()):pin(path,descriptor)
    result=dict(schema='conditions-balanced-concrete-training-independent-review/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),phase='training',package_root=plan['package_root'],run_root=str(RUN_ROOT),plan_sha256=plan_pin['sha256'],runner_sha256=runner_pin['sha256'],guardian_sha256=guardian_pin['sha256'],plan=plan_pin,capacity_clearance=clearance_pin,baseline=baseline_pin,source_owner_count=39,raw_algorithm_source_file_count=40,loaded_source_owners=15,mandatory_loaded_source_owners=7,training_budget=dict(updates=32,batch_size=12,seed=1729,source_row_occurrences=384,fresh_Adam=True,only_conditions_balanced_CE=True,ranking_enabled=False),source_checks=['Qualified fixed F12 model/test/design and exact N10 donor; source-only physical relocation and extra attention recipe rawsource admitted.','Actual qualified roots-only migration provenance, exact538record map/fullclaims145B cap and fresh full-run capacityPASS.','One never-used attempt;1280inference+32training=1312forwards/1664occurrences;6copiedparentfiles240rows=0calls.','All632initial/protectedheads;62output freeze precedes references/scoring; stableCE analyzer and strict scientific acceptance unchanged.'],artifacts={path:{k:value[k] for k in ('bytes','sha256')} for path,value in OBSERVED.items()},models_created_by_reviewer=0,optimizer_updates_by_reviewer=0,checkpoint_JSON_parses_by_reviewer=0,private_body_reads_by_reviewer=0,resource_API_calls_by_reviewer=0,default_promotion=False,scientific_success=None)
    with OUTPUT.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT),sort_keys=True))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan-bytes',required=True,type=int);parser.add_argument('--plan-sha256',required=True)
    main(parser.parse_args())
