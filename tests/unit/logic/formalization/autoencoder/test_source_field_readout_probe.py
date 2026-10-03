"""Synthetic raw-head diagnostics; no formula qualification or source parser."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import time

import pytest

torch = pytest.importorskip("torch")
_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/source_field_readout_probe.py"
_SPEC = importlib.util.spec_from_file_location("standalone_source_field_readout_probe", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def fixture():
    training = dict(schema=subject.TRAINING_SCHEMA, split="train", dimension=8, vocabulary_size=32,
        fields=list(subject.FIELDS), rows=[dict(id="training:"+str(i), source_sha256=subject.digest(str(i)),
            input=[math.sin(i+j) for j in range(8)], labels=dict(actor=i % 3, modality=4+i % 2, object=6+i % 4))
            for i in range(8)])
    head = dict(schema=subject.HEAD_SCHEMA, dimension=8, vocabulary_size=32, hidden_width=64,
        fields=list(subject.FIELDS), parameters={
            "source_projection.weight": [[math.sin(i*8+j)/math.sqrt(8) for j in range(8)] for i in range(64)],
            "source_projection.bias": [0.]*64,
            "field_readout.weight": [[0.]*64 for _ in range(96)], "field_readout.bias": [0.]*96})
    return training, head


def run(training=None, head=None, **kwargs):
    if training is None:
        training, head = fixture()
    return subject.run_source_field_readout_probe(torch, training, head,
        expected_training_sha256=kwargs.pop("expected_training_sha256", subject.digest(training)),
        expected_initial_head_sha256=kwargs.pop("expected_initial_head_sha256", subject.digest(head)),
        mode=kwargs.pop("mode", "shared_non_action"), learning_rate=kwargs.pop("learning_rate", .001),
        max_updates=kwargs.pop("max_updates", 2), checkpoints=kwargs.pop("checkpoints", (0, 1, 2)),
        deadline=kwargs.pop("deadline", time.monotonic()+30), **kwargs)


@pytest.mark.parametrize("mode,count", [("shared_non_action", 3), ("isolated_object", 1)])
@pytest.mark.parametrize("lr", [.001, .01])
def test_full_vocabulary_scaled_objective_and_actual_updates(mode, count, lr):
    result = run(mode=mode, learning_rate=lr)
    assert result["complete"] and result["completed_updates"] == 2
    first = result["checkpoints"][0]
    assert first["objective"] == pytest.approx(count*.0625*math.log(32))
    assert result["updates"][0]["objective"] == pytest.approx(count*.0625*math.log(32))
    for field in first["fields"].values():
        assert field["cross_entropy"] == pytest.approx(math.log(32))
        assert all(len(row) == 32 and set(row) == {0.} for row in field["logits"])
        assert field["weighted_gradient_norms"]["source_projection"] == 0.
        assert field["weighted_gradient_norms"]["field_readout"] > 0.
    assert all(pair["projection_cosine"] is None for pair in first["projection_gradient_geometry"])
    assert result["checkpoints"][-1]["fields"]["object"]["cross_entropy"] < math.log(32)
    assert result["checkpoints"][1]["fields"]["object"]["weighted_gradient_norms"]["source_projection"] > 0.
    assert result["checkpoints"][-1]["parameters_sha256"] != first["parameters_sha256"]
    assert all(value["step"] == 2 for value in result["final_adam_state"].values())
    assert len(result["final_parameters"]["field_readout.weight"]) == count*32
    assert result["field_coefficient"] == .0625
    assert result["optimizer"] == dict(name="AdamW", betas=[.9,.999], eps=1e-8,
        weight_decay=.01, foreach=False, max_grad_norm=1., full_batch=True, scheduler=None)


def test_initial_raw_head_and_isolated_slice_exact():
    shared = run(max_updates=1, checkpoints=(0, 1))
    isolated = run(mode="isolated_object", max_updates=1, checkpoints=(0, 1))
    assert shared["checkpoints"][0]["fields"]["object"] == isolated["checkpoints"][0]["fields"]["object"]
    assert shared["checkpoints"][0]["parameters"]["source_projection.weight"] == isolated["checkpoints"][0]["parameters"]["source_projection.weight"]
    assert shared["final_parameters"]["field_readout.weight"][64:96] == isolated["final_parameters"]["field_readout.weight"]


def test_metrics_match_independent_full_vocabulary_arithmetic_and_margin():
    training, head = fixture()
    result = run(training, head, learning_rate=.01)
    for check in result["checkpoints"]:
        objective = 0.
        for field, record in check["fields"].items():
            loss, correct = 0., 0
            for row, logits, margin, prediction in zip(training["rows"], record["logits"],
                    record["target_minus_best_other_margins"], record["predictions"]):
                target = row["labels"][field]
                high = max(logits)
                loss += high+math.log(sum(math.exp(v-high) for v in logits))-logits[target]
                expected = logits[target]-max(v for i,v in enumerate(logits) if i != target)
                assert margin == pytest.approx(expected, abs=1e-7)
                assert prediction == logits.index(high)
                correct += prediction == target
            assert record["cross_entropy"] == pytest.approx(loss/len(training["rows"]), abs=5e-7)
            assert record["correct"] == correct
            assert record["accuracy"] == correct/len(training["rows"])
            objective += .0625*loss/len(training["rows"])
        assert check["objective"] == pytest.approx(objective, abs=1e-7)


def test_preserves_caller_plain_inputs_rng_and_unrelated_gradients():
    training, head = fixture()
    before = deepcopy((training, head))
    rng = torch.get_rng_state().clone()
    unrelated = torch.nn.Parameter(torch.tensor([1.]))
    unrelated.grad = torch.tensor([3.])
    result = run(training, head)
    assert (training, head) == before and torch.equal(rng, torch.get_rng_state())
    assert unrelated.item() == 1. and unrelated.grad.item() == 3.
    for flag in ("optimizer_resumable", "validation_access", "source_parser_used", "formula_decoder_used",
                 "generated_formula_metrics_computed", "qualification_gates_changed", "lake_executed",
                 "admitted", "qualified", "production_checkpoint", "convergence_proven"):
        assert result[flag] is False
    assert result["training_only"] is True
    assert result["source_order_sha256"] == subject.digest([row["id"] for row in training["rows"]])
    assert result["source_inputs_sha256"] == subject.digest([row["input"] for row in training["rows"]])


def test_repeated_literal_occurrences_retain_full_batch_weighting():
    training, head = fixture()
    training["rows"].append(dict(deepcopy(training["rows"][0]), id="duplicate-occurrence"))
    result = run(training, head)
    assert result["training_occurrences"] == 9 and result["training_unique_clauses"] == 8
    assert len(result["checkpoints"][0]["fields"]["object"]["logits"]) == 9


@pytest.mark.parametrize("mode", ["shared_non_action", "isolated_object"])
def test_one_step_matches_direct_full_vocabulary_adam(mode):
    training, head = fixture()
    actual = run(training, head, mode=mode, max_updates=1, checkpoints=(0, 1))
    fields = list(subject.FIELDS) if mode == "shared_non_action" else ["object"]
    arrays = deepcopy(head["parameters"])
    if mode == "isolated_object":
        arrays["field_readout.weight"] = arrays["field_readout.weight"][64:96]
        arrays["field_readout.bias"] = arrays["field_readout.bias"][64:96]
    parameters = [torch.nn.Parameter(torch.tensor(arrays[name])) for name in subject.PARAMETER_NAMES]
    optimizer = torch.optim.AdamW(parameters, lr=.001, betas=(.9, .999), eps=1e-8,
                                 weight_decay=.01, foreach=False)
    x = torch.tensor([row["input"] for row in training["rows"]])
    y = torch.tensor([[row["labels"][field] for field in fields] for row in training["rows"]])
    hidden = torch.tanh(torch.nn.functional.linear(x, *parameters[:2]))
    logits = torch.nn.functional.linear(hidden, *parameters[2:]).reshape(len(x), len(fields), 32)
    loss = .0625*sum(torch.nn.functional.cross_entropy(logits[:, i], y[:, i]) for i in range(len(fields)))
    loss.backward()
    torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True)
    optimizer.step()
    assert actual["final_parameters"] == {name: p.detach().tolist() for name,p in zip(subject.PARAMETER_NAMES,parameters)}
    expected_adam = {name: {key: value.detach().tolist() for key,value in optimizer.state[p].items()}
                     for name,p in zip(subject.PARAMETER_NAMES,parameters)}
    assert actual["final_adam_state"] == expected_adam


@pytest.mark.parametrize("context", [torch.no_grad, torch.inference_mode,
    lambda: torch.autocast("cpu", dtype=torch.bfloat16)])
def test_non_float32_or_no_gradient_context_is_rejected(context):
    with context(), pytest.raises(ValueError, match="ordinary float32 gradient context"):
        run()


@pytest.mark.parametrize("after_step", [1, 2])
def test_deadline_after_adam_rolls_back_both_parameters_and_optimizer(monkeypatch, after_step):
    reference = run(max_updates=1, checkpoints=(0, 1)) if after_step == 2 else None
    clock = [0.]
    original = torch.optim.AdamW.step
    calls = [0]
    def expires(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        calls[0] += 1
        if calls[0] == after_step:
            clock[0] = 2.
        return result
    monkeypatch.setattr(torch.optim.AdamW, "step", expires)
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    result = run(deadline=1.)
    assert result["completed_updates"] == after_step-1 and not result["complete"]
    assert result["stopped_reason"] == "deadline" and result["pending_update_rolled_back"]
    if reference is None:
        assert result["final_parameters"] == result["checkpoints"][0]["parameters"]
        assert all(value == {} for value in result["final_adam_state"].values())
    else:
        assert result["final_parameters"] == reference["final_parameters"]
        assert result["final_adam_state"] == reference["final_adam_state"]
    assert len(result["updates"]) == after_step-1


def test_initial_deadline_performs_no_step(monkeypatch):
    monkeypatch.setattr(torch.optim.AdamW, "step", lambda *a, **k: pytest.fail("deadline allowed an update"))
    result = run(deadline=time.monotonic()-1)
    assert result["completed_updates"] == 0 and not result["complete"]
    assert not result["checkpoints"] and not result["pending_update_rolled_back"]
    assert all(value == {} for value in result["final_adam_state"].values())


def test_deadline_after_backward_does_not_touch_adam(monkeypatch):
    clock = [0.]
    original = torch.Tensor.backward
    def expires(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        clock[0] = 2.
        return result
    monkeypatch.setattr(torch.Tensor, "backward", expires)
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    result = run(deadline=1.)
    assert result["completed_updates"] == 0 and not result["pending_update_rolled_back"]
    assert all(value == {} for value in result["final_adam_state"].values())


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(split="validation"),
    lambda d: d.update(validation_rows=[]),
    lambda d: d.update(dimension=True),
    lambda d: d.update(dimension=384),
    lambda d: d.update(vocabulary_size=2),
    lambda d: d.update(fields=["object", "modality", "actor"]),
    lambda d: d.update(rows=[]),
    lambda d: d.update(rows=d["rows"]*23),
    lambda d: d["rows"][0].update(input=[0.]*7),
    lambda d: d["rows"][0].update(input=[True]*8),
    lambda d: d["rows"][0].update(input=[float("nan")]*8),
    lambda d: d["rows"][0].update(input=[float("inf")]*8),
    lambda d: d["rows"][0].update(input=[1e7]*8),
    lambda d: d["rows"][0].update(input=[10**1000]*8),
    lambda d: d["rows"][0]["labels"].update(object=True),
    lambda d: d["rows"][0]["labels"].update(object=-1),
    lambda d: d["rows"][0]["labels"].update(object=32),
    lambda d: d["rows"][0]["labels"].update(action=1),
    lambda d: d["rows"][0].update(source_sha256="unbound"),
    lambda d: d["rows"][1].update(id=d["rows"][0]["id"]),
    lambda d: d["rows"][1].update(source_sha256=d["rows"][0]["source_sha256"]),
])
def test_closed_training_rejects_malformed_or_hidden_inputs_before_fit(mutation, monkeypatch):
    training, head = fixture()
    mutation(training)
    monkeypatch.setattr(torch.optim, "AdamW", lambda *a, **k: pytest.fail("invalid data constructed optimizer"))
    with pytest.raises(ValueError):
        run(training, head, expected_training_sha256="0"*64)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(hidden_width=128),
    lambda d: d.update(dimension=True),
    lambda d: d.update(validation_head={}),
    lambda d: d["parameters"]["field_readout.bias"].__setitem__(0, .01),
    lambda d: d["parameters"]["field_readout.weight"][0].__setitem__(0, .01),
    lambda d: d["parameters"]["source_projection.weight"][0].__setitem__(0, float("nan")),
    lambda d: d["parameters"]["source_projection.bias"].__setitem__(0, True),
    lambda d: d["parameters"].update(extra=[1.]),
])
def test_invalid_initial_head_rejected(mutation):
    training, head = fixture()
    mutation(head)
    with pytest.raises(ValueError):
        run(training, head, expected_initial_head_sha256="0"*64)


@pytest.mark.parametrize("options", [
    {"expected_training_sha256": "0"*64}, {"expected_initial_head_sha256": "0"*64},
    {"expected_training_sha256": None}, {"mode": "production"}, {"learning_rate": True},
    {"learning_rate": .1}, {"max_updates": True}, {"max_updates": 1001},
    {"checkpoints": (0, 2, 1)}, {"checkpoints": (0, 0, 2)}, {"checkpoints": (1, 2)},
    {"checkpoints": (0, True, 2)}, {"deadline": float("inf")}, {"deadline": True},
    {"deadline": 10**1000},
])
def test_policy_and_external_binding_rejected(options):
    with pytest.raises(ValueError):
        run(**options)


def test_no_package_dependencies_or_file_network_access():
    import ast
    tree = ast.parse(_PATH.read_text())
    names = [node.module if isinstance(node, ast.ImportFrom) else alias.name
             for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
             for alias in (node.names if isinstance(node, ast.Import) else [None])]
    assert set(names) == {"copy", "hashlib", "json", "math", "re", "time"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"open", "eval", "exec", "__import__"} for node in ast.walk(tree))
