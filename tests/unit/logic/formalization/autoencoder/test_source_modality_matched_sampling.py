"""Content grouping changes update composition, preserving full-budget exposure."""
from collections import Counter
from copy import deepcopy
import random

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import source_modality_auxiliary_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
from . import test_source_modality_auxiliary_training as fixture
from . import test_source_modality_training_integration as integration


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def caches(monkeypatch, *, seed=1729, updates=340, dimension=8, kind="recurrent"):
    bank, data = fixture.bank("full180", dimension)
    model, codec = fixture.model_for(monkeypatch, dimension, kind=kind)
    options = dict(codec=codec, input_transform=fixture.transform(dimension), seed=seed,
                   max_optimizer_steps=updates, deadline=fixture.deadline())
    independent = subject.prepare_tensor_cache(torch, model, bank, **options)
    matched = subject.prepare_tensor_cache(torch, model, bank, sampler="content_matched_cycles", **options)
    return model, bank, independent, matched


@pytest.mark.parametrize("seed", [1729, 2718])
@pytest.mark.parametrize("updates", [1, 29, 30, 31, 60, 339, 340])
def test_complete_cycles_and_original_tail_preserve_each_sources_exact_exposure(monkeypatch, seed, updates):
    _, bank, independent, matched = caches(monkeypatch, seed=seed, updates=updates)
    original = [subject.select_indices(independent, step) for step in range(updates)]
    actual = [subject.select_indices(matched, step) for step in range(updates)]
    bound = updates//30*30
    assert actual[bound:] == original[bound:]
    assert Counter(i for batch in actual for i in batch) == Counter(i for batch in original for i in batch)
    for start in range(0, bound, 30):
        assert Counter(i for batch in actual[start:start+30] for i in batch) == Counter(range(180))
    for batch in actual[:bound]:
        rules = [subject._source(bank["rows"][i]["source_text"], bank["rows"][i]["wording_style"]) for i in batch]
        assert len({tuple(rule[k] for k in ("actor", "action", "object")) for rule in rules}) == 1
        assert tuple((rule["modality"], bank["rows"][i]["wording_style"]) for i, rule in zip(batch, rules)) == subject.STRATA
    if updates == 340:
        assert Counter(Counter(i for batch in actual for i in batch).values()) == {11:120, 12:60}
    receipt = matched.receipt
    assert receipt["content_group_count"] == 30 and receipt["matched_update_bound"] == bound
    assert receipt["independent_remainder_updates"] == updates-bound
    assert receipt["content_group_order_sha256"] == subject.digest(receipt["content_group_order"])
    assert receipt["full_budget_per_source_exposure_matches_independent"] is True


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("kind", ["recurrent", "factorized"])
def test_actual_matched_loss_is_six_full_vocabulary_source_losses(monkeypatch, dimension, kind):
    model, bank, _, cache = caches(monkeypatch, dimension=dimension, kind=kind)
    before = fixture.core.tensor_digest(model)
    rng = torch.get_rng_state().clone(); python_rng = random.getstate()
    modes = {name: module.training for name, module in model.named_modules()}
    for parameter in model.parameters():
        if parameter.requires_grad:
            parameter.grad = torch.ones_like(parameter)
    gradients = {name: p.grad.clone() for name,p in model.named_parameters() if p.grad is not None}
    # Raw source readout only: a recurrent/count pass or repeated bank digest
    # would invalidate the intended cheap, cached auxiliary route.
    monkeypatch.setattr(model, "next_logits", lambda *a, **kw: pytest.fail("recurrent pass"))
    monkeypatch.setattr(model, "count_logits", lambda *a, **kw: pytest.fail("count pass"))
    monkeypatch.setattr(subject, "digest", lambda *a: pytest.fail("per-step bank hash"))
    result = subject.modality_loss(torch, model, cache, committed_step=29, deadline=fixture.deadline())
    receipt = result["receipt"]
    logits = torch.tensor(receipt["full_vocabulary_logits"])
    targets = torch.tensor(receipt["target_token_ids"])
    expected = torch.nn.functional.cross_entropy(logits, targets)
    assert logits.shape == (6, 32) and result["loss"].detach() == expected
    assert receipt["sampling_mode"] == "content_matched" and receipt["content_group_index"] == 29
    assert receipt["content_cycle_index"] == 0 and len(receipt["row_ids"]) == 6
    first = bank["rows"][receipt["indices"][0]]
    rule = subject._source(first["source_text"], first["wording_style"])
    assert receipt["content_group"] == {k:rule[k] for k in ("actor", "action", "object")}
    assert fixture.core.tensor_digest(model) == before
    assert all(torch.equal(p.grad, gradients[name]) for name,p in model.named_parameters() if name in gradients)
    assert torch.equal(torch.get_rng_state(), rng) and random.getstate() == python_rng
    assert modes == {name: module.training for name,module in model.named_modules()}
    assert all(receipt[key] is False for key in subject.FALSE)
    model.zero_grad(set_to_none=True)
    (.05*result["loss"]).backward()
    touched = {name for name,p in model.named_parameters() if p.grad is not None and bool(p.grad.any())}
    assert touched and all(name.startswith("non_action_head.") for name in touched)


def test_independent_is_default_and_remainder_has_identical_graph_and_receipt(monkeypatch):
    model, bank, old, matched = caches(monkeypatch)
    codec = fixture.corpus()["codec"]
    explicit = subject.prepare_tensor_cache(torch, model, bank, codec=codec, input_transform=fixture.transform(8),
        seed=1729, deadline=fixture.deadline(), sampler="independent")
    a, b = old.receipt, explicit.receipt
    a.pop("elapsed_seconds"); b.pop("elapsed_seconds")
    assert a == b and "sampler_policy" not in a
    for step in (0, 329, 330, 339):
        assert subject.select_indices(old, step) == subject.select_indices(explicit, step)
    baseline = subject.modality_loss(torch, model, old, committed_step=333, deadline=fixture.deadline())
    candidate = subject.modality_loss(torch, model, matched, committed_step=333, deadline=fixture.deadline())
    a, b = baseline["receipt"], deepcopy(candidate["receipt"])
    assert b.pop("sampling_mode") == "independent_remainder"
    assert b.pop("sampler_policy") == "content_matched_cycles" and b.pop("matched_update_bound") == 330
    a.pop("elapsed_seconds"); b.pop("elapsed_seconds")
    assert a == b and baseline["loss"].detach() == candidate["loss"].detach()
    parameters = [p for p in model.parameters() if p.requires_grad]
    left = torch.autograd.grad(baseline["loss"], parameters, allow_unused=True)
    right = torch.autograd.grad(candidate["loss"], parameters, allow_unused=True)
    assert all((x is None and y is None) or (x is not None and y is not None and torch.equal(x,y)) for x,y in zip(left,right))


def test_same_uncommitted_step_replays_and_does_not_consume_global_rng(monkeypatch):
    _, _, old, matched = caches(monkeypatch)
    a, b = random.getstate(), torch.get_rng_state().clone()
    first = subject.select_indices(matched, 31)
    for step in (339, 0, 29, 330, 31, 55):
        subject.select_indices(matched, step)
    assert first == subject.select_indices(matched, 31)
    assert random.getstate() == a and torch.equal(torch.get_rng_state(), b)
    assert Counter(i for batch in (subject.select_indices(matched,s) for s in range(7)) for i in batch) != \
           Counter(i for batch in (subject.select_indices(old,s) for s in range(7)) for i in batch)


@pytest.mark.parametrize("sampler", [None, True, 1, "matched", [], {}])
def test_invalid_sampler_rejected_before_tensor_allocation(monkeypatch, sampler):
    bank, _ = fixture.bank("full180"); model, codec = fixture.model_for(monkeypatch)
    monkeypatch.setattr(torch,"tensor", lambda *a, **kw: pytest.fail("allocation before validation"))
    with pytest.raises(ValueError, match="sampler"):
        subject.prepare_tensor_cache(torch, model, bank, codec=codec, input_transform=fixture.transform(8),
            seed=1729, deadline=fixture.deadline(), sampler=sampler)


@pytest.mark.parametrize("mutation", ["used113", "incomplete_content"])
def test_matched_bank_requires_all_six_authenticated_variants_before_allocating(monkeypatch, mutation):
    bank, _ = fixture.bank("used113" if mutation == "used113" else "full180")
    model, codec = fixture.model_for(monkeypatch)
    if mutation == "incomplete_content":
        row = bank["rows"][0]
        old_rule = subject._source(row["source_text"], row["wording_style"])
        replacement = next(action for action in fixture.authored.ACTIONS if not any(
            subject._source(r["source_text"], r["wording_style"])["action"] == action
            and subject._source(r["source_text"], r["wording_style"])["actor"] == old_rule["actor"] for r in bank["rows"]))
        row["source_text"] = row["source_text"].replace(" "+old_rule["action"]+" the ", " "+replacement+" the ")
        rule = subject._source(row["source_text"], row["wording_style"])
        row["source_sha256"] = subject._sha(row["source_text"])
        row["target_sha256"] = subject.digest({"rules":[rule]})
        bank["bank_sha256"] = subject.digest({k:v for k,v in bank.items() if k != "bank_sha256"})
    monkeypatch.setattr(subject.contexts,"batch_source_context", lambda *a, **kw: pytest.fail("cache allocation before completeness check"))
    with pytest.raises(ValueError, match="complete"):
        subject.prepare_tensor_cache(torch,model,bank,codec=codec,input_transform=fixture.transform(8),
            seed=1729, deadline=fixture.deadline(), sampler="content_matched_cycles")


def test_expired_preparation_and_post_forward_deadline_do_not_advance_sampler(monkeypatch):
    model, bank, _, cache = caches(monkeypatch)
    original = subject.select_indices(cache, 30)
    before = fixture.core.tensor_digest(model)
    with pytest.raises(TimeoutError):
        subject.prepare_tensor_cache(torch,model,bank,codec=fixture.corpus()["codec"],
            input_transform=fixture.transform(8),seed=1729,deadline=0.,sampler="content_matched_cycles")
    clock = [0.]; forward = model.source_value_logits
    def expire(*args, **kwargs):
        result = forward(*args, **kwargs); clock[0] = 100.; return result
    with monkeypatch.context() as patch:
        patch.setattr(subject.time, "monotonic", lambda:clock[0])
        patch.setattr(model, "source_value_logits", expire)
        with pytest.raises(TimeoutError):
            subject.modality_loss(torch,model,cache,committed_step=30,deadline=50.)
    assert subject.select_indices(cache,30) == original and fixture.core.tensor_digest(model) == before
    successful = subject.modality_loss(torch,model,cache,committed_step=30,deadline=fixture.deadline())
    assert successful["receipt"]["indices"] == list(original)
    assert successful["receipt"]["sampler_state_advanced"] is False


@pytest.mark.parametrize("sampler", [None, True, 1, "matched", [], {}])
def test_trainer_rejects_invalid_sampler_before_private_copy(monkeypatch, sampler):
    model,_,train,tune,options,contexts = integration.real_fixture(monkeypatch)
    monkeypatch.setattr(trainer,"deepcopy",lambda *a:pytest.fail("model copy before validation"))
    with pytest.raises(ValueError, match="sampler"):
        integration.fit(model,train,tune,options,contexts,auxiliary_source_modality_sampler=sampler)


@pytest.mark.parametrize("weight, bank", [(0.,None),(.05,{"bank_kind":"used113"}),(.05,{})])
def test_trainer_matched_requires_positive_auxiliary_complete_bank(monkeypatch, weight, bank):
    model,_,train,tune,options,contexts = integration.real_fixture(monkeypatch)
    monkeypatch.setattr(trainer,"deepcopy",lambda *a:pytest.fail("model copy before validation"))
    with pytest.raises(ValueError, match="positive auxiliary weight"):
        integration.fit(model,train,tune,options,contexts,auxiliary_source_modality_sampler="content_matched_cycles",
                        auxiliary_source_modality_weight=weight,auxiliary_source_modality_bank=bank)


def test_trainer_default_sampler_preserves_disabled_and_positive_independent_results(monkeypatch):
    model,_,train,tune,options,contexts = integration.real_fixture(monkeypatch)
    integration.fake_context_boundary(monkeypatch)
    integration.same(integration.fit(model,train,tune,options,contexts),
        integration.fit(model,train,tune,options,contexts,auxiliary_source_modality_sampler="independent"))
    integration.fake_auxiliary(monkeypatch)
    kwargs = dict(auxiliary_source_modality_weight=.05, auxiliary_source_modality_bank={"synthetic_training_bank":True})
    a = integration.fit(model,train,tune,options,contexts,**kwargs)
    b = integration.fit(model,train,tune,options,contexts,auxiliary_source_modality_sampler="independent",**kwargs)
    # Preparation wall time is intentionally telemetry, not numerical state.
    for result in (a,b): result["report"].pop("auxiliary_source_modality_preparation_elapsed_seconds")
    integration.same(a,b)
    assert "auxiliary_source_modality_sampler" not in b["report"]


@pytest.mark.parametrize("expire", [None, "preparation", "loss", "backward"])
def test_trainer_forwards_matched_sampler_and_counts_only_committed_updates(monkeypatch, expire):
    model,_,train,tune,options,contexts = integration.real_fixture(monkeypatch)
    integration.fake_context_boundary(monkeypatch)
    clock = [0.]
    observed = integration.fake_auxiliary(monkeypatch,expire=expire,clock=clock)
    owner = integration.package.source_modality_auxiliary_training
    old_estimate,old_prepare,old_loss = owner.estimate_training_work_bytes,owner.prepare_tensor_cache,owner.modality_loss
    forwarded = []
    def estimate(bank, **kwargs): return old_estimate({"synthetic_training_bank":True}, **kwargs)
    def prepare(torch,model,bank,*,sampler,**kwargs):
        forwarded.append(sampler)
        return old_prepare(torch,model,{"synthetic_training_bank":True},**kwargs)
    def loss(*args, **kwargs):
        value = old_loss(*args, **kwargs)
        value["receipt"]["sampling_mode"] = "independent_remainder"
        return value
    monkeypatch.setattr(owner,"estimate_training_work_bytes",estimate)
    monkeypatch.setattr(owner,"prepare_tensor_cache",prepare)
    monkeypatch.setattr(owner,"modality_loss",loss)
    if expire == "backward": monkeypatch.setattr(trainer.time,"monotonic",lambda:clock[0])
    before = fixture.core.tensor_digest(model)
    result = integration.fit(model,train,tune,options,contexts,auxiliary_source_modality_sampler="content_matched_cycles",
        auxiliary_source_modality_weight=.05, auxiliary_source_modality_bank={"bank_kind":"full180"})
    report = result["report"]
    expected = 2 if expire is None else 0
    assert forwarded == ["content_matched_cycles"] and report["optimizer_steps"] == expected
    assert report["auxiliary_source_modality_matched_update_bound"] == 0
    assert report["auxiliary_source_modality_independent_remainder_updates_planned"] == 2
    assert report["auxiliary_source_modality_matched_committed_updates"] == 0
    assert report["auxiliary_source_modality_independent_remainder_committed_updates"] == expected
    assert report["auxiliary_source_modality_full_budget_exposure_equivalence_reached"] is (expire is None)
    assert fixture.core.tensor_digest(model) == before
    assert observed["steps"] == ([] if expire == "preparation" else list(range(max(1,expected))))
