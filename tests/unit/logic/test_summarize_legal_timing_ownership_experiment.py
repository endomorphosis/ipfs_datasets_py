"""Independent probability, source-alias and gate contracts; no corpus reads."""
from copy import deepcopy
from types import SimpleNamespace
import math
import random
import pytest
import torch

from scripts.ops.legal_ir import summarize_legal_timing_ownership_experiment as q


def fixture(length=5, seed=1):
    torch.manual_seed(seed)
    records=[]
    for row in range(4):
        labels={'modality':row%3,'presence':[True,True,True, row>=2, row<2, row>=2],
                'spans':[[0,0],[1 if length>1 else 0]*2,[length-1]*2,
                         [0,min(1,length-1)] if row>=2 else [-100,-100],
                         [0,0] if row<2 else [-100,-100],
                         [length-1,length-1] if row>=2 else [-100,-100]]}
        records.append({'id':str(row),'tokens':['token']*length,'labels':labels})
    output={key:torch.randn(*shape,dtype=torch.float64,requires_grad=True) for key,shape in
            {'modality':(4,3),'presence':(4,4,2),'start':(4,6,length),'end':(4,6,length)}.items()}
    return output,records


def direct_probability_loss(output,records):
    losses=[]
    for field in ('conditions','temporal'):
        i=q.SPAN_FIELDS.index(field);o=q.OPTIONAL_FIELDS.index(field); groups={False:[],True:[]}
        for n,record in enumerate(records):
            length=len(record['tokens']); present=record['labels']['presence'][i]
            start,end=record['labels']['spans'][i]
            spans=[(a,b) for a in range(length) for b in range(a,length)]
            weights=torch.stack([torch.exp(output['start'][n,i,a]+output['end'][n,i,b]) for a,b in spans])
            weights=weights/weights.sum();p=output['presence'][n,o].softmax(0)[1]
            owned=[];unowned=[]
            for token in range(length):
                coverage=sum(weights[k] for k,(a,b) in enumerate(spans) if a<=token<=b)
                membership=p*coverage
                (owned if present and start<=token<=end else unowned).append(
                    -torch.log(membership) if present and start<=token<=end else -torch.log1p(-membership))
            groups[present].append(torch.stack([torch.stack(g).mean() for g in (owned,unowned) if g]).mean())
        losses.append(torch.stack([torch.stack(groups[label]).mean() for label in (False,True)]).mean())
    return torch.stack(losses).mean()


@pytest.mark.parametrize('length',[1,2,3,5,7])
def test_enumerated_log_oracle_matches_direct_probability_and_gradients(length):
    for seed in range(5):
        output,records=fixture(length,seed)
        actual,parts=q.ownership_loss_oracle(torch,output,records)
        expected=direct_probability_loss(output,records)
        assert actual.item()==pytest.approx(expected.item(),abs=2e-12)
        inputs=[output[k] for k in ('presence','start','end')]
        left=torch.autograd.grad(actual,inputs,retain_graph=True)
        right=torch.autograd.grad(expected,inputs)
        for a,b in zip(left,right):
            assert torch.isfinite(a).all()
            assert torch.allclose(a,b,atol=2e-12,rtol=2e-12)
        assert all(v['present_rows']==v['absent_rows']==2 for v in parts.values())
        assert all(v['positive_tokens']+v['negative_tokens']==4*length for v in parts.values())


@pytest.mark.parametrize('sign',[-1,1])
def test_extreme_logits_remain_finite_without_probability_clipping(sign):
    output,records=fixture(3)
    with torch.no_grad():
        output['presence'][:,:,0]=sign*1000
        output['presence'][:,:,1]=-sign*1000
        output['start'][:]=torch.tensor([1000.,-1000.,0.])
        output['end'][:]=torch.tensor([-1000.,1000.,0.])
    loss,_=q.ownership_loss_oracle(torch,output,records)
    assert math.isfinite(loss.item())
    gradients=torch.autograd.grad(loss,[output[k] for k in ('presence','start','end')])
    assert all(torch.isfinite(value).all() for value in gradients)


def test_absent_temporal_facet_penalizes_spurious_presence_and_span_ownership():
    output,records=fixture(5)
    output={k:v.detach().clone() for k,v in output.items()}
    _,before=q.ownership_loss_oracle(torch,output,records)
    output['presence'][:2,3]=torch.tensor([-10.,10.])
    _,after=q.ownership_loss_oracle(torch,output,records)
    assert after['temporal']['absent_loss']>before['temporal']['absent_loss']


def test_padding_and_unrelated_heads_have_no_ownership_gradient():
    output,records=fixture(7)
    for record in records: record['tokens']=record['tokens'][:5]
    for record in records:
        for span in record['labels']['spans']:
            span[0]=min(span[0],4);span[1]=min(span[1],4)
    loss,_=q.ownership_loss_oracle(torch,output,records)
    loss.backward()
    assert output['modality'].grad is None
    for key in ('start','end'):
        assert output[key].grad[:,:,5:].count_nonzero()==0
        assert output[key].grad[:,[0,1,2,4]].count_nonzero()==0
    assert output['presence'].grad[:,[0,2]].count_nonzero()==0


@pytest.mark.parametrize('mutation',['unbalanced','reversed','out_of_range','absent_nonignore'])
def test_bad_reference_membership_rejected(mutation):
    output,records=fixture(5)
    if mutation=='unbalanced': records[0]['labels']['presence'][3]=True;records[0]['labels']['spans'][3]=[0,1]
    if mutation=='reversed': records[2]['labels']['spans'][3]=[2,1]
    if mutation=='out_of_range': records[2]['labels']['spans'][3]=[0,5]
    if mutation=='absent_nonignore': records[0]['labels']['spans'][3]=[0,0]
    with pytest.raises((ValueError,AssertionError)):q.ownership_loss_oracle(torch,output,records)


def saved_job(tmp_path,name='a',**updates):
    pin=q.write(tmp_path/(name+'.json'),{'rows':[{'status':'abstained'}]})
    job={'kind':'single','name':name,'sources':[{'id':'x','source_text':'text'}],
         'generation':pin,'model':{'decoder_kind':'timing_ownership','checkpoint':{'path':'/model','sha256':'1'*64}}}
    job.update(updates);return job


def test_identical_outputs_alias_with_full_provenance(tmp_path):
    a=saved_job(tmp_path,'a');b=saved_job(tmp_path,'b')
    unique,aliases=q.deduplicate_replay_jobs([a,b])
    assert unique==[a] and aliases[1]['executed_name']=='a'
    actual=[{'name':'a','kind':'single','rows':1,'generation':a['generation'],'checkpoint':a['model']['checkpoint'],
             'clause_occurrences_replayed':2,'copied_facets_verified':6,'exact_recorded_payload_replay':True}]
    rows=q.expand_replay_aliases([a,b],actual,aliases)
    assert rows[1]['recomputed_for_this_saved_panel'] is False
    assert rows[1]['inference_alias_of']=='a' and rows[1]['clause_occurrences_replayed']==0
    assert rows[1]['logical_clause_occurrences']==2


@pytest.mark.parametrize('change',['checkpoint','kind','source_id','source_text'])
def test_distinct_input_does_not_alias(tmp_path,change):
    a=saved_job(tmp_path,'a');b=saved_job(tmp_path,'b')
    if change=='checkpoint': b['model']['checkpoint']['sha256']='2'*64
    if change=='kind': b['model']['decoder_kind']='facet_retention'
    if change=='source_id': b['sources'][0]['id']='other'
    if change=='source_text': b['sources'][0]['source_text']='other'
    assert len(q.deduplicate_replay_jobs([a,b])[0])==2


def test_same_model_inputs_but_changed_saved_logits_rejected(tmp_path):
    a=saved_job(tmp_path,'a');b=saved_job(tmp_path,'b')
    b['generation']=q.write(tmp_path/'corrupt.json',{'rows':[{'status':'decoded'}]})
    with pytest.raises((ValueError,AssertionError)):q.deduplicate_replay_jobs([a,b])


def test_missing_alias_execution_rejected(tmp_path):
    a=saved_job(tmp_path);_,aliases=q.deduplicate_replay_jobs([a])
    with pytest.raises((ValueError,AssertionError)):q.expand_replay_aliases([a],[],aliases)


def test_stage_wrapper_aliases_exact_final_payload(tmp_path):
    a=saved_job(tmp_path,'a');b=saved_job(tmp_path,'b',stage=True)
    b['generation']=q.write(tmp_path/'stage.json',{'generation':q.read_ref(a['generation']),'metrics':{'exact':0}})
    assert len(q.deduplicate_replay_jobs([a,b])[0])==1


def test_build_identity_includes_complete_exclusions_and_toolchain(tmp_path):
    binary=tmp_path/'lake';binary.write_bytes(b'fixed executable')
    args=SimpleNamespace(lake_executable=str(binary),toolchain='v1')
    selected={'rows':[],'excluded':[{'id':'x'}],'source_count':1}
    first=q.build_identity(selected,args)
    assert first==q.build_identity(deepcopy(selected),args)
    assert first!=q.build_identity({**selected,'excluded':[{'id':'y'}]},args)
    args.toolchain='v2';assert first!=q.build_identity(selected,args)

@pytest.mark.parametrize('length',[1,2,4,7])
def test_runtime_matches_independent_interval_enumeration_and_gradient(length):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_timing_ownership as runtime
    for seed in range(8):
        output,records=fixture(length,seed+10)
        actual,parts=runtime._timing_ownership_loss(torch,output,records)
        expected,_=q.ownership_loss_oracle(torch,output,records)
        assert actual.item()==pytest.approx(expected.item(),abs=2e-12)
        gradients=torch.autograd.grad(actual,[output[k] for k in ('presence','start','end')],retain_graph=True)
        wanted=torch.autograd.grad(expected,[output[k] for k in ('presence','start','end')])
        assert all(torch.allclose(a,b,atol=3e-12,rtol=3e-12) for a,b in zip(gradients,wanted))


def receipt_fixture():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_timing_ownership as runtime
    output,records=fixture(5)
    _,parts=runtime._timing_ownership_loss(torch,output,records)
    parts={k:float(v.detach()) for k,v in parts.items()}
    parts['auxiliary_standard_ce']=float(q.standard_auxiliary_loss_oracle(torch,output,records).detach())
    receipt={'optimizer_step':1,'ids':[r['id'] for r in records],
             'token_counts':[len(r['tokens']) for r in records], 'labels':[r['labels'] for r in records],
             'logits':{k:v.detach().tolist() for k,v in output.items()},
             'ownership_masks':runtime._ownership_masks(records),
             'ownership_masks_sha256':q.digest(runtime._ownership_masks(records))}
    return receipt,records,parts


def test_auxiliary_receipt_complete_loss_and_membership_oracle():
    receipt,records,parts=receipt_fixture()
    result=q.verify_auxiliary_receipt(receipt,records,parts,step=1)
    assert result['maximum_numerical_error']<1e-12
    assert result['logits_generated_by_model_independently_replayed'] is False


@pytest.mark.parametrize('field',['mask','count','loss','label','source','padding','step'])
def test_corrupted_receipt_fails_even_when_other_hashes_are_repaired(field):
    receipt,records,parts=receipt_fixture();receipt=deepcopy(receipt)
    if field=='mask':receipt['ownership_masks'][0]['conditions'][0]=True
    if field=='count':parts['ownership_temporal_owned_tokens']+=1
    if field=='loss':parts['timing_ownership_nll']+=.01
    if field=='label':receipt['labels'][2]['spans'][3]=[0,2]
    if field=='source':receipt['ids'][0]='tampered'
    if field=='padding':receipt['token_counts'][0]+=1
    if field=='step':receipt['optimizer_step']=2
    with pytest.raises((ValueError,AssertionError)):
        q.verify_auxiliary_receipt(receipt,records,parts,step=1)


def clause_fixture(count=192, exact=0):
    sources, targets, predictions = [], [], []
    for index in range(count):
        text = f'The unit{index} shall file notice{index}.'
        source = {'id': str(index), 'source_text': text, 'source_sha256': q.boundary.text_sha(text)}
        rule = {'modality': 'OPF'[index % 3], 'actor': f'The unit{index}', 'action': 'file',
                'object': f'notice{index}', 'conditions': ['permit active'] if index & 1 else [],
                'exceptions': ['record sealed'] if index & 2 else [],
                'temporal': ['within 3 days'] if index & 4 else []}
        canonical = {'rules': [rule]}
        target = {'id': str(index), 'source_text': text, 'canonical_ir': canonical}
        prediction = {'source_sha256': source['source_sha256'],
                      'status': 'decoded' if index < exact else 'abstained',
                      'canonical_ir': deepcopy(canonical) if index < exact else None}
        sources.append(source); targets.append(target); predictions.append(prediction)
    return {'rows': predictions}, sources, targets


def measured(count=192, exact=0):
    return q.clause_metrics(*clause_fixture(count, exact))['metrics']


def nested(count):
    return {'count': count, 'fullrule_exact': 0,
            'modality_fullrule': {m: {'count': count // 3, 'exact': 0} for m in 'OPF'},
            **{kind: {label: {'count': count // 2, 'exact': 0} for label in ('present', 'absent')}
               for kind in ('condition_facet', 'temporal_facet', 'condition_fullrule', 'temporal_fullrule')}}


def doc_metrics(supported=4, unsupported=2, exact=(), accepted=()):
    rows = [{'id': f's{i}', 'supported': True, 'joint_exact': i in exact, 'composed': i in exact}
            for i in range(supported)]
    rows += [{'id': f'u{i}', 'supported': False, 'joint_exact': False, 'composed': i in accepted}
             for i in range(unsupported)]
    return q.document_metrics(rows)


def stage_fixture():
    from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as historical
    result = {key: 0 for key in historical.metric_keys()}
    result.update(retention_metrics={panel: nested(192) for panel in ('facet', 'temporal')},
                  condition_metrics=nested(96), new_single_metrics=measured(),
                  prior_condition_metrics=measured(),
                  old_atom_oracle_metrics={panel: measured(120) for panel in q.ATOM_PANELS},
                  oracle_document_metrics={panel: doc_metrics(4, 0) for panel in q.GATE_DOCUMENT_PANELS},
                  fixed_document_metrics={panel: {policy: doc_metrics() for policy in q.PRIMARY_BOUNDARIES}
                                          for panel in q.GATE_DOCUMENT_PANELS}, role_retention_metrics={p:measured() for p in ('tuning','fresh')},
                  role_oracle_metrics={p:measured(120) for p in q.ROLE_PANELS},steps=100)
    return result



def test_all_abstaining_candidate_cannot_qualify():
    parent=stage_fixture()
    assert not q.eligible(deepcopy(parent),parent)


def test_new_semantic_gain_and_all_retention_pass():
    parent=stage_fixture();stage=deepcopy(parent);stage['new_single_metrics']=measured(exact=1)
    assert q.eligible(stage,parent)


@pytest.mark.parametrize('panel',list(q.GATE_DOCUMENT_PANELS))
@pytest.mark.parametrize('policy',q.PRIMARY_BOUNDARIES)
def test_every_panel_policy_rejects_new_unsupported_source_even_if_count_unchanged(panel,policy):
    parent=stage_fixture();parent['fixed_document_metrics'][panel][policy]=doc_metrics(accepted=(0,))
    stage=deepcopy(parent);stage['new_single_metrics']=measured(exact=1)
    stage['fixed_document_metrics'][panel][policy]=doc_metrics(accepted=(1,))
    assert not q.eligible(stage,parent)


@pytest.mark.parametrize('kind,panel',[('role_retention_metrics','tuning'),('role_retention_metrics','fresh'),
                                     ('role_oracle_metrics','role_tuning'),('role_oracle_metrics','role_fresh')])
def test_prior_role_fullrule_regression_blocks_new_timing_gain(kind,panel):
    parent=stage_fixture();parent[kind][panel]=measured(192 if kind=='role_retention_metrics' else 120,1)
    stage=deepcopy(parent);stage['new_single_metrics']=measured(exact=2)
    stage[kind][panel]=measured(parent[kind][panel]['count'],0)
    assert not q.eligible(stage,parent)


def test_independent_gates_and_rank_agree_with_new_runner():
    from scripts.ops.legal_ir import run_legal_timing_ownership_experiment as runner
    parent=stage_fixture()
    for seed in range(40):
        rng=random.Random(seed);stage=deepcopy(parent);stage['steps']=rng.choice([100,200])
        stage['new_single_metrics']=measured(exact=rng.randrange(3))
        if seed%3==0:
            stage['fixed_document_metrics'][rng.choice(q.GATE_DOCUMENT_PANELS)][rng.choice(q.PRIMARY_BOUNDARIES)]=doc_metrics(accepted=(0,))
        assert q.eligible(stage,parent)==runner.gates(stage,parent)['eligible']
        assert q.ranking(stage)==runner.ranking(stage)


def test_actual_os_guard_blocks_seven_semantic_paths_until_release(tmp_path):
    import subprocess,sys
    paths=[]
    for n in range(7):
        path=tmp_path/str(n);path.write_text('sealed');paths.append(str(path))
    script='''
import sys
from scripts.ops.legal_ir import summarize_legal_timing_ownership_experiment as q
pins=[q.ref(path) for path in sys.argv[1:]]
guard=q.legacy.SealedReadGuard(pins);sys.addaudithook(guard.event)
for path in sys.argv[1:]:
 try:open(path).read()
 except (ValueError,PermissionError,RuntimeError):pass
 else:raise AssertionError('premature open allowed')
assert len(guard.events)==7
guard.released=True
for path in sys.argv[1:]:assert open(path).read()=='sealed'
assert len(guard.events)==14
'''
    result=subprocess.run([sys.executable,'-c',script,*paths],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def alias_inventory_fixture(tmp_path):
    models=[]
    for architecture in q.ARCHITECTURES:
        parent={'name':'parent_'+architecture+'-1730','objective':'parent','decoder_kind':'facet_retention' if architecture=='continuation' else 'temporal_presence',
                'checkpoint':{'path':'/'+architecture,'sha256':q.digest(architecture)}}
        models.append(parent)
        for objective in q.OBJECTIVES:
            model={**parent,'name':objective+'_'+architecture+'-1730','objective':objective}
            models.append(model)
            models.append({**model,'name':model['name']+'_final200','decoder_kind':'timing_ownership',
                           'checkpoint':{'path':'/'+objective+architecture,'sha256':q.digest([objective,architecture])}})
    data={'sources':{'fresh':[]},'documents':{'fresh':[]},'oracle_documents':{'fresh':[]},'oracle_plans':{'fresh':[]},'training_sources':{'main':[],'auxiliary':[]}}
    boundary=q.write(tmp_path/'boundary.json',{'rows':[]})
    frozen={'models':models,'files':{},'oracle_files':{},'document_files':{},'training_files':{},
            'boundaries':{p:{'fresh':boundary} for p in q.PRIMARY_BOUNDARIES}}
    descriptor={'single_sources_sha256':q.digest(data['sources']),'document_sources_sha256':q.digest(data['documents']),
      'oracle_document_sources_sha256':q.digest(data['oracle_documents']),'oracle_plans_sha256':q.digest(data['oracle_plans']),
      'fixed_boundaries_sha256':q.digest({p:{'fresh':{'rows':[]}} for p in q.PRIMARY_BOUNDARIES}),
      'training_sources_sha256':q.digest(data['training_sources'])}
    mapping={};groups={}
    for model in models:groups.setdefault((model['decoder_kind'],model['checkpoint']['sha256']),[]).append(model)
    for group in groups.values():
        origin=min(group,key=lambda m:(0 if m['objective']=='parent' else 1 if m['name'].endswith('_final200') else 2,m['name']))['name']
        pin=q.write(tmp_path/(origin+'.json'),{'rows':[]})
        for model in group:
            name=model['name'];train=model['objective']=='parent' or name.endswith('_final200')
            mapping[name]={'executed_model':origin,'decoder_kind':model['decoder_kind'],'checkpoint_sha256':model['checkpoint']['sha256'],**descriptor,'training_logical_slot':train}
            frozen['files'][name]={'fresh':pin};frozen['oracle_files'][name]={'fresh':pin}
            for policy in q.PRIMARY_BOUNDARIES:frozen['document_files'][name+'__boundary_'+policy]={'fresh':pin}
            if train:frozen['training_files'][name]={'main':pin,'auxiliary':pin}
    receipt={'schema':'legal-timing-ownership-generation-aliases/v1','logical_models':10,'numerically_executed_models':6,
             'logical_job_mapping':mapping,'all_logical_slots_retained':True}
    frozen['generation_aliases']=q.write(tmp_path/'aliases.json',receipt)
    return frozen,data,receipt


def test_complete_logical_generation_alias_provenance(tmp_path):
    frozen,data,_=alias_inventory_fixture(tmp_path)
    assert q.verify_generation_aliases(frozen,data)['executed_models']==6


@pytest.mark.parametrize('mutation',['model','source','plan','count','files','training','dropped'])
def test_false_generation_alias_provenance_rejected(tmp_path,mutation):
    frozen,data,receipt=alias_inventory_fixture(tmp_path);name='common_continuation-1730'
    if mutation=='model':receipt['logical_job_mapping'][name]['executed_model']='parent_grounding-1730'
    if mutation=='source':receipt['logical_job_mapping'][name]['single_sources_sha256']='0'*64
    if mutation=='plan':receipt['logical_job_mapping'][name]['oracle_plans_sha256']='0'*64
    if mutation=='count':receipt['numerically_executed_models']=5
    if mutation=='files':frozen['files'][name]={'fresh':q.write(tmp_path/'other.json',{'rows':[]})}
    if mutation=='training':receipt['logical_job_mapping'][name]['training_logical_slot']=True
    if mutation=='dropped':del receipt['logical_job_mapping'][name]
    frozen['generation_aliases']=q.write(tmp_path/'changed.json',receipt)
    with pytest.raises((ValueError,AssertionError)):q.verify_generation_aliases(frozen,data)


def test_full_auxiliary_cycle_retains_unmodified_main_schedule():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_timing_ownership as runtime
    pools={'earlier':[f'e{i}' for i in range(12)],'historical_new':[f'h{i}' for i in range(18)],
           'positive_pairs':[[f'p{i}a',f'p{i}b'] for i in range(8)],'negative_pairs':[[f'n{i}a',f'n{i}b'] for i in range(8)]}
    blocks=[{'block_id':str(i),'pair_ids':[f'a{i}',f'b{i}']} for i in range(192)]
    rows=[[f'aux{i}-{j}' for j in range(4)] for i in range(192)]
    traces=[q.expected_batch(1730,step,pools,blocks,rows) for step in range(1,201)]
    assert len({r['auxiliary_block_id'] for r in traces[:192]})==192
    assert len({r['auxiliary_block_id'] for r in traces[192:]})==8
    for step,row in enumerate(traces,1):
        actual={key:deepcopy(row[key]) for key in ('optimizer_step','indices_by_pool','ids','pairs')}
        actual['indices_by_pool'].pop('auxiliary_block')
        assert actual==q.legacy.prior.expected_batch(1730,step,pools)
    expected=runtime._aux_order(192,1730,0)
    assert [r['indices_by_pool']['auxiliary_block'][0] for r in traces[:192]]==expected


def test_integer_masks_are_not_booleans_even_after_digest_repair():
    receipt,records,parts=receipt_fixture()
    receipt['ownership_masks'][0]['conditions'][0]=0
    receipt['ownership_masks_sha256']=q.digest(receipt['ownership_masks'])
    with pytest.raises((ValueError,AssertionError)):q.verify_auxiliary_receipt(receipt,records,parts,step=1)


def test_alias_builds_keep_fidelity_but_do_not_claim_reexecution():
    metric={'count':48,'built':20,'built_exact':5,'built_reference_mismatch':15,'build_invocations':1,'actual_lake_build_invocations':1}
    alias={'slot':'oracle/fallback','executed_slot':'oracle/parent','actual_backend_invocations_for_this_slot':0}
    actual=q.attribute_build_execution(metric,alias)
    assert actual['built']==20 and actual['built_exact']==5 and actual['built_reference_mismatch']==15
    assert actual['actual_lake_build_invocations']==actual['build_invocations']==0
    assert actual['bound_build_invocations']==1 and actual['build_evidence_reused'] is True
    assert actual['actual_lake_build_executed'] is False
