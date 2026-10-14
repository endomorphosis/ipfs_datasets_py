"""Synthetic source-only ledger/root transition controls; no live/private reads or resource APIs."""
import ast
import copy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

F=Path(__file__).resolve().parent
P=Path('/home/barberb/lift_coding/artifacts/legal-conditions-recall-20261014-01')
SOURCES={P/'conditions_balanced_resource_protocol_v01.py':(13965,'265d96839054a16d4c4ab0f2550dc69948263a87566e9337a429b3ddb02f69f0'),
 F/'balanced_execution_root_identity_v01.py':(11831,'a0ecd10daaac94605c07146307a89a6a63f526826f018b59cce15f86a898efc5')}
OUTPUT=F/'root-identity-author-source-controls-v01.json'


def main():
    reads={};trees={}
    for path,(size,sha) in SOURCES.items():
        raw=path.read_bytes();assert len(raw)==size and hashlib.sha256(raw).hexdigest()==sha
        reads[str(path)]=dict(path=str(path),bytes=size,sha256=sha);trees[path]=ast.parse(raw)
    names={'require','canonical','digest','qualify_ledger'}
    nodes=[n for n in trees[P/'conditions_balanced_resource_protocol_v01.py'].body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==4
    from collections import Counter
    scope=dict(json=json,hashlib=hashlib,Counter=Counter)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'exact_f12_pure_ledger_predicates','exec'),scope)
    scope['p']=SimpleNamespace(qualify_ledger=scope['qualify_ledger'])
    names={'qualify_ledger_roots','qualify_transition'}
    nodes=[n for n in trees[F/'balanced_execution_root_identity_v01.py'].body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==2
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'exact_f14_pure_transition_predicates','exec'),scope)
    old=[dict(path='/fixture/root'+str(i),device=17,inode=i+10) for i in range(4)]
    new=copy.deepcopy(old);new[3]['inode']=99
    contract=dict(global_cap_bytes=145000000000,counted_root_metadata=old,required_preserved_claims=[dict(reservation_id='n7',status='retained',storage_bytes=200000000),dict(reservation_id='n8',status='released',storage_bytes=200000000)],
        prior_record_status_counts={'released':437,'retained':101},prior_full_nonreleased_claim_bytes=44381777216)
    records={'n7':dict(reservation_id='n7',status='retained',storage_bytes=200000000),'n8':dict(reservation_id='n8',status='released',storage_bytes=200000000)}
    for i in range(436):records['released'+str(i)]=dict(reservation_id='released'+str(i),status='released',storage_bytes=1)
    for i in range(100):records['retained'+str(i)]=dict(reservation_id='retained'+str(i),status='retained',storage_bytes=44181777117 if i==0 else 1)
    before=dict(schema='daemon-resource-reservations-v1',roots=old,limit_bytes=145000000000,reservations=records)
    hashes={key:scope['digest'](row) for key,row in records.items()}
    after=copy.deepcopy(before);after['roots']=new
    cases=[]
    def positive(name,fn):fn();cases.append(dict(name=name,passed=True))
    def negative(name,fn):
        try:fn()
        except (ValueError,KeyError,TypeError):cases.append(dict(name=name,passed=True));return
        raise AssertionError(name+' accepted')
    positive('exact roots-only migration preserves538 fullclaim bodies',lambda:scope['qualify_transition'](before,after,contract,hashes,new))
    positive('already-current roots no-change accepted',lambda:scope['qualify_transition'](after,after,contract,hashes,new))
    bad=copy.deepcopy(after);bad['reservations']['n7']['status']='released'
    negative('retained foreign or historical claim release refuses',lambda:scope['qualify_transition'](before,bad,contract,hashes,new))
    bad=copy.deepcopy(after);bad['reservations']['extra']=dict(reservation_id='extra',status='released',storage_bytes=1)
    negative('extra record refuses under lock',lambda:scope['qualify_transition'](before,bad,contract,hashes,new))
    bad=copy.deepcopy(after);bad['limit_bytes']+=1
    negative('cap edit refuses',lambda:scope['qualify_transition'](before,bad,contract,hashes,new))
    bad=copy.deepcopy(after);bad['roots'][0]['inode']+=1
    negative('persistent-root edit refuses',lambda:scope['qualify_transition'](before,bad,contract,hashes,new))
    bad=copy.deepcopy(before);bad['roots'][3]['inode']=55
    negative('unapproved third root form refuses',lambda:scope['qualify_transition'](bad,after,contract,hashes,new))
    bad=copy.deepcopy(after);bad['reservations']['n8']['extra_field']='forbidden'
    negative('any unchanged-status record-body edit refuses',lambda:scope['qualify_transition'](before,bad,contract,hashes,new))
    value=dict(schema='conditions-balanced-root-identity-author-source-controls/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        control_count=len(cases),cases=cases,artifacts=reads,actual_model_calls=0,actual_censuses=0,private_body_reads=0,resource_API_calls=0,shared_mutations=0)
    with OUTPUT.open('x') as out:json.dump(value,out,indent=2,sort_keys=True);out.write('\n');out.flush();os.fsync(out.fileno())
    OUTPUT.chmod(0o444);raw=OUTPUT.read_bytes();print(json.dumps(dict(path=str(OUTPUT),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())))

if __name__=='__main__':main()
