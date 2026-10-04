from copy import deepcopy
import math
import pytest
from scripts.ops.legal_ir import summarize_legal_scope_adapter_experiment as q


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
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as runtime
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
    model.train();out=model(*batch[:3])[1];loss,_=runtime.scope_loss(torch,out,torch.tensor([0,1]));loss.backward()
    assert all(p.grad is None for n,p in model.named_parameters() if n not in runtime.trainable_names(arm))
    assert not model.encoder.training and not model.embedding.training and not model.boundary.training


def test_valid_token_attention_oracle_and_gradient_ignore_padding():
    torch,runtime,parent=adapter_parent();initial=runtime.build_checkpoint(parent,arm='adapter',training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256=q.PARENT_SHA)
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
    child=deepcopy(initial);child['model_state']['scope.bias'][0]+=.25
    result=q.verify_frozen_states(parent,initial,child,arm,initial['trainable_parameters'])
    assert result['trainable_parameters']==(130 if arm=='control' else 1317)
    child['model_state']['embedding.weight'][1][0]+=.1
    child['frozen_non_scope_state_sha256']=q.digest(runtime.frozen_state(child['model_state']))
    with pytest.raises(ValueError):q.verify_frozen_states(parent,initial,child,arm,initial['trainable_parameters'])
    if arm=='control':
        child=deepcopy(initial);child['model_state']['scope.bias'][0]+=.25;child['model_state']['scope_residual.bias'][0]+=.5
        with pytest.raises(ValueError):q.verify_frozen_states(parent,initial,child,arm,initial['trainable_parameters'])


def test_initial_inference_checkpoint_binding_cannot_mask_numerical_output_mutation():
    torch,runtime,parent=adapter_parent();initial=runtime.build_checkpoint(parent,arm='adapter',training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256=q.PARENT_SHA)
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
    from scripts.ops.legal_ir import run_legal_scope_adapter_experiment as runner
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
    code="from pathlib import Path\nfrom scripts.ops.legal_ir import summarize_legal_scope_adapter_experiment as q\nq.init_worker([{'path':"+repr(str(file))+"}])\ntry: Path("+repr(str(file))+").read_bytes()\nexcept ValueError: pass\nelse: raise AssertionError('sealed access succeeded')\nassert len(q._WORKER_GUARD.events)==1\n"
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
