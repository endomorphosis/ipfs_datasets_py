"""Gold-dependent postfreeze saved-score diagnostic; no models or numerical imports."""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from types import SimpleNamespace

F=Path(__file__).resolve().parent;N10=F.parent/'legal-actor-features-20261013-01';N6=F.parent/'legal-temporal-adapter-20261013-01';N7=F.parent/'legal-temporal-attention-20261013-01';N2=F.parent/'legal-targeted-loss-20261012-01'
FIELDS=('actor','action','object','conditions','exceptions','temporal');PINS={}
def require(value,message):
    if not value:raise ValueError(message)
def pin(path):
    path=Path(path);raw=path.read_bytes();v=dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());PINS[str(path)]=v;return v

def read(path,expected=None):
    path=Path(path);require('checkpoint' not in path.name and 'private-runtime-snapshots' not in path.parts,'no checkpoint/private bodies')
    d=pin(path)
    if expected:require(all(d[k]==expected[k] for k in ('bytes','sha256')),'exact saved identity')
    return json.loads(path.read_bytes())
def detached(path,names,namespace):
    pin(path);nodes=[n for n in ast.parse(Path(path).read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    require({n.name for n in nodes}==set(names),'exact AST set');require(not any(isinstance(c,(ast.Import,ast.ImportFrom)) for n in nodes for c in ast.walk(n)),'no imports in pure helpers')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#source-only-oracle','exec'),namespace);return namespace

def main():
    review=read(N10/'result-independent-review-v01.json');require(review['passed'] is True and review['findings']==[],'qualified N10 result')
    freeze=read(review['freeze']['path'],review['freeze']);require(freeze['all_outputs_frozen'] is True and len(freeze['results'])==62,'complete frozen output62')
    summary=read(freeze['summary']['path'],freeze['summary']);analysis=read(review['analysis']['path'],review['analysis']);recount=read(review['independent_recount']['path'],review['independent_recount'])
    ownerdir=F/'datasets/ipfs_datasets_py';jointpath=ownerdir/'logic/legal_ir/joint_span_selection.py'
    tools=dict(require=require,re=re,FIELDS=FIELDS)
    detached(N2/'analyze_targeted_results_v01.py',{'tokenize','strict_rule','gold_coordinates'},tools)
    namespace=dict(hashlib=hashlib,json=json,math=math,struct=struct,SCORE_SCHEMA='joint-source-span-scores/v1',SCHEMA='joint-copied-span-selection/v1',ORIGIN='bounded_joint_source_span_selector',FIELDS=FIELDS,OPTIONAL_FIELDS=FIELDS[2:],QUALIFIERS=FIELDS[3:],MODALITIES=('O','P','F'),AMBIGUITY_GUARD=1e-7,MAX_TOP_K=16,MAX_SEARCH_NODES=50000,FALSE={},_owner=lambda:SimpleNamespace(tokenize_source=tools['tokenize'],codec_module=SimpleNamespace(_rule=tools['strict_rule'])))
    selected={'JointSelectionError','_require','_raw','_f32','_keys','_validated','_choice','_rank_spans','_span','_canonical','_greedy','select_joint_spans'}
    detached(jointpath,selected,namespace)
    plan=read(review['plan']['path'],review['plan']);data=read(plan['data_export']['path'],plan['data_export'])
    parent=read(N6/'two-cell-output-freeze-v01.json');full=read(parent['reference_source_export']['path'],parent['reference_source_export']);packet=read(parent['reference_packet']['path'],parent['reference_packet'])
    populations=full['diagnostic_populations'];populations['authored_eval']=[r['model_example'] for r in packet['geometry_review_packet']['authored_eval']]
    freshcontract=read(N7/'evaluation-contract-v01.json');fresh=read(freshcontract['fresh_reference_packet']['path'],freshcontract['fresh_reference_packet'])
    populations.update(fresh['populations']);populations['training168']=data['training_rows']
    results={};failure_rows=[]
    for panel in ('training168','old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','fresh_dev','fresh_test'):
        rows=populations[panel];pair=summary['final_training_capture'] if panel=='training168' else summary['diagnostics'][panel]
        for name in ('raw','joint'):require({k:pair[name][k] for k in ('bytes','sha256')}==freeze['results'][pair[name]['path']],'captured output part of complete freeze')
        raw=read(pair['raw']['path'],pair['raw']);saved=read(pair['joint']['path'],pair['joint'])['rows'];require(len(rows)==len(raw['occurrences'])==len(saved),'complete row joins')
        counts={name:dict(raw_before=0,raw_after=0,joint_before=0,joint_after=0,raw_gain_ids=[],raw_loss_ids=[],joint_gain_ids=[],joint_loss_ids=[]) for name in ('conditions_only','modality_only','all_presence_only','all_fixed_heads')}
        headerrors=[]
        for row,occ,j in zip(rows,raw['occurrences'],saved,strict=True):
            require(row['id']==occ['id']==j['id'] and occ['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest(),'source identity')
            scores=occ['scores'];original=namespace['select_joint_spans'](row['source_text'],scores,top_k=8,max_search_nodes=50000)
            require(original['canonical_ir']==j['result']['canonical_ir'] and original['status']==j['result']['status'],'exact frozen selector replay')
            gold=row['canonical_ir'];rule=gold['rules'][0];tokens,coords=tools['gold_coordinates'](row)
            mode=namespace['_choice'](scores['modality_logits'])[0];presencebad=[f for f in FIELDS[2:] if (namespace['_choice'](scores['presence_logits'][f])[0]==1)!=(f in coords)]
            if mode!=('O','P','F').index(rule['modality']) or presencebad:headerrors.append(dict(id=row['id'],modality_wrong=mode!=('O','P','F').index(rule['modality']),presence_wrong=presencebad))
            rowout={}
            for intervention,entry in counts.items():
                revised=deepcopy(scores)
                if intervention in ('modality_only','all_fixed_heads'):revised['modality_logits']=[1. if x==rule['modality'] else 0. for x in ('O','P','F')]
                for field in (('conditions',) if intervention=='conditions_only' else FIELDS[2:] if intervention in ('all_presence_only','all_fixed_heads') else ()):
                    revised['presence_logits'][field]=[0.,1.] if field in coords else [1.,0.]
                require(revised['start_logits']==scores['start_logits'] and revised['end_logits']==scores['end_logits'],'pointer scores unchanged')
                result=namespace['select_joint_spans'](row['source_text'],revised,top_k=8,max_search_nodes=50000)
                before=dict(raw=original['independent_greedy']['canonical_ir']==gold,joint=original['canonical_ir']==gold)
                after=dict(raw=result['independent_greedy']['canonical_ir']==gold,joint=result['canonical_ir']==gold)
                for route in ('raw','joint'):
                    entry[route+'_before']+=before[route];entry[route+'_after']+=after[route]
                    if after[route] and not before[route]:entry[route+'_gain_ids'].append(row['id'])
                    if before[route] and not after[route]:entry[route+'_loss_ids'].append(row['id'])
                rowout[intervention]=dict(raw_exact=after['raw'],joint_exact=after['joint'],joint_status=result['status'],joint_reason=result.get('reason'))
            if panel=='training168' and original['canonical_ir']!=gold:
                failure_rows.append(dict(id=row['id'],source_text=row['source_text'],gold_coordinates={f:list(c) for f,c in coords.items()},gold_modality=rule['modality'],predicted_modality=('O','P','F')[mode],presence_wrong=presencebad,actual_wrong_fields=[f for f in ('modality',*FIELDS) if original['canonical_ir'] is None or original['canonical_ir']['rules'][0][f]!=rule[f]],counterfactual=rowout))
        results[panel]=dict(rows=len(rows),head_errors=headerrors,oracle=counts)
    require(len(failure_rows)==15,'exact fifteen training failures')
    train=results['training168']['oracle'];require(train['conditions_only']['joint_after']==train['conditions_only']['raw_after']==154,'exact +1 ceiling')
    require(train['modality_only']['joint_after']==153 and train['all_fixed_heads']['joint_after']==154,'mode0 and allfixed+1')
    out=dict(schema='conditions-presence-gold-dependent-oracle-diagnostic/v1',passed=True,findings=[],training_failures=failure_rows,panels=results,
        all_scored_rows=sum(p['rows'] for p in results.values()),scope='Gold-dependent postfreeze counterfactual upper bound with frozen pointer vectors, not model performance, training rows, inference feature, legal accuracy or blind evaluation.',
        saved_selector_replay=True,actual_source_forwards=0,model_calls=0,numerical_imports=0,optimizer_updates=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0,source_pins=PINS)
    output=F/'conditions-presence-oracle-diagnostic-v01.json';require(not output.exists(),'exclusive new diagnostic output');output.write_text(json.dumps(out,sort_keys=True,indent=2)+'\n');output.chmod(0o444);print(json.dumps(dict(path=str(output),bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),training_oracle=train)))

if __name__=='__main__':main()
