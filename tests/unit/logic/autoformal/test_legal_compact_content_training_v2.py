"""Four real Adam updates on authored compact-content engineering fixtures.

Independent lexical catalogs nominate context before labels are constructed.
The supplied 384D vectors are arbitrary: this is neither an encoder test nor a
legal-meaning, held-out, inference, projection, or statutory-gold qualification.
Only the owned native qualification runner may execute these tests.
"""
from copy import deepcopy
import hashlib
import json
import math
import os

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as contexts
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as subject
from ipfs_datasets_py.logic.syntax_core import signatures


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def write_exclusive(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def no_authority(value):
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is int and value["training_mask"] == 0
    assert type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0


def authored_catalog():
    """Input vocabulary and roles, authored without receiving any target tree."""
    obj = signatures.LogicSort("Object")
    entries = [("Retain", ["holder", "record"], ["retain"]),
               ("Inspect", ["inspector", "record"], ["inspect"]),
               ("Approve", ["approver", "request"], ["approve"])]
    signature = signatures.LogicSignature("authored-compact-training-catalog",
        family="tdfol", profile="tdfol_default", sorts=(obj,), symbols=tuple(
            signatures.declare_predicate(name, (obj,) * len(roles))
            for name, roles, _ in entries))
    return {"schema": "legal-compact-source-catalog/v1", "signature": signature.to_dict(),
        "argument_roles": [{"symbol": name, "roles": roles} for name, roles, _ in entries],
        "aliases": [{"symbol": name, "forms": forms} for name, _, forms in entries]}


def authored_case():
    catalog_raw = wire(authored_catalog())
    originals = [("fictional-retention", "fictional-source-group-a",
                  b"A fictional custodian may retain records.", "P", [.25, -.125]),
                 ("fictional-inspection", "fictional-source-group-b",
                  b"A fictional examiner must inspect records.", "O", [-.5, .375])]
    # Freeze all source/catalog nominations before authoring either target.
    selected = [contexts.prepare_source_context_v1(source_raw, catalog_raw,
        expected_source_sha256=sha(source_raw), expected_catalog_sha256=sha(catalog_raw))
        for _, _, source_raw, _, _ in originals]
    rows, companions = [], []
    codec = tokens.build_compact_content_token_codec_v1()
    codec_sha = tokens.compact_content_token_codec_sha256(codec)
    for original, context_report in zip(originals, selected):
        identity, source_group, source_raw, modality, beginning = original
        assert context_report["status"] == "nominated"
        context_raw = wire(context_report["context"])
        # Explicitly authored label; nomination does not establish its meaning.
        target_raw = wire({"schema": "legal-relational-compact-content/v1", "tree":
            ["forall", 0, ["forall", 1, ["extension", modality,
                ["predicate", 0, [["variable", 0], ["variable", 1]]]]]]})
        encoding = tokens.encode_compact_content_tokens_v1(target_raw, context_raw,
            expected_content_sha256=sha(target_raw), expected_context_sha256=sha(context_raw),
            codec=codec, expected_codec_sha256=codec_sha)
        assert encoding["status"] == "encoded_unreviewed_content"
        assert encoding["target_ids"][0] == 1 and encoding["target_ids"][-1] == 2
        assert 40 <= len(encoding["target_ids"]) <= 64
        rows.append({"id": identity, "source_group": source_group, "source_raw": source_raw,
            "context_raw": context_raw, "target_raw": target_raw,
            "conditioning": list(beginning) + [0.] * 382})
        companions.append({"id": identity, "catalog_raw": catalog_raw,
            "source_context_report": context_report, "target_encoding": encoding})
    population = {"schema": "legal-compact-content-training-population/v2",
        "origin": "authored_engineering_fixture", "partition": "engineering_training", "rows": [
            {"id": row["id"], "source_group": row["source_group"],
             "source_sha256": sha(row["source_raw"]), "context_sha256": sha(row["context_raw"]),
             "target_sha256": sha(row["target_raw"]), "conditioning_sha256": digest(row["conditioning"])}
            for row in rows]}
    return {"population": population, "population_raw": wire(population) + b"\n",
            "rows": rows, "companions": companions, "codec": codec}


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def initial():
    case = authored_case()
    parent = head.create_compact_content_head_v1(config={"hidden_size": 8,
        "token_embedding_dim": 8, "projection_width": 4, "seed": 1729})
    before = deepcopy(parent)
    checkpoint = subject.build_compact_content_training_v2(parent,
        case["population_raw"], case["rows"], expected_initial_checkpoint_sha256=digest(parent),
        expected_population_sha256=sha(case["population_raw"]), learning_rate=.001)
    assert parent == before
    return {"case": case, "parent": parent, "checkpoint": checkpoint}


def train(checkpoint, case, steps, **changes):
    options = {"expected_checkpoint_sha256": digest(checkpoint),
        "expected_population_sha256": sha(case["population_raw"]),
        "max_optimizer_steps": steps, "max_seconds": 60}
    options.update(changes)
    return subject.train_compact_content_v2(checkpoint, case["population_raw"], case["rows"], **options)


def optimizer_snapshot(optimizer):
    parameters = [p for group in optimizer.param_groups for p in group["params"]]
    return {"parameters_sha256": digest([p.detach().tolist() for p in parameters]),
        "state_steps": [int(optimizer.state[p]["step"].item()) if optimizer.state.get(p) else 0
                        for p in parameters],
        "all_parameters_finite": all(bool(torch.isfinite(p).all()) for p in parameters)}


def retain_fixture(initial_value, results, calls, gradients, directory, saved_first):
    case = initial_value["case"]
    artifacts = {"population.json": case["population_raw"], "codec.json": wire(case["codec"]),
        "initial-parent-v1.json": wire(initial_value["parent"]),
        "initial-training-v2.json": wire(initial_value["checkpoint"]),
        "observed-optimizer-steps.json": wire(calls), "observed-formula-gradients.json": wire(gradients),
        "scope.json": wire({"origin": "authored_engineering_fixture", "source_groups": 2,
            "selected_rows": 2, "actual_optimizer_updates": 4, "uninterrupted_updates": 2,
            "split_first_updates": 1, "resumed_updates": 1, "arbitrary_conditioning_dimension": 384,
            "source_encoder_verified": False, "teacher_forced_training": True,
            "optimizer_step_instrumentation_inside_batch_clock": True,
            "nested_training_clocks_additive": False, "throughput_comparison_performed": False,
            "inference_executed": False, "heldout_evaluated": False,
            "statutory_meaning_verified": False, "training_mask": 0, "evaluation_gold_mask": 0})}
    for name, result in results.items():
        artifacts[name + "-result.json"] = wire(result)
        artifacts[name + "-checkpoint.json"] = wire(result["checkpoint"])
    rows = []
    for row, companion in zip(case["rows"], case["companions"]):
        identity = row["id"]
        declarations = {key: value for key, value in row.items() if not key.endswith("_raw")}
        for kind in ("source", "context", "target"):
            name = identity + "-" + kind + (".txt" if kind == "source" else ".json")
            artifacts[name] = row[kind + "_raw"]
            declarations[kind + "_file"] = name
        artifacts[identity + "-catalog.json"] = companion["catalog_raw"]
        artifacts[identity + "-source-context-report.json"] = wire(companion["source_context_report"])
        artifacts[identity + "-target-encoding.json"] = wire(companion["target_encoding"])
        rows.append(declarations)
    artifacts["input-rows.json"] = wire(rows)
    manifest = {}
    for name, raw in artifacts.items():
        path = directory / name
        write_exclusive(path, raw)
        manifest[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    manifest[saved_first.name] = {"path": str(saved_first), "bytes": saved_first.stat().st_size,
        "sha256": sha(saved_first.read_bytes())}
    path = directory / "manifest.json"
    raw = wire({"schema": "authored-compact-training-fixture/v2", "artifacts": manifest})
    write_exclusive(path, raw)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"path": str(path), "sha256": sha(raw)}


@pytest.fixture(scope="module")
def trajectory(initial, tmp_path_factory):
    """The entire module performs exactly 2 + 1 + 1 real optimizer updates."""
    directory = tmp_path_factory.mktemp("compact-training-v2", numbered=False)
    checkpoint, case = initial["checkpoint"], initial["case"]
    before_initial, before_case = deepcopy(initial), deepcopy(case)
    calls, gradients, stage = [], [], {"value": "uninterrupted"}
    real_step, real_grad = torch.optim.Adam.step, torch.autograd.grad

    def observed_step(optimizer, *args, **kwargs):
        before = optimizer_snapshot(optimizer)
        result = real_step(optimizer, *args, **kwargs)
        after = optimizer_snapshot(optimizer)
        calls.append({"stage": stage["value"], "before": before, "after": after})
        return result

    def observed_grad(*args, **kwargs):
        output = real_grad(*args, **kwargs)
        gradients.append({"stage": stage["value"],
            "all_finite": all(value is not None and bool(torch.isfinite(value).all()) for value in output),
            "squared_norm": sum(float(value.detach().double().square().sum().item())
                                for value in output if value is not None)})
        return output

    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.optim.Adam, "step", observed_step)
        patch.setattr(torch.autograd, "grad", observed_grad)
        uninterrupted = train(checkpoint, case, 2)
        stage["value"] = "split_first"
        split_first = train(checkpoint, case, 1)
        raw = subject.compact_content_training_bytes_v2(split_first["checkpoint"],
            expected_checkpoint_sha256=digest(split_first["checkpoint"]))
        saved_first = directory / "split-first-exclusive-save.json"
        write_exclusive(saved_first, raw)
        with pytest.raises(FileExistsError):
            with saved_first.open("xb"):
                pytest.fail("exclusive save replaced the first checkpoint")
        assert saved_first.read_bytes() == raw
        restored = subject.load_compact_content_training_v2(saved_first.read_bytes(), expected_raw_sha256=sha(raw))
        assert restored == split_first["checkpoint"] and restored is not split_first["checkpoint"]
        before_restored = deepcopy(restored)
        stage["value"] = "resumed"
        resumed = train(restored, case, 1)
        assert restored == before_restored
    assert initial == before_initial and case == before_case
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    results = {"uninterrupted": uninterrupted, "split-first": split_first, "resumed": resumed}
    manifest = retain_fixture(initial, results, calls, gradients, directory, saved_first)
    return {**results, "calls": calls, "gradients": gradients, "manifest": manifest}


def test_four_actual_updates_resume_bit_exact_with_positive_projection_gradient(initial, trajectory, record_property):
    record_property("compact_training_fixture", json.dumps(trajectory["manifest"], sort_keys=True))
    parent, start = initial["parent"], initial["checkpoint"]
    assert len(initial["case"]["rows"]) == 2
    assert len({row["source_group"] for row in initial["case"]["rows"]}) == 2
    uninterrupted, first, resumed = [trajectory[name]["checkpoint"]
        for name in ("uninterrupted", "split-first", "resumed")]
    assert len(trajectory["calls"]) == 4
    assert [call["stage"] for call in trajectory["calls"]] == ["uninterrupted", "uninterrupted", "split_first", "resumed"]
    for call in trajectory["calls"]:
        assert call["before"]["parameters_sha256"] != call["after"]["parameters_sha256"]
        assert call["before"]["all_parameters_finite"] and call["after"]["all_parameters_finite"]
        assert all(new == old + 1 for old, new in zip(call["before"]["state_steps"], call["after"]["state_steps"]))
    assert len(trajectory["gradients"]) == 4
    assert all(row["all_finite"] and math.isfinite(row["squared_norm"]) and row["squared_norm"] > 0
               for row in trajectory["gradients"])
    assert start["model_state"] == parent["model_state"]
    assert start["initial_checkpoint"] == parent and start["initial_checkpoint_sha256"] == digest(parent)
    assert start["initial_weights_sha256"] == parent["weights_sha256"]
    assert start["progress"] == {"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0}
    assert first["progress"] == {"optimizer_steps": 1, "epochs_completed": 0, "row_cursor": 1}
    assert uninterrupted["progress"] == resumed["progress"] == {"optimizer_steps": 2, "epochs_completed": 1, "row_cursor": 0}
    assert start["parent_checkpoint_sha256"] is None
    assert uninterrupted["parent_checkpoint_sha256"] == first["parent_checkpoint_sha256"] == digest(start)
    assert resumed["parent_checkpoint_sha256"] == digest(first)
    assert {key: value for key, value in uninterrupted.items() if key != "parent_checkpoint_sha256"} == {
        key: value for key, value in resumed.items() if key != "parent_checkpoint_sha256"}
    assert uninterrupted["model_state"] != start["model_state"]
    for name, expected_steps in (("uninterrupted", 2), ("split-first", 1), ("resumed", 1)):
        checkpoint, report = trajectory[name]["checkpoint"], trajectory[name]["report"]
        assert report["optimizer_steps"] == expected_steps and report["training_executed"] is True
        assert report["teacher_forcing"] is True
        assert report["heldout_evaluated"] is report["free_running_evaluated"] is False
        assert len(report["batch_losses"]) == expected_steps
        assert all(math.isfinite(loss["token_cross_entropy"]) and loss["token_cross_entropy"] > 0
                   for loss in report["batch_losses"])
        expected_ids = (["fictional-retention", "fictional-inspection"] if name == "uninterrupted" else
                        ["fictional-retention"] if name == "split-first" else ["fictional-inspection"])
        assert [loss["row_id"] for loss in report["batch_losses"]] == expected_ids
        assert report["token_count"] == sum(loss["token_count"] for loss in report["batch_losses"])
        assert report["encoder_sha256"] is None and report["source_text_is_neural_input"] is False
        assert report["conditioning_producer_verified"] is False
        assert math.isfinite(report["formula_projection_gradient_norm_max"]) and report["formula_projection_gradient_norm_max"] > 0
        for group in ("projection", "decoder"):
            evidence = report["parameter_evidence"][group]
            assert math.isfinite(evidence["gradient_norm_max"]) and evidence["gradient_norm_max"] > 0
            assert math.isfinite(evidence["parameter_update_l2"]) and evidence["parameter_update_l2"] > 0
            assert evidence["initial_parameters_sha256"] != evidence["final_parameters_sha256"]
        assert checkpoint["initial_checkpoint"] == parent
        assert checkpoint["initial_weights_sha256"] == parent["weights_sha256"]
        assert checkpoint["weights_sha256"] == digest(checkpoint["model_state"])
        assert subject.compact_content_training_sha256(checkpoint) == digest(checkpoint)
        assert subject.validate_compact_content_training_v2(checkpoint, expected_checkpoint_sha256=digest(checkpoint)) == checkpoint
        no_authority(checkpoint)
        no_authority(report)
    assert parent["compact_training_steps"] == 0 and parent["optimizer_state_included"] is False
    assert head.validate_compact_content_head_v1(parent, expected_checkpoint_sha256=digest(parent)) == parent
    with pytest.raises(ValueError):
        head.validate_compact_content_head_v1(resumed, expected_checkpoint_sha256=digest(resumed))


@pytest.fixture
def prohibit_updates(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("negative or zero-step control reached a real optimizer update")
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)


def test_zero_step_preserves_entire_checkpoint_identity(initial, prohibit_updates):
    before = deepcopy(initial)
    result = train(initial["checkpoint"], initial["case"], 0)
    assert result["checkpoint"] == initial["checkpoint"]
    assert result["report"]["optimizer_steps"] == 0 and result["report"]["training_executed"] is False
    assert initial == before


@pytest.mark.parametrize("binding", ["initial_checkpoint", "population", "checkpoint", "saved_raw"])
def test_independent_wrong_pins_refuse_without_update(initial, binding, prohibit_updates):
    case, checkpoint = initial["case"], initial["checkpoint"]
    with pytest.raises(ValueError):
        if binding == "initial_checkpoint":
            subject.build_compact_content_training_v2(initial["parent"], case["population_raw"], case["rows"],
                expected_initial_checkpoint_sha256="0" * 64, expected_population_sha256=sha(case["population_raw"]))
        elif binding == "population":
            train(checkpoint, case, 1, expected_population_sha256="0" * 64)
        elif binding == "checkpoint":
            train(checkpoint, case, 1, expected_checkpoint_sha256="0" * 64)
        else:
            raw = subject.compact_content_training_bytes_v2(checkpoint, expected_checkpoint_sha256=digest(checkpoint))
            subject.load_compact_content_training_v2(raw, expected_raw_sha256="0" * 64)


@pytest.mark.parametrize("mutation", ["source", "target_swap", "context_swap", "conditioning", "source_group",
    "missing_row", "duplicate_row", "reordered_rows", "extra_reference", "coordinated_manifest_change"])
def test_bound_population_and_row_changes_refuse_before_update(initial, mutation, prohibit_updates):
    case = deepcopy(initial["case"])
    if mutation == "source":
        case["rows"][0]["source_raw"] += b" Changed."
    elif mutation == "target_swap":
        case["rows"][0]["target_raw"], case["rows"][1]["target_raw"] = case["rows"][1]["target_raw"], case["rows"][0]["target_raw"]
    elif mutation == "context_swap":
        case["rows"][0]["context_raw"], case["rows"][1]["context_raw"] = case["rows"][1]["context_raw"], case["rows"][0]["context_raw"]
    elif mutation == "conditioning":
        case["rows"][0]["conditioning"][0] += .125
    elif mutation == "source_group":
        case["rows"][0]["source_group"] = "another-source-group"
    elif mutation == "missing_row":
        case["rows"].pop()
    elif mutation == "duplicate_row":
        case["rows"][1] = deepcopy(case["rows"][0])
    elif mutation == "reordered_rows":
        case["rows"].reverse()
    elif mutation == "extra_reference":
        case["rows"][0]["reference_formula"] = {"unapproved": True}
    else:
        case["rows"][0]["source_raw"] += b" Changed with matching replacement manifest."
        case["population"]["rows"][0]["source_sha256"] = sha(case["rows"][0]["source_raw"])
        case["population_raw"] = wire(case["population"])
    with pytest.raises(ValueError):
        train(initial["checkpoint"], case, 1)


def set_first_scalar(value, replacement):
    while isinstance(value[0], list):
        value = value[0]
    value[0] = replacement


def test_final_row_invalid_grammar_is_checked_before_first_update(initial, prohibit_updates):
    case, checkpoint = deepcopy(initial["case"]), deepcopy(initial["checkpoint"])
    malformed = json.loads(case["rows"][-1]["target_raw"])
    # The selected context declares predicate zero only. This complete lexical
    # object therefore violates the public context-aware target grammar.
    malformed["tree"][2][2][2][1] = 1
    case["rows"][-1]["target_raw"] = wire(malformed)
    case["population"]["rows"][-1]["target_sha256"] = sha(case["rows"][-1]["target_raw"])
    case["population_raw"] = wire(case["population"])
    # An explicitly offered altered zero-step checkpoint with a fresh caller
    # pin is no historical provenance claim. Its final target still requires
    # independent public validation before the valid first row may update.
    checkpoint["population_raw_utf8"] = case["population_raw"].decode("utf-8")
    checkpoint["population_sha256"] = sha(case["population_raw"])
    before = deepcopy(checkpoint)
    with pytest.raises(tokens.CompactContentTokensError, match="complete content violates"):
        train(checkpoint, case, 1)
    assert checkpoint == before


@pytest.mark.parametrize("mutation", ["cursor_out_of_range", "cursor_step_mismatch", "moment_step", "missing_moment",
    "negative_second_moment", "parameter_order", "optimizer_policy", "optimizer_config", "initial_parent_pin", "promoted_authority"])
def test_rehashed_checkpoint_corruption_is_structurally_refused(initial, trajectory, mutation, prohibit_updates):
    checkpoint = deepcopy(trajectory["split-first"]["checkpoint"])
    parameters = checkpoint["optimizer_state"]["parameters"]
    first = next(iter(parameters))
    if mutation == "cursor_out_of_range":
        checkpoint["progress"]["row_cursor"] = 2
    elif mutation == "cursor_step_mismatch":
        checkpoint["progress"]["row_cursor"] = 0
    elif mutation == "moment_step":
        parameters[first]["step"] += 1
    elif mutation == "missing_moment":
        del parameters[first]
    elif mutation == "negative_second_moment":
        set_first_scalar(parameters[first]["exp_avg_sq"], -.125)
    elif mutation == "parameter_order":
        checkpoint["parameter_order"].reverse()
    elif mutation == "optimizer_policy":
        checkpoint["optimizer_policy"]["defaults"]["foreach"] = True
    elif mutation == "optimizer_config":
        checkpoint["optimizer_config"]["learning_rate"] = .01
    elif mutation == "initial_parent_pin":
        checkpoint["initial_checkpoint_sha256"] = "0" * 64
    else:
        checkpoint["authority"][next(iter(checkpoint["authority"]))] = True
    with pytest.raises(ValueError):
        train(checkpoint, initial["case"], 1)


@pytest.mark.parametrize("location", ["conditioning", "model_state", "moment", "learning_rate"])
def test_nonfinite_values_refuse_without_numeric_update(initial, location, prohibit_updates):
    case, checkpoint = deepcopy(initial["case"]), deepcopy(initial["checkpoint"])
    if location == "conditioning":
        case["rows"][0]["conditioning"][0] = float("nan")
    elif location == "model_state":
        set_first_scalar(checkpoint["model_state"]["projection_down.weight"], float("nan"))
    elif location == "moment":
        checkpoint["optimizer_state"]["parameters"]["projection_down.weight"] = {
            "step": 0, "exp_avg": [[float("nan")]], "exp_avg_sq": [[0.]]}
    else:
        checkpoint["optimizer_config"]["learning_rate"] = float("nan")
    # The malformed object is deliberately not represented as canonical JSON.
    invalid_pin = sha(json.dumps(checkpoint, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=True).encode("utf-8"))
    with pytest.raises(ValueError):
        subject.train_compact_content_v2(checkpoint, case["population_raw"], case["rows"],
            expected_checkpoint_sha256=invalid_pin, expected_population_sha256=sha(case["population_raw"]),
            max_optimizer_steps=1, max_seconds=60)


@pytest.mark.parametrize("mutation", ["row_limit", "conditioning_dimension", "source_bytes", "target_bytes", "step_limit"])
def test_bounds_refuse_without_update(initial, mutation, prohibit_updates):
    case = deepcopy(initial["case"])
    if mutation == "row_limit":
        case["rows"] = [deepcopy(case["rows"][0]) for _ in range(17)]
        for index, row in enumerate(case["rows"]):
            row["id"] = "oversized-population-row-" + str(index)
    elif mutation == "conditioning_dimension":
        case["rows"][0]["conditioning"].append(0.)
    elif mutation == "source_bytes":
        case["rows"][0]["source_raw"] = b"x" * 65537
    elif mutation == "target_bytes":
        case["rows"][0]["target_raw"] = b" " * 16385
    # Fresh, internally bound manifests prevent a stale hash from masking the
    # actual intake bound under test. Building performs no optimizer update.
    case["population"]["rows"] = [{"id": row["id"], "source_group": row["source_group"],
        "source_sha256": sha(row["source_raw"]), "context_sha256": sha(row["context_raw"]),
        "target_sha256": sha(row["target_raw"]), "conditioning_sha256": digest(row["conditioning"])}
        for row in case["rows"]]
    case["population_raw"] = wire(case["population"])
    with pytest.raises(ValueError):
        if mutation == "step_limit":
            train(initial["checkpoint"], initial["case"], 17)
        else:
            subject.build_compact_content_training_v2(initial["parent"], case["population_raw"], case["rows"],
                expected_initial_checkpoint_sha256=digest(initial["parent"]),
                expected_population_sha256=sha(case["population_raw"]))
