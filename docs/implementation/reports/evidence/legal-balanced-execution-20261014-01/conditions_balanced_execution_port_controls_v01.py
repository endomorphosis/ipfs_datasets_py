from pathlib import Path
import ast,copy,hashlib,json
from types import SimpleNamespace
F=Path('/home/barberb/lift_coding/artifacts/legal-balanced-execution-20261014-01')
OLD=F.parent/'legal-conditions-recall-20261014-01'

def require(v,m):
 if not v:raise ValueError(m)
def pin_file(p):
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def funcs(p):return {n.name:n for n in ast.parse(p.read_bytes()).body if isinstance(n,ast.FunctionDef)}
def normalized(n):return ast.dump(n,include_attributes=False)
new=funcs(F/'run_conditions_balanced_v01.py');old=funcs(OLD/'run_conditions_balanced_v01.py')
unchanged=sorted(n for n in old if n in new and normalized(old[n])==normalized(new[n]))
changed=sorted(n for n in old if n not in unchanged)
require(changed==['main','qualify_capacity_clearance','validate_plan'],'Only exact custody-boundary runner functions may change')
require(set(new)-set(old)=={'resource_protocol'},'Only resource protocol loader added')
require((F/'conditions_balanced_bootstrap_smoke_controls_v01.py').read_bytes()==(OLD/'conditions_balanced_bootstrap_smoke_controls_v01.py').read_bytes(),'Exact production bootstrap smoke retained')
require((F/'freeze_conditions_balanced_outputs_v01.py').read_bytes()==(F.parent/'legal-storage-continuation-20261014-01/freeze_conditions_balanced_outputs_draft_v01.py').read_bytes(),'Exact reviewed freezer algorithm retained')
for name in ['training-design-v01.json','evaluation-contract-v01.json']:
 require((F/name).read_bytes()==(OLD/name).read_bytes(),'Exact scientific contract bytes retained')
main=new['main'];outindex=next(i for i,n in enumerate(main.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='out' for t in n.targets))
prefix=ast.FunctionDef(name='prefix_only',args=copy.deepcopy(main.args),body=copy.deepcopy(main.body[:outindex]),decorator_list=[])
ast.fix_missing_locations(prefix)
protocol=str(F/'conditions_balanced_resource_protocol_v01.py')
def fakepin(path,label):return {'path':path,'bytes':123,'sha256':hashlib.sha256(label.encode()).hexdigest()}
base=fakepin(str(F/'resource-baseline-v01.json'),'baseline');clear=fakepin(str(F/'capacity-clearance-v01.json'),'clearance')
bgate=fakepin(str(F/'resource-observer-source-independent-review-v01.json'),'baselinegate');cgate=fakepin(str(F/'capacity-clearance-source-independent-review-v01.json'),'clearancegate')
bobserver=fakepin(str(F/'review_conditions_balanced_resource_baseline_v01.py'),'baselineobserver');cobserver=fakepin(str(F/'review_conditions_balanced_capacity_clearance_v01.py'),'clearanceobserver')
extra=fakepin(str(F/'root-rebind-proof.json'),'rootrebind')
proto=fakepin(protocol,'protocol')
brief=lambda p:{k:p[k] for k in ('bytes','sha256')}
plan={'artifacts':{p['path']:brief(p) for p in [base,clear,bgate,cgate,bobserver,cobserver,extra,proto]}}
baseline={'source_qualification':bgate,'observer':bobserver}
clearance={'baseline':base,'source_qualification':cgate,'observer':cobserver}
bapproval={'schema':'conditions-balanced-resource-observer-source-independent-review/v1','passed':True,'findings':[],'observer':bobserver,'artifacts':{extra['path']:brief(extra)}}
capproval={'schema':'conditions-balanced-capacity-clearance-source-independent-review/v1','passed':True,'findings':[],'observer':cobserver,'artifacts':{extra['path']:brief(extra)}}
seed={'plan':plan,'baseline':baseline,'clearance':clearance,'bgate':bapproval,'cgate':capproval,'pins':{p['path']:p for p in [base,clear,bgate,cgate,bobserver,cobserver,extra,proto]},'capacity':True}
checks=[]
def run(data):
 events=[]
 def read(path,expected=None):
  path=str(path)
  maps={'synthetic-plan':data['plan'],base['path']:data['baseline'],clear['path']:data['clearance'],bgate['path']:data['bgate'],cgate['path']:data['cgate']}
  if expected is not None:require(data['pins'][path]==expected,'Synthetic exact metadata descriptor refusal')
  return copy.deepcopy(maps[path])
 def bqual(value):events.append('qualified_baseline');return {}
 def cqual(value,*,for_training):
  require(for_training is True,'Real execution must require training capacity')
  require(data['capacity'],'Synthetic REFUSED capacity')
  events.append('capacity_PASS');return True
 ns={'time':SimpleNamespace(monotonic=lambda:0),'read':read,'validate_plan':lambda value:events.append('closed_plan_validator_called'),'F':F,'Path':Path,'pin':lambda path:copy.deepcopy(data['pins'][str(path)]),'require':require,'resource_protocol':lambda:SimpleNamespace(qualify_execution_baseline=bqual,qualify_capacity_clearance=cqual)}
 exec(compile(ast.Module(body=[copy.deepcopy(new['qualify_capacity_clearance']),prefix],type_ignores=[]),'detached-f14-prefix-only','exec'),ns)
 ns['prefix_only'](SimpleNamespace(plan='synthetic-plan'))
 require(events==['closed_plan_validator_called','qualified_baseline','capacity_PASS'],'Exact pre-model custody order')
 return events

def test(name,mutate=None,accept=True):
 data=copy.deepcopy(seed)
 if mutate:mutate(data)
 try:run(data);ok=True
 except (ValueError,KeyError):ok=False
 require(ok==accept,name)
 checks.append({'name':name,'passed':True,'expected_acceptance':accept})
test('synthetic exact baseline/clearance/gate/protocol closure reaches capacity gate')
test('refused capacity cannot proceed',lambda d:d.update(capacity=False),False)
test('baseline qualification wrong schema rejected',lambda d:d['bgate'].update(schema='wrong/v1'),False)
test('clearance qualification wrong observer rejected',lambda d:d['cgate'].update(observer=bobserver),False)
test('unadmitted baseline descriptor rejected',lambda d:d['plan']['artifacts'].pop(base['path']),False)
test('unadmitted root rebind sourceproof rejected',lambda d:d['plan']['artifacts'].pop(extra['path']),False)
test('resource protocol rawpin drift rejected before loading',lambda d:d['pins'][protocol].update(sha256='0'*64),False)
test('baseline observer rawsource drift rejected',lambda d:d['pins'][bobserver['path']].update(sha256='0'*64),False)
test('failed baseline independent gate rejected',lambda d:d['bgate'].update(passed=False),False)
allcalls=[n for n in ast.walk(main) if isinstance(n,ast.Call)]
cap=min(n.lineno for n in allcalls if isinstance(n.func,ast.Name) and n.func.id=='qualify_capacity_clearance')
model=min(n.lineno for n in allcalls if isinstance(n.func,ast.Attribute) and n.func.attr in ['mkdir','bootstrap','build_checkpoint'])
require(cap<model,'Full capacity gate precedes all producer/model/output work')
checks.append({'name':'capacity gate statically precedes output mkdir/bootstrap/build_checkpoint','passed':True})
result={'schema':'conditions-balanced-execution-port-controls/v1','passed':True,'findings':[],'cases':checks,'case_count':len(checks),'unchanged_runner_function_ASTs':unchanged,'changed_runner_functions':changed,'smoke_byte_identical':True,'reviewed_freezer_byte_identical':True,'scientific_design_and_eval_contract_byte_identical':True,'scope':'Only actual runner AST prefix through capacity gate is detached; synthetic public metadata/fake resource validators. No production main/import, actual capacity authorization, or model execution. Unchanged weighted/model/inference/trace controls not repeated.','sources':{str(F/n):pin_file(F/n) for n in ['run_conditions_balanced_v01.py','prepare_conditions_balanced_v01.py','conditions_balanced_bootstrap_smoke_controls_v01.py','freeze_conditions_balanced_outputs_v01.py']},'actual_model_calls':0,'numerical_imports':0,'checkpoint_JSON_parses':0,'reference_savedscore_or_private_body_reads':0,'resource_API_calls':0,'claim_or_cleanup_calls':0}
out=F/'execution-port-controls-v01.json'
with out.open('x') as s:json.dump(result,s,sort_keys=True,indent=2);s.write('\n')
out.chmod(0o444)
print(json.dumps(pin_file(out),sort_keys=True))
