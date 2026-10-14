"""One synthetic equal-huge-logit CE regression, both signs and class weights."""
import ast
import hashlib
import json
import math
from pathlib import Path
import struct

F=Path(__file__).resolve().parent

def pin(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def f32(value):
    return struct.unpack('!f',struct.pack('!f',value))[0]

def expression(path):
    function=next(node for node in ast.parse(path.read_bytes()).body if isinstance(node,ast.FunctionDef) and node.name=='training_metadata')
    node=next(node for node in ast.walk(function) if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='nll' for target in node.targets))
    return compile(ast.Module(body=[node],type_ignores=[]),'<detached-exact-CE-assignment>','exec')

def main():
    old=F/'analyze_conditions_balanced_v01.py';new=F/'analyze_conditions_balanced_v02.py'
    old_ce=expression(old);stable_ce=expression(new);cases=[]
    expected=math.log(2.)
    for sign in [1.,-1.]:
        equal=f32(sign*1e20);logits=[equal,equal]
        assert all(f32(value)==value and math.isfinite(value) for value in logits)
        for target in [0,1]:
            env=dict(math=math,logits=logits,maximum=max(logits),target=target)
            exec(old_ce,env);assert env['nll']==0.,'Original cancellation fixture must reproduce'
            exec(stable_ce,env);assert env['nll']==expected,'Stable exact equal-logit CE must be log2'
            weight=f32(7/8 if target==0 else 7/6)
            weighted=env['nll']*weight
            assert weighted==expected*weight and weighted>0.,'Class weighted CE must preserve log2'
            saved_unweighted=f32(env['nll']);saved_weighted=f32(saved_unweighted*weight)
            assert saved_unweighted==f32(expected)
            assert saved_weighted==f32(f32(expected)*weight)
            cases.append(dict(equal_logit=equal,target=target,class_weight_float32=weight,unweighted_CE=env['nll'],weighted_CE=weighted,saved_unweighted_CE_float32=saved_unweighted,saved_weighted_CE_float32=saved_weighted))
    value=dict(schema='conditions-balanced-CE-cancellation-author-controls/v1',passed=True,findings=[],case='One equal-huge-float32-logit regression with positive/negative signs and absent/present class weights',variants=cases,previous_analyzer=pin(old),analyzer=pin(new),controls_source=pin(Path(__file__).resolve()),old_cancellation_reproduced=True,new_unweighted_equals_math_log2_exactly=True,new_weighted_log2_preserved=True,previous_controls_not_replayed=True,actual_saved_outputs_or_reference_bodies_read=0,model_calls=0,numerical_imports=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0)
    out=F/'CE-cancellation-author-controls-v01.json'
    with out.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')
    out.chmod(0o444);print(json.dumps(pin(out)))

if __name__=='__main__':main()
