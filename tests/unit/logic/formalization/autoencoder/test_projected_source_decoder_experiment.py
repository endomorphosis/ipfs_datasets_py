"""Synthetic invariants for the source-only readout, not fidelity evidence."""
from copy import deepcopy
import hashlib
import json
import math
import re

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import projected_source_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as cardinality
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as conditioning
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def rule():
    return dict(modality="O", actor="agency", action="save", object="report", conditions=[], exceptions=[], temporal=[])


def setup(dimension=384):
    strings = (*cardinality.FIELDS, "rules", "O", "P", "F", "agency", "save", "report", "a", "b", "}")
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"]+
        sorted(set([json.dumps(value) for value in strings]+list('{}[],:'))))
    body = numerical._model(dict(dimension=dimension), codec,
        dict(seed=132, hidden_size=8, token_embedding_dim=8, projection_width=2))
    persistent = conditioning.bind_persistent_model(body, dimension=dimension)
    return persistent, codec


def inputs(dimension=384, n=2):
    return torch.randn((n, dimension), generator=torch.Generator().manual_seed(44))


def encode(codec, document=None):
    text = json.dumps(document or {"rules": [rule(), rule()]}, sort_keys=True, separators=(",", ":"))
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]', text)
    return [1]+[codec["target_vocabulary"].index(token) for token in tokens]+[2]


def rows(dimension=384):
    return [dict(id=f"train-{i}", source_sha256=hashlib.sha256(str(i).encode()).hexdigest(), features=value)
        for i, value in enumerate(inputs(dimension, 4).tolist())]


def receipts(dimension=384, kind="none"):
    features = rows(dimension)
    keywords = dict(expected_training_ids=[row["id"] for row in features],
        forbidden_validation_ids=["validation-1"], training_rows_sha256="a"*64)
    normalization = subject.fit_source_normalization(features, kind=kind, **keywords)
    counts = [{k:v for k,v in row.items() if k != "features"} | dict(count=count)
        for row, count in zip(features, [1, 2, 4, 8])]
    prior = subject.fit_source_count_prior(counts, **keywords)
    return normalization, prior


def bound(dimension=384, kind="none", guided=False):
    base, codec = setup(dimension)
    normalization, prior = receipts(dimension, kind)
    model = subject.bind_projected_source_model(base, codec=codec, normalization_receipt=normalization,
        count_prior_receipt=prior, guide_boundary=guided)
    return model, codec, base


@pytest.mark.parametrize("kind", ["none", "center_rms"])
def test_training_only_global_rms_matches_declared_arithmetic(kind):
    normalization, prior = receipts(8, kind)
    x = torch.tensor([row["features"] for row in rows(8)], dtype=torch.float64)
    mean = x.mean(0); scale = math.sqrt(float((x-mean).square().sum()/len(x)))
    assert normalization["fitted_training_mean"] == mean.tolist()
    assert normalization["fitted_training_scale"] == scale
    assert normalization["mean"] == (mean.tolist() if kind == "center_rms" else [0.]*8)
    assert normalization["scale"] == (scale if kind == "center_rms" else 1.)
    assert normalization["training_inventory"] == prior["training_inventory"]
    assert normalization["validation_rows_used_for_fitting"] == 0
    assert normalization["receipt_sha256"] == core.digest({k:v for k,v in normalization.items() if k != "receipt_sha256"})


def test_constant_training_features_get_finite_identity_scale_and_zero_centered_features():
    data = rows(8)
    for row in data: row["features"] = [3.]*8
    receipt = subject.fit_source_normalization(data, kind="center_rms",
        expected_training_ids=[row["id"] for row in data], forbidden_validation_ids=[], training_rows_sha256="a"*64)
    assert receipt["constant_training_features"] is True
    assert receipt["scale"] == 1. and receipt["mean"] == [3.]*8


@pytest.mark.parametrize("mutation", ["validation", "duplicate", "nan", "shape", "target", "missing_id"])
def test_normalization_rejects_contamination_and_malformed_feature_rows(mutation):
    data = rows(8); expected = [row["id"] for row in data]
    forbidden = ["validation-1"]
    if mutation == "validation": forbidden = [expected[0]]
    elif mutation == "duplicate": data[1]["id"] = data[0]["id"]
    elif mutation == "nan": data[0]["features"][0] = float("nan")
    elif mutation == "shape": data[0]["features"].pop()
    elif mutation == "target": data[0]["target"] = {"rules": [rule()]}
    else: expected[0] = "missing-id"
    with pytest.raises(ValueError):
        subject.fit_source_normalization(data, kind="center_rms", expected_training_ids=expected,
            forbidden_validation_ids=forbidden, training_rows_sha256="a"*64)


def test_prior_has_exact_unit_pseudocount_all_class_support_and_no_validation_access():
    _, prior = receipts(8)
    assert prior["alpha_per_class"] == 1/32 and prior["total_pseudocount"] == 1.
    assert len(prior["probabilities"]) == 32 and all(value > 0 for value in prior["probabilities"])
    assert sum(prior["probabilities"]) == 1.
    assert prior["probabilities"][0] == (1+1/32)/5
    assert prior["probabilities"][2] == (1/32)/5
    assert prior["log_prior"] == torch.tensor(prior["probabilities"], dtype=torch.float32).log().tolist()


@pytest.mark.parametrize("value", [0, 33, True, 1.5])
def test_prior_rejects_out_of_scope_training_counts(value):
    data = [dict(id="train", source_sha256="a"*64, count=value)]
    with pytest.raises(ValueError):
        subject.fit_source_count_prior(data, expected_training_ids=["train"],
            forbidden_validation_ids=[], training_rows_sha256="a"*64)


def test_prior_centered_odds_are_exactly_zero_at_initial_prior_all_boundaries():
    _, receipt = receipts(8)
    prior = torch.tensor(receipt["log_prior"], dtype=torch.float32)
    counts = torch.arange(34)
    actual = subject.prior_centered_boundary_log_odds(prior.repeat(34, 1), counts, prior)
    assert torch.equal(actual, torch.zeros(34))
    # The old uniform-centering yields a nonzero stop preference at this prior.
    old = cardinality.boundary_log_odds(prior.repeat(34, 1), counts)
    assert old[1] > 1.


def test_prior_odds_direction_shift_invariance_and_gradient():
    _, receipt = receipts(8)
    prior = torch.tensor(receipt["log_prior"], dtype=torch.float32)
    logits = prior.repeat(3, 1)
    logits[0, 0] += 1.; logits[1, 1:] += 1.; logits[2] += 3.
    logits.requires_grad_()
    actual = subject.prior_centered_boundary_log_odds(logits, torch.ones(3, dtype=torch.long), prior)
    assert torch.allclose(actual, torch.tensor([1., -1., 0.]), atol=3e-7)
    actual.sum().backward()
    assert logits.grad is not None and bool(torch.isfinite(logits.grad).all()) and logits.grad.abs().sum() > 0


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("kind", ["none", "center_rms"])
@pytest.mark.parametrize("guided", [False, True])
def test_zero_heads_preserve_inherited_generation_logits_and_caller_exactly(dimension, kind, guided):
    base, codec = setup(dimension)
    normalization, prior = receipts(dimension, kind)
    base.train(False)
    for parameter in base.parameters(): parameter.grad = torch.ones_like(parameter)
    before, rng = core.tensor_digest(base), torch.get_rng_state().clone()
    flags = [(p.requires_grad, p.grad.clone()) for p in base.parameters()]
    model = subject.bind_projected_source_model(base, codec=codec, normalization_receipt=normalization,
        count_prior_receipt=prior, guide_boundary=guided)
    assert core.tensor_digest(base) == core.tensor_digest(model.body) == before
    assert torch.equal(rng, torch.get_rng_state()) and not base.training
    assert all(p.requires_grad == flag and torch.equal(p.grad, grad) for p,(flag,grad) in zip(base.parameters(), flags))
    x = inputs(dimension); prefix = torch.tensor([encode(codec)]*len(x))
    old_projected, old_logits = base(x, prefix)
    projected, logits = model(x, prefix)
    assert torch.equal(projected, old_projected) and torch.equal(logits, old_logits)
    assert torch.equal(model.count_logits(projected), model.count_prior_logits.expand(len(x), -1))
    assert all(not p.requires_grad for name,p in model.named_parameters() if ".projection_" in name)
    assert model.describe()["feature_dimension"] == dimension


@pytest.mark.parametrize("field", ["scale", "probabilities", "inventory", "qualification"])
def test_resealed_receipt_corruption_is_rejected(field):
    base, codec = setup(8); normalization, prior = receipts(8)
    if field == "scale": normalization["scale"] = 2.
    elif field == "probabilities": prior["probabilities"][0] += .1
    elif field == "inventory": prior["training_inventory"][0]["source_sha256"] = "b"*64
    else: prior["qualified"] = True
    for receipt in (normalization, prior):
        receipt["receipt_sha256"] = core.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"})
    with pytest.raises(ValueError):
        subject.bind_projected_source_model(base, codec=codec, normalization_receipt=normalization,
            count_prior_receipt=prior)


def test_joint_losses_reach_both_heads_and_recurrent_decoder_without_projection_gradient():
    model, codec, base = bound(8, "center_rms", True)
    x = inputs(8); prefix = torch.tensor([encode(codec)]*2)
    projected, logits = model(x, prefix[:, :-1])
    sequence = torch.nn.functional.cross_entropy(logits.flatten(0,1), prefix[:, 1:].flatten())
    counts = torch.nn.functional.cross_entropy(model.count_logits(projected), torch.tensor([0,7]))
    values = model.source_value_logits(projected)
    scalar = torch.nn.functional.cross_entropy(values[:, 0, 0], torch.tensor([3,4]))
    (sequence+counts*.25+scalar*.25).backward()
    for head in (model.count_head, model.source_value_head):
        assert head.weight.grad is not None and head.weight.grad.abs().sum() > 0
    assert model.body.body.decoder.weight_ih_l0.grad is not None
    assert all(p.grad is None for name,p in model.named_parameters() if ".projection_" in name)
    assert all(p.grad is None for p in base.parameters())
    assert all(not value.requires_grad for _,value in model.named_buffers())


@pytest.mark.parametrize("guided", [False, True])
def test_full_incremental_equivalence_and_explicit_state_immutability(guided):
    model, codec, _ = bound(8, "center_rms", guided)
    with torch.no_grad():
        model.count_head.weight.fill_(.2)
        model.count_head.bias.copy_(torch.arange(32)/10.)
        model.source_value_head.weight.fill_(.03)
    prefix = torch.tensor([encode(codec)]*2)
    state = model.start(model.project(inputs(8)))
    original = tuple(value.clone() for value in state)
    expected, full = model.next_logits(prefix, state)
    partial, actual = state, []
    for i in range(prefix.shape[1]):
        value, partial = model.next_logits(prefix[:, i:i+1], partial); actual.append(value)
    assert torch.allclose(expected, torch.cat(actual, 1), atol=3e-7, rtol=1e-6)
    assert all(torch.equal(left,right) for left,right in zip(state, original))
    assert torch.equal(full[4], partial[4]) and full[4][:,3].tolist() == [2,2]
    assert partial[3] is state[3] and partial[5] is state[5]


def test_guidance_changes_only_causal_scalar_and_complete_rule_boundary_sites():
    model, codec, _ = bound(8, guided=True)
    plain, _, _ = bound(8, guided=False)
    with torch.no_grad():
        model.count_head.bias[0] = 2.
        model.source_value_head.bias.fill_(.4)
    plain.load_state_dict(model.state_dict())
    prefix = torch.tensor([encode(codec)]*2); x=inputs(8)
    _, guided = model(x,prefix); _, unguided = plain(x,prefix)
    difference = guided-unguided
    tables = cardinality._tables(codec,len(codec["target_vocabulary"]),torch)
    _, boundaries = cardinality._scan_prefix(prefix.tolist(),[[0]*6]*2,tables)
    allowed = torch.zeros_like(difference,dtype=torch.bool)
    for batch,offset,_ in boundaries: allowed[batch,offset,tables[0]["]"]] = True
    assert torch.count_nonzero(difference[~allowed]) == 0 and torch.count_nonzero(difference[allowed]) > 0


def test_invalid_prefix_permanently_disables_both_guidance_paths():
    model, codec, base = bound(8, guided=True)
    with torch.no_grad():
        model.count_head.bias[0] = 2.
        model.source_value_head.bias.fill_(.4)
    prefix = [1,codec["target_vocabulary"].index("]")]+encode(codec)
    prefix = torch.tensor([prefix])
    x=inputs(8,1)
    _, expected=base(x,prefix); _, actual=model(x,prefix)
    assert torch.equal(expected,actual)
    _,state=model.next_logits(prefix,model.start(model.project(x)))
    assert state[4][0,0] == cardinality._INVALID


@pytest.mark.parametrize("kind", ["none","center_rms"])
def test_zero_source_removes_recurrent_and_both_head_sources_retains_frozen_and_learned_priors(kind):
    model,codec,_=bound(8,kind,True)
    with torch.no_grad():
        model.body.source_to_embedding.weight.fill_(.3)
        model.count_head.weight.fill_(.2); model.count_head.bias.copy_(torch.arange(32)/10.)
        model.source_value_head.weight.fill_(.1); model.source_value_head.bias.fill_(.03)
    before=core.tensor_digest(model)
    control=subject.bind_zero_condition_model(model)
    projected=control.project(inputs(8));state=control.start(projected)
    assert torch.count_nonzero(state[0]) == torch.count_nonzero(state[1]) == 0
    expected=model.count_head.bias+model.count_prior_logits
    assert torch.equal(state[3],expected.expand(2,-1))
    assert torch.equal(control.count_logits(projected),state[3])
    assert torch.equal(control.source_value_logits(projected),state[5])
    logits,_=control.next_logits(torch.tensor([encode(codec)]*2),state)
    assert torch.equal(logits[0],logits[1]) and not torch.equal(projected[0],projected[1])
    assert core.tensor_digest(model) == before


def test_state_dict_reload_retains_priors_normalization_and_outputs():
    model,codec,_=bound(8,"center_rms",True)
    replica,_,_=bound(8,"center_rms",True)
    with torch.no_grad(): model.count_head.bias[3]=.7; model.source_value_head.bias[5]=.2
    replica.load_state_dict(deepcopy(model.state_dict()),strict=True)
    x=inputs(8); prefix=torch.tensor([encode(codec)]*2)
    assert core.tensor_digest(model) == core.tensor_digest(replica)
    assert torch.equal(model(x,prefix)[1],replica(x,prefix)[1])


@pytest.mark.parametrize("name", ["source_mean", "source_scale", "count_prior_logits"])
def test_restore_rejects_altered_frozen_statistics_before_mutating_model(name):
    model,_,_=bound(8,"center_rms",True)
    before=core.tensor_digest(model)
    changed=deepcopy(model.state_dict()); changed[name].add_(.1)
    with pytest.raises(ValueError, match="restored frozen source buffer differs"):
        model.load_state_dict(changed,strict=True)
    assert core.tensor_digest(model) == before


def test_scalar_guidance_retains_full_vocabulary_and_only_changes_causal_scalar_sites():
    model,codec,base=bound(8)
    normal,prior=receipts(8)
    plain=subject.bind_projected_source_model(base,codec=codec,normalization_receipt=normal,
        count_prior_receipt=prior,scalar_guidance=False)
    with torch.no_grad():
        model.source_value_head.bias.copy_(torch.arange(model.source_value_head.bias.numel())/100.)
    plain.load_state_dict(model.state_dict())
    prefix=torch.tensor([encode(codec)]*2); x=inputs(8)
    _,actual=model(x,prefix); _,expected=plain(x,prefix)
    difference=actual-expected
    tables=cardinality._tables(codec,len(codec["target_vocabulary"]),torch)
    _,sites=subject.source_values._scan_value_prefix(prefix.tolist(),[[0]*6]*2,tables,8)
    allowed=torch.zeros_like(difference,dtype=torch.bool)
    for batch,offset,_,_ in sites: allowed[batch,offset,:]=True
    assert torch.count_nonzero(difference[~allowed]) == 0
    # Punctuation and special tokens remain possible head outputs; no mask or
    # forced-valid scalar replacement is hidden inside this soft residual.
    first=sites[0]
    assert difference[first[0],first[1],codec["target_vocabulary"].index("{")] > 0
    assert torch.isfinite(actual).all()


def test_later_prefix_changes_cannot_change_earlier_logits_or_guidance():
    model,codec,_=bound(8,"center_rms",True)
    with torch.no_grad():
        model.count_head.bias[0]=1.
        model.source_value_head.bias.fill_(.3)
    first=encode(codec); changed=first[:]
    changed[-8]=codec["target_vocabulary"].index("{")
    state=model.start(model.project(inputs(8,1)))
    before,_=model.next_logits(torch.tensor([first]),state)
    after,_=model.next_logits(torch.tensor([changed]),state)
    assert torch.equal(before[:,:-8],after[:,:-8])


def test_different_request_states_do_not_share_a_mutable_source_cache():
    model,codec,_=bound(8,"center_rms",True)
    with torch.no_grad(): model.count_head.weight.fill_(.2); model.source_value_head.weight.fill_(.1)
    source=model.project(inputs(8)); left=model.start(source[:1]);right=model.start(source[1:])
    prefix=torch.tensor([encode(codec)])
    expected,_=model.next_logits(prefix,left)
    first,middle=model.next_logits(prefix[:,:9],left)
    model.next_logits(prefix,right)
    rest,_=model.next_logits(prefix[:,9:],middle)
    assert torch.allclose(expected,torch.cat([first,rest],1),atol=3e-7,rtol=1e-6)
    assert torch.count_nonzero(left[4]) == torch.count_nonzero(right[4]) == 0
