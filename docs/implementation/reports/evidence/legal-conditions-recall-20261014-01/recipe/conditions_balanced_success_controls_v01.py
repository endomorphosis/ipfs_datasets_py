"""Synthetic conjunctive-success fixtures for two separate saved-output predicates."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

F=Path(__file__).resolve().parent
PANELS=('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law','fresh_dev','fresh_test')

def pin(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def require(value,message):
    if not value:raise ValueError(message)

def detached(path,name):
    node=next(n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    env=dict(PANELS=PANELS,require=require)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<synthetic-scientific-predicate>','exec'),env)
    return env[name]

def main():
    analyzer=F/'analyze_conditions_balanced_v01.py';recount=F/'review_conditions_balanced_result_recount_v01.py'
    first=detached(analyzer,'scientific_acceptance');second=detached(recount,'independent_acceptance')
    contract=json.loads((F/'evaluation-contract-v01.json').read_bytes())
    target_counts=contract['strict_scientific_success']['recover_N11_added_FN_ids']['expected_panel_counts']
    scopes=[p for p in (*PANELS,'training168') if p!='law']
    summaries={};records={}
    for panel in scopes:
        gains=contract['strict_scientific_success']['preserve_N11_complete_IR_gain_ids'].get(panel,[])
        targets=[panel+'-synthetic-recall-'+str(i) for i in range(target_counts.get(panel,0))]
        identifiers=[panel+'-synthetic-stable',*gains,*targets]
        for state in ['parent','trained','frozen_N11']:
            fn=targets if state=='frozen_N11' else []
            tp=[i for i in identifiers if i not in fn]
            confusion=dict(views=dict(head=dict(conditions={key:dict(ids=values) for key,values in [('TP',tp),('TN',[]),('FP',[]),('FN',fn)]})),excluded_by_gold=dict(head=dict(conditions=dict(gold_present=dict(ids=[])))))
            summaries[state,panel]=dict(state=state,panel=panel,optional_presence_confusion=confusion)
            records[state,panel]=[dict(id=identifier,raw_exact_ir=identifier not in targets and (state!='parent' or identifier not in gains),joint_exact_ir=identifier not in targets and (state!='parent' or identifier not in gains)) for identifier in identifiers]
    def run(data):
        summaries,records=data
        confusion={key:value['optional_presence_confusion'] for key,value in summaries.items()}
        flags={key:[dict(id=row['id'],raw=dict(full_IR=row['raw_exact_ir']),joint=dict(full_IR=row['joint_exact_ir'])) for row in rows] for key,rows in records.items()}
        a=first(contract,list(summaries.values()),records);b=second(contract,confusion,flags)
        assert a==b
        assert a['technical_pass'] is True and a['default_promotion'] is False
        return a
    baseline=(summaries,records);value=run(baseline);assert value['scientific_success'] is True
    cases=['Both independent predicates accept four recovered targets, both gain IDs, no new errors and zero paired losses']
    def head(data,panel,label):return data[0]['trained',panel]['optional_presence_confusion']['views']['head']['conditions'][label]['ids']
    def fp(data):head(data,'old_tune','FP').append('old_tune-synthetic-stable')
    def fn(data):head(data,'authored_eval','FN').append('authored_eval-synthetic-recall-0');head(data,'authored_eval','TP').remove('authored_eval-synthetic-recall-0')
    def ambiguous(data):
        c=data[0]['trained','fresh_dev']['optional_presence_confusion'];c['excluded_by_gold']['head']['conditions']['gold_present']['ids'].append('fresh_dev-synthetic-recall-0');c['views']['head']['conditions']['TP']['ids'].remove('fresh_dev-synthetic-recall-0')
    def loss(data):data[1]['trained','old_tune'][0]['joint_exact_ir']=False
    def gain(data):
        identifier=contract['strict_scientific_success']['preserve_N11_complete_IR_gain_ids']['training168'][0]
        next(r for r in data[1]['trained','training168'] if r['id']==identifier)['raw_exact_ir']=False
    def diagnostic_only_loss(data):
        data[1]['parent','fresh_test'][0]['raw_exact_ir']=False;data[1]['trained','fresh_test'][0]['raw_exact_ir']=False
    for label,mutation in [('new false positive',fp),('new false negative and unrecovered target',fn),('new positive ambiguity and unrecovered target',ambiguous),('paired completeIR regression',loss),('required gain lost in raw route',gain),('regression vs diagnostic N11 despite no N10 loss',diagnostic_only_loss)]:
        bad=deepcopy(baseline);mutation(bad);assert run(bad)['scientific_success'] is False;cases.append(label+' makes scientific success false while technical pass stays true')
    wrong=deepcopy(baseline);wrong[0]['frozen_N11','fresh_dev']['optional_presence_confusion']['views']['head']['conditions']['FN']['ids'].pop()
    for function,args in [(first,(contract,list(wrong[0].values()),wrong[1])),(second,(contract,{k:v['optional_presence_confusion'] for k,v in wrong[0].items()},{key:[dict(id=r['id'],raw=dict(full_IR=r['raw_exact_ir']),joint=dict(full_IR=r['joint_exact_ir'])) for r in values] for key,values in wrong[1].items()}))]:
        try:function(*args)
        except ValueError:pass
        else:raise AssertionError('Changed diagnostic four-target scope accepted')
    cases.append('Both implementations reject changed diagnostic four-target custody scope')
    result=dict(schema='conditions-balanced-scientific-success-author-controls/v1',passed=True,findings=[],case_count=len(cases),cases=cases,analyzer=pin(analyzer),recount=pin(recount),contract=pin(F/'evaluation-contract-v01.json'),controls_source=pin(Path(__file__).resolve()),actual_saved_outputs_or_reference_bodies_read=0,model_calls=0,numerical_imports=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0)
    out=F/'scientific-success-author-controls-v01.json'
    with out.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    out.chmod(0o444);print(json.dumps(pin(out)))

if __name__=='__main__':main()
