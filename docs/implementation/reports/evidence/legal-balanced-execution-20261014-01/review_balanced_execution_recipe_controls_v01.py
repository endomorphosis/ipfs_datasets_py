"""Independent detached entry-guard and supplemental-source checks; no actual producer mains."""
import ast
import copy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

F=Path(__file__).resolve().parent
N12=F.parent/'legal-conditions-recall-20261014-01'
OUTPUT=F/'runner-preparer-independent-source-controls-v01.json'


def require(value,message):
    if not value:raise ValueError(message)


def main():
    paths=[F/'run_conditions_balanced_v01.py',F/'prepare_conditions_balanced_v02.py']
    raw={path:path.read_bytes() for path in paths};trees={path:ast.parse(data) for path,data in raw.items()}
    runner_tree=trees[paths[0]];prep_tree=trees[paths[1]]
    production=next(n for n in runner_tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    stop=next(i for i,node in enumerate(production.body) if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='out' for target in node.targets))
    prefix=copy.deepcopy(production);prefix.body=copy.deepcopy(production.body[:stop]);prefix.name='detached_entry_guard'
    wrapper=copy.deepcopy(next(n for n in runner_tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_capacity_clearance'))
    code=compile(ast.fix_missing_locations(ast.Module(body=[prefix,wrapper],type_ignores=[])),'exact_detached_F14_entry_guard','exec')
    def descriptor(name):return dict(path=str(F/name),bytes=1,sha256='a'*64)
    baseline=descriptor('resource-baseline-v01.json');clearance=descriptor('capacity-clearance-v01.json');protocol=descriptor('conditions_balanced_resource_protocol_v01.py')
    bg=descriptor('resource-observer-source-independent-review-v01.json');bo=descriptor('review_conditions_balanced_resource_baseline_v01.py')
    cg=descriptor('capacity-clearance-source-independent-review-v01.json');co=descriptor('review_conditions_balanced_capacity_clearance_v01.py')
    proof=descriptor('root-identity-reconciliation-v01.json');plan_path=F/'synthetic-plan.json'
    docs={str(plan_path):{'artifacts':{item['path']:{key:item[key] for key in ('bytes','sha256')} for item in (baseline,clearance,protocol,bg,bo,cg,co,proof)}},
        baseline['path']:dict(passed=True,source_qualification=bg,observer=bo),clearance['path']:dict(passed=True,baseline=baseline,source_qualification=cg,observer=co),
        bg['path']:dict(schema='conditions-balanced-resource-observer-source-independent-review/v1',passed=True,findings=[],observer=bo,artifacts={proof['path']:proof}),
        cg['path']:dict(schema='conditions-balanced-capacity-clearance-source-independent-review/v1',passed=True,findings=[],observer=co,artifacts={proof['path']:proof})}
    pins={item['path']:item for item in (baseline,clearance,protocol,bg,bo,cg,co,proof)}
    cases=[]
    def exercise(name,change=None,accept=True,expect_loader=None):
        values=copy.deepcopy(docs);identities=copy.deepcopy(pins);calls=[]
        if change:change(values,identities)
        class FakeProtocol:
            def qualify_execution_baseline(self,value):calls.append('baseline');require(value['passed'],'synthetic baseline refusal')
            def qualify_capacity_clearance(self,value,*,for_training):
                calls.append(('capacity',for_training));require(for_training is True and value['passed'],'synthetic capacity refusal')
        def load():calls.append('loader');return FakeProtocol()
        def read(path,expected=None):
            path=str(path)
            if expected is not None:require(identities[path]==expected,'synthetic raw read differs')
            return values[path]
        ns=dict(F=F,time=SimpleNamespace(monotonic=lambda:0),Path=Path,require=require,read=read,pin=lambda path:identities[str(path)],
            validate_plan=lambda value:None,resource_protocol=load)
        exec(code,ns)
        try:ns['detached_entry_guard'](SimpleNamespace(plan=str(plan_path)))
        except (ValueError,KeyError,TypeError):require(not accept,name+' unexpectedly refused')
        else:
            require(accept,name+' unexpectedly accepted');require(calls[-1]==('capacity',True),'training capacity flag was not true')
        if expect_loader is not None:require(calls.count('loader')==expect_loader,'protocol imported before raw source fence')
        cases.append(dict(name=name,passed=True))
    exercise('exact admitted observer/source/proof closure reaches training capacity guard')
    exercise('false clearance refuses before output creation',lambda d,p:d[clearance['path']].update(passed=False),False)
    exercise('false baseline refuses before output creation',lambda d,p:d[baseline['path']].update(passed=False),False)
    exercise('wrong source qualification schema refuses',lambda d,p:d[bg['path']].update(schema='wrong'),False)
    exercise('wrong clearance qualified observer refuses',lambda d,p:d[cg['path']].update(observer=bo),False)
    exercise('failed independent source gate refuses',lambda d,p:d[cg['path']].update(passed=False),False)
    exercise('missing admitted baseline refuses',lambda d,p:d[str(plan_path)]['artifacts'].pop(baseline['path']),False)
    exercise('missing admitted root-rebind proof refuses',lambda d,p:d[str(plan_path)]['artifacts'].pop(proof['path']),False)
    exercise('raw protocol drift refuses before loader',lambda d,p:p[protocol['path']].update(sha256='b'*64),False,0)
    exercise('raw qualified observer drift refuses',lambda d,p:p[co['path']].update(sha256='b'*64),False)
    supplemental=next(n for n in prep_tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_supplemental_source')
    ns=dict(F=F,N12=N12,runner=SimpleNamespace(require=require));exec(compile(ast.Module(body=[supplemental],type_ignores=[]),'exact_supplemental_source_guard','exec'),ns)
    relative='ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py'
    new=dict(path=str(F/'datasets'/relative),bytes=56776,sha256='c'*64);old=dict(new,path=str(N12/'datasets'/relative))
    relocation=dict(supplemental_source_pins={relative:new},artifacts={new['path']:new})
    def extra(name,mutate=None,accept=True):
        r,n,o=copy.deepcopy((relocation,new,old));sha='c'*64
        if mutate:sha=mutate(r,n,o) or sha
        try:ns['qualify_supplemental_source'](r,n,o,sha)
        except (ValueError,KeyError,TypeError):require(not accept,name+' unexpectedly refused')
        else:require(accept,name+' unexpectedly accepted')
        cases.append(dict(name=name,passed=True))
    extra('one exact raw attention source accepted')
    extra('additional supplemental source refuses',lambda r,n,o:r['supplemental_source_pins'].update(extra=n),False)
    extra('attention recipe constant drift refuses',lambda r,n,o:'d'*64,False)
    extra('original attention raw source hash drift refuses',lambda r,n,o:o.update(sha256='d'*64),False)
    extra('supplemental source absent from relocation artifacts refuses',lambda r,n,o:r.update(artifacts={}),False)
    for path,data in raw.items():require(path.read_bytes()==data,'reviewed producer source drift')
    result=dict(schema='conditions-balanced-runner-preparer-independent-source-controls/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        control_count=len(cases),cases=cases,scope='Exact runner prefix and supplemental guard AST with fake public metadata/protocol. No actual main, source package or numerical import.',
        artifacts={str(path):dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for path,data in raw.items()},
        actual_producer_main_calls=0,model_calls=0,numerical_imports=0,private_body_reads=0,checkpoint_JSON_parses=0,reference_reads=0,resource_API_calls=0,Git_calls=0)
    with OUTPUT.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444);data=OUTPUT.read_bytes();print(json.dumps(dict(path=str(OUTPUT),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())))

if __name__=='__main__':main()
