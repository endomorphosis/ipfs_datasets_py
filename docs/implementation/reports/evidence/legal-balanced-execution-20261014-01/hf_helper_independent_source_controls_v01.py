"""Detached source-only HF inventory/refusal controls; no SDK, payload, model or network."""
from pathlib import Path
import ast,copy,hashlib,json
F=Path(__file__).resolve().parent
HELPER=F/'archive_conditions_balanced_hf_v01.py'
OLD=F.parent/'legal-conditions-recall-20261014-01/archive_conditions_balanced_hf_v01.py'

def pin(path):
    data=path.read_bytes();return dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
def require(ok,message):
    if not ok:raise ValueError(message)

tree=ast.parse(HELPER.read_bytes());nodes={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
namespace=dict(F=F,Path=Path,REPO='Publicus/legal-ir-autoencoder',PREFIX='releases/20261014-conditions-balanced-v1',MAX_BYTES=200000000,PRIOR_REVISION='702caba2da183f9d98a0ffd12f1240243167aab2',PRIOR_FILES=5269,OWNER_COUNT=39,ALGORITHM_SOURCE_COUNT=40,SUPPLEMENT_RELATIVE='ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py',SUPPLEMENT_BYTES=56776,SUPPLEMENT_SHA256='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731')
selected=['require','brief','private','destination','qualify_hf_baseline','algorithm_sources']
exec(compile(ast.Module(body=[nodes[n] for n in selected],type_ignores=[]),'detached-HF-source-guards','exec'),namespace)
plan=json.loads((F/'conditions-balanced-ce-plan-v01.json').read_bytes())
relocation=json.loads((F/'trainer-relocation-source-independent-review-v01.json').read_bytes())
checks=[]
def test(name,fn,expected=True):
    try:fn();accepted=True
    except (ValueError,KeyError,TypeError):accepted=False
    require(accepted==expected,name);checks.append(dict(name=name,passed=True,expected_acceptance=expected))
algorithm=namespace['algorithm_sources'];sources=algorithm(plan,relocation)
require(len(sources)==40 and all(name.startswith(namespace['PREFIX']+'/source/ipfs_datasets_py/') for name in sources),'40 full package-relative paths')
require(sources[namespace['PREFIX']+'/source/'+namespace['SUPPLEMENT_RELATIVE']]['sha256']==namespace['SUPPLEMENT_SHA256'],'exact attention rawsource hierarchy')
test('actual public plan/relocation metadata yields40 package sources',lambda:algorithm(plan,relocation))
def fixture(mutation):
    p=copy.deepcopy(plan);r=copy.deepcopy(relocation);mutation(p,r);return lambda:algorithm(p,r)
test('missing supplemental rawsource rejected',fixture(lambda p,r:r.update(supplemental_source_pins={})),False)
test('wrong supplemental hash rejected',fixture(lambda p,r:r['supplemental_source_pins'][namespace['SUPPLEMENT_RELATIVE']].update(sha256='0'*64)),False)
test('wrong supplemental bytecount rejected',fixture(lambda p,r:r['supplemental_source_pins'][namespace['SUPPLEMENT_RELATIVE']].update(bytes=1)),False)
owner=next(iter(plan['source_owner_pins']));other=next(k for k in plan['source_owner_pins'] if k!=owner)
test('missing admitted owner rawpin rejected',fixture(lambda p,r:p['artifacts'].pop(p['source_owner_pins'][owner]['path'])),False)
def duplicate(p,r):
    p['source_owner_pins'][owner]=copy.deepcopy(p['source_owner_pins'][other]);r['source_owner_pins']=copy.deepcopy(p['source_owner_pins'])
test('duplicate physical algorithm source rejected',fixture(duplicate),False)
def outside(p,r):
    d=p['source_owner_pins'][owner];d['path']=str(F.parent/'outside_source.py');p['artifacts'][d['path']]={k:d[k] for k in ('bytes','sha256')};r['source_owner_pins']=copy.deepcopy(p['source_owner_pins'])
test('source outside actual F14 package rejected',fixture(outside),False)
def new_adapter(p,r):
    p['source_owner_pins']['unmeasured.future_context']=copy.deepcopy(p['source_owner_pins'][owner]);r['source_owner_pins']=copy.deepcopy(p['source_owner_pins'])
test('new context adapter cannot expand current39module roster',fixture(new_adapter),False)
test('failed relocation review rejected',fixture(lambda p,r:r.update(passed=False)),False)
test('owner rawhash differs from admitted plan rejected',fixture(lambda p,r:p['artifacts'][p['source_owner_pins'][owner]['path']].update(sha256='0'*64)),False)
identity=dict(size=1,blob_id='a'*40,lfs=None)
prior={'.gitattributes':copy.deepcopy(identity),**{f'old/{i}':copy.deepcopy(identity) for i in range(5268)}}
baseline=dict(repo=namespace['REPO'],revision='b'*40,files={**copy.deepcopy(prior),'newer/upstream':copy.deepcopy(identity)},prior_release_revision=namespace['PRIOR_REVISION'],prior_release_files=prior)
qualify=namespace['qualify_hf_baseline']
test('all5269immutable identities plus newer baseline entry accepted',lambda:qualify(baseline))
def bfixture(mutation):
    value=copy.deepcopy(baseline);mutation(value);return lambda:qualify(value)
test('wrong immutable revision rejected',bfixture(lambda v:v.update(prior_release_revision='c'*40)),False)
test('missing old identity rejected despite currentcount5269',bfixture(lambda v:v['files'].pop('old/0')),False)
test('changed old blob identity rejected',bfixture(lambda v:v['files']['old/0'].update(blob_id='d'*40)),False)
test('changed old bytecount rejected',bfixture(lambda v:v['files']['old/0'].update(size=2)),False)
test('incomplete immutable5268map rejected',bfixture(lambda v:v['prior_release_files'].pop('old/0')),False)
test('occupied new release prefix rejected',bfixture(lambda v:v['files'].update({namespace['PREFIX']+'/already-there':identity})),False)
test('private roots-only backup destination rejected',lambda:namespace['destination'](namespace['PREFIX']+'/private-root-identity-rebind-v01/ledger.json'),False)
oldtree=ast.parse(OLD.read_bytes());oldnodes={n.name:n for n in oldtree.body if isinstance(n,ast.FunctionDef)}
dump=lambda n:ast.dump(n,include_attributes=False)
unchanged=sorted(n for n in oldnodes if dump(oldnodes[n])==dump(nodes[n]))
require(set(oldnodes)-set(unchanged)=={'private','baseline','prepare','publish'},'only inventory/baseline/private boundaries changed')
oldloop=next(n for n in ast.walk(oldnodes['publish']) if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, names)')
newloop=next(n for n in ast.walk(nodes['publish']) if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, names)')
require(dump(oldloop)==dump(newloop),'entire perchunk parentCAS/oldidentity/newbyte/unknownoutcome loop preserved')
readback=lambda n:[v for v in n.body if getattr(v,'lineno',0)>=next(x.lineno for x in n.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='target' for t in x.targets))]
require([dump(n) for n in readback(oldnodes['publish'])]==[dump(n) for n in readback(nodes['publish'])],'immutable CLI readback block preserved')
result=dict(schema='conditions-balanced-Hub-helper-independent-source-controls/v1',passed=True,findings=[],helper=pin(HELPER),original=pin(OLD),controls_source=pin(Path(__file__).resolve()),cases=checks,case_count=len(checks),unchanged_function_ASTs=unchanged,whole_perchunk_CAS_preservation_loop_AST_exact=True,whole_immutable_readback_block_AST_exact=True,metadata_fixture_scope='Only actualpublicplan/relocation metadata and synthetic5269identitymap. No resultbody/checkpoint/payload/reference/private/API/network reads or helpermains.',actual_sdk_calls=0,actual_helper_main_calls=0,actual_publication=0,numerical_or_production_imports=0,model_calls=0,checkpoint_JSON_parses=0,private_or_savedscore_or_reference_body_reads=0)
output=F/'hf-helper-independent-source-controls-v01.json'
with output.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
output.chmod(0o444);print(json.dumps(pin(output),sort_keys=True))
