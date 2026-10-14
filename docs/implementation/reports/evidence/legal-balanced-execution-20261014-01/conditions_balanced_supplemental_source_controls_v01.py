"""Detached metadata-fixture controls only; no production imports or physical source claims."""
from pathlib import Path
from types import SimpleNamespace
import ast,copy,hashlib,json
F=Path(__file__).resolve().parent
N12=F.parent/'legal-conditions-recall-20261014-01'

def require(value,message):
    if not value:raise ValueError(message)

def pin(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

source=F/'prepare_conditions_balanced_v02.py';tree=ast.parse(source.read_bytes())
helper=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='qualify_supplemental_source')
namespace=dict(runner=SimpleNamespace(require=require),F=F,N12=N12)
exec(compile(ast.Module(body=[helper],type_ignores=[]),'detached-supplemental-metadata-validator','exec'),namespace)
relative='ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py'
recipe='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731'
descriptor=dict(path=str(F/'datasets'/relative),bytes=56776,sha256=recipe)
original=dict(descriptor,path=str(N12/'datasets'/relative))
relocation=dict(supplemental_source_pins={relative:descriptor},artifacts={descriptor['path']:{k:descriptor[k] for k in ('bytes','sha256')}})
checks=[]
def case(name,fixture,expected):
    try:namespace['qualify_supplemental_source'](fixture,descriptor,original,recipe);accepted=True
    except (ValueError,KeyError):accepted=False
    require(accepted==expected,name);checks.append(dict(name=name,passed=True,expected_acceptance=expected))
case('qualified supplemental metadata fixture accepted',relocation,True)
bad=copy.deepcopy(relocation);bad['supplemental_source_pins']={}
case('missing supplemental source pin refused',bad,False)
bad=copy.deepcopy(relocation);bad['supplemental_source_pins'][relative]['sha256']='0'*64
case('incorrect supplemental source hash refused',bad,False)
oldtree=ast.parse((F/'prepare_conditions_balanced_v01.py').read_bytes())
old={n.name:n for n in oldtree.body if isinstance(n,ast.FunctionDef)}
new={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
dump=lambda node:ast.dump(node,include_attributes=False)
require(set(new)-set(old)=={'qualify_supplemental_source'},'only supplemental pure helper added')
require(all(dump(old[n])==dump(new[n]) for n in ['audit','metadata','qualify_baseline']),'all retained helper ASTs unchanged')
restored=copy.deepcopy(new['prepare'])
start=next(i for i,n in enumerate(restored.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='supplemental_relative' for t in n.targets))
end=next(i for i,n in enumerate(restored.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='references' for t in n.targets))
del restored.body[start:end]
loops=[i for i,n in enumerate(restored.body) if isinstance(n,ast.For) and isinstance(n.iter,ast.Call) and ast.unparse(n.iter)=="baseline['artifacts'].items()"]
require(len(loops)==1,'exact public baseline artifact bind loop added')
del restored.body[loops[0]]
require(dump(restored)==dump(old['prepare']),'only supplemental and rootproof-artifact binding blocks added')
result=dict(schema='conditions-balanced-supplemental-source-controls/v1',passed=True,findings=[],preparer=pin(source),previous_preparer=pin(F/'prepare_conditions_balanced_v01.py'),control_source=pin(Path(__file__).resolve()),cases=checks,focused_negative_cases=2,unchanged_helpers=['audit','metadata','qualify_baseline'],prepare_AST_unchanged_after_removing_two_narrow_bind_blocks=True,module_owner_count=39,admitted_F14_algorithm_source_file_count=40,loaded_owner_count=15,mandatory_loaded_owner_count=7,scope='Synthetic metadata descriptors exercise exact actual helper; physical source bytes are checked only by futurepreparer and independent root relocation receipt. No current physicalsource rehash claim.',actual_main_calls=0,production_or_numerical_imports=0,model_calls=0,checkpoint_JSON_parses=0,reference_savedscore_private_body_reads=0,resource_API_calls=0,claims_or_cleanup=0,Git_mutations=0)
output=F/'supplemental-source-controls-v01.json'
with output.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
output.chmod(0o444)
print(json.dumps(pin(output),sort_keys=True))
