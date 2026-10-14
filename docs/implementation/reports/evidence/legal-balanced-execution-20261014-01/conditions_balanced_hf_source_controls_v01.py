"""Pure source/publication identity guards only; no model, network or producer mains."""
import ast
import copy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path

F=Path(__file__).resolve().parent
SOURCE=F/'archive_conditions_balanced_hf_v01.py'
OLD=F.parent/'legal-conditions-recall-20261014-01/archive_conditions_balanced_hf_v01.py'
EXPECTED=(24481,'90e63b176bb7b4080a20e56031e57c5f561ac4b41141fb6307179e31fc9ed921')
OUTPUT=F/'hf-helper-author-source-controls-v01.json'


def main():
    raw=SOURCE.read_bytes();assert (len(raw),hashlib.sha256(raw).hexdigest())==EXPECTED
    tree=ast.parse(raw);constants={}
    wanted={'REPO','PREFIX','MAX_BYTES','PRIOR_REVISION','PRIOR_FILES','OWNER_COUNT','ALGORITHM_SOURCE_COUNT','SUPPLEMENT_RELATIVE','SUPPLEMENT_BYTES','SUPPLEMENT_SHA256'}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in wanted:
            constants[node.targets[0].id]=ast.literal_eval(node.value)
    assert set(constants)==wanted
    names={'require','private','brief','qualify_hf_baseline','algorithm_sources'}
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names];assert len(nodes)==5
    ns=dict(constants,F=F,Path=Path);exec(compile(ast.Module(body=nodes,type_ignores=[]),'exact_hf_pure_guards','exec'),ns)
    def descriptor(path,i=0):return dict(path=str(path),bytes=i+1,sha256=hashlib.sha256(str(i).encode()).hexdigest())
    owners={str(i):descriptor(F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer'/('fixture_'+str(i)+'.py'),i) for i in range(39)}
    supplemental=dict(path=str(F/'datasets'/constants['SUPPLEMENT_RELATIVE']),bytes=constants['SUPPLEMENT_BYTES'],sha256=constants['SUPPLEMENT_SHA256'])
    plan=dict(schema='conditions-balanced-cell-plan/v1',cell='conditions-balanced-ce',attempt_name='conditions-balanced-20261014-conditions-balanced-ce-01',package_root=str(F/'datasets'),source_owner_pins=owners,
        artifacts={d['path']:{key:d[key] for key in ('bytes','sha256')} for d in [*owners.values(),supplemental]})
    relocation=dict(schema='conditions-balanced-trainer-relocation-source-independent-review/v1',passed=True,findings=[],source_owner_pins=owners,supplemental_source_pins={constants['SUPPLEMENT_RELATIVE']:supplemental})
    cases=[]
    def positive(name,fn):fn();cases.append(dict(name=name,passed=True))
    def negative(name,fn):
        try:fn()
        except (ValueError,KeyError,TypeError):cases.append(dict(name=name,passed=True));return
        raise AssertionError(name+' accepted')
    result=ns['algorithm_sources'](plan,relocation)
    assert len(result)==40 and constants['PREFIX']+'/source/'+constants['SUPPLEMENT_RELATIVE'] in result
    positive('exact39owners plus sibling attention produce40 package-relative destinations',lambda:ns['algorithm_sources'](plan,relocation))
    bad=copy.deepcopy(relocation);bad['supplemental_source_pins']={}
    negative('omitted attention dependency refuses',lambda:ns['algorithm_sources'](plan,bad))
    bad=copy.deepcopy(plan);bad['artifacts'].pop(supplemental['path'])
    negative('unadmitted supplemental raw file refuses',lambda:ns['algorithm_sources'](bad,relocation))
    bad=copy.deepcopy(plan);bad['artifacts'].pop(owners['0']['path'])
    negative('unadmitted owner raw file refuses',lambda:ns['algorithm_sources'](bad,relocation))
    bad=copy.deepcopy(relocation);bad['supplemental_source_pins'][constants['SUPPLEMENT_RELATIVE']]['sha256']='f'*64
    negative('wrong attention bytes refuse',lambda:ns['algorithm_sources'](plan,bad))
    bp,br=copy.deepcopy((plan,relocation));bp['source_owner_pins']['1']=bp['source_owner_pins']['0'];br['source_owner_pins']=bp['source_owner_pins']
    negative('duplicate actual owner file refuses despite39modulekeys',lambda:ns['algorithm_sources'](bp,br))
    identity=dict(size=1,blob_id='a'*40,lfs=None)
    prior={'.gitattributes':identity,**{'old/'+str(i):identity for i in range(5268)}}
    baseline=dict(repo=constants['REPO'],revision='e'*40,files={**prior,'newer-agent/file':identity},prior_release_revision=constants['PRIOR_REVISION'],prior_release_files=prior)
    positive('immutable5269 plus newer additions remain exact',lambda:ns['qualify_hf_baseline'](baseline))
    bad=copy.deepcopy(baseline);bad['files']['old/0']=dict(identity,blob_id='b'*40)
    negative('changed old identity refuses',lambda:ns['qualify_hf_baseline'](bad))
    bad=copy.deepcopy(baseline);bad['files'].pop('old/0');bad['files']['extra-replacement']=identity
    negative('same-or-greater count cannot hide missing old file',lambda:ns['qualify_hf_baseline'](bad))
    bad=copy.deepcopy(baseline);bad['files'][constants['PREFIX']+'/occupied']=identity
    negative('occupied candidate release prefix refuses',lambda:ns['qualify_hf_baseline'](bad))
    assert ns['private'](F/'private-root-identity-rebind-v01/ledger-before.json')
    assert ns['private'](F/'private-runtime-snapshots/opening-v01/ledger.json')
    cases.append(dict(name='both private backup and private endpoint copies excluded',passed=True))
    old=ast.parse(OLD.read_bytes());functions=lambda t:{node.name:node for node in t.body if isinstance(node,ast.FunctionDef)}
    a,b=functions(old),functions(tree)
    changed={name for name in a if ast.dump(a[name],include_attributes=False)!=ast.dump(b[name],include_attributes=False)}
    assert changed=={'private','baseline','prepare','publish'}
    def suffix(node):
        start=next(i for i,item in enumerate(node.body) if isinstance(item,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='payload' for target in item.targets))
        return ast.dump(ast.Module(body=node.body[start:],type_ignores=[]),include_attributes=False)
    assert suffix(a['publish'])==suffix(b['publish'])
    cases.append(dict(name='entire payload CAS/chunk/oldidentity/immutable readback loop AST unchanged',passed=True))
    assert SOURCE.read_bytes()==raw
    value=dict(schema='conditions-balanced-Hub-helper-author-source-controls/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        control_count=len(cases),cases=cases,unchanged_helper_functions_AST=sorted(set(a)-changed),helper=dict(path=str(SOURCE),bytes=len(raw),sha256=EXPECTED[1]),
        actual_helper_action_calls=0,HF_calls=0,network_calls=0,model_calls=0,numerical_imports=0,checkpoint_JSON_parses=0,private_body_reads=0,payload_copies=0,Git_calls=0)
    with OUTPUT.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444);data=OUTPUT.read_bytes();print(json.dumps(dict(path=str(OUTPUT),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())))

if __name__=='__main__':main()
