from copy import deepcopy
import math
import pytest
from scripts.ops.legal_ir import summarize_legal_heading_boundary_experiment as q


def fixture(supported=True):
    text='The clerk shall retain the file. Record duty [1]. The auditor may inspect the file.'
    identity='scope-'+q.boundary.text_sha(text)
    row={'candidate_id':identity,'source_text':text,'source_sha256':q.boundary.text_sha(text),'supported':supported,
        'clauses':[{'char_end':text.index('.')+1},{'char_end':len(text)}] if supported else []}
    tokens=q.boundary.tokenize(text);spans=[{'char_start':text.index('Record'),'char_end':text.index('The auditor')}]
    ends=[i for i,t in enumerate(tokens) if t['char_end'] in {c['char_end'] for c in row['clauses']}]
    neg=[i for i,t in enumerate(tokens) if i not in ends and q.re.fullmatch(r'[^\w\s]',t['text']) and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in spans)]
    annotation={'candidate_id':identity,'source_sha256':row['source_sha256'],'true_end_token_indices':ends,
        'editorial_hard_negative_token_indices':neg,'editorial_heading_spans':spans,'provenance':'pinned_train_endpoints_and_optional_editorial_spans/v1'}
    return row,annotation


def tensors():
    import torch
    row,annotation=fixture();labels,pos,neg=q.training_role_masks(row,annotation);length=len(labels);width=length+3
    x=torch.linspace(-2.,3.,3*width,dtype=torch.float64).reshape(3,width).requires_grad_()
    gold=torch.zeros(3,width,dtype=torch.float64);gold[0,:length]=torch.tensor(labels);gold[1,:length]=torch.tensor(labels)
    valid=torch.zeros(3,width,dtype=torch.bool);valid[:,:length]=True
    supported=torch.tensor([True,False,True]);positive=torch.zeros_like(valid);positive[0,:length]=torch.tensor(pos)
    negative=torch.zeros_like(valid);negative[0,:length]=torch.tensor(neg)
    # One shorter supported example supplies a single real terminal endpoint.
    valid[2,3:]=False;gold[2,2]=1;positive[2,2]=True
    return torch,x,gold,valid,supported,positive,negative


def test_source_bound_role_masks_include_all_editorial_punctuation_and_exact_true_ends():
    row,annotation=fixture();labels,pos,neg=q.training_role_masks(row,annotation)
    assert sum(pos)==2 and sum(neg)==3 and not any(a and b for a,b in zip(pos,neg,strict=True))
    assert labels==[float(v) for v in pos]


@pytest.mark.parametrize('mutation',['source','omit_end','heading_gold','missing_punctuation','heading_range','provenance','extra_key'])
def test_repaired_training_role_masks_cannot_change_authoritative_source_targets(mutation):
    row,a=fixture()
    if mutation=='source':a['source_sha256']='a'*64
    if mutation=='omit_end':a['true_end_token_indices'].pop()
    if mutation=='heading_gold':a['editorial_hard_negative_token_indices'].append(a['true_end_token_indices'][0])
    if mutation=='missing_punctuation':a['editorial_hard_negative_token_indices'].pop()
    if mutation=='heading_range':a['editorial_heading_spans'][0]['char_end']=len(row['source_text'])+1
    if mutation=='provenance':a['provenance']='mined_from_model_errors'
    if mutation=='extra_key':a['fresh_target']=True
    with pytest.raises(ValueError):q.training_role_masks(row,a)


def test_unsupported_documents_have_no_synthetic_allnegative_endpoint_annotation():
    row,a=fixture(False);labels,pos,neg=q.training_role_masks(row,None)
    assert not any(labels+pos+neg)
    with pytest.raises(ValueError):q.training_role_masks(row,a)


@pytest.mark.parametrize('arm',q.ARMS)
def test_supported_token_objective_value_and_gradient_match_independent_oracle(arm):
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    torch,x,y,valid,supported,pos,neg=tensors()
    actual,parts=runtime.objective_loss(torch,x,y,valid,supported,pos,neg,arm=arm)
    expected,oracle=q.boundary_loss_oracle(torch,x,y,valid,supported,pos,neg,arm)
    ga=torch.autograd.grad(actual,x,retain_graph=True)[0];ge=torch.autograd.grad(expected,x)[0]
    assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12) and torch.allclose(ga,ge,atol=1e-12,rtol=1e-12)
    assert torch.count_nonzero(ga[1])==0 and torch.count_nonzero(ga[~valid])==0
    assert parts['eligible_token_count']==int((valid&supported[:,None]).sum())
    assert parts['positive_weight']==12 and parts['unsupported_token_supervision'] is False


@pytest.mark.parametrize('arm',q.ARMS)
def test_unsupported_and_padding_logits_do_not_affect_either_objective(arm):
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    torch,x,y,valid,supported,pos,neg=tensors();eligible=valid&supported[:,None]
    first,_=runtime.objective_loss(torch,x,y,valid,supported,pos,neg,arm=arm)
    changed=x.detach().clone();changed[~eligible]=10000
    second,_=runtime.objective_loss(torch,changed,y,valid,supported,pos,neg,arm=arm)
    assert torch.equal(first.detach(),second)


@pytest.mark.parametrize('mutation',['unsupported','padding','true_end','missing_positive','empty_negative'])
def test_inadmissible_hardnegative_or_positive_mask_rejected(mutation):
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    torch,x,y,valid,supported,pos,neg=tensors()
    if mutation=='unsupported':neg[1,0]=True
    if mutation=='padding':neg[0,-1]=True
    if mutation=='true_end':neg|=pos
    if mutation=='missing_positive':pos[0]=False
    if mutation=='empty_negative':neg[:]=False
    with pytest.raises(ValueError):q.boundary_loss_oracle(torch,x,y,valid,supported,pos,neg,'rehearsal')
    with pytest.raises(ValueError):runtime.objective_loss(torch,x,y,valid,supported,pos,neg,arm='rehearsal')


def metric(raw=10,delivered=8,guard=3):
    return {'count':32,'supported':24,'unsupported':8,'raw_supported_correct':20,'raw_unsupported_accepted':6,'raw_boundary_exact':raw,'supported_exact':delivered,'unsupported_accepted':guard}


def selection_fixture():
    parent={'heading_new':metric(),'retention':metric()}
    stages=[{'steps':s,'metrics':deepcopy(parent),'raw_scope_logits_unchanged':True} for s in q.STAGES]
    return parent,stages


def test_no_candidate_when_new_tuning_boundary_exactness_does_not_strictly_improve():
    parent,stages=selection_fixture();assert q.boundary_choice(stages,parent) is None
    stages[1]['metrics']['heading_new']['raw_boundary_exact']+=1
    assert q.boundary_choice(stages,parent)['steps']==200


@pytest.mark.parametrize('mutation',['raw_regression','delivered_regression','guard_increase','scope_support_change','scope_guard_change','scope_logits_change'])
def test_boundary_gain_cannot_hide_retention_scope_or_final_guard_regression(mutation):
    parent,stages=selection_fixture();s=stages[0];s['metrics']['heading_new']['raw_boundary_exact']+=1;m=s['metrics']['retention']
    if mutation=='raw_regression':m['raw_boundary_exact']-=1
    if mutation=='delivered_regression':m['supported_exact']-=1
    if mutation=='guard_increase':m['unsupported_accepted']+=1
    if mutation=='scope_support_change':m['raw_supported_correct']-=1
    if mutation=='scope_guard_change':m['raw_unsupported_accepted']-=1
    if mutation=='scope_logits_change':s['raw_scope_logits_unchanged']=False
    assert q.boundary_choice(stages,parent) is None


def test_identical_scope_with_unchanged_nonzero_parent_guard_count_can_qualify_boundary_only():
    parent,stages=selection_fixture()
    for s in stages:s['metrics']['heading_new']['raw_boundary_exact']+=1
    assert q.boundary_choice(stages,parent)['steps']==100


def test_frozen_scope_probability_and_logits_are_checked_even_when_argmax_is_unchanged():
    parent={'rows':[{'candidate_id':'a','source_sha256':'b','scope_logits':[1.,2.],'scope_supported_probability':.7,'raw_learned_scope_supported':True}]}
    assert q.verify_frozen_scope_outputs(parent,deepcopy(parent))==1
    for key,value in [('scope_logits',[1.,2.01]),('scope_supported_probability',.71),('raw_learned_scope_supported',False)]:
        child=deepcopy(parent);child['rows'][0][key]=value
        with pytest.raises(ValueError):q.verify_frozen_scope_outputs(parent,child)


@pytest.mark.parametrize('mutation',['negative','float','boolean','denominator','oversupport','overguard','delivered_without_raw','accepted_without_scope','scope_flag_integer'])
def test_malformed_gate_denominators_and_types_fail_closed(mutation):
    parent,stages=selection_fixture();m=stages[0]['metrics']['heading_new'];m['raw_boundary_exact']+=1
    if mutation=='negative':m['supported_exact']=-1
    if mutation=='float':m['raw_boundary_exact']=11.
    if mutation=='boolean':m['unsupported_accepted']=False
    if mutation=='denominator':m['count']+=1
    if mutation=='oversupport':m['raw_boundary_exact']=25
    if mutation=='overguard':m['raw_unsupported_accepted']=9
    if mutation=='delivered_without_raw':m['supported_exact']=12
    if mutation=='accepted_without_scope':m['unsupported_accepted']=7
    if mutation=='scope_flag_integer':stages[0]['raw_scope_logits_unchanged']=1
    with pytest.raises(ValueError):q.boundary_choice(stages,parent)


def test_ranking_uses_new_raw_then_delivered_then_old_raw_then_earliest():
    parent,stages=selection_fixture()
    for s in stages:s['metrics']['heading_new']['raw_boundary_exact']=12
    assert q.boundary_choice(stages,parent)['steps']==100
    stages[1]['metrics']['retention']['raw_boundary_exact']+=1
    assert q.boundary_choice(stages,parent)['steps']==200
    stages[2]['metrics']['heading_new']['supported_exact']+=1
    assert q.boundary_choice(stages,parent)['steps']==400
    stages[0]['metrics']['heading_new']['raw_boundary_exact']+=1
    assert q.boundary_choice(stages,parent)['steps']==100


def loss_receipt_fixture():
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    row,a=fixture();rows={};roles={}
    for i in range(12):
        name=f'fictional-{i}';r=deepcopy(row);r['candidate_id']=name;note=deepcopy(a);note['candidate_id']=name;rows[name]=r;roles[name]=note
    batch={'steps':1,'common_replay_ids':list(rows)[:6],'extra_ids':list(rows)[6:],'supported_count':12,'unsupported_count':0}
    labels,pos,neg=q.training_role_masks(row,a);width=len(labels)
    logits=torch.linspace(-3.,3.,12*width).reshape(12,width)
    y=torch.tensor([labels]*12);v=torch.ones_like(y,dtype=torch.bool);p=torch.tensor([pos]*12);n=torch.tensor([neg]*12);s=torch.ones(12,dtype=torch.bool)
    loss,parts=runtime.objective_loss(torch,logits,y,v,s,p,n,arm='rehearsal')
    receipt={'steps':1,'labels':y.tolist(),'valid_mask':v.tolist(),'supported':s.tolist(),'positive_mask':p.tolist(),'negative_mask':n.tolist(),'candidate_logits':logits.tolist(),'objective_components':parts,'total_loss':float(loss)}
    return receipt,batch,rows,roles,float(loss)


def test_receipt_independently_reconstructs_all_masks_and_bce_denominators():
    record,batch,rows,roles,loss=loss_receipt_fixture()
    assert q.verify_loss_receipt(record,batch,rows,roles,loss,'rehearsal')


@pytest.mark.parametrize('mutation',['labels','negative_mask','supported','logit_nan','missing_row','denominator','class_weight','aux_weight','mask_sha','unsupported_claim','total','integer_bool'])
def test_loss_receipt_corruptions_rejected_even_with_self_consistent_report_total(mutation):
    record,batch,rows,roles,loss=loss_receipt_fixture();parts=record['objective_components']
    if mutation=='labels':record['labels'][0][-1]=0.
    if mutation=='negative_mask':record['negative_mask'][0][0]=True
    if mutation=='supported':record['supported'][0]=False
    if mutation=='logit_nan':record['candidate_logits'][0][0]=float('nan')
    if mutation=='missing_row':record['candidate_logits'].pop()
    if mutation=='denominator':parts['eligible_token_count']+=1
    if mutation=='class_weight':parts['positive_weight']=1.
    if mutation=='aux_weight':parts['auxiliary_weight']=0.
    if mutation=='mask_sha':parts['negative_mask_sha256']='a'*64
    if mutation=='unsupported_claim':parts['unsupported_token_supervision']=True
    if mutation=='total':record['total_loss']+=.1;parts['total_loss']=record['total_loss'];loss=record['total_loss']
    if mutation=='integer_bool':record['valid_mask'][0][0]=1
    with pytest.raises(ValueError):q.verify_loss_receipt(record,batch,rows,roles,loss,'rehearsal')


def test_matched_cycling_schedule_preserves_pool_order_quotas_and_epoch_wraps():
    from scripts.ops.legal_ir.run_legal_heading_boundary_experiment import old
    left=[{'candidate_id':f'left{i}','supported':True} for i in range(7)]
    right=[{'candidate_id':f'right{i}','supported':True} for i in range(11)]
    a=old.CyclingRows(left,q.random.Random(1730));b=old.CyclingRows(right,q.random.Random(1731))
    actual=q.matched_batches(left,right)
    for step,receipt in enumerate(actual,1):
        assert receipt=={'steps':step,'common_replay_ids':[r['candidate_id'] for r in a.take(6)],'extra_ids':[r['candidate_id'] for r in b.take(6)],'supported_count':12,'unsupported_count':0}


def endpoint_fixture():
    row,a=fixture();labels,pos,neg=q.training_role_masks(row,a)
    span=a['editorial_heading_spans'][0];annotation={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'factors':{'heading':'fictional'},'local_clause_coordinates':[{'editorial_context':[{'start_char':span['char_start'],'end_char':span['char_end']}]}]}
    unsupported=deepcopy(row);unsupported['source_text']+=' Unless';unsupported['source_sha256']=q.boundary.text_sha(unsupported['source_text']);unsupported['candidate_id']='scope-'+unsupported['source_sha256'];unsupported['supported']=False;unsupported['clauses']=[]
    ua=deepcopy(annotation);ua.update(candidate_id=unsupported['candidate_id'],source_sha256=unsupported['source_sha256'])
    prediction={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'boundary_logits':[1. if p else -1. for p in pos],'boundary_token_indices':a['true_end_token_indices'],'raw_learned_scope_supported':False}
    up={'candidate_id':unsupported['candidate_id'],'source_sha256':unsupported['source_sha256'],'boundary_logits':[1.]*len(q.boundary.tokenize(unsupported['source_text'])),'boundary_token_indices':list(range(len(q.boundary.tokenize(unsupported['source_text'])))),'raw_learned_scope_supported':True}
    rows=[row,unsupported];sources=[{k:r[k] for k in ('candidate_id','source_text','source_sha256')} for r in rows]
    return {'rows':[prediction,up]},sources,rows,[annotation,ua],a


def test_endpoint_diagnostics_score_scope_abstentions_and_never_invent_unsupported_gold():
    generation,sources,targets,annotations,a=endpoint_fixture();result=q.endpoint_diagnostics(generation,sources,targets,annotations)
    assert result['metrics']['documents']==2 and result['metrics']['supported_documents']==1
    assert result['metrics']['raw_endpoint_exact']==1 and result['metrics']['unsupported_without_endpoint_gold']==1
    assert result['metrics']['gold_end_count']==2 and result['metrics']['editorial_negative_tokens']==3
    assert result['rows'][1]['endpoint_error_scored'] is False and 'false_positive' not in result['rows'][1]
    p=generation['rows'][0];idx=a['editorial_hard_negative_token_indices'][0];p['boundary_logits'][idx]=0.;p['boundary_token_indices']=sorted(p['boundary_token_indices']+[idx])
    changed=q.endpoint_diagnostics(generation,sources,targets,annotations)
    assert changed['metrics']['editorial_false_ends']==1 and changed['metrics']['false_positive']==1 and changed['metrics']['raw_endpoint_exact']==0


@pytest.mark.parametrize('mutation',['missing_source','source_hash','threshold','nan'])
def test_endpoint_diagnostic_source_threshold_corruptions_fail(mutation):
    generation,sources,targets,annotations,_=endpoint_fixture()
    if mutation=='missing_source':generation['rows'].pop()
    if mutation=='source_hash':annotations[0]['source_sha256']='a'*64
    if mutation=='threshold':generation['rows'][0]['boundary_token_indices']=[]
    if mutation=='nan':generation['rows'][0]['boundary_logits'][0]=float('nan')
    with pytest.raises(ValueError):q.endpoint_diagnostics(generation,sources,targets,annotations)


def test_actual_os_guard_blocks_file_before_release_then_records_open(tmp_path):
    import subprocess,sys
    secret=tmp_path/'sealed.json';secret.write_text('{}')
    program='''import json,sys\nfrom scripts.ops.legal_ir import summarize_legal_heading_boundary_experiment as q\np=sys.argv[1];g=q.SealedReadGuard([q.ref(p)]);sys.addaudithook(g.event)\ntry:open(p).read()\nexcept (PermissionError,ValueError,RuntimeError):pass\nelse:raise AssertionError("sealed read succeeded")\nassert len(g.events)==1 and not g.events[0]["after_build_freeze"]\ng.released=True\nassert open(p).read()=="{}"\nassert g.events[-1]["after_build_freeze"]\n'''
    result=subprocess.run([sys.executable,'-c',program,str(secret)],cwd=q.ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def state_fixture():
    parent={'model_state':{'encoder.weight':[[1.,2.]],'scope.weight':[[3.,4.]],'boundary.weight':[[5.,6.]]}}
    residual={'boundary_hidden.weight':[[0.]*64 for _ in range(16)],'boundary_hidden.bias':[0.]*16,'boundary_residual.weight':[[0.]*16],'boundary_residual.bias':[0.]}
    initial={'model_state':{**deepcopy(parent['model_state']),**residual}};candidate=deepcopy(initial);candidate['model_state']['boundary_residual.bias'][0]=.01
    return parent,initial,candidate,list(residual)


def test_only_1057_boundary_residual_parameters_may_change():
    parent,initial,candidate,names=state_fixture()
    result=q.verify_frozen_states(parent,initial,candidate,'rehearsal',names)
    assert result['trainable_parameters']==1057 and result['all_original_parent_tensors_exact']


@pytest.mark.parametrize('mutation',['encoder','scope','old_boundary','missing_residual','extra_parameter','nan','unchanged'])
def test_frozen_original_state_and_closed_residual_inventory_corruption_rejected(mutation):
    parent,initial,candidate,names=state_fixture()
    if mutation in ('encoder','scope','old_boundary'):candidate['model_state'][{'encoder':'encoder.weight','scope':'scope.weight','old_boundary':'boundary.weight'}[mutation]][0][0]+=.1
    if mutation=='missing_residual':candidate['model_state']['boundary_hidden.weight'].pop()
    if mutation=='extra_parameter':candidate['model_state']['new.weight']=[0.]
    if mutation=='nan':candidate['model_state']['boundary_residual.bias'][0]=float('nan')
    if mutation=='unchanged':candidate=deepcopy(initial)
    with pytest.raises(ValueError):q.verify_frozen_states(parent,initial,candidate,'control',names)


def test_randomized_float64_loss_and_gradient_oracle_fifty_cases():
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    generator=torch.Generator().manual_seed(193047)
    for i in range(50):
        _,x,y,valid,supported,pos,neg=tensors();x=(torch.randn(x.shape,generator=generator,dtype=torch.float64)*8).requires_grad_()
        arm=q.ARMS[i%2];actual,_=runtime.objective_loss(torch,x,y,valid,supported,pos,neg,arm=arm)
        expected,_=q.boundary_loss_oracle(torch,x,y,valid,supported,pos,neg,arm)
        ga=torch.autograd.grad(actual,x,retain_graph=True)[0];ge=torch.autograd.grad(expected,x)[0]
        assert torch.allclose(actual,expected,atol=2e-12,rtol=2e-12) and torch.allclose(ga,ge,atol=2e-12,rtol=2e-12)
