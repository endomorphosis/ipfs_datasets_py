"""Synthetic clause architecture/causality invariants, not formal qualification."""
from copy import deepcopy
import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import projected_source_decoder_experiment as projected
from ipfs_datasets_py.logic.formalization.autoencoder import shared_slot_source_decoder_experiment as shared
from .test_projected_source_decoder_experiment import bound as donor_bound, encode, inputs
from .test_clause_source_context import fixtures, transform


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def bound(dimension=8, seed=1729):
    base, codec, _ = donor_bound(dimension,kind="center_rms",guided=True)
    train, validation, _, contexts = fixtures(dimension)
    unique = contexts_owner.unique_training_clauses(train,validation,contexts)
    with torch.no_grad(): features = base.project(torch.tensor([row["input"] for row in unique])).tolist()
    rows = [dict(id=row["id"], source_sha256=row["source_sha256"], features=value) for row,value in zip(unique,features)]
    receipt = projected.fit_source_normalization(rows,kind="center_rms",expected_training_ids=[row["id"] for row in rows],
        forbidden_validation_ids=[row["id"] for row in contexts_owner.validate_training_contexts(train,validation,contexts)["validation_clause_inventory"]],
        training_rows_sha256="a"*64)
    receipt["training_contexts_sha256"] = core.digest(contexts["train"])
    receipt["receipt_sha256"] = core.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"})
    model = subject.bind_clause_source_model(base,head_seed=seed,clause_normalization_receipt=receipt)
    packet = contexts_owner.batch_source_context(torch,train,contexts["train"],transform(dimension))
    return model,base,codec,packet,receipt


def trained(model):
    with torch.no_grad():
        gen = torch.Generator().manual_seed(55)
        for p in model.clause_head.parameters(): p.uniform_(-.3,.3,generator=gen)
    return model


@pytest.mark.parametrize("dimension", [8,384,768])
def test_zero_initialized_full_logits_projection_and_donor_parity(dimension):
    model,base,codec,packet,_ = bound(dimension)
    before = core.tensor_digest(base)
    x = inputs(dimension,1); prefix = torch.tensor([encode(codec)])
    actual, logits = model(x,prefix,source_context=packet)
    expected, original = base(x,prefix)
    assert torch.equal(actual,expected) and torch.equal(logits,original)
    spec = subject.checked_specification(model,codec)
    assert spec["source_value_parameter_count"] == (dimension+1)*64+65*4*len(codec["target_vocabulary"])
    assert not spec["slot_parameters"] and spec["source_context_required"] and not spec["admitted"]
    assert core.tensor_digest(base) == before
    assert not dict(model.body.source_value_head.named_parameters())


def test_private_rng_same_shared_initial_source_weights_and_copy_preserved():
    base,codec,_ = donor_bound(8,kind="center_rms",guided=True)
    before = core.tensor_digest(base); rng = torch.random.get_rng_state().clone()
    model,_,_,_,receipt = bound()
    # Fixture creation consumes RNG in donor setup; test binding itself separately.
    rng = torch.random.get_rng_state().clone()
    private = subject.bind_clause_source_model(base,head_seed=1729,clause_normalization_receipt=receipt)
    assert torch.equal(rng,torch.random.get_rng_state()) and core.tensor_digest(base)==before
    comparator = shared.bind_shared_slot_source_model(base,head_seed=1729)
    for name,p in private.clause_head.named_parameters():
        assert torch.equal(p,dict(comparator.body.source_value_head.named_parameters())[name])
        assert p.data_ptr() != dict(model.clause_head.named_parameters())[name].data_ptr()


def test_position_free_shared_head_is_exactly_equivariant_and_full_vocabulary():
    model,_,codec,packet,_ = bound(); trained(model)
    x=model.project(inputs(8,1)); values=model.source_value_logits(x,source_context=packet)
    swapped={"vectors":packet["vectors"].clone(),"mask":packet["mask"].clone()}
    swapped["vectors"][:,[0,1]]=swapped["vectors"][:,[1,0]]
    observed=model.source_value_logits(x,source_context=swapped)
    assert torch.equal(observed[:,0],values[:,1]) and torch.equal(observed[:,1],values[:,0])
    assert observed.shape==(1,8,4,len(codec["target_vocabulary"])) and not observed[:,2:].any()
    assert torch.count_nonzero(observed[:,:2]).item()==2*4*len(codec["target_vocabulary"])
    assert not torch.equal(values[:,0],values[:,1])


def test_clause_mask_only_changes_scalar_values_not_count_or_recurrent_state():
    model,_,_,packet,_=bound(); trained(model); x=model.project(inputs(8,1))
    one={"vectors":packet["vectors"].clone(),"mask":packet["mask"].clone()}
    one["vectors"][:,1:]=0;one["mask"][:,1:]=False
    a=model.start(x,source_context=packet);b=model.start(x,source_context=one)
    assert all(torch.equal(left,right) for left,right in zip(a[:-1],b[:-1]))
    assert torch.equal(a[-1][:,0],b[-1][:,0]) and not b[-1][:,1:].any()


def test_hidden_readout_gradient_and_frozen_projection():
    model,_,_,packet,_=bound(); trained(model)
    loss=model.source_value_logits(model.project(inputs(8,1)),source_context=packet).square().sum()
    loss.backward()
    assert all(p.grad is not None and torch.count_nonzero(p.grad) for p in model.clause_head.parameters())
    for name,p in model.named_parameters():
        if "projection_down." in name or "projection_up." in name:
            assert not p.requires_grad and p.grad is None


def test_zero_control_removes_both_source_and_clause_count_signal_retains_bias():
    model,_,codec,packet,_=bound();trained(model);zero=subject.bind_zero_condition_model(model)
    other={"vectors":torch.zeros_like(packet["vectors"]),"mask":torch.ones_like(packet["mask"])}
    other["vectors"][:]=torch.randn(other["vectors"].shape,generator=torch.Generator().manual_seed(5))
    a=zero.start(zero.project(inputs(8,1)),source_context=packet)
    b=zero.start(zero.project(inputs(8,1)+20),source_context=other)
    assert all(torch.equal(left,right) for left,right in zip(a,b))
    assert not a[0].any() and not a[1].any()
    assert a[-1].any() and torch.equal(a[-1][:,0],a[-1][:,7])
    prefix=torch.tensor([encode(codec)])
    assert torch.equal(zero.next_logits(prefix,a)[0],zero.next_logits(prefix,b)[0])


@pytest.mark.parametrize("method", ["start","source_value_logits","source_value_guidance_logits"])
def test_missing_context_has_no_fallback(method):
    model,_,_,_,_=bound()
    with pytest.raises(TypeError): getattr(model,method)(model.project(inputs(8,1)))


@pytest.mark.parametrize("mutation", ["field","dtype","shape","finite","requiresgrad","maskdtype","empty","hole","padding"])
def test_packet_guards(mutation):
    model,_,_,packet,_=bound(); x=model.project(inputs(8,1))
    if mutation=="field":packet["target_ids"]=[]
    elif mutation=="dtype":packet["vectors"]=packet["vectors"].double()
    elif mutation=="shape":packet["vectors"]=packet["vectors"][:,:7]
    elif mutation=="finite":packet["vectors"][0,0,0]=float("nan")
    elif mutation=="requiresgrad":packet["vectors"].requires_grad_()
    elif mutation=="maskdtype":packet["mask"]=packet["mask"].long()
    elif mutation=="empty":packet["mask"][:]=False;packet["vectors"][:]=0
    elif mutation=="hole":packet["mask"][0,1]=False;packet["mask"][0,2]=True;packet["vectors"][0,1]=0
    else:packet["vectors"][0,7,0]=1
    with pytest.raises(ValueError):model.start(x,source_context=packet)


@pytest.mark.parametrize("field", ["clause_source_mean","clause_source_scale","head_initialization_seed","body.source_mean","body.count_prior_logits"])
def test_frozen_restore_rejects_before_mutating_parameters(field):
    model,_,_,_,_=bound(); state=deepcopy(model.state_dict()); before=core.tensor_digest(model)
    state["clause_head.source_projection.weight"]+=1
    state[field]=state[field]+1
    with pytest.raises(ValueError):model.load_state_dict(state,strict=False)
    assert core.tensor_digest(model)==before


def test_state_reload_and_seed_dtype_stale_old_head_guards():
    model,_,_,_,_=bound(); trained(model); other,_,_,_,_=bound()
    other.load_state_dict(model.state_dict());assert core.tensor_digest(model)==core.tensor_digest(other)
    for kind in ("dtype","oldhead"):
        state=deepcopy(model.state_dict())
        if kind=="dtype":state["head_initialization_seed"]=state["head_initialization_seed"].float()
        else:state["body.source_value_head.weight"]=torch.zeros(1)
        with pytest.raises(ValueError):other.load_state_dict(state,strict=False)


@pytest.mark.parametrize("mutation", ["digest","contextdigest","missingcontextdigest","sourceid","forbidden","scale","kind","cohort","policy"])
def test_receipt_rejects_bad_stats_bindings(mutation):
    _,base,_,_,receipt=bound()
    if mutation=="digest":receipt["receipt_sha256"]="0"*64
    elif mutation=="contextdigest":receipt["training_contexts_sha256"]="bad"
    elif mutation=="missingcontextdigest":del receipt["training_contexts_sha256"]
    elif mutation=="sourceid":receipt["training_inventory"][0]["id"]="target:foo"
    elif mutation=="forbidden":receipt["forbidden_validation_ids"]=[receipt["expected_training_ids"][0]]
    elif mutation=="scale":receipt["scale"]*=2
    elif mutation=="kind":receipt["kind"]="none"
    elif mutation=="cohort":receipt["training_rows_sha256"]="b"*64
    else:receipt["admitted"]=True
    if mutation!="digest":receipt["receipt_sha256"]=core.digest({k:v for k,v in receipt.items() if k!="receipt_sha256"})
    with pytest.raises(ValueError):subject.bind_clause_source_model(base,head_seed=1729,clause_normalization_receipt=receipt)


def test_fitted_old_head_and_invalid_seed_fail_closed():
    _,base,_,_,receipt=bound()
    with pytest.raises(ValueError):subject.bind_clause_source_model(base,head_seed=True,clause_normalization_receipt=receipt)
    with torch.no_grad():base.source_value_head.bias[0]=1
    with pytest.raises(ValueError):subject.bind_clause_source_model(base,head_seed=1,clause_normalization_receipt=receipt)


@pytest.mark.parametrize("mutation", ["buffer","frozenprojection","headtrainable","describe","codec","headgeometry"])
def test_checked_spec_rejects_actual_architecture_tampering(mutation):
    model,_,codec,_,_=bound()
    if mutation=="buffer":model.clause_source_mean+=1
    elif mutation=="frozenprojection":
        next(p for n,p in model.named_parameters() if "projection_down." in n).requires_grad_()
    elif mutation=="headtrainable":model.clause_head.field_readout.weight.requires_grad_(False)
    elif mutation=="describe":
        original=model.describe;model.describe=lambda:original()|{"slot_parameters":True}
    elif mutation=="codec":codec["target_vocabulary"].append('"intruder"')
    else:model.clause_head.field_readout=torch.nn.Linear(64,1)
    with pytest.raises(ValueError):subject.checked_specification(model,codec)


@pytest.mark.parametrize("mutation",["shape","dtype","nan","missing"])
def test_malformed_restore_preflight_never_partially_mutates(mutation):
    model,_,_,_,_=bound();state=deepcopy(model.state_dict());before=core.tensor_digest(model)
    state["clause_head.source_projection.weight"]+=1
    key="clause_head.field_readout.weight"
    if mutation=="shape":state[key]=state[key][:1]
    elif mutation=="dtype":state[key]=state[key].double()
    elif mutation=="nan":state[key][0,0]=float("nan")
    else:del state[key]
    with pytest.raises(ValueError):model.load_state_dict(state)
    assert core.tensor_digest(model)==before
