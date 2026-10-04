from copy import deepcopy
import math
import pytest
from scripts.ops.legal_ir import summarize_legal_scope_preservation_experiment as q


def source(text='The clerk shall retain the record.'):
    h=q.boundary.text_sha(text)
    return {'candidate_id':'scope-'+h,'source_text':text,'source_sha256':h}


def test_opaque_source_contract_retains_text_without_class_metadata():
    result=q.verify_opaque_sources([source()])
    assert result['source_rows']==1 and result['labels_or_pair_membership_in_source_metadata'] is False


@pytest.mark.parametrize('mutation',['class_id','pair_key','side_key','sha','duplicate'])
def test_class_metadata_and_unbound_source_hash_rejected(mutation):
    rows=[source()]
    if mutation=='class_id':rows[0]['candidate_id']='scope-independent-'+rows[0]['source_sha256']
    if mutation=='pair_key':rows[0]['pair_id']='pair-0'
    if mutation=='side_key':rows[0]['side']=1
    if mutation=='sha':rows[0]['source_sha256']='0'*64
    if mutation=='duplicate':rows.append(deepcopy(rows[0]))
    with pytest.raises(ValueError):q.verify_opaque_sources(rows)


@pytest.mark.parametrize('supported',[3,4,6,8,9])
def test_scope_loss_oracle_reconstructs_weighted_ce_and_gradient(supported):
    import torch
    generator=torch.Generator().manual_seed(621+supported)
    a=torch.randn(12,2,generator=generator,dtype=torch.float64,requires_grad=True)
    b=a.detach().clone().requires_grad_();labels=[1]*supported+[0]*(12-supported)
    expected=torch.nn.functional.cross_entropy(a,torch.tensor(labels),weight=torch.tensor([3.,1.],dtype=torch.float64))
    actual,parts=q.scope_loss_oracle(torch,b,labels)
    assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12)
    assert torch.allclose(torch.autograd.grad(actual,b)[0],torch.autograd.grad(expected,a)[0],atol=1e-12,rtol=1e-12)
    receipt={k:float(v) if torch.is_tensor(v) else v for k,v in parts.items()}
    assert q.verify_scope_loss_receipt(receipt,{'supported_count':supported,'unsupported_count':12-supported},float(actual))


@pytest.mark.parametrize('mutation',['denominator','class_counts','loss','nan','negative'])
def test_weighted_loss_receipts_cannot_hide_denominator_or_class_changes(mutation):
    p={'unsupported_count':4,'supported_count':8,'unsupported_nll_sum':8.,'supported_nll_sum':4.,'weighted_denominator':20}
    e={'unsupported_count':4,'supported_count':8};loss=1.4
    if mutation=='denominator':p['weighted_denominator']=12
    if mutation=='class_counts':p['unsupported_count']=3;p['supported_count']=9
    if mutation=='loss':loss=28/12
    if mutation=='nan':p['unsupported_nll_sum']=math.nan
    if mutation=='negative':p['supported_nll_sum']=-1.
    with pytest.raises(ValueError):q.verify_scope_loss_receipt(p,e,loss)


def sampler_fixture():
    old=[{'candidate_id':f'old-{i}','supported':i%3!=0} for i in range(17)]
    new=[];pairs=[]
    for i in range(11):
        ids=[f'new-{i}-{j}' for j in range(2)]
        new.extend({'candidate_id':identity,'supported':j==0} for j,identity in enumerate(ids))
        pairs.append({'pair_id':str(i),'independent_id':ids[0],'nested_id':ids[1]})
    return old,new,pairs


def test_both_arms_have_identical400_step_sources_and_complete_pool_wraps():
    receipts=q.matched_batches(*sampler_fixture());assert len(receipts)==400
    assert receipts==q.matched_batches(*sampler_fixture())
    assert {r['steps'] for r in receipts}==set(range(1,401))
    assert all(len(r['common_replay_ids'])==len(r['extra_ids'])==6 and len(r['pair_ids'])==3 and r['supported_count']+r['unsupported_count']==12 for r in receipts)
    assert len({identity for r in receipts for identity in r['common_replay_ids']})==17
    assert len({identity for r in receipts for identity in r['pair_ids']})==11


def test_sampler_refuses_contrastive_class_inversion():
    old,new,pairs=sampler_fixture();new[0]['supported']=False
    with pytest.raises(ValueError):q.matched_batches(old,new,pairs)


def adapter_parent():
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(741);network=q.boundary.model(torch)
    parent=q.boundary.checkpoint(network,steps=800,training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64)
    return torch,runtime,parent


@pytest.mark.parametrize('arm',q.ARMS)
def test_exact_initialization_frozen_features_and_complete_parent_predictions(arm):
    torch,runtime,parent=adapter_parent();manifest={'arm':arm};tuning={'unit':[]};pin={'sha256':q.PARENT_SHA}
    initial=runtime.build_checkpoint(parent,arm=arm,training_manifest_sha256=q.digest(manifest),tuning_manifest_sha256=q.digest(tuning),parent_file_sha256=q.PARENT_SHA)
    assert q.verify_initialization(parent,initial,arm,manifest,tuning,pin)
    sources={'unit':[source(),source('The registrar may retain the permit within 4 days.')]}
    original={'unit':q.clauses.decode_all(q.boundary.ClauseBoundaryDecoder(parent),sources['unit'])}
    audit=q.initial_parent_parity(initial,original,sources)
    assert audit['source_evaluations']==2 and audit['all_numeric_and_final_outputs_equal_parent']
    _,model=runtime.restore(initial);batch=q.boundary.tensor_batch(torch,sources['unit'])
    model.train();out=model(*batch[:3])[1];loss,_=runtime.objective_loss(torch,out,torch.tensor([0,1]),teacher_logits=out.detach(),arm=arm);loss.backward()
    assert all(p.grad is None for n,p in model.named_parameters() if n not in runtime.trainable_names(arm))
    assert not model.encoder.training and not model.embedding.training and not model.boundary.training


def test_valid_token_attention_oracle_and_gradient_ignore_padding():
    torch,runtime,parent=adapter_parent();initial=runtime.build_checkpoint(parent,arm='control',training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256=q.PARENT_SHA)
    _,network=runtime.restore(initial);network.double()
    rng=torch.Generator().manual_seed(817)
    values=torch.randn(3,7,64,dtype=torch.float64,generator=rng,requires_grad=True);lengths=torch.tensor([1,4,7])
    actual,weights=network.attend(values,lengths);expected,wanted=q.attention_oracle(torch,network,values,lengths)
    assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12) and torch.allclose(weights,wanted,atol=1e-12,rtol=1e-12)
    parameters=[values,network.attention_hidden.weight,network.attention_score.weight]
    ga=torch.autograd.grad(actual.square().sum(),parameters,retain_graph=True)
    ge=torch.autograd.grad(expected.square().sum(),parameters)
    assert all(torch.allclose(a,b,atol=1e-11,rtol=1e-11) for a,b in zip(ga,ge,strict=True))
    assert torch.count_nonzero(weights[0,1:])==torch.count_nonzero(weights[1,4:])==0
    changed=values.detach().clone();changed[0,1:]=1e9;changed[1,4:]=-1e9
    again,_=network.attend(changed,lengths)
    assert torch.equal(actual.detach(),again.detach())


@pytest.mark.parametrize('arm',q.ARMS)
def test_frozen_state_verifier_rejects_repaired_hash_encoder_or_control_adapter_changes(arm):
    torch,runtime,parent=adapter_parent();initial=runtime.build_checkpoint(parent,arm=arm,training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256=q.PARENT_SHA)
    child=deepcopy(initial);child['model_state']['scope_residual.bias'][0]+=.25
    result=q.verify_frozen_states(parent,initial,child,arm,initial['trainable_parameters'])
    assert result['trainable_parameters']==(1187 if arm in q.FROZEN_READOUT else 1317)
    child['model_state']['embedding.weight'][1][0]+=.1
    child['frozen_non_scope_state_sha256']=q.digest(runtime.frozen_state(child['model_state']))
    with pytest.raises(ValueError):q.verify_frozen_states(parent,initial,child,arm,initial['trainable_parameters'])
    if arm in q.FROZEN_READOUT:
        child=deepcopy(initial);child['model_state']['scope_residual.bias'][0]+=.25;child['model_state']['scope.bias'][0]+=.5
        with pytest.raises(ValueError):q.verify_frozen_states(parent,initial,child,arm,initial['trainable_parameters'])


def test_initial_inference_checkpoint_binding_cannot_mask_numerical_output_mutation():
    torch,runtime,parent=adapter_parent();initial=runtime.build_checkpoint(parent,arm='control',training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256=q.PARENT_SHA)
    sources={'unit':[source()]};original={'unit':q.clauses.decode_all(q.boundary.ClauseBoundaryDecoder(parent),sources['unit'])}
    original['unit']['rows'][0]['scope_logits'][0]+=.1
    with pytest.raises(ValueError):q.initial_parent_parity(initial,original,sources)


def test_native_selection_preserves192_abstentions_across_both_immutable_lowering_batches():
    sources=[source(f'The clerk{i} shall retain the record{i}.') for i in range(192)]
    rows=[{'candidate_id':s['candidate_id'],'source_sha256':s['source_sha256'],'composition':None,'status':'abstained','reason':'learned_scope_abstention'} for s in sources]
    result=q.document_selection(rows,sources,toolchain='leanprover/lean4:v4.34.1')
    assert result['source_count']==len(result['excluded'])==192 and not result['rows']
    rows[-1]=deepcopy(rows[0])
    with pytest.raises(ValueError):q.document_selection(rows,sources,toolchain='leanprover/lean4:v4.34.1')


def test_matched_sampler_matches_frozen_runner_across400_actual_admitted_update_batches():
    from scripts.ops.legal_ir import prepare_legal_scope_adapter_corpus as corpus
    from scripts.ops.legal_ir import run_legal_scope_preservation_experiment as runner
    rows=[];pairs=[]
    for i in range(8):
        pair,metadata,_=corpus.make_pair('train',i);rows.extend(pair);pairs.append(metadata)
    old=[]
    for i,r in enumerate(rows):old.append({**r,'candidate_id':'history-'+str(i)})
    expected=q.matched_batches(old,rows,pairs)
    assert expected==[receipt for _,receipt in runner.batch_schedule(old,rows,pairs)]


def test_worker_OS_guard_blocks_current_reference_file(tmp_path):
    import subprocess,sys
    from pathlib import Path
    file=tmp_path/'fresh.sealed.json';file.write_text('{}')
    code="from pathlib import Path\nfrom scripts.ops.legal_ir import summarize_legal_scope_preservation_experiment as q\nq.init_worker([{'path':"+repr(str(file))+"}])\ntry: Path("+repr(str(file))+").read_bytes()\nexcept ValueError: pass\nelse: raise AssertionError('sealed access succeeded')\nassert len(q._WORKER_GUARD.events)==1\n"
    result=subprocess.run([sys.executable,'-c',code],cwd=Path(q.ROOT),capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_all_three_stage_scope_selection_retains_raw_guard_failures_and_parent_fallback():
    def metric(supported=12,guard=0):return {'count':32,'supported':24,'unsupported':8,'raw_supported_correct':supported,'raw_unsupported_accepted':guard,'supported_exact':10,'unsupported_accepted':0,'raw_boundary_exact':10}
    parent={'scope_new':metric(),'retention':metric()}
    stages=[{'steps':step,'metrics':deepcopy(parent),'raw_token_logits_unchanged':True} for step in q.STAGES]
    for s in stages:s['metrics']['scope_new']['raw_unsupported_accepted']=1
    assert q.scope_choice(stages,parent) is None
    stages[1]['metrics']['scope_new']['raw_unsupported_accepted']=0
    assert q.scope_choice(stages,parent)['steps']==200
    stages[1]['metrics']['retention']['raw_supported_correct']=11
    assert q.scope_choice(stages,parent) is None


@pytest.mark.parametrize('arm',q.ARMS)
@pytest.mark.parametrize('teacher_mode',['mixed','none','all','ties'])
def test_independent_parent_kl_oracle_and_candidate_gradient_with_detached_teacher(arm,teacher_mode):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    generator=torch.Generator().manual_seed(551)
    labels=torch.tensor([0,1]*6)
    candidate=torch.randn(12,2,generator=generator,dtype=torch.float64,requires_grad=True)
    teacher=torch.randn(12,2,generator=generator,dtype=torch.float64)
    if teacher_mode=='none':teacher=torch.nn.functional.one_hot(1-labels,2).double()*2
    if teacher_mode=='all':teacher=torch.nn.functional.one_hot(labels,2).double()*2
    if teacher_mode=='ties':teacher=torch.zeros(12,2,dtype=torch.float64)
    teacher.requires_grad_(True)
    actual,parts=runtime.objective_loss(torch,candidate,labels,teacher_logits=teacher,arm=arm)
    oracle,expected=q.preservation_loss_oracle(torch,candidate,labels,teacher,arm)
    ga,gt=torch.autograd.grad(actual,(candidate,teacher),allow_unused=True,retain_graph=True)
    ge,gett=torch.autograd.grad(oracle,(candidate,teacher),allow_unused=True)
    assert torch.allclose(actual,oracle,atol=1e-12,rtol=1e-12)
    assert torch.allclose(ga,ge,atol=1e-12,rtol=1e-12) and gt is None and gett is None
    assert parts['teacher_correct_mask']==expected['teacher_correct_mask']
    if teacher_mode=='none':assert parts['teacher_correct_count']==0 and parts['teacher_kl']==0
    if teacher_mode=='ties':assert parts['teacher_correct_mask']==[True,False]*6


def objective_fixture(arm='distill'):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    labels=[0,1]*6;teacher=torch.tensor([[2.,-1.],[-2.,3.],[-1.,1.],[2.,-1.]]*3)
    candidate=torch.tensor([[.2,-.3],[-.2,.3],[.4,-.1],[.2,-.4]]*3)
    loss,parts=runtime.objective_loss(torch,candidate,torch.tensor(labels),teacher_logits=teacher,arm=arm)
    exposure={'steps':1,'unsupported_count':6,'supported_count':6}
    actual={'steps':1,**{k:parts[k] for k in ('unsupported_count','supported_count','unsupported_nll_sum','supported_nll_sum','weighted_denominator')},'candidate_logits':candidate.tolist(),'objective_components':parts,'total_loss':float(loss)}
    expected={'steps':1,'labels':labels,'teacher_logits':teacher.tolist(),'teacher_correct_mask':parts['teacher_correct_mask']}
    record={'steps':1,'scope_labels':labels,'teacher_logits':teacher.tolist(),'teacher_correct_mask':parts['teacher_correct_mask']}
    return actual,record,expected,exposure,float(loss),arm


def test_complete_logged_candidate_and_teacher_loss_receipt_matches_independent_oracle():
    for arm in q.ARMS:assert q.verify_objective_receipt(*objective_fixture(arm))


@pytest.mark.parametrize('mutation',['mask','teacher_logit','teacher_sha','correct_count','correct_class','temperature','weight','direction_value','candidate','labels','weighted_KL','total','detach','classweighted','nonfinite','CE_denom'])
def test_repaired_objective_receipts_reject_teacher_or_loss_corruption(mutation):
    p,t,e,b,loss,arm=objective_fixture();o=p['objective_components']
    if mutation=='mask':t['teacher_correct_mask']=[not v for v in t['teacher_correct_mask']]
    if mutation=='teacher_logit':t['teacher_logits'][0][0]+=.1
    if mutation=='teacher_sha':o['teacher_scope_logits_sha256']='a'*64
    if mutation=='correct_count':o['teacher_correct_count']+=1
    if mutation=='correct_class':o['teacher_correct_unsupported_count']+=1
    if mutation=='temperature':o['teacher_kl_temperature']=2
    if mutation=='weight':o['teacher_kl_weight']=.5
    if mutation=='direction_value':o['teacher_kl']+=.1
    if mutation=='candidate':p['candidate_logits'][0][0]+=1
    if mutation=='labels':t['scope_labels']=[1-v for v in t['scope_labels']]
    if mutation=='weighted_KL':o['weighted_teacher_kl']+=.1
    if mutation=='total':p['total_loss']+=.1
    if mutation=='detach':o['teacher_logits_detached']=False
    if mutation=='classweighted':o['teacher_kl_class_weighted']=True
    if mutation=='nonfinite':p['candidate_logits'][0][0]=math.nan
    if mutation=='CE_denom':p['weighted_denominator']=12
    with pytest.raises(ValueError):q.verify_objective_receipt(p,t,e,b,loss,arm)


def test_wrong_parent_predictions_receive_no_kl_candidate_gradient():
    import torch
    labels=torch.tensor([0,1]);candidate=torch.tensor([[.5,-.7],[-.8,.9]],dtype=torch.float64,requires_grad=True)
    teacher=torch.tensor([[2.,-2.],[2.,-2.]],dtype=torch.float64)
    total,parts=q.preservation_loss_oracle(torch,candidate,labels,teacher,'distill')
    assert parts['teacher_correct_mask']==[True,False]
    grad=torch.autograd.grad(parts['teacher_kl'],candidate)[0]
    assert torch.count_nonzero(grad[0])>0 and torch.count_nonzero(grad[1])==0


def test_primary_scope_ties_follow_preregistered_simplicity_order_without_omitting_slots():
    audits=[{'name':a,'selection':'candidate','selected_steps':400} for a in q.ARMS]
    scores={a:{400:{'scope_new':{'raw_supported_correct':48,'supported_exact':30},'retention':{'supported_exact':20}}} for a in q.ARMS}
    for arm in q.ARMS:
        assert q.primary_scope_choice(audits,scores)==arm
        next(a for a in audits if a['name']==arm)['selection']='parent_fallback_no_eligible_scope_stage'
    assert q.primary_scope_choice(audits,scores)=='parent'
    with pytest.raises(ValueError):q.primary_scope_choice(audits[:-1],scores)


def test_primary_scope_rank_prefers_supported_retention_before_simplicity_or_later_stage():
    audits=[{'name':a,'selection':'candidate','selected_steps':400} for a in q.ARMS]
    scores={a:{400:{'scope_new':{'raw_supported_correct':48,'supported_exact':30},'retention':{'supported_exact':20}}} for a in q.ARMS}
    scores['freeze_distill'][400]['retention']['supported_exact']=21
    assert q.primary_scope_choice(audits,scores)=='freeze_distill'
    scores['freeze_distill'][400]['scope_new']['raw_supported_correct']=47
    assert q.primary_scope_choice(audits,scores)=='control'


def test_teacher_mask_integer_aliases_cannot_hide_nonboolean_receipts():
    p,t,e,b,loss,arm=objective_fixture()
    t['teacher_correct_mask']=[int(v) for v in t['teacher_correct_mask']]
    with pytest.raises(ValueError):q.verify_objective_receipt(p,t,e,b,loss,arm)
