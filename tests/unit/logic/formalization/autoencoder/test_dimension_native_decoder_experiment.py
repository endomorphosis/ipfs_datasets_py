"""Synthetic native-width contract tests; no semantic or teacher qualification."""
from copy import deepcopy
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import dimension_native_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as adapter
from .test_decoder_distillation_experiment_v2 import body, data


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_actual_dimensions_identity_projection_copied_decoder_and_receipt(dimension):
    donor = body(); initial = core.tensor_digest(donor)
    model, receipt = subject.bind_dimension_native_body(donor, dimension=dimension)
    assert adapter._body_spec(model, dimension, torch)["dimension"] == dimension
    assert not hasattr(model, "dimension")
    assert set(model.state_dict()) == adapter._BODY_PARAMETERS
    assert model.condition.in_features == model.projection_down.in_features == dimension
    assert model.projection_up.out_features == dimension
    assert model.condition.out_features == donor.condition.out_features
    source, prefix = data(dimension)
    projected, logits = model(source, prefix)
    assert torch.equal(projected, source)
    assert logits.shape == (3,4,5) and torch.count_nonzero(model.start(projected)) == 0
    for name in subject.COPIED_NAMES:
        assert torch.equal(model.state_dict()[name], donor.state_dict()[name])
        assert model.state_dict()[name].data_ptr() != donor.state_dict()[name].data_ptr()
    assert subject.checked_specification(model, receipt) == receipt
    assert receipt["input_dimension"] == receipt["projected_output_dimension"] == dimension
    assert receipt["initial_tensor_sha256"] == core.tensor_digest(model)
    assert receipt["donor_tensor_sha256"] == initial == core.tensor_digest(donor)
    assert receipt["copied_parameter_names"] == list(subject.COPIED_NAMES)
    assert receipt["reset_parameter_names"] == list(subject.RESET_NAMES)
    assert receipt["reconstruction_mse_scope"] == "identity_by_construction_not_learned_reconstruction"
    assert all(receipt[key] is False for key in subject.FALSE)
    assert receipt["native_sidecar"] and not receipt["historical_8d_linguistic_teacher"]


def test_initial_logits_and_complete_greedy_sequences_match_all_dimensions_and_sources():
    donor = body(); outcomes=[]; logits=[]
    for dimension in (8,384,768):
        native, _ = subject.bind_dimension_native_body(donor, dimension=dimension)
        persistent = adapter.bind_persistent_model(native, dimension=dimension)
        source, prefix = data(dimension)
        logits.append(persistent(source,prefix)[1])
        with torch.inference_mode():
            result=core._greedy(torch,persistent,source,32,5,time.monotonic()+10)
            zero=core._greedy(torch,persistent,torch.zeros_like(source),32,5,time.monotonic()+10)
        assert result[1:] == zero[1:]
        outcomes.append(result[1:])
    assert all(torch.equal(logits[0], value) for value in logits[1:])
    assert outcomes[0] == outcomes[1] == outcomes[2]


def test_local_seed_preserves_ambient_rng_donor_modes_flags_gradients_and_values():
    donor=body();donor.eval();donor.decoder.train()
    donor.output.weight.requires_grad_(False)
    for parameter in donor.parameters():parameter.grad=torch.full_like(parameter,.125)
    modes={k:v.training for k,v in donor.named_modules()}
    flags={k:v.requires_grad for k,v in donor.named_parameters()}
    grads={k:v.grad.clone() for k,v in donor.named_parameters()}
    before=core.tensor_digest(donor);rng=torch.get_rng_state().clone();pyrng=random.getstate()
    a,ra=subject.bind_dimension_native_body(donor,dimension=8,source_seed=7)
    assert torch.equal(torch.get_rng_state(),rng) and random.getstate()==pyrng
    b,rb=subject.bind_dimension_native_body(donor,dimension=8,source_seed=7)
    c,rc=subject.bind_dimension_native_body(donor,dimension=8,source_seed=8)
    assert ra==rb and core.tensor_digest(a)==core.tensor_digest(b)
    assert not torch.equal(a.projection_down.weight,c.projection_down.weight)
    assert ra['initial_tensor_sha256']!=rc['initial_tensor_sha256']
    assert all(p.grad is None for p in a.parameters())
    assert not a.output.weight.requires_grad
    assert modes=={k:v.training for k,v in donor.named_modules()}
    assert flags=={k:v.requires_grad for k,v in donor.named_parameters()}
    assert all(torch.equal(grads[k],v.grad) for k,v in donor.named_parameters())
    assert core.tensor_digest(donor)==before
    assert subject.checked_specification(a,ra)==ra


@pytest.mark.parametrize("dimension", [8,384,768])
def test_native_source_paths_learn_while_identity_projection_and_donor_stay_frozen(dimension):
    donor=body();before=core.tensor_digest(donor)
    native,receipt=subject.bind_dimension_native_body(donor,dimension=dimension)
    model=adapter.bind_persistent_model(native,dimension=dimension)
    source,prefix=data(dimension)
    frozen={k:v.clone() for k,v in model.body.state_dict().items() if k in subject.PROJECTION_NAMES}
    optimizer=torch.optim.Adam([p for p in model.parameters() if p.requires_grad],lr=.01)
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        _,logits=model(source,prefix[:,:-1])
        loss=torch.nn.functional.cross_entropy(logits.flatten(0,1),prefix[:,1:].flatten(),ignore_index=0)
        loss.backward()
        for parameter in (model.body.condition.weight,model.source_to_embedding.weight):
            assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
            assert torch.count_nonzero(parameter.grad)>0
        assert all(p.grad is None for n,p in model.body.named_parameters() if n in subject.PROJECTION_NAMES)
        optimizer.step()
    assert torch.count_nonzero(model.body.condition.weight)>0 and torch.count_nonzero(model.source_to_embedding.weight)>0
    assert all(torch.equal(v,model.body.state_dict()[k]) for k,v in frozen.items())
    assert subject.checked_specification(model.body,receipt)==receipt
    assert core.tensor_digest(donor)==before and all(p.grad is None for p in donor.parameters())


@pytest.mark.parametrize("dimension", [8,384,768])
def test_strict_reload_accepts_learned_source_condition_and_readout(dimension):
    model,receipt=subject.bind_dimension_native_body(body(),dimension=dimension)
    state=deepcopy(model.state_dict());state['condition.weight'].fill_(.031);state['output.bias'].fill_(.3)
    model.load_state_dict(state)
    assert torch.equal(model.condition.weight,state['condition.weight'])
    assert subject.checked_specification(model,receipt)==receipt


@pytest.mark.parametrize("corruption", ['down','up','missing','extra','nan','shape','dtype','wrong_seed'])
def test_restore_fails_before_any_mutation(corruption):
    donor=body();model,_=subject.bind_dimension_native_body(donor,dimension=8,source_seed=7)
    state=deepcopy(model.state_dict());state['condition.bias'].fill_(9)
    if corruption=='down':state['projection_down.weight'][0,0]+=1
    elif corruption=='up':state['projection_up.bias'][0]=1
    elif corruption=='missing':del state['output.bias']
    elif corruption=='extra':state['unexpected']=torch.zeros(1)
    elif corruption=='nan':state['output.bias'][0]=float('nan')
    elif corruption=='shape':state['output.bias']=torch.zeros(4)
    elif corruption=='dtype':state['output.bias']=state['output.bias'].double()
    elif corruption=='wrong_seed':
        other,_=subject.bind_dimension_native_body(donor,dimension=8,source_seed=8);state=other.state_dict()
    before=core.tensor_digest(model)
    with pytest.raises(ValueError):model.load_state_dict(state)
    assert core.tensor_digest(model)==before


@pytest.mark.parametrize("bad", [True,0,16,383,769,8.,None])
def test_invalid_dimensions_rejected(bad):
    with pytest.raises(ValueError,match='dimension'):subject.bind_dimension_native_body(body(),dimension=bad)


@pytest.mark.parametrize("bad", [True,-1,2**31,1.5,None])
def test_invalid_seeds_rejected(bad):
    with pytest.raises(ValueError,match='seed'):subject.bind_dimension_native_body(body(),dimension=8,source_seed=bad)


@pytest.mark.parametrize("dimension", [8,768])
def test_donor_must_be_raw384(dimension):
    with pytest.raises(ValueError,match='dimension'):subject.bind_dimension_native_body(body(dimension),dimension=8)


def test_receipt_tampering_and_frozen_flag_changes_are_rejected():
    model,receipt=subject.bind_dimension_native_body(body(),dimension=8)
    changed=deepcopy(receipt);changed['source_seed']=1;changed['receipt_sha256']=core.digest({k:v for k,v in changed.items() if k!='receipt_sha256'})
    with pytest.raises(ValueError,match='provenance'):subject.checked_specification(model,changed)
    model.projection_down.weight.requires_grad_(True)
    with pytest.raises(ValueError,match='trainability'):subject.checked_specification(model,receipt)


def test_public_wrapper_restore_preflight_is_read_only_and_rejects_changed_projection():
    model,receipt=subject.bind_dimension_native_body(body(),dimension=8)
    state=deepcopy(model.state_dict());state['condition.bias'].fill_(.5)
    before=core.tensor_digest(model)
    subject.validate_restored_state(model,receipt,state)
    assert core.tensor_digest(model)==before
    state['projection_up.weight'][0,0]=.1
    with pytest.raises(ValueError,match='frozen native projection'):
        subject.validate_restored_state(model,receipt,state)
    assert core.tensor_digest(model)==before


@pytest.mark.parametrize("option", [dict(strict=False),dict(assign=True)])
def test_partial_or_replacing_reload_is_explicitly_rejected(option):
    model,_=subject.bind_dimension_native_body(body(),dimension=8)
    before=core.tensor_digest(model)
    with pytest.raises(ValueError,match='strict nonassigning'):
        model.load_state_dict(model.state_dict(),**option)
    assert core.tensor_digest(model)==before


@pytest.mark.parametrize("change", ['width','dtype','nan'])
def test_input_boundary_rejects_incompatible_sources(change):
    model,_=subject.bind_dimension_native_body(body(),dimension=8)
    source,_=data(8)
    if change=='width':source=source[:,:7]
    elif change=='dtype':source=source.double()
    else:source[0,0]=float('nan')
    with pytest.raises(ValueError,match='source input'):model.project(source)
