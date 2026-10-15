"""Detached terminal closing-map and exact-command controls; source/synthetic only."""
import ast
import builtins
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

F=Path(__file__).resolve().parent
TERMINAL=F/'audit_actor_refinement_terminal_resources_v01.py'
PROTOCOL=F/'actor_refinement_resource_protocol_v03.py'
OUTPUT=F/'actor-refinement-terminal-independent-controls-v01.json'
def require(value,message):
    if not value:raise ValueError(message)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def pin(path):
    b=path.read_bytes();return dict(path=str(path),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def selected(path,names,ns):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    require({n.name for n in nodes}==set(names) and len(nodes)==len(names),'exact detached set')
    require(not any(isinstance(c,(ast.Import,ast.ImportFrom)) for n in nodes for c in ast.walk(n)),'detached imports refused')
    ns['__builtins__']=dict(vars(builtins),__import__=lambda *a,**k:(_ for _ in ()).throw(ValueError('no imports')))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#detached','exec'),ns)
def main():
    pns=dict(require=require,digest=digest,Counter=Counter);selected(PROTOCOL,{'qualify_ledger'},pns)
    p=SimpleNamespace(require=require,digest=digest,qualify_ledger=pns['qualify_ledger'])
    ns=dict(p=p,F=F,Path=Path,Counter=Counter);selected(TERMINAL,{'qualify_closing','qualify_public_custody'},ns)
    contract=dict(cell='actor-refinement-ce',attempt_name='actor-refinement-20261014-actor-refinement-ce-01',run_root='/synthetic/run',
        global_cap_bytes=145000000000,counted_root_metadata=[dict(path='/synthetic/root',device=1,inode=2)],limits=dict(max_records=4096),required_preserved_claims=[],
        resources=dict(cpu_slots=2,memory_mb=1536,child_process_slots=1,storage_bytes=200000000,child_deadline_seconds=300,admission_timeout_seconds=120,ledger_lock_timeout_seconds=60),guardian=pin(F/'run_scope_guardian_v02.py'))
    old=dict(reservation_id='preserved',status='retained',storage_bytes=17);hashes=dict(preserved=digest(old))
    closing=dict(schema='daemon-resource-reservations-v1',roots=contract['counted_root_metadata'],limit_bytes=145000000000,reservations=dict(preserved=old,own=dict(reservation_id='own',status='released',storage_bytes=200000000),foreign=dict(reservation_id='foreign',status='active',storage_bytes=29),foreign_released=dict(reservation_id='foreign_released',status='released',storage_bytes=43)))
    controls=[]
    def check(label,fn,refuses=False):
        try:fn()
        except (ValueError,KeyError):
            if not refuses:raise
        else:
            if refuses:raise AssertionError(label+' accepted')
        controls.append(dict(name=label,passed=True,expected_refusal=refuses))
    def valid():
        value=ns['qualify_closing'](contract,closing,hashes,'own')
        require((value['record_count'],value['preserved_prior_record_count'],value['full_nonreleased_claim_bytes'],value['additional_concurrent_record_count'],value['additional_concurrent_full_nonreleased_claim_bytes'])==(4,1,46,2,29),'all actual records/fullclaim accounted')
    check('dynamic closing permits active+released foreign records and fully charges active claim',valid)
    for label,mutate in (('preserved body mutation refused',lambda c:c['reservations']['preserved'].update(storage_bytes=18)),('missing prior refused',lambda c:c['reservations'].pop('preserved')),('own nonrelease refused',lambda c:c['reservations']['own'].update(status='retained')),('own budget change refused',lambda c:c['reservations']['own'].update(storage_bytes=199999999)),('typed foreign fullclaim required',lambda c:c['reservations']['foreign'].update(storage_bytes=True)),('changed cap refused',lambda c:c.update(limit_bytes=145000000001))):
        bad=copy.deepcopy(closing);mutate(bad);check(label,lambda b=bad:ns['qualify_closing'](contract,b,hashes,'own'),True)
    check('own historicalID reuse refused',lambda:ns['qualify_closing'](contract,closing,hashes,'preserved'),True)
    plan_pin=dict(path=str(F/'actor-refinement-ce-plan-v01.json'),bytes=1,sha256='a'*64);review_pin=dict(path=str(F/'actor-refinement-ce-training-review-v01.json'),bytes=1,sha256='b'*64)
    producers=dict(runner=pin(F/'run_actor_refinement_v03.py'),guardian=contract['guardian'])
    plan=dict(schema='actor-refinement-cell-plan/v1',cell=contract['cell'],attempt_name=contract['attempt_name'],package_root=str(F/'datasets'),runner_path=producers['runner']['path'],guardian_path=producers['guardian']['path'],artifacts={d['path']:{k:d[k] for k in ('bytes','sha256')} for d in producers.values()})
    review=dict(schema='actor-refinement-concrete-training-independent-review/v1',passed=True,findings=[],phase='training',plan_sha256=plan_pin['sha256'],package_root=plan['package_root'],run_root=contract['run_root'],artifacts={plan_pin['path']:plan_pin},runner_sha256=producers['runner']['sha256'],guardian_sha256=producers['guardian']['sha256'])
    wrappers={'pre-admission.json':dict(plan=plan_pin,review=review_pin,runner=producers['runner'],guardian=producers['guardian']),
        'command.json':dict(argv=['/usr/bin/python3',str(F/'run_actor_refinement_v03.py'),'--plan',plan_pin['path'],'--output',str(Path(contract['run_root'])/contract['attempt_name']/'results')],cwd=plan['package_root'],candidate_pythonpath=plan['package_root'],resources=contract['resources'],no_cuda=True,no_proof_workers=True,model_authority=False)}
    check('exact V03 concrete plan/review/admission/command custody accepted',lambda:ns['qualify_public_custody'](contract,plan,review,plan_pin,review_pin,producers,wrappers))
    for label,mutate in (('wrong output target refused',lambda w:w['command.json']['argv'].__setitem__(-1,'/synthetic/other')),('stale runner refused',lambda w:w['command.json']['argv'].__setitem__(1,str(F/'run_actor_refinement_v02.py'))),('admission plan mismatch refused',lambda w:w['pre-admission.json'].update(plan=dict(plan_pin,sha256='f'*64))),('GPU envelope enable refused',lambda w:w['command.json'].update(no_cuda=False)),('model authority refused',lambda w:w['command.json'].update(model_authority=True))):
        bad=copy.deepcopy(wrappers);mutate(bad);check(label,lambda b=bad:ns['qualify_public_custody'](contract,plan,review,plan_pin,review_pin,producers,b),True)
    value=dict(schema='actor-refinement-terminal-independent-detached-controls/v1',passed=True,findings=[],control_count=len(controls),controls=controls,artifacts={str(path):pin(path) for path in (Path(__file__).resolve(),TERMINAL,PROTOCOL,F/'run_actor_refinement_v03.py')},terminal_main_calls=0,actual_baseline_or_private_body_reads=0,model_calls=0,numerical_imports=0,resource_API_calls=0)
    with OUTPUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))
if __name__=='__main__':main()
