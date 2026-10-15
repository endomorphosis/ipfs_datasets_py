"""Finite detached recovery predicates; no helper main, SDK, network or payload reads."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

F=Path(__file__).resolve().parent
SOURCE=F/'resume_actor_context_ranking_hf_v01.py'
TREE=ast.parse(SOURCE.read_bytes())
NAMES={'require','revision','byte_identity','qualify_partial','qualify_attributes','qualify_restored','qualify_chunk'}
nodes=[n for n in TREE.body if isinstance(n,ast.Assign) or isinstance(n,ast.FunctionDef) and n.name in NAMES]
ns=dict(Path=Path,hashlib=hashlib,__file__=str(SOURCE))
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#detached','exec'),ns)
m=SimpleNamespace(**ns);CASES=[]


def raw_identity(raw,lfs=False):
    return dict(size=len(raw),blob_id=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
        lfs=None if not lfs else dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),pointer_size=135))


def fixture():
    names=[m.PREFIX+'/fixture/'+str(i)+'.txt' for i in range(201)];names[19]=m.CHECKPOINT_NAME
    groups=[];start=0
    for count in [18,1,1,15,18,37,48,48,15]:groups.append(names[start:start+count]);start+=count
    payload={n:('opaque fixture '+str(i)).encode() for i,n in enumerate(names)}
    original={'original/'+str(i):raw_identity(('prior '+str(i)).encode()) for i in range(5645)}
    original['.gitattributes']=copy.deepcopy(m.OLD_ATTRIBUTES)
    created=[dict(parent_revision=p,revision=r,names=groups[i]) for i,(p,r) in enumerate(((m.BASELINE_REVISION,m.FIRST_REVISION),(m.FIRST_REVISION,m.SECOND_REVISION),(m.SECOND_REVISION,m.PARTIAL_REVISION)))]
    verified=[dict(parent_revision=c['parent_revision'],revision=c['revision'],new_files=len(c['names']),old_identities_exact=True,new_byte_identities_exact=True) for c in created[:2]]
    current=copy.deepcopy(original);current['.gitattributes']=copy.deepcopy(m.PARTIAL_ATTRIBUTES)
    current.update({n:raw_identity(payload[n],n==m.CHECKPOINT_NAME) for g in groups[:3] for n in g})
    snapshot=dict(schema='actor-context-ranking-Hub-immutable-file-snapshot/v1',repository=m.REPO,requested_revision=m.PARTIAL_REVISION,returned_revision=m.PARTIAL_REVISION,metadata_queries=1,files=current)
    return [original,snapshot,payload,groups,created,verified]


def good(name,call):call();CASES.append(dict(name=name,passed=True,expected='accepted'))
def reject(name,call):
    try:call()
    except (ValueError,KeyError,TypeError):CASES.append(dict(name=name,passed=True,expected='refused'));return
    raise AssertionError(name+': mutation accepted')
def mutate(name,change):
    values=fixture();change(values);reject(name,lambda:m.qualify_partial(*values))


def main():
    good('exact5666_partial20_created_first2_verified',lambda:m.qualify_partial(*fixture()))
    mutate('extra_remote_path',lambda v:v[1]['files'].update(unexpected=raw_identity(b'x')))
    mutate('missing_original',lambda v:v[1]['files'].pop('original/0'))
    mutate('other_original_changed',lambda v:v[1]['files']['original/0'].update(size=999))
    mutate('wrong_partial_attrs',lambda v:v[1]['files']['.gitattributes'].update(size=999))
    mutate('missing_created',lambda v:v[1]['files'].pop(v[3][0][0]))
    mutate('wrong_created_Git_blob',lambda v:v[1]['files'][v[3][0][0]].update(blob_id='0'*40))
    mutate('wrong_created_LFS_SHA',lambda v:v[1]['files'][m.CHECKPOINT_NAME]['lfs'].update(sha256='0'*64))
    mutate('wrong_created_LFS_size',lambda v:v[1]['files'][m.CHECKPOINT_NAME]['lfs'].update(size=0))
    mutate('wrong_partial_revision',lambda v:v[1].update(returned_revision='0'*40))
    mutate('boolean_query_count',lambda v:v[1].update(metadata_queries=True))
    mutate('wrong_chunk2_parent',lambda v:v[4][1].update(parent_revision=m.BASELINE_REVISION))
    mutate('wrong_chunk3_parent',lambda v:v[4][2].update(parent_revision=m.FIRST_REVISION))
    mutate('wrong_chunk3_names',lambda v:v[4][2].update(names=v[3][0]))
    mutate('first_verification_failed',lambda v:v[5][0].update(old_identities_exact=False))
    mutate('second_verification_failed',lambda v:v[5][1].update(new_byte_identities_exact=False))
    mutate('duplicate_name',lambda v:v[3][4].__setitem__(0,v[3][0][0]))
    mutate('wrong_group_geometry',lambda v:v[3][0].pop())
    mutate('missing_original_attrs',lambda v:v[0].pop('.gitattributes'))
    values=fixture();original,snapshot,payload,groups=values[:4];additions=m.qualify_partial(*values);restored={**original,**additions}
    good('exact5646plus20_restored_map',lambda:m.qualify_restored(restored,original,additions))
    for mode in ('attrs','payload','extra'):
        wrong=copy.deepcopy(restored)
        if mode=='attrs':wrong['.gitattributes']=copy.deepcopy(m.PARTIAL_ATTRIBUTES)
        elif mode=='payload':wrong[groups[0][0]]['blob_id']='0'*40
        else:wrong['unexpected']=raw_identity(b'x')
        reject('correction_rejects_'+mode,lambda:m.qualify_restored(wrong,original,additions))
    names=groups[3];after={**restored,**{n:raw_identity(payload[n]) for n in names}}
    good('next_original_chunk4_only',lambda:m.qualify_chunk(after,restored,names,payload))
    for mode in ('attrs','repeat','duplicate','newhash','missingold','extra'):
        wrong=copy.deepcopy(after);selected=list(names)
        if mode=='attrs':wrong['.gitattributes']=copy.deepcopy(m.PARTIAL_ATTRIBUTES)
        elif mode=='repeat':selected=groups[0]
        elif mode=='duplicate':selected+=names[:1]
        elif mode=='newhash':wrong[names[0]]['blob_id']='0'*40
        elif mode=='missingold':wrong.pop('original/0')
        else:wrong['unapproved']=raw_identity(b'x')
        reject('resume_rejects_'+mode,lambda:m.qualify_chunk(wrong,restored,selected,payload))
    # Public historical baseline bytes + proposed exact line; never a claimed observation.
    baseline=(F.parent/'legal-actor-refinement-20261014-01/hf-reconciliation-attrs-readback-v01/baseline/.gitattributes').read_bytes()
    line=(m.CHECKPOINT_NAME+' filter=lfs diff=lfs merge=lfs -text\n').encode();partial=baseline+line
    obs=dict(schema='actor-context-ranking-Hub-partial-observation/v1',observation_completed=True,repository=m.REPO,metadata_queries=5,
        immutable_attributes_downloads=2,remote_mutations=0,automatic_retry_performed=False,strict_publication_invariants_passed=False,live_exactly_matches_known_partial=True,
        attributes_readback={},attributes_difference=dict(exact_checkpoint_LFS_rule_append=True,byte_delta=142,added_line_count=1,removed_line_count=0))
    for key,raw,identity,rev in [('baseline',baseline,m.OLD_ATTRIBUTES,m.BASELINE_REVISION),('chunk03',partial,m.PARTIAL_ATTRIBUTES,m.PARTIAL_REVISION)]:
        obs['attributes_readback'][key]=dict(revision=rev,remote_identity=identity,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),force_download=True,immutable_download_byte_identity_matches=True)
    good('proposed2230plus142_exact_case_requires_matching_actual_readback',lambda:m.qualify_attributes(obs,baseline,partial,original,snapshot['files']))
    reject('baseline_byte_drift',lambda:m.qualify_attributes(obs,baseline+b'x',partial,original,snapshot['files']))
    reject('partial_byte_drift',lambda:m.qualify_attributes(obs,baseline,partial+b'x',original,snapshot['files']))
    for mode in ('removedline','notforced','unverified','original_coerced_to_pass','wrong_live_parent'):
        wrong=copy.deepcopy(obs)
        if mode=='removedline':wrong['attributes_difference']['removed_line_count']=1
        elif mode=='notforced':wrong['attributes_readback']['baseline']['force_download']=False
        elif mode=='unverified':wrong['attributes_readback']['chunk03']['immutable_download_byte_identity_matches']=False
        elif mode=='original_coerced_to_pass':wrong['strict_publication_invariants_passed']=True
        else:wrong['live_exactly_matches_known_partial']=False
        reject('attrs_rejects_'+mode,lambda:m.qualify_attributes(wrong,baseline,partial,original,snapshot['files']))
    reject('invalid_returned_revision',lambda:m.revision('invalid'))
    main_ast=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='main');text=ast.unparse(main_ast)
    assert 'groups[3:]' in text and 'parent_commit=current' in text and "'--force-download'" in text
    assert "discrepancy['passed'] is False" in text and "interruption['publisher_returncode'] == 1" in text
    assert 'CommitOperationDelete' not in text and 'automatic_retry_performed=False' in text
    assert 'len(after) == 5847' in text and 'len(commits) == 6' in text
    assert 'Git_clone_LFS_automatic_materialization_qualified=False' in text
    CASES.append(dict(name='source_only_finite_case_original_failure_CAS_and201_forcedreadback_limits',passed=True,expected='source_only'))
    def pin(p):
        raw=p.read_bytes();return dict(path=str(p),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    receipt=dict(schema='actor-context-ranking-Hub-resume-author-controls/v1',passed=True,findings=[],source=pin(SOURCE),tests=pin(Path(__file__).resolve()),controls=CASES,count=len(CASES),
        scope='Detached synthetic5666-identity fixtures and historical public baseline attrs plus proposed F16 checkpoint line; no claimed actualpartial body observations.',
        producer_main_calls=0,SDK_imports=0,network_calls=0,uploads=0,model_calls=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0,
        actual_checkpoint_or_payload_reads=0,proposed_attributes_fixture_is_not_observed_state=True)
    output=F/'actor-context-ranking-hf-resume-author-controls-v01.json'
    with output.open('x') as out:json.dump(receipt,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
    output.chmod(0o444);print(json.dumps(pin(output)));print('PASS',len(CASES))

if __name__=='__main__':main()
