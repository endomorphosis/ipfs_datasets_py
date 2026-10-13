"""Execute real publisher main to its first source-owner check using inert IO.

A sentinel stops at that helper, before SDK import or any network operation.
The historical lexical-local defect must be reproduced, and reintroducing the
same local assignment into the repaired AST must be refused.
"""
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace

F=Path(__file__).resolve().parent
OLD=F/'publish_hf_temporal_adapter_release_v01.py'
NEW=F/'publish_hf_temporal_adapter_release_v02.py'
OUT=F/'hf-publisher-scope-controls-v01.json'

class OwnerReached(Exception):
    pass

def identity(path):
    return dict(path=str(path),bytes=7,sha256='a'*64)

def namespace(path):
    raw=path.read_bytes();tree=ast.parse(raw)
    scope=dict(__file__=str(path),Path=Path,re=re,hashlib=hashlib,json=json,math=math)
    selected=[node for node in tree.body if isinstance(node,(ast.Assign,ast.FunctionDef))]
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path)+'#inert-main','exec'),scope)
    return scope,tree,dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def probe(path,reintroduce_local=False):
    scope,tree,pin=namespace(path)
    if reintroduce_local:
        main=copy.deepcopy(next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main'))
        main.body.append(ast.Assign(targets=[ast.Name(id='owned',ctx=ast.Store())],value=ast.Dict(keys=[],values=[])))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[main],type_ignores=[])),str(path)+'#synthetic-local-regression','exec'),scope)
    # Derive the required receipt key set from the actual closed-schema check.
    # This keeps fixtures inert and lets the executable probe reach the first
    # owner-helper call without duplicating or reading actual preparation data.
    main=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    receipt_keys=None
    for node in ast.walk(main):
        if isinstance(node,ast.Compare) and isinstance(node.left,ast.Call) and isinstance(node.left.func,ast.Name) and node.left.func.id=='set' and len(node.left.args)==1 and isinstance(node.left.args[0],ast.Name) and node.left.args[0].id=='receipt' and len(node.comparators)==1 and isinstance(node.comparators[0],ast.Set):
            receipt_keys=ast.literal_eval(node.comparators[0])
    assert receipt_keys is not None
    review_path=F/'synthetic-concrete-review.json'
    runtime_path=F/'synthetic-runtime-review.json'
    receipt_expression=next(node.value for node in ast.walk(main) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='receipt_path' for t in node.targets) and isinstance(node.value,ast.BinOp))
    receipt_path=F/ast.literal_eval(receipt_expression.right)
    receipt={key:None for key in receipt_keys}
    receipt.update(schema='temporal-adapter-Hub-preparation/v1',default_promotion=False,additive_only=True,runtime_review=identity(runtime_path),source_preparer=identity(F/'prepare_hf_temporal_adapter_release_v02.py'),source_publisher=identity(path))
    review=dict(schema='temporal-adapter-Hub-publication-independent-review/v1',passed=True,findings=[],repository=scope['REPO'],release_prefix=scope['PREFIX'],expected_parent_revision='b'*40,payload_files=1,payload_bytes=7,artifacts={str(receipt_path):identity(receipt_path),str(runtime_path):identity(runtime_path)},scope={},limitations=[])
    runtime=dict(schema='temporal-adapter-runtime-independent-review/v1',passed=True,findings=[],artifacts={})
    bodies={str(review_path):review,str(receipt_path):receipt,str(runtime_path):runtime}
    calls=[]
    scope['pin']=lambda path:identity(path)
    scope['read']=lambda path,expected=None:copy.deepcopy(bodies[str(path)])
    scope['approved_map']=lambda review:{}
    def owner(*args):
        calls.append(args)
        raise OwnerReached('Source owner helper reached; stopped before SDK import')
    scope['owned']=owner
    try:
        scope['main'](SimpleNamespace(review=str(review_path)))
    except OwnerReached:
        assert len(calls)==1
        return 'global_owner_helper_reached',pin
    except UnboundLocalError as error:
        assert not calls and 'owned' in str(error)
        return 'lexical_local_owner_collision',pin
    raise AssertionError('Probe must stop before SDK import')

def main():
    assert not OUT.exists()
    old,old_pin=probe(OLD);assert old=='lexical_local_owner_collision'
    new,new_pin=probe(NEW);assert new=='global_owner_helper_reached'
    regression,regression_pin=probe(NEW,True);assert regression=='lexical_local_owner_collision' and regression_pin==new_pin
    for path,expected in ((OLD,old_pin),(NEW,new_pin)):
        raw=path.read_bytes();assert len(raw)==expected['bytes'] and hashlib.sha256(raw).hexdigest()==expected['sha256']
    result=dict(schema='temporal-adapter-Hub-publisher-scope-independent-controls/v1',passed=True,findings=[],historical_publisher=old_pin,repaired_publisher=new_pin,positive_controls=['Real repaired main resolves global source-owner helper before SDK import'],refusal_controls=['Historical main reproduces UnboundLocalError before helper call','Synthetic reintroduced local owned assignment reproduces UnboundLocalError'],positive_count=1,refusal_count=2,SDK_imports=0,network_calls=0,model_calls=0,resource_API_calls=0,checkpoint_JSON_parses=0,private_body_reads=0,actual_publication_main_executed=False,inert_real_main_prefix_executed=True)
    with OUT.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
    OUT.chmod(0o444);raw=OUT.read_bytes();print(json.dumps(dict(path=str(OUT),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),passed=True)))

if __name__=='__main__':main()
