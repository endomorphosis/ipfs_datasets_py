"""Two real consumer profiles and CPU CE controls; synthetic encoder reports.

The fixtures execute the unchanged source-bank validators, tensor preparation
and full-vocabulary source-value loss. Their vectors and producer reports are
explicit test doubles. No encoder, optimizer step, saved fit or qualification
is performed, and the tiny random decoder is not an experimental result.
"""
from collections import Counter
import builtins
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import random
import time
from types import ModuleType

import pytest

torch = pytest.importorskip("torch")

from ipfs_datasets_py.logic.formalization.autoencoder import (
    contextual_training_mixture as mixture,
    normative_wording_modality_auxiliary as profile,
    normative_wording_training_sources as normative,
    paraphrase_modality_auxiliary_training as auxiliary,
)
from tests.unit.logic.formalization.autoencoder.test_contextual_training_mixture import fixture as original_fixture
from tests.unit.logic.formalization.autoencoder import test_contextual_training_mixture_integration as tiny


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


retention = load("_dual_bank_numeric_retention", "dual_bank_retention.py")


def adapter():
    return load("_dual_bank_numeric_adapter", "dual_bank_training_adapter.py")


def seal(value, key):
    value[key] = retention.digest({k: v for k, v in value.items() if k != key})
    return value


@pytest.fixture(autouse=True)
def cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def pairing_fixture(banks, helpers):
    """Independently construct the prior declaration from authentic bank rows."""
    rules_by_sha = {retention.rule_sha(row["target"]): row["target"]
        for row in banks["control"]["rows"]}
    rules = [deepcopy(rules_by_sha[sha]) for sha in sorted(rules_by_sha)]
    census, declarations = {}, {}
    for role in retention.ROLES:
        templates = list(helpers[role].mixture.authored.TEMPLATES)
        bank = banks[role]
        census[role] = [dict(index=i, row_id=row["id"], source_sha256=row["source_sha256"],
            original_rule_sha256=retention.rule_sha(row["target"]), template=row["template"],
            modality=row["modality"], template_slot=templates.index(row["template"]))
            for i, row in enumerate(bank["rows"])]
        declarations[role] = dict(bank_sha256=bank["bank_sha256"], templates=templates)
    orders = {role: [[row["index"] for row in sorted((row for row in census[role]
        if row["modality"] == modality and row["template_slot"] == slot),
        key=lambda row: retention.digest([1729, modality, slot, row["original_rule_sha256"]]))]
        for modality in retention.MODALITIES for slot in (0, 1)] for role in retention.ROLES}
    draws = [dict(step=step, indices={role: [order[step % 30] for order in orders[role]]
        for role in retention.ROLES}, original_rule_sha256=[retention.rule_sha(
        banks["control"]["rows"][order[step % 30]]["target"])
        for order in orders["control"]]) for step in range(170)]
    pairing = seal(dict(schema="balanced-wording-paired-draws/v1", seed=1729, steps=170,
        original_rules_sha256=retention.digest(rules), banks=declarations, census=census,
        orders=orders, draws=draws, qualified=False, admitted=False, proof_authority=False,
        train_eligible=False), "pairing_sha256")
    # Check our independent fixture before using any new adapter behavior.
    retention.build_schedule(pairing=pairing, banks_by_role=banks, original_rules=rules)
    return pairing, rules


def bank_fixture(monkeypatch, first_bank="control"):
    """Two closed inventories consumed by real isolated normative profiles."""
    train, validation, kwargs, _ = original_fixture(monkeypatch)
    original = kwargs.pop("mixture")
    prior = {name: [dict(id=f"exclusion:{name}:{i}",
        source_text=f"Distinct excluded {name} text {i}.") for i in range(count)]
        for name, count in normative.REQUIRED_PRIOR_COUNTS.items()}
    prior.update(original_train_bank=mixture._source_rows(original["training_bank"]),
        raw_train=mixture._source_rows(original["training_bank"]),
        paragraph_train=mixture._source_rows(train),
        paragraph_validation=mixture._source_rows(validation),
        r4_training_paraphrases=original["corpus"]["source_rows"],
        prospective_development_sources=[dict(id=f"future:{i}",
            source_text=f"Prospective excluded source {i}.") for i in range(60)])
    inventories, helpers, reports, calls = {}, {}, {}, []
    original_caches, original_cache_receipts = {}, {}
    for role in retention.ROLES:
        if role == "control":
            authored = normative
            configured_profile = profile
        else:
            templates = ("fixture_balanced_actor_v1", "fixture_balanced_operator_v1")

            def sentence(template, rule, names=templates):
                if template not in names:
                    raise ValueError("fixture template differs")
                # Deliberately labelled fixture text; this is no new authored
                # semantic corpus or claim about the saved balanced experiment.
                return "For this fixture rule, " + normative.sentence(
                    normative.TEMPLATES[names.index(template)], rule)

            authored = profile.private_module(normative, TEMPLATES=templates, sentence=sentence)
            configured_profile = profile.private_module(profile, TEMPLATES=templates,
                STRATA=tuple((m, t) for m in retention.MODALITIES for t in templates),
                SCHEMA="fixture-balanced-wording-modality-bank/v1")
        helper = configured_profile.configure(auxiliary_owner=auxiliary,
            mixture_owner=mixture, authored_owner=authored)
        built = authored.build(training_bank=original["training_bank"],
            prior_sources_by_dataset=prior, codec=kwargs["codec"],
            sealed_recipe_sha256="a" * 64, validate_rule=kwargs["validate_rule"])
        corpus = {key: built[key] for key in ("source_rows", "references", "receipt")}
        plan = mixture.producer.source_plan(corpus["source_rows"],
            expected_source_rows_sha256=corpus["receipt"]["source_rows_sha256"],
            sealed_recipe_sha256="a" * 64)
        phase = 5. if role == "control" else 6.
        vectors = {normative.text_sha(row["source_text"]):
            [math.cos(phase + i * .0001), math.sin(phase + i * .0001)] + [0.] * 382
            for i, row in enumerate(plan["shape_plan"]["source_inputs"])}
        production = dict(dimension=384, production_sha256=("b" if role == "control" else "c") * 64,
            vectors=[dict(id=row["id"], source_sha256=normative.text_sha(row["source_text"]),
                vector=vectors[normative.text_sha(row["source_text"])])
                for row in plan["shape_plan"]["source_inputs"]])
        reports[role] = plan, production
        rows = [dict(row, input=vectors[normative.text_sha(row["source_text"])])
            for row in corpus["source_rows"]]
        clauses = {ref["source_text"]: dict(id="clause:" + ref["source_sha256"],
            source_text=ref["source_text"], input=vectors[ref["source_sha256"]])
            for ref in built["clause_references"]}
        clause_cache = [clauses[text] for row in corpus["source_rows"]
            for text in row["source_text"].split("\n\n")]
        contexts = mixture.context.build_source_contexts(corpus["source_rows"], clause_cache)
        source_inputs = seal(dict(schema="training-paraphrase-source-inputs/v1", complete=True,
            role="train_augmentation", dimension=384, rows=rows, clause_cache=clause_cache,
            source_contexts=contexts, production_sha256=production["production_sha256"],
            source_plan_sha256=plan["plan_sha256"], targets_attached=False,
            preprocessing_fitted=False, qualified=False, admitted=False,
            checkpoint_promoted=False), "inputs_sha256")
        inventories[role] = seal(dict(policy="original_only", training_bank=original["training_bank"],
            prior_sources_by_dataset=prior, corpus=corpus, source_plan=plan,
            source_inputs=source_inputs, production_report=production,
            evaluation_vectors_by_dataset={name: [] for name in mixture.EVALUATION_DATASETS},
            clause_training_references=built["clause_references"]), "payload_sha256")
        original_cache_function = helper.prepare_tensor_cache

        def observe_cache(*args, cached_function=original_cache_function, bank_role=role, **options):
            result = cached_function(*args, **options)
            original_caches[bank_role] = result
            original_cache_receipts[bank_role] = deepcopy(result.receipt)
            return result

        # This observation wrapper belongs only to the fixture's private
        # profile. The genuine numerical owner and default module stay intact.
        helper.prepare_tensor_cache = observe_cache
        helpers[role] = helper

    def native_validator(given_plan, given_report):
        matches = [role for role, (plan, report) in reports.items()
            if given_plan == plan and given_report == report]
        if len(matches) != 1:
            raise ValueError("synthetic producer receipt binding differs")
        calls.append(matches[0])
        return 384

    monkeypatch.setattr(mixture.producer, "validate_report", native_validator)
    banks = {role: helpers[role].prepare_bank(train, validation, **kwargs,
        source_inventory=inventories[role], deadline=time.monotonic() + 30.)
        for role in retention.ROLES}
    pairing, rules = pairing_fixture(banks, helpers)
    owner = adapter()
    dual = owner.configure(helpers_by_role=helpers, pairing=pairing,
        original_rules=rules, first_bank=first_bank)
    envelope = owner.build_source_inventory(inventories_by_role=inventories, pairing=pairing)
    return dict(owner=owner, helper=dual, helpers=helpers, inventories=inventories,
        envelope=envelope, banks=banks, pairing=pairing, rules=rules, train=train,
        validation=validation, kwargs=kwargs, calls=calls,
        original_caches=original_caches, original_cache_receipts=original_cache_receipts)


def prepare(fixture):
    return fixture["helper"].prepare_bank(fixture["train"], fixture["validation"],
        **fixture["kwargs"], source_inventory=fixture["envelope"],
        deadline=time.monotonic() + 30.)


def cache_fixture(monkeypatch, first_bank="control"):
    # This established tiny decoder fixture locally mocks preparation only
    # while creating its model; discard those patches before bank validation.
    with monkeypatch.context() as isolated:
        model, _, _, options, _, _ = tiny.fixture(isolated)
    fixture = bank_fixture(monkeypatch, first_bank)
    banks = prepare(fixture)
    cache = fixture["helper"].prepare_tensor_cache(torch, model, banks,
        codec=options["codec"], input_transform=options["input_transform"],
        seed=1729, deadline=time.monotonic() + 30., max_optimizer_steps=170)
    return fixture, model, banks, cache, options


def loss(fixture, model, cache, step, requires_grad=False):
    return fixture["helper"].modality_loss(torch, model, cache,
        committed_step=step, deadline=time.monotonic() + 30., requires_grad=requires_grad)


def legacy_report_fixture(banks, cache, receipts, uncommitted=(), weight=0.):
    """Explicit synthetic commit ledger, backed by actual CE observations.

    The optimizer does not execute. These fields reproduce the inherited
    trainer report shape solely to verify the ledger reconciliation contract.
    """
    templates = [template for receipt in cache.receipt["bank_receipts"].values()
        for template in {row["template"] for row in receipt["row_inventory"]}]
    return dict(fixture_optimizer_not_executed=True, optimizer_steps=len(receipts),
        committed_updates=[dict(optimizer_step=i + 1, decoder_row_ids=["original-fixture-row"],
            count_row_ids=["original-fixture-row"], paraphrase_modality_auxiliary=dict(
                zero_based_committed_step=i, weight=weight,
                weighted_loss=weight * receipt["mean_cross_entropy"],
                receipt=deepcopy(receipt))) for i, receipt in enumerate(receipts)],
        paraphrase_modality_auxiliary=dict(weight=weight, bank_receipt=banks.receipt,
            cache_receipt=cache.receipt, committed_updates=len(receipts),
            committed_clause_presentations=6 * len(receipts),
            positively_supervised_clause_presentations=6 * len(receipts) if weight > 0. else 0,
            completed_forward_observations=len(receipts) + len(uncommitted),
            observed_clause_presentations=6 * (len(receipts) + len(uncommitted)),
            committed_presentations_per_modality={m: 2 * len(receipts) for m in retention.MODALITIES},
            committed_presentations_per_template={t: 3 * len(receipts) for t in templates},
            uncommitted_observations=list(deepcopy(uncommitted)),
            zero_weight_graph_attached=False, training_only=True, used_for_selection=False))


def test_complete_profiles_authenticate_separately_without_mutation(monkeypatch):
    fixture = bank_fixture(monkeypatch)
    before = deepcopy((fixture["train"], fixture["validation"], fixture["kwargs"], fixture["envelope"]))
    defaults = auxiliary.STRATA, auxiliary.mixture, mixture.authored, profile.TEMPLATES
    rng = random.getstate()
    prepared = prepare(fixture)
    assert fixture["calls"] == ["control", "balanced", "control", "balanced"]
    assert defaults == (auxiliary.STRATA, auxiliary.mixture, mixture.authored, profile.TEMPLATES)
    assert random.getstate() == rng
    assert (fixture["train"], fixture["validation"], fixture["kwargs"], fixture["envelope"]) == before
    assert len(list(prepared.items())) != 360
    with pytest.raises(AttributeError):
        prepared.metadata = {}


@pytest.mark.parametrize("first_bank", ["control", "balanced"])
def test_real170_forwards_cover_all360_sources_at2_or3_exposures(monkeypatch, first_bank):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch, first_bank)
    expected = retention.build_schedule(pairing=fixture["pairing"], banks_by_role=fixture["banks"],
        original_rules=fixture["rules"], first_bank=first_bank)
    state = {name: tensor.clone() for name, tensor in model.state_dict().items()}
    rng = torch.random.get_rng_state().clone()
    python_rng = random.getstate()
    forward = model.source_value_logits
    calls = []

    def observed(*args, **kwargs):
        assert len(args) == 1 and set(kwargs) == {"source_context"}
        assert set(kwargs["source_context"]) == {"vectors", "mask"}
        calls.append(1)
        return forward(*args, **kwargs)

    monkeypatch.setattr(model, "source_value_logits", observed)
    exposures = {role: Counter() for role in retention.ROLES}
    templates = Counter()
    receipts = []
    for step, draw in enumerate(expected["draws"]):
        result = loss(fixture, model, cache, step)
        assert not result["loss"].requires_grad
        receipt = result["receipt"]
        assert receipt["global_committed_step"] == step
        assert receipt["bank_local_committed_step"] == step // 2
        assert receipt["bank_role"] == draw["bank_role"]
        local = receipt["bank_local_loss_receipt"]
        assert local["schema"] == fixture["helpers"][draw["bank_role"]].LOSS_SCHEMA
        assert local["committed_step"] == step // 2
        assert local["bank_sha256"] == draw["selected_bank_sha256"]
        assert local["indices"] == draw["indices"]
        assert local["row_ids"] == draw["row_ids"]
        assert local["source_sha256"] == draw["source_sha256"]
        assert local["target_token_ids"] == draw["target_token_ids"]
        assert len(local["full_vocabulary_logits"]) == 6
        assert all(len(vector) == 32 for vector in local["full_vocabulary_logits"])
        assert local["sampler_state_advanced"] is False
        assert local["labels_passed_to_model"] is False
        assert local["recurrent_forward_calls"] == local["count_forward_calls"] == 0
        assert receipt["correct"] == local["correct"]
        assert receipt["mean_cross_entropy"] == local["mean_cross_entropy"]
        exposures[draw["bank_role"]].update(local["row_ids"])
        templates.update(item["template"] for item in local["strata"])
        receipts.append(receipt)
    assert len(calls) == 170
    assert sum(sum(counts.values()) for counts in exposures.values()) == 1020
    for role, counts in exposures.items():
        assert len(counts) == 180 and sum(counts.values()) == 510
        assert Counter(counts.values()) == {3: 150, 2: 30}
        assert dict(counts) == expected["per_source_exposures"][role]
    assert len(templates) == 4 and set(templates.values()) == {255}
    assert all(torch.equal(tensor, state[name]) for name, tensor in model.state_dict().items())
    assert torch.equal(rng, torch.random.get_rng_state()) and random.getstate() == python_rng
    raw_report = legacy_report_fixture(banks, cache, receipts)
    before_report = deepcopy(raw_report)
    report = fixture["owner"].reconcile_training_report(raw_report)
    assert raw_report == before_report
    summary = report["dual_bank_wording_replay"]
    assert summary["committed_updates"] == 170 and summary["completed_schedule"] is True
    assert summary["updates_per_bank"] == {role: 85 for role in retention.ROLES}
    assert summary["presentations_per_bank"] == {role: 510 for role in retention.ROLES}
    assert summary["per_source_exposures"] == expected["per_source_exposures"]
    assert len(summary["committed_draws"]) == 170
    assert report["paraphrase_modality_auxiliary"]["committed_presentations_per_template"] == dict(templates)
    inherited = report["paraphrase_modality_auxiliary"]["inherited_single_bank_template_counts"]
    assert inherited["applicable_to_dual_bank"] is False and set(inherited["counts"].values()) == {510}
    assert all(summary[key] is False for key in fixture["owner"].FALSE)
    assert report["committed_updates"] == raw_report["committed_updates"]


def stable(receipt):
    result = deepcopy(receipt)
    result.pop("elapsed_seconds", None)
    result["bank_local_loss_receipt"].pop("elapsed_seconds", None)
    return result


def test_retry_and_noncommitted_observation_never_advance_bank_local_sampler(monkeypatch):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    first = loss(fixture, model, cache, 0)
    abandoned = loss(fixture, model, cache, 1)
    retry = loss(fixture, model, cache, 1)
    assert stable(abandoned["receipt"]) == stable(retry["receipt"])
    assert torch.equal(abandoned["loss"], retry["loss"])
    assert stable(first["receipt"]) == stable(loss(fixture, model, cache, 0)["receipt"])
    assert loss(fixture, model, cache, 2)["receipt"]["bank_local_committed_step"] == 1
    raw_report = legacy_report_fixture(banks, cache, [first["receipt"]], [abandoned["receipt"], retry["receipt"]])
    summary = fixture["owner"].reconcile_training_report(raw_report)["dual_bank_wording_replay"]
    assert summary["committed_updates"] == 1 and summary["completed_schedule"] is False
    assert summary["updates_per_bank"] == {"control": 1, "balanced": 0}
    assert summary["presentations_per_bank"] == {"control": 6, "balanced": 0}
    assert summary["per_source_exposures"]["balanced"] == {}


def test_full32v_ce_detached_zero_and_positive_non_action_gradients(monkeypatch):
    fixture, model, _, cache, _ = cache_fixture(monkeypatch)
    state = {name: tensor.clone() for name, tensor in model.state_dict().items()}
    zero = loss(fixture, model, cache, 0)
    positive = loss(fixture, model, cache, 0, requires_grad=True)
    assert not zero["loss"].requires_grad and positive["loss"].requires_grad
    zero_receipt = zero["receipt"]["bank_local_loss_receipt"]
    positive_receipt = positive["receipt"]["bank_local_loss_receipt"]
    assert zero_receipt["full_vocabulary_logits"] == positive_receipt["full_vocabulary_logits"]
    manual = []
    for vector, target in zip(positive_receipt["full_vocabulary_logits"], positive_receipt["target_token_ids"]):
        peak = max(vector)
        manual.append(peak + math.log(sum(math.exp(value - peak) for value in vector)) - vector[target])
    assert positive["receipt"]["mean_cross_entropy"] == pytest.approx(sum(manual) / 6, abs=5e-7)
    (.05 * positive["loss"]).backward()
    gradients = {name: parameter.grad for name, parameter in model.named_parameters() if parameter.grad is not None}
    assert gradients and any(bool(value.any()) for value in gradients.values())
    assert all(name.startswith("non_action_head.") or not bool(value.any()) for name, value in gradients.items())
    assert all(parameter.grad is None for name, parameter in model.named_parameters()
        if name.startswith(("projection_down.", "projection_up.")))
    assert all(torch.equal(tensor, state[name]) for name, tensor in model.state_dict().items())


@pytest.mark.parametrize("step", [True, False, -1, 170, 1., "1"])
def test_invalid_committed_step_refused_before_model_forward(monkeypatch, step):
    fixture, model, _, cache, _ = cache_fixture(monkeypatch)
    monkeypatch.setattr(model, "source_value_logits", lambda *args, **kwargs: pytest.fail("invalid step forward"))
    with pytest.raises(ValueError):
        loss(fixture, model, cache, step)


def test_expired_loss_and_foreign_cache_or_model_refused_before_forward(monkeypatch):
    fixture, model, _, cache, _ = cache_fixture(monkeypatch)
    monkeypatch.setattr(model, "source_value_logits", lambda *args, **kwargs: pytest.fail("refused forward"))
    with pytest.raises(TimeoutError):
        fixture["helper"].modality_loss(torch, model, cache, committed_step=0,
            deadline=time.monotonic() - 1, requires_grad=False)
    with pytest.raises(ValueError):
        loss(fixture, model, object(), 0)
    foreign = deepcopy(model)
    with pytest.raises(ValueError):
        loss(fixture, foreign, cache, 0)


def test_cache_receipts_retain_original_orders_and_distinct_bank_handles(monkeypatch):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    handles = cache.caches_by_role
    assert set(handles) == set(retention.ROLES)
    assert handles["control"] is not handles["balanced"]
    assert handles["control"]._data is not handles["balanced"]._data
    assert handles["control"]._vectors is not handles["balanced"]._vectors
    assert handles["control"]._mask is not handles["balanced"]._mask
    assert handles["control"]._targets is not handles["balanced"]._targets
    handles.pop("control")
    assert set(cache.caches_by_role) == set(retention.ROLES)
    receipt = cache.receipt
    for role, handle in cache.caches_by_role.items():
        local = receipt["bank_receipts"][role]
        original = local["original_cache_receipt"]
        assert original == fixture["original_cache_receipts"][role]
        assert original == fixture["original_caches"][role].receipt
        assert handle is not fixture["original_caches"][role]
        for name in ("_model", "_data", "_vectors", "_mask", "_targets", "_fixed", "_versions", "_rows"):
            assert getattr(handle, name) is getattr(fixture["original_caches"][role], name)
        assert original["schema"] == fixture["helpers"][role].CACHE_SCHEMA
        assert original["bank_sha256"] == banks.banks_by_role[role]["bank_sha256"]
        assert local["original_cache_receipt_sha256"] == retention.digest(original)
        assert "bank_role" not in original and "pairing_sha256" not in original
        assert local["orders"] == fixture["pairing"]["orders"][role]
        assert [list(order) for order in handle._orders] == local["orders"]
        assert local["original_cache_mutated"] is False and local["tensors_copied"] is False
        assert handle._model is model
    receipt["bank_receipts"]["control"]["orders"][0][0] = -1
    assert cache.receipt["bank_receipts"]["control"]["orders"][0][0] >= 0
    with pytest.raises(AttributeError):
        cache._caches = {}


@pytest.mark.parametrize("mutation", ["swap", "missing_role", "extra_role", "order", "tensor", "receipt", "buffer"])
def test_changed_cache_member_or_frozen_projection_refused_before_model_forward(monkeypatch, mutation):
    fixture, model, _, cache, _ = cache_fixture(monkeypatch)
    selected = cache.caches_by_role["control"]
    if mutation == "swap":
        cache._caches["control"], cache._caches["balanced"] = cache._caches["balanced"], cache._caches["control"]
    elif mutation == "missing_role":
        cache._caches.pop("control")
    elif mutation == "extra_role":
        cache._caches["other"] = selected
    elif mutation == "order":
        orders = [list(order) for order in selected._orders]
        orders[0][0], orders[0][1] = orders[0][1], orders[0][0]
        object.__setattr__(selected, "_orders", tuple(tuple(order) for order in orders))
    elif mutation == "tensor":
        selected._data.add_(1)
    elif mutation == "receipt":
        selected._receipt["dimension"] = True
    else:
        with torch.no_grad():
            next(model.buffers()).add_(1)
    monkeypatch.setattr(model, "source_value_logits", lambda *args, **kwargs: pytest.fail("changed cache forward"))
    with pytest.raises(ValueError):
        loss(fixture, model, cache, 0)


def test_two_bank_readout_is_detached_and_preserves_modes_rng_state_and_gradients(monkeypatch):
    fixture, model, _, cache, _ = cache_fixture(monkeypatch)
    parameter = next(model.parameters())
    parameter.grad = torch.ones_like(parameter)
    gradient = parameter.grad.clone()
    before = {name: tensor.clone() for name, tensor in model.state_dict().items()}
    rng = torch.random.get_rng_state().clone()
    modes = {name: module.training for name, module in model.named_modules()}
    result = fixture["helper"].evaluate_bank(torch, model, cache, deadline=time.monotonic() + 30.)
    assert set(result["banks_by_role"]) == set(retention.ROLES)
    for role, readout in result["banks_by_role"].items():
        assert readout["groups"]["all"]["rows"] == len(readout["rows"]) == 180
        assert readout["source_head_forward_calls"] == 30 and readout["optimizer_steps"] == 0
        assert readout["bank_sha256"] == fixture["banks"][role]["bank_sha256"]
        assert all(readout["groups"]["modality:" + m]["rows"] == 60 for m in retention.MODALITIES)
        assert all(readout["groups"]["template:" + t]["rows"] == 90
            for t in fixture["helpers"][role].mixture.authored.TEMPLATES)
        assert readout["groups"]["all"]["cross_entropy"] == pytest.approx(
            sum(row["cross_entropy"] for row in readout["rows"]) / 180)
        assert readout["used_for_selection"] is False
    assert all(torch.equal(tensor, before[name]) for name, tensor in model.state_dict().items())
    assert torch.equal(rng, torch.random.get_rng_state())
    assert {name: module.training for name, module in model.named_modules()} == modes
    assert torch.equal(parameter.grad, gradient)


@pytest.mark.parametrize("role", ["control", "balanced"])
def test_changed_role_inventory_still_refused_by_original_consumer(monkeypatch, role):
    fixture = bank_fixture(monkeypatch)
    bad = deepcopy(fixture["inventories"])
    bad[role]["source_inputs"]["clause_cache"][0]["input"][0] = 3.
    seal(bad[role]["source_inputs"], "inputs_sha256")
    seal(bad[role], "payload_sha256")
    fixture["envelope"] = fixture["owner"].build_source_inventory(
        inventories_by_role=bad, pairing=fixture["pairing"])
    with pytest.raises(ValueError):
        prepare(fixture)


@pytest.mark.parametrize("roles", [{"control"}, {"balanced"}, {"control", "balanced", "other"}])
def test_missing_or_extra_bank_roles_refused(monkeypatch, roles):
    fixture = bank_fixture(monkeypatch)
    helpers = {role: fixture["helpers"].get(role, auxiliary) for role in roles}
    with pytest.raises(ValueError):
        fixture["owner"].configure(helpers_by_role=helpers, pairing=fixture["pairing"],
            original_rules=fixture["rules"])


@pytest.mark.parametrize("first_bank", [None, True, "other", 0])
def test_invalid_initial_role_refused(monkeypatch, first_bank):
    fixture = bank_fixture(monkeypatch)
    with pytest.raises(ValueError):
        fixture["owner"].configure(helpers_by_role=fixture["helpers"], pairing=fixture["pairing"],
            original_rules=fixture["rules"], first_bank=first_bank)


def test_changed_codec_and_model_width_refused_before_tensor_loss(monkeypatch):
    fixture, model, banks, _, options = cache_fixture(monkeypatch)
    bad_codec = deepcopy(options["codec"])
    bad_codec["target_vocabulary"][3], bad_codec["target_vocabulary"][4] = (
        bad_codec["target_vocabulary"][4], bad_codec["target_vocabulary"][3])
    with pytest.raises(ValueError):
        fixture["helper"].prepare_tensor_cache(torch, model, banks, codec=bad_codec,
            input_transform=options["input_transform"], seed=1729,
            deadline=time.monotonic() + 30, max_optimizer_steps=170)
    monkeypatch.setattr(model, "dimension", 768)
    with pytest.raises(ValueError):
        fixture["helper"].prepare_tensor_cache(torch, model, banks, codec=options["codec"],
            input_transform=options["input_transform"], seed=1729,
            deadline=time.monotonic() + 30, max_optimizer_steps=170)


@pytest.mark.parametrize("mutation", ["swapped_roles", "wrong_pairing_digest", "unknown_field"])
def test_dual_envelope_rejects_role_relabeling_and_undeclared_metadata(monkeypatch, mutation):
    fixture = bank_fixture(monkeypatch)
    if mutation == "swapped_roles":
        given = {"control": fixture["inventories"]["balanced"],
            "balanced": fixture["inventories"]["control"]}
        with pytest.raises(ValueError):
            envelope = fixture["owner"].build_source_inventory(
                inventories_by_role=given, pairing=fixture["pairing"])
            fixture["helper"].prepare_bank(fixture["train"], fixture["validation"],
                **fixture["kwargs"], source_inventory=envelope,
                deadline=time.monotonic() + 30.)
    else:
        envelope = deepcopy(fixture["envelope"])
        if mutation == "unknown_field":
            envelope["fixture_unknown"] = True
        else:
            # Find the explicit pairing binding without relying on digest-key
            # spelling. A constructor that omits it is itself an error.
            keys = [key for key, value in envelope.items()
                if value == fixture["pairing"]["pairing_sha256"]]
            assert len(keys) == 1
            envelope[keys[0]] = "0" * 64
        if "payload_sha256" in envelope:
            seal(envelope, "payload_sha256")
        with pytest.raises(ValueError):
            fixture["helper"].prepare_bank(fixture["train"], fixture["validation"],
                **fixture["kwargs"], source_inventory=envelope,
                deadline=time.monotonic() + 30.)


@pytest.mark.parametrize("mutation", ["order", "bool_index", "bank_sha", "qualified"])
def test_changed_or_resealed_pairing_cannot_reach_tensor_preparation(monkeypatch, mutation):
    fixture = bank_fixture(monkeypatch)
    pairing = deepcopy(fixture["pairing"])
    if mutation == "order":
        order = pairing["orders"]["balanced"][0]
        order[0], order[1] = order[1], order[0]
    elif mutation == "bool_index":
        pairing["orders"]["control"][0][0] = False
    elif mutation == "bank_sha":
        pairing["banks"]["control"]["bank_sha256"] = "0" * 64
    else:
        pairing["qualified"] = True
    seal(pairing, "pairing_sha256")
    with pytest.raises(ValueError):
        helper = fixture["owner"].configure(helpers_by_role=fixture["helpers"],
            pairing=pairing, original_rules=fixture["rules"])
        envelope = fixture["owner"].build_source_inventory(
            inventories_by_role=fixture["inventories"], pairing=pairing)
        helper.prepare_bank(fixture["train"], fixture["validation"],
            **fixture["kwargs"], source_inventory=envelope,
            deadline=time.monotonic() + 30.)


@pytest.mark.parametrize("mutation", ["global_bool", "local_bool", "optimizer_bool", "wrong_role", "indices",
    "row_ids", "strata", "token_ids", "commit_count_bool", "presentation_count"])
def test_commit_reconciliation_refuses_rewritten_or_untyped_draws(monkeypatch, mutation):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    receipt = loss(fixture, model, cache, 0)["receipt"]
    report = legacy_report_fixture(banks, cache, [receipt])
    update = report["committed_updates"][0]
    outer = update["paraphrase_modality_auxiliary"]["receipt"]
    inner = outer["bank_local_loss_receipt"]
    if mutation == "global_bool":
        outer["global_committed_step"] = False
    elif mutation == "local_bool":
        outer["bank_local_committed_step"] = inner["committed_step"] = False
    elif mutation == "optimizer_bool":
        update["optimizer_step"] = True
    elif mutation == "wrong_role":
        outer["bank_role"] = "balanced"
    elif mutation == "indices":
        inner["indices"][0], inner["indices"][1] = inner["indices"][1], inner["indices"][0]
    elif mutation == "row_ids":
        inner["row_ids"][0], inner["row_ids"][1] = inner["row_ids"][1], inner["row_ids"][0]
    elif mutation == "strata":
        inner["strata"][0]["modality"] = "F"
    elif mutation == "token_ids":
        inner["target_token_ids"][0] = False
    elif mutation == "commit_count_bool":
        report["paraphrase_modality_auxiliary"]["committed_updates"] = True
    else:
        report["paraphrase_modality_auxiliary"]["committed_clause_presentations"] += 6
    with pytest.raises(ValueError):
        fixture["owner"].reconcile_training_report(report)


def trainer_fixture(report):
    """A trainer-shape double solely for private import/report isolation."""
    trainer = ModuleType("_dual_fixture_trainer")
    trainer.__package__ = "ipfs_datasets_py.logic.formalization.autoencoder"
    calls = []

    def importer(*args, **kwargs):
        calls.append((args[0], tuple(args[3] or ()) if len(args) > 3 else (), args[4] if len(args) > 4 else 0))
        return builtins.__import__(*args, **kwargs)

    trainer.__dict__.update(deepcopy=deepcopy, fixture_report=report,
        __builtins__=dict(vars(builtins), __import__=importer))
    exec('def train(*, paraphrase_modality_auxiliary=None):\n'
         ' if paraphrase_modality_auxiliary is None:\n'
         '  return {"report":{"committed_updates":[],"fixture_default":True}}\n'
         ' from . import paraphrase_modality_auxiliary_training as owner\n'
         ' return {"report":deepcopy(fixture_report),"imported_owner":owner}\n'
         'def ordinary():\n'
         ' import math\n'
         ' return math\n', trainer.__dict__)
    return trainer, calls, importer


def test_private_trainer_import_and_report_reconciliation_leave_default_owner_unchanged(monkeypatch):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    receipts = [loss(fixture, model, cache, step)["receipt"] for step in range(2)]
    raw_report = legacy_report_fixture(banks, cache, receipts)
    trainer, calls, importer = trainer_fixture(raw_report)
    original_train = trainer.train
    configured = fixture["owner"].configure_trainer(trainer, fixture["helper"])
    result = configured.train(paraphrase_modality_auxiliary={"explicit_fixture_hook": True})
    assert result["imported_owner"] is fixture["helper"] and calls == []
    summary = result["report"]["dual_bank_wording_replay"]
    assert summary["updates_per_bank"] == {role: 1 for role in retention.ROLES}
    assert summary["presentations_per_bank"] == {role: 6 for role in retention.ROLES}
    assert set(result["report"]["paraphrase_modality_auxiliary"]["committed_presentations_per_template"].values()) == {3}
    assert result["report"]["committed_updates"] == raw_report["committed_updates"]
    assert trainer.train is original_train and trainer.__dict__["__builtins__"]["__import__"] is importer
    assert configured.ordinary().__name__ == "math" and calls == [("math", (), 0)]
    assert trainer.fixture_report == raw_report and "dual_bank_wording_replay" not in raw_report


def test_private_trainer_default_and_explicit_none_bypass_auxiliary_import_and_summary(monkeypatch):
    fixture = bank_fixture(monkeypatch)
    trainer, calls, importer = trainer_fixture({})
    configured = fixture["owner"].configure_trainer(trainer, fixture["helper"])
    before = trainer.train()
    assert configured.train() == before
    assert configured.train(paraphrase_modality_auxiliary=None) == before
    assert calls == []
    assert trainer.__dict__["__builtins__"]["__import__"] is importer


@pytest.mark.parametrize("first_bank", ["control", "balanced"])
def test_prepared_handles_belong_to_one_private_configuration(monkeypatch, first_bank):
    fixture, model, banks, cache, options = cache_fixture(monkeypatch)
    other = fixture["owner"].configure(helpers_by_role=fixture["helpers"],
        pairing=fixture["pairing"], original_rules=fixture["rules"], first_bank=first_bank)
    # Matching source bytes, module objects and models do not authorize a
    # separate private configuration to adopt handles prepared by its peer.
    monkeypatch.setattr(model, "source_value_logits", lambda *args, **kwargs: pytest.fail("foreign configuration forward"))
    monkeypatch.setattr(torch, "tensor", lambda *args, **kwargs: pytest.fail("foreign configuration allocation"))
    with pytest.raises(ValueError):
        other.estimate_training_work_bytes(banks, max_optimizer_steps=170)
    with pytest.raises(ValueError):
        other.prepare_tensor_cache(torch, model, banks, codec=options["codec"],
            input_transform=options["input_transform"], seed=1729,
            deadline=time.monotonic() + 30, max_optimizer_steps=170)
    with pytest.raises(ValueError):
        other.modality_loss(torch, model, cache, committed_step=0,
            deadline=time.monotonic() + 30, requires_grad=False)
    with pytest.raises(ValueError):
        other.evaluate_bank(torch, model, cache, deadline=time.monotonic() + 30)


@pytest.mark.parametrize("mutation", ["rebound_bank_sha", "outer_bank_sha", "selection", "training_scope",
    "commit_authority", "inner_qualified", "cache_role", "cache_dimension", "cache_proof", "cache_qualified"])
def test_report_reconciliation_refuses_rebound_banks_and_authority_claims(monkeypatch, mutation):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    receipt = loss(fixture, model, cache, 0)["receipt"]
    report = legacy_report_fixture(banks, cache, [receipt])
    auxiliary_report = report["paraphrase_modality_auxiliary"]
    local_cache = auxiliary_report["cache_receipt"]["bank_receipts"]["control"]
    outer = report["committed_updates"][0]["paraphrase_modality_auxiliary"]["receipt"]
    inner = outer["bank_local_loss_receipt"]
    if mutation == "rebound_bank_sha":
        # Changing both the claimed cache and the observed bank together must
        # still fail the independent retained schedule's original bank pins.
        local_cache["bank_sha256"] = inner["bank_sha256"] = "0" * 64
    elif mutation == "outer_bank_sha":
        outer["selected_bank_sha256"] = "0" * 64
    elif mutation == "selection":
        auxiliary_report["used_for_selection"] = True
    elif mutation == "training_scope":
        auxiliary_report["training_only"] = False
    elif mutation == "commit_authority":
        outer["optimizer_commit_observed"] = True
    elif mutation == "inner_qualified":
        inner["qualified"] = True
    elif mutation == "cache_role":
        local_cache["bank_role"] = "balanced"
    elif mutation == "cache_dimension":
        local_cache["dimension"] = 768
    elif mutation == "cache_proof":
        local_cache["proof_authority"] = True
    else:
        local_cache["qualified"] = True
    with pytest.raises(ValueError):
        fixture["owner"].reconcile_training_report(report)


def preparation_timeout_fixture():
    return dict(fixture_optimizer_not_executed=True, optimizer_steps=0, committed_updates=[],
        stopped_reason="deadline_during_paraphrase_modality_preparation",
        paraphrase_modality_auxiliary=dict(weight=0., cache_receipt=None,
            committed_updates=0, committed_clause_presentations=0,
            positively_supervised_clause_presentations=0, completed_forward_observations=0,
            forward_attempts=0, observed_clause_presentations=0, uncommitted_observations=[],
            zero_weight_graph_attached=False, training_only=True, used_for_selection=False))


def test_preparation_timeout_preserves_inherited_zero_commit_report_without_caches():
    owner = adapter()
    report = preparation_timeout_fixture()
    before = deepcopy(report)
    result = owner.reconcile_training_report(report)
    assert report == before
    assert all(result[key] == value for key, value in report.items())
    summary = result["dual_bank_wording_replay"]
    assert summary["cache_prepared"] is False
    assert summary["committed_updates"] == 0 and summary["completed_schedule"] is False
    assert summary["updates_per_bank"] == summary["presentations_per_bank"] == {role: 0 for role in retention.ROLES}
    assert all(summary[name] is False for name in owner.FALSE)


@pytest.mark.parametrize("mutation", ["commits", "missing_reason", "wrong_reason", "committed_presentations",
    "observed_presentations", "supervised_presentations", "forwards", "observations", "optimizer_steps", "bool_count"])
def test_absent_cache_is_only_allowed_for_consistent_preparation_timeout(mutation):
    owner = adapter()
    report = preparation_timeout_fixture()
    auxiliary_report = report["paraphrase_modality_auxiliary"]
    if mutation == "commits":
        report["committed_updates"] = [dict(optimizer_step=1)]
    elif mutation == "missing_reason":
        report.pop("stopped_reason")
    elif mutation == "wrong_reason":
        report["stopped_reason"] = "deadline_during_forward"
    elif mutation == "committed_presentations":
        auxiliary_report["committed_clause_presentations"] = 6
    elif mutation == "observed_presentations":
        auxiliary_report["observed_clause_presentations"] = 6
    elif mutation == "supervised_presentations":
        auxiliary_report["positively_supervised_clause_presentations"] = 6
    elif mutation == "forwards":
        auxiliary_report["forward_attempts"] = 1
    elif mutation == "observations":
        auxiliary_report["uncommitted_observations"] = [{"fixture": True}]
    elif mutation == "optimizer_steps":
        report["optimizer_steps"] = 1
    else:
        auxiliary_report["committed_updates"] = False
    with pytest.raises(ValueError):
        owner.reconcile_training_report(report)


@pytest.mark.parametrize("mutation", ["inner_schema", "zero_true_graph", "inner_true_graph", "update_weight",
    "top_weight_bool", "update_weight_bool", "top_weight_int", "top_weight_disagrees"])
def test_committed_graph_and_loss_schema_match_exact_profile_and_weight(monkeypatch, mutation):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    receipt = loss(fixture, model, cache, 0)["receipt"]
    report = legacy_report_fixture(banks, cache, [receipt])
    auxiliary_report = report["paraphrase_modality_auxiliary"]
    update = report["committed_updates"][0]["paraphrase_modality_auxiliary"]
    outer = update["receipt"]
    inner = outer["bank_local_loss_receipt"]
    if mutation == "inner_schema":
        inner["schema"] = "fixture_foreign_loss/v1"
    elif mutation == "zero_true_graph":
        outer["gradient_enabled"] = inner["gradient_enabled"] = True
    elif mutation == "inner_true_graph":
        inner["gradient_enabled"] = True
    elif mutation == "update_weight":
        update["weight"] = .75
    elif mutation == "top_weight_bool":
        auxiliary_report["weight"] = False
    elif mutation == "update_weight_bool":
        update["weight"] = False
    elif mutation == "top_weight_int":
        auxiliary_report["weight"] = 0
    else:
        auxiliary_report["weight"] = .05
    with pytest.raises(ValueError):
        fixture["owner"].reconcile_training_report(report)


def test_positive_weight_reconciles_real_gradient_enabled_source_forwards(monkeypatch):
    fixture, model, banks, cache, _ = cache_fixture(monkeypatch)
    before = {name: tensor.clone() for name, tensor in model.state_dict().items()}
    observations = [loss(fixture, model, cache, step, requires_grad=True) for step in range(2)]
    assert all(result["loss"].requires_grad for result in observations)
    raw_report = legacy_report_fixture(banks, cache,
        [result["receipt"] for result in observations], weight=.05)
    report = fixture["owner"].reconcile_training_report(raw_report)
    assert report["dual_bank_wording_replay"]["updates_per_bank"] == {role: 1 for role in retention.ROLES}
    assert report["paraphrase_modality_auxiliary"]["positively_supervised_clause_presentations"] == 12
    assert all(update["paraphrase_modality_auxiliary"]["weighted_loss"] == pytest.approx(
        .05 * update["paraphrase_modality_auxiliary"]["receipt"]["mean_cross_entropy"])
        for update in report["committed_updates"])
    assert report["committed_updates"] == raw_report["committed_updates"]
    assert all(parameter.grad is None for parameter in model.parameters())
    assert all(torch.equal(tensor, before[name]) for name, tensor in model.state_dict().items())
