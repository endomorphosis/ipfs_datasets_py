"""Synthetic action composition controls, never corpus/qualification evidence."""
from copy import deepcopy
import hashlib
import math
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import action_contrastive_decoder_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_decoder_training as tokens_owner
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
from .test_long_span_cardinality_training import setup, validate_rule


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def sources(*, duplicate=True):
    _, base, _, _, options = setup()
    first = dict(actor="officer", action="retain", object="file", modality="O",
        conditions=[], exceptions=[], temporal=[])
    rules = [first, dict(first, actor="agency"), dict(first, actor="agency", action="disclose")]
    cache = []
    def split(name, start):
        rows, references = [], []
        clauses = [name+" actual source clause "+str(i)+"." for i in range(3)]
        for index, text in enumerate(clauses):
            cache.append(dict(id=name+"-cache-"+str(index), source_text=text,
                input=[float(j == start+index) for j in range(8)]))
        orders = [[0], [1], [2]]+([[0, 1]] if duplicate else [])
        vocabulary = options["codec"]["target_vocabulary"]
        for index, order in enumerate(orders):
            identity = name+"-"+str(index)
            source = "\n\n".join(clauses[i] for i in order)
            target = dict(rules=[deepcopy(rules[i]) for i in order])
            ids = [1]+[vocabulary.index(token) for token,_ in tokens_owner._tokens(target, semantic=False)]+[2]
            rows.append(dict(id=identity, source_text=source, input=[.1*(start+index+1)]+[0.]*7, target_ids=ids))
            references.append(dict(id=identity, source_text=source, target=target, clause_count=len(order)))
        return rows, references
    train, train_refs = split("train", 0)
    tune, tune_refs = split("validation", 4)
    contexts = {name:contexts_owner.build_source_contexts(
        [{key:row[key] for key in ("id", "source_text")} for row in rows], cache)
        for name,rows in (("train",train),("validation",tune))}
    options.update(training_references=train_refs, validation_references=tune_refs,
        curriculum=[dict(name="all", training_ids=[row["id"] for row in train], epochs=2)])
    options["config"].update(batch_size=4, max_optimizer_steps=2, validation_interval=2, epochs=2,
        max_seconds=30., max_memory_bytes=268435456)
    return base, train, tune, options, contexts


class ActionProbe(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.action_projection = torch.nn.Linear(8, 64)
        self.unrelated = torch.nn.Linear(8, 64)
        self.calls = []
        with torch.no_grad():
            self.action_projection.weight.copy_(torch.arange(512).reshape(64,8).remainder(17)/17-.5)
            self.action_projection.bias.zero_()

    def describe(self):
        return dict(schema=subject.MODEL_SCHEMA)

    def source_action_features(self, projected, *, source_context):
        self.calls.append(source_context)
        assert set(source_context) == {"vectors", "mask"}
        return torch.tanh(self.action_projection(source_context["vectors"])) * source_context["mask"].unsqueeze(-1)


def prepared_loss(*, duplicate=True, model=None):
    _, rows, _, options, contexts = sources(duplicate=duplicate)
    inventory = subject.prepare_training_inventory(rows, options["training_references"],
        contexts=contexts["train"], codec=options["codec"], validate_rule=validate_rule)
    packet = core._source_context_kwargs(torch, rows, contexts["train"], options["input_transform"])["source_context"]
    return model or ActionProbe(), rows, packet, inventory


def calculate(model, rows, packet, inventory, **kwargs):
    deadline = kwargs.pop("deadline") if "deadline" in kwargs else time.monotonic()+10
    return subject.source_action_contrastive_loss(torch, model, torch.zeros(len(rows),8), rows,
        source_context=packet, inventory=inventory, deadline=deadline, **kwargs)


def test_authentication_deduplication_and_recomputable_supervised_loss():
    model, rows, packet, inventory = prepared_loss()
    before = core.tensor_digest(model); rng = torch.random.get_rng_state().clone()
    result = calculate(model, rows, packet, inventory)
    receipt = result["receipt"]
    assert receipt["clause_occurrences"] == 5 and receipt["unique_clause_count"] == 3
    assert receipt["duplicate_clause_occurrences"] == 2
    assert receipt["active_anchor_count"] == receipt["directed_positive_pairs"] == receipt["directed_negative_pairs"] == 2
    assert receipt["pair_sets"][0]["positive_indices"] == [1]
    assert receipt["pair_sets"][0]["negative_indices"] == [2]
    assert receipt["unique_clauses"][0]["occurrences"] == [dict(row_id="train-0",slot=0),dict(row_id="train-3",slot=0)]
    vectors = receipt["normalized_features"]
    losses = []
    for pair in receipt["pair_sets"]:
        if not pair["eligible"]: continue
        scores = {j:sum(a*b for a,b in zip(vectors[pair["anchor"]],vectors[j]))/.1
            for j in pair["positive_indices"]+pair["negative_indices"]}
        peak = max(scores.values())
        expected = peak+math.log(sum(math.exp(score-peak) for score in scores.values()))
        expected -= sum(scores[j] for j in pair["positive_indices"])/len(pair["positive_indices"])
        assert pair["loss"] == pytest.approx(expected, abs=2e-6)
        losses.append(expected)
    assert float(result["loss"].detach()) == pytest.approx(sum(losses)/len(losses), abs=2e-6)
    assert core.tensor_digest(model) == before and torch.equal(torch.random.get_rng_state(),rng)
    assert model.calls == [packet]
    assert not receipt["reference_documents_passed_to_model"] and not receipt["validation_rows_used"]
    assert receipt["temperature_scope"] == "contrastive_loss_only_not_generation"


def test_gradients_only_through_separate_action_features_and_weighted_receipt():
    model, rows, packet, inventory = prepared_loss()
    result = calculate(model, rows, packet, inventory)
    (.05*result["loss"]).backward()
    assert model.action_projection.weight.grad.abs().sum() > 0
    assert model.unrelated.weight.grad is None and model.unrelated.bias.grad is None
    subject.record_feature_gradient(torch, result, weight=.05)
    assert result["receipt"]["weighted_feature_gradient_norm"] == float(result["features"].grad.norm())
    assert result["receipt"]["weighted_feature_gradient_norm"] > 0
    assert result["receipt"]["weight"] == .05


def test_preexisting_main_graph_is_not_detached_or_replaced():
    model, rows, packet, inventory = prepared_loss()
    main = model.unrelated(torch.ones(1,8)).square().sum()
    result = calculate(model, rows, packet, inventory)
    (main+.05*result["loss"]).backward()
    assert model.action_projection.weight.grad.abs().sum() > 0
    assert model.unrelated.weight.grad.abs().sum() > 0


def test_zero_action_features_remain_finite_and_recomputable():
    model, rows, packet, inventory = prepared_loss()
    with torch.no_grad():
        model.action_projection.weight.zero_(); model.action_projection.bias.zero_()
    result = calculate(model,rows,packet,inventory)
    assert result["receipt"]["loss"] == pytest.approx(math.log(2),abs=1e-7)
    assert result["receipt"]["unnormalized_feature_norms"] == [0.,0.,0.]
    (.05*result["loss"]).backward()
    subject.record_feature_gradient(torch,result,weight=.05)
    assert result["receipt"]["weighted_feature_gradient_norm"] == 0.


@pytest.mark.parametrize("indices", [[0], [0,1], [0,2], [2]])
def test_no_positive_or_negative_has_no_feature_forward_or_graph(indices):
    model, rows, packet, inventory = prepared_loss()
    actual = [rows[i] for i in indices]
    reduced = {key:value[indices] for key,value in packet.items()}
    result = calculate(model, actual, reduced, inventory)
    assert result["loss"] is None and result["features"] is None and not model.calls
    assert result["receipt"]["normalized_features"] is None
    assert result["receipt"]["active_anchor_count"] == 0
    subject.record_feature_gradient(torch, result, weight=.05)
    assert result["receipt"]["weighted_feature_gradient_norm"] is None


def test_same_actor_same_action_other_source_is_excluded_not_negative():
    model, rows, packet, inventory = prepared_loss()
    extra = deepcopy(inventory["rows"][rows[0]["id"]]["clauses"][0])
    extra["source_sha256"] = "a"*64
    inventory["rows"][rows[3]["id"]]["clauses"][1] = extra
    inventory["inventory_sha256"] = core.digest({key:value for key,value in inventory.items() if key != "inventory_sha256"})
    result = calculate(model, rows, packet, inventory)
    pair = result["receipt"]["pair_sets"][0]
    assert pair["positive_indices"] == [1] and pair["negative_indices"] == [2]
    assert 3 not in pair["positive_indices"]+pair["negative_indices"]


@pytest.mark.parametrize("change", [
    lambda r,i: r[0].update(id="validation-0"),
    lambda r,i: r[0].update(source_text="forged"),
    lambda r,i: r[0].update(input=[0.]*8),
    lambda r,i: i["rows"][r[0]["id"]]["clauses"][0].update(action_token_id=0),
])
def test_batch_or_inventory_tampering_rejects_before_feature_graph(change):
    model, rows, packet, inventory = prepared_loss()
    change(rows,inventory)
    with pytest.raises(ValueError): calculate(model,rows,packet,inventory)
    assert not model.calls


def test_wrong_context_mask_rejects_before_model_call():
    model, rows, packet, inventory = prepared_loss()
    packet["mask"][0,1] = True
    with pytest.raises(ValueError,match="mask differs"): calculate(model,rows,packet,inventory)
    assert not model.calls


@pytest.mark.parametrize("mutation", ["reference", "target", "source", "duplicate_labels", "count"])
def test_preparation_refuses_unauthenticated_or_inconsistent_training_labels(mutation):
    _, rows, _, options, contexts = sources()
    references = options["training_references"]
    if mutation == "reference": references[0]["target"]["rules"][0]["actor"] = "agency"
    if mutation == "target": rows[0]["target_ids"][-2] = 0
    if mutation == "source": references[0]["source_text"] = "other source"
    if mutation in ("duplicate_labels", "count"):
        if mutation == "duplicate_labels": references[3]["target"]["rules"][0]["actor"] = "agency"
        else:
            references[3]["target"]["rules"] = references[3]["target"]["rules"][:1]
            references[3]["clause_count"] = 1
        vocabulary = options["codec"]["target_vocabulary"]
        rows[3]["target_ids"] = [1]+[vocabulary.index(token) for token,_ in tokens_owner._tokens(
            references[3]["target"],semantic=False)]+[2]
    with pytest.raises(ValueError):
        subject.prepare_training_inventory(rows,references,contexts=contexts["train"],
            codec=options["codec"],validate_rule=validate_rule)


def test_deadline_refuses_before_and_after_feature_forward(monkeypatch):
    model, rows, packet, inventory = prepared_loss()
    with pytest.raises(TimeoutError): calculate(model, rows, packet, inventory, deadline=0.)
    assert not model.calls
    clock = iter([0.,2.]); monkeypatch.setattr(subject.time,"monotonic",lambda:next(clock))
    with pytest.raises(TimeoutError): calculate(model, rows, packet, inventory, deadline=1.)
    assert len(model.calls) == 1 and all(p.grad is None for p in model.parameters())


def actual_fixture():
    from ipfs_datasets_py.logic.formalization.autoencoder import projected_source_decoder_experiment as projected
    from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_decoder_experiment as clauses
    from ipfs_datasets_py.logic.formalization.autoencoder import action_factorized_clause_decoder_experiment as actions
    base, train, tune, options, contexts = sources(duplicate=False)
    kwargs = dict(expected_training_ids=[row["id"] for row in train],
        forbidden_validation_ids=[row["id"] for row in tune],training_rows_sha256=core.digest(train))
    with torch.no_grad(): features = base.project(torch.tensor([row["input"] for row in train])).tolist()
    feature_rows = [dict(id=row["id"],source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),features=vector)
        for row,vector in zip(train,features)]
    normalization = projected.fit_source_normalization(feature_rows,kind="center_rms",**kwargs)
    counts = [dict(id=row["id"],source_sha256=row["source_sha256"],count=1) for row in feature_rows]
    prior = projected.fit_source_count_prior(counts,**kwargs)
    donor = projected.bind_projected_source_model(base,codec=options["codec"],normalization_receipt=normalization,
        count_prior_receipt=prior,guide_boundary=True)
    unique = contexts_owner.unique_training_clauses(train,tune,contexts)
    context_inventory = contexts_owner.validate_training_contexts(train,tune,contexts)
    with torch.no_grad(): features = donor.project(torch.tensor([row["input"] for row in unique])).tolist()
    clause_rows = [dict(id=row["id"],source_sha256=row["source_sha256"],features=feature) for row,feature in zip(unique,features)]
    clause_norm = projected.fit_source_normalization(clause_rows,kind="center_rms",
        expected_training_ids=[row["id"] for row in unique],training_rows_sha256=core.digest(train),
        forbidden_validation_ids=[row["id"] for row in context_inventory["validation_clause_inventory"]])
    clause_norm["training_contexts_sha256"] = core.digest(contexts["train"])
    clause_norm["receipt_sha256"] = core.digest({key:value for key,value in clause_norm.items() if key != "receipt_sha256"})
    model = clauses.bind_clause_source_model(donor,head_seed=1729,clause_normalization_receipt=clause_norm)
    return actions.bind_action_factorized_clause_model(model,codec=options["codec"]),train,tune,options,contexts


def test_weight_zero_preserves_exact_legacy_report_states_and_no_helper_work(monkeypatch):
    from .test_long_span_source_value_training import prepared
    model, _, train, tune, options = prepared()
    kwargs = dict(source_value_weight=.25, cardinality_weight=.25, count_exposure="balanced_all",**options)
    expected = trainer.train(model,train,tune,**kwargs)
    monkeypatch.setattr(subject,"prepare_training_inventory",lambda *a,**kw:pytest.fail("zero-weight preparation"))
    monkeypatch.setattr(subject,"source_action_contrastive_loss",lambda *a,**kw:pytest.fail("zero-weight graph"))
    actual = trainer.train(model,train,tune,action_contrastive_weight=0.,**kwargs)
    for role in ("state_dict","last_complete_attempt_state_dict"):
        assert set(expected[role]) == set(actual[role])
        assert all(torch.equal(value,actual[role][key]) for key,value in expected[role].items())
    for result in (expected,actual): result["report"].pop("elapsed_seconds")
    assert expected["report"] == actual["report"]
    assert expected["predictions"] == actual["predictions"]
    assert not any(key.startswith("action_contrastive") for key in actual["report"])


@pytest.mark.parametrize("weight", [True,None,-.1,1.1,float("nan"),float("inf"),".05"])
def test_invalid_weight_fails_before_copy(weight,monkeypatch):
    from .test_long_span_source_value_training import prepared
    model, _, train, tune, options = prepared()
    monkeypatch.setattr(trainer,"deepcopy",lambda value:pytest.fail("premature copy"))
    with pytest.raises(ValueError,match="action-contrastive weight"):
        trainer.train(model,train,tune,action_contrastive_weight=weight,**options)


def test_positive_weight_requires_new_schema():
    from .test_clause_context_training_integration import contextual_training_fixture
    model,train,tune,options,contexts = contextual_training_fixture()
    with pytest.raises(ValueError,match="requires action-factorized"):
        trainer.train(model,train,tune,action_contrastive_weight=.05,source_contexts=contexts,**options)


def test_new_schema_zero_weight_skips_contrastive_work_and_preserves_report(monkeypatch):
    model,train,tune,options,contexts = actual_fixture()
    kwargs = dict(source_contexts=contexts,source_value_weight=.25,cardinality_weight=.25,**options)
    expected = trainer.train(model,train,tune,**kwargs)
    monkeypatch.setattr(subject,"prepare_training_inventory",lambda *a,**kw:pytest.fail("zero-weight preparation"))
    monkeypatch.setattr(type(model),"source_action_features",lambda *a,**kw:pytest.fail("zero-weight feature branch"))
    actual = trainer.train(model,train,tune,action_contrastive_weight=0.,**kwargs)
    for role in ("state_dict","last_complete_attempt_state_dict"):
        assert all(torch.equal(value,actual[role][key]) for key,value in expected[role].items())
    for result in (expected,actual): result["report"].pop("elapsed_seconds")
    assert expected["report"] == actual["report"]


def test_actual_action_feature_loss_cannot_update_recurrent_or_non_action_parameters():
    model,train,_,options,contexts = actual_fixture()
    inventory = subject.prepare_training_inventory(train,options["training_references"],
        contexts=contexts["train"],codec=options["codec"],validate_rule=validate_rule)
    packet = core._source_context_kwargs(torch,train,contexts["train"],options["input_transform"])["source_context"]
    result = calculate(model,train,packet,inventory)
    (.05*result["loss"]).backward()
    changed = {name for name,p in model.named_parameters() if p.grad is not None}
    assert changed == {"action_head.source_projection.weight","action_head.source_projection.bias"}
    assert model.action_head.source_projection.weight.grad.abs().sum() > 0


def test_actual_opt_in_training_adds_only_current_training_loss_and_preserves_inputs():
    model,train,tune,options,contexts = actual_fixture()
    before = core.tensor_digest(model); inputs = deepcopy((train,tune,options,contexts))
    result = trainer.train(model,train,tune,action_contrastive_weight=.05,source_contexts=contexts,
        source_value_weight=.25,cardinality_weight=.25,count_exposure="balanced_all",**options)
    report = result["report"]
    assert report["optimizer_steps"] == report["action_contrastive_active_updates"] == 2
    assert report["action_contrastive_skipped_updates"] == 0
    assert report["generation_temperature"] == 0 and report["action_contrastive_temperature"] == .1
    assert report["selection"] == "per_length_nonregression_then_fidelity_progress_then_reference_ce"
    assert report["source_value_presentations"] == 24
    for update in report["committed_updates"]:
        receipt = update["action_contrastive"]
        assert receipt["row_ids"] == update["decoder_row_ids"]
        assert set(receipt["row_ids"]) == {row["id"] for row in train}
        assert receipt["active_anchor_count"] == 2 and receipt["weighted_feature_gradient_norm"] > 0
        expected = update["weighted_token_ce"]+.25*update["count_ce"]+.25*update["source_value_ce"]
        expected += report["config"]["reconstruction_weight"]*update["raw_reconstruction_mse"]+.05*receipt["loss"]
        assert update["objective"] == pytest.approx(expected,abs=1e-6)
        assert not receipt["used_for_selection"] and not receipt["admitted"]
    assert core.tensor_digest(model) == before and (train,tune,options,contexts) == inputs
    for name,value in model.state_dict().items():
        if name in dict(model.named_buffers()) or name in report["frozen_parameter_names"]:
            assert torch.equal(value,result["last_complete_attempt_state_dict"][name])


def test_deadline_inside_contrastive_cannot_commit_partial_update(monkeypatch):
    model,train,tune,options,contexts = actual_fixture()
    def expired(*args,**kwargs): raise TimeoutError("controlled deadline")
    monkeypatch.setattr(subject,"source_action_contrastive_loss",expired)
    monkeypatch.setattr(torch.optim.AdamW,"step",lambda *a,**kw:pytest.fail("partial update"))
    result = trainer.train(model,train,tune,action_contrastive_weight=.05,source_contexts=contexts,
        source_value_weight=.25,cardinality_weight=.25,**options)
    assert result["report"]["optimizer_steps"] == 0
    assert result["report"]["stopped_reason"] == "deadline_during_action_contrastive"
    assert result["report"]["committed_updates"] == []


def test_contrastive_improvement_does_not_override_original_source_fidelity_gate(monkeypatch):
    from .test_long_span_cardinality_training import evaluated
    model,train,tune,options,contexts = actual_fixture()
    observed = [evaluated(options,ce=2.),evaluated(options,ce=.01,
        mutate=lambda target:target["rules"][0].update(actor="agency"))]
    for item in observed: item["source_values"] = dict(cross_entropy=.001,predictions=[])
    sequence = iter(observed)
    monkeypatch.setattr(trainer,"_evaluate",lambda *a,**kw:next(sequence))
    result = trainer.train(model,train,tune,action_contrastive_weight=.05,source_contexts=contexts,
        source_value_weight=.25,cardinality_weight=.25,**options)
    assert result["report"]["selected_epoch"] == 0
    assert any("actor" in reason for reason in result["report"]["history"][-1]["rejection_reasons"])
