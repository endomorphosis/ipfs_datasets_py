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


# Additive varied-population mechanics only. The module's original four-update
# qualification above remains historical and is not selected by this new case.
# This case proposes ten actual updates: five versus three plus two after load.
# No numerical execution or qualification is established by staging this file.
_VARIED_TRAINING_DECLARATIONS_V2 = [
    {"id": "varied-fictional-permission", "source_group": "varied-source-group-a",
     "source_utf8": "Fictional example A: every holder may retain every record.",
     "conditioning_prefix": [.25, -.125, .0625, 0.],
     "tree": ["forall", 0, ["forall", 1, ["extension", "P",
         ["predicate", 0, [["variable", 0], ["variable", 1]]]]]]},
    {"id": "varied-fictional-reversed-obligation", "source_group": "varied-source-group-b",
     "source_utf8": "Fictional example B: some record must be retained by every holder.",
     "conditioning_prefix": [-.5, .375, 0., -.125],
     "tree": ["exists", 0, ["forall", 1, ["extension", "O",
         ["predicate", 0, [["variable", 1], ["variable", 0]]]]]]},
    {"id": "varied-fictional-conditional-prohibition", "source_group": "varied-source-group-c",
     "source_utf8": "Fictional example C: if an object retains itself, it is forbidden from retaining itself.",
     "conditioning_prefix": [.125, .25, -.375, .0625],
     "tree": ["forall", 0, ["implies",
         ["predicate", 0, [["variable", 0], ["variable", 0]]],
         ["extension", "F", ["predicate", 0, [["variable", 0], ["variable", 0]]]]]]},
    {"id": "varied-fictional-negated-obligation", "source_group": "varied-source-group-d",
     "source_utf8": "Fictional example D: each holder has a record for which an obligation to retain it is negated.",
     "conditioning_prefix": [-.25, -.125, .5, .125],
     "tree": ["forall", 0, ["exists", 1, ["not", ["extension", "O",
         ["predicate", 0, [["variable", 0], ["variable", 1]]]]]]]},
]


def _authored_varied_population_v2():
    """Fix the complete context before constructing any of the four labels.

    The binary Retain declaration and roles are authored input. Neither their
    legal meaning nor the independence of a caller-supplied context is granted.
    The fictional prose is retained/hash-bound; no encoder consumes its text.
    """
    from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as compact

    obj = signatures.LogicSort("Object")
    signature = signatures.LogicSignature("authored-varied-fixed-context",
        family="tdfol", profile="tdfol_default", sorts=(obj,), symbols=(
            signatures.declare_predicate("Retain", (obj, obj)),))
    signature_raw = wire(signature.to_dict())
    roles_raw = wire([{"symbol": "Retain", "roles": ["holder", "record"]}])
    context = compact.prepare_context_v1(signature_raw, roles_raw,
        expected_signature_sha256=sha(signature_raw), expected_argument_roles_sha256=sha(roles_raw))
    context_raw = wire(context)
    # Everything above is fixed before reading a target declaration below.
    frozen_context_raw = bytes(context_raw)
    codec = tokens.build_compact_content_token_codec_v1()
    codec_sha = tokens.compact_content_token_codec_sha256(codec)
    rows, encodings = [], []
    for authored in deepcopy(_VARIED_TRAINING_DECLARATIONS_V2):
        target_raw = wire({"schema": "legal-relational-compact-content/v1", "tree": authored["tree"]})
        encoded = tokens.encode_compact_content_tokens_v1(target_raw, frozen_context_raw,
            expected_content_sha256=sha(target_raw), expected_context_sha256=sha(frozen_context_raw),
            codec=codec, expected_codec_sha256=codec_sha)
        assert encoded["status"] == "encoded_unreviewed_content"
        assert encoded["target_ids"][0] == 1 and encoded["target_ids"][-1] == 2
        assert 3 <= len(encoded["target_ids"]) <= 512
        no_authority(encoded)
        no_authority(encoded["prediction"])
        rows.append({"id": authored["id"], "source_group": authored["source_group"],
            "source_raw": authored["source_utf8"].encode("utf-8"), "context_raw": frozen_context_raw,
            "target_raw": target_raw,
            "conditioning": list(authored["conditioning_prefix"]) + [0.] * 380})
        encodings.append(encoded)
    assert context_raw == frozen_context_raw == wire(context)
    assert len(rows) == len({row["id"] for row in rows}) == len({row["source_group"] for row in rows}) == 4
    assert len({row["context_raw"] for row in rows}) == 1
    assert len({row["target_raw"] for row in rows}) == len({digest(row["conditioning"]) for row in rows}) == 4
    assert len({len(encoded["target_ids"]) for encoded in encodings}) == 3
    assert [encoded["counts"]["nodes"] for encoded in encodings] == [6, 6, 9, 7]
    assert [encoded["counts"]["quantifiers"] for encoded in encodings] == [2, 2, 1, 2]
    assert [encoded["counts"]["predicate_occurrences"] for encoded in encodings] == [1, 1, 2, 1]
    population = {"schema": "legal-compact-content-training-population/v2",
        "origin": "authored_engineering_fixture", "partition": "engineering_training", "rows": [
            {"id": row["id"], "source_group": row["source_group"],
             "source_sha256": sha(row["source_raw"]), "context_sha256": sha(row["context_raw"]),
             "target_sha256": sha(row["target_raw"]), "conditioning_sha256": digest(row["conditioning"])}
            for row in rows]}
    return {"population": population, "population_raw": wire(population) + b"\n", "rows": rows,
        "context_raw": frozen_context_raw, "signature_raw": signature_raw, "roles_raw": roles_raw,
        "codec": codec, "encodings": encodings}


def test_varied_four_row_population_crosses_epoch_and_resumes_with_fixed_bos_parity(tmp_path):
    """One finite positive case, not a new trainer or a legal accuracy experiment."""
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as runtime
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as selection
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

    case = _authored_varied_population_v2()
    before_case = deepcopy(case)
    stage = {"value": "seed_create"}
    counts = dict.fromkeys(("model_constructions", "state_restores", "adam_constructions",
        "gru_forwards", "cross_entropy_calls", "autograd_grad_calls", "backward_calls",
        "clip_calls", "optimizer_updates", "selector_calls"), 0)
    events, updates, gradients, losses = [], [], [], []
    real_init, real_load = torch.nn.GRU.__init__, torch.nn.Module.load_state_dict
    real_adam, real_gru = torch.optim.Adam.__init__, torch.nn.GRU.forward
    real_ce, real_grad = torch.nn.functional.cross_entropy, torch.autograd.grad
    real_backward, real_clip = torch.Tensor.backward, torch.nn.utils.clip_grad_norm_
    real_step, real_select = torch.optim.Adam.step, selection.select_compact_content_token_v1

    def observed_init(model, *args, **kwargs):
        result = real_init(model, *args, **kwargs)
        counts["model_constructions"] += 1
        events.append({"event": "model_construction", "stage": stage["value"]})
        return result

    def observed_load(model, *args, **kwargs):
        result = real_load(model, *args, **kwargs)
        counts["state_restores"] += 1
        events.append({"event": "state_restore", "stage": stage["value"]})
        return result

    def observed_adam(optimizer, *args, **kwargs):
        result = real_adam(optimizer, *args, **kwargs)
        counts["adam_constructions"] += 1
        events.append({"event": "adam_construction", "stage": stage["value"]})
        return result

    def observed_gru(model, inputs, *args, **kwargs):
        result = real_gru(model, inputs, *args, **kwargs)
        counts["gru_forwards"] += 1
        events.append({"event": "gru_forward", "stage": stage["value"],
            "input_shape": list(inputs.shape), "output_shape": list(result[0].shape),
            "model_training": model.training})
        return result

    def observed_ce(logits, labels, *args, **kwargs):
        result = real_ce(logits, labels, *args, **kwargs)
        assert not args and kwargs == {"ignore_index": 0}
        assert list(logits.shape) == [labels.numel(), 537]
        label_ids = labels.detach().tolist()
        assert label_ids and label_ids[-1] == 2 and 0 not in label_ids
        matrix = logits.detach().double().tolist()
        terms = []
        for scores, target_id in zip(matrix, label_ids):
            maximum = max(scores)
            terms.append(maximum + math.log(math.fsum(math.exp(score - maximum) for score in scores)) - scores[target_id])
        independent_mean = math.fsum(terms) / len(label_ids)
        actual_mean = float(result.detach())
        assert math.isclose(actual_mean, independent_mean, rel_tol=0., abs_tol=2e-6)
        counts["cross_entropy_calls"] += 1
        losses.append({"stage": stage["value"], "shape": list(logits.shape), "labels": label_ids,
            "logits": matrix, "logits_sha256": digest(matrix), "eos_included": True,
            "torch_mean_cross_entropy": actual_mean, "python_mean_cross_entropy": independent_mean})
        return result

    def observed_grad(*args, **kwargs):
        result = real_grad(*args, **kwargs)
        counts["autograd_grad_calls"] += 1
        gradients.append({"stage": stage["value"],
            "all_finite": all(value is not None and bool(torch.isfinite(value).all()) for value in result),
            "squared_norm": sum(float(value.detach().double().square().sum()) for value in result)})
        return result

    def observed_backward(loss, *args, **kwargs):
        counts["backward_calls"] += 1
        return real_backward(loss, *args, **kwargs)

    def observed_clip(*args, **kwargs):
        counts["clip_calls"] += 1
        return real_clip(*args, **kwargs)

    def observed_step(optimizer, *args, **kwargs):
        before = optimizer_snapshot(optimizer)
        result = real_step(optimizer, *args, **kwargs)
        after = optimizer_snapshot(optimizer)
        counts["optimizer_updates"] += 1
        updates.append({"stage": stage["value"], "before": before, "after": after})
        return result

    def observed_select(*args, **kwargs):
        result = real_select(*args, **kwargs)
        counts["selector_calls"] += 1
        return result

    def forbidden_in_score(*args, **kwargs):
        pytest.fail("model-only fixed-BOS score allocated/restored Adam or reached training")

    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.nn.GRU, "__init__", observed_init)
        patch.setattr(torch.nn.Module, "load_state_dict", observed_load)
        patch.setattr(torch.optim.Adam, "__init__", observed_adam)
        patch.setattr(torch.nn.GRU, "forward", observed_gru)
        patch.setattr(torch.nn.functional, "cross_entropy", observed_ce)
        patch.setattr(torch.autograd, "grad", observed_grad)
        patch.setattr(torch.Tensor, "backward", observed_backward)
        patch.setattr(torch.nn.utils, "clip_grad_norm_", observed_clip)
        patch.setattr(torch.optim.Adam, "step", observed_step)
        patch.setattr(selection, "select_compact_content_token_v1", observed_select)
        parent = head.create_compact_content_head_v1(config={"hidden_size": 8,
            "token_embedding_dim": 8, "projection_width": 4, "seed": 1729})
        before_parent = deepcopy(parent)
        stage["value"] = "build"
        start = subject.build_compact_content_training_v2(parent, case["population_raw"], case["rows"],
            expected_initial_checkpoint_sha256=digest(parent),
            expected_population_sha256=sha(case["population_raw"]), learning_rate=.001)
        before_start = deepcopy(start)
        stage["value"] = "uninterrupted"
        uninterrupted = train(start, case, 5)
        stage["value"] = "split_first"
        first = train(start, case, 3)
        stage["value"] = "checkpoint_bytes"
        saved_raw = subject.compact_content_training_bytes_v2(first["checkpoint"],
            expected_checkpoint_sha256=digest(first["checkpoint"]))
        saved_path = tmp_path / "varied-split-first-exclusive-save.json"
        write_exclusive(saved_path, saved_raw)
        with pytest.raises(FileExistsError):
            with saved_path.open("xb"):
                pytest.fail("exclusive checkpoint save was replaced")
        assert saved_path.read_bytes() == saved_raw
        stage["value"] = "checkpoint_load"
        restored = subject.load_compact_content_training_v2(saved_path.read_bytes(), expected_raw_sha256=sha(saved_raw))
        assert restored == first["checkpoint"] and restored is not first["checkpoint"]
        before_restored = deepcopy(restored)
        stage["value"] = "resumed"
        resumed = train(restored, case, 2)
        assert restored == before_restored
        before_scored = (deepcopy(uninterrupted["checkpoint"]), deepcopy(resumed["checkpoint"]))
        before_score_counts = dict(counts)
        # Only model tensors are restored. Pure checkpoint validation still
        # reads retained training labels/population; this is no target-blind claim.
        with pytest.MonkeyPatch.context() as score_patch:
            for owner, name in ((torch.optim.Optimizer, "__init__"), (torch.optim.Adam, "__init__"),
                    (torch.optim.Adam, "step"), (numerical, "_optimizer"), (subject, "_restore"),
                    (subject, "build_compact_content_training_v2"), (subject, "train_compact_content_v2"),
                    (torch.Tensor, "backward"), (torch.autograd, "grad")):
                score_patch.setattr(owner, name, forbidden_in_score)
            scores = []
            row = case["rows"][2]
            for name, checkpoint in (("uninterrupted_bos", uninterrupted["checkpoint"]),
                                     ("resumed_bos", resumed["checkpoint"])):
                stage["value"] = name
                scores.append(runtime.score_compact_content_trained_v2(checkpoint,
                    row["conditioning"], [1], row["context_raw"],
                    expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(row["context_raw"])))
        assert (uninterrupted["checkpoint"], resumed["checkpoint"]) == before_scored
        assert {name: counts[name] - before_score_counts[name] for name in counts} == {
            "model_constructions": 2, "state_restores": 2, "adam_constructions": 0,
            "gru_forwards": 2, "cross_entropy_calls": 0, "autograd_grad_calls": 0,
            "backward_calls": 0, "clip_calls": 0, "optimizer_updates": 0, "selector_calls": 2}
    assert counts == {"model_constructions": 19, "state_restores": 18, "adam_constructions": 6,
        "gru_forwards": 12, "cross_entropy_calls": 10, "autograd_grad_calls": 10,
        "backward_calls": 10, "clip_calls": 10, "optimizer_updates": 10, "selector_calls": 2}
    assert parent == before_parent and start == before_start and case == before_case
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    ids = [row["id"] for row in case["rows"]]
    expected_rows = {"uninterrupted": ids + ids[:1], "split_first": ids[:3], "resumed": ids[3:] + ids[:1]}
    label_counts = {row["id"]: len(encoded["target_ids"]) - 1
        for row, encoded in zip(case["rows"], case["encodings"])}
    assert len(set(label_counts.values())) == 3
    for name, result in (("uninterrupted", uninterrupted), ("split_first", first), ("resumed", resumed)):
        report, checkpoint = result["report"], result["checkpoint"]
        row_sequence = expected_rows[name]
        assert report["population_count"] == checkpoint["population_count"] == 4
        assert report["optimizer_steps"] == len(row_sequence) and report["stopped_reason"] == "optimizer_step_budget"
        assert [loss["row_id"] for loss in report["batch_losses"]] == row_sequence
        assert [loss["token_count"] for loss in report["batch_losses"]] == [label_counts[row_id] for row_id in row_sequence]
        assert report["token_count"] == sum(label_counts[row_id] for row_id in row_sequence)
        assert report["objective"] == "compact_token_cross_entropy" and report["teacher_forcing"] is True
        assert report["selection_performed"] is report["heldout_evaluated"] is report["free_running_evaluated"] is False
        assert report["encoder_sha256"] is None and report["source_text_is_neural_input"] is False
        assert report["conditioning_producer_verified"] is False
        observed = [loss for loss in losses if loss["stage"] == name]
        assert len(observed) == len(row_sequence)
        for loss, row_id, observed_loss in zip(report["batch_losses"], row_sequence, observed):
            encoded = case["encodings"][ids.index(row_id)]
            assert observed_loss["labels"] == encoded["target_ids"][1:]
            assert observed_loss["shape"] == [label_counts[row_id], 537]
            assert loss["token_cross_entropy"] == observed_loss["torch_mean_cross_entropy"]
        for parameter_group in ("projection", "decoder"):
            evidence = report["parameter_evidence"][parameter_group]
            assert evidence["gradient_norm_max"] > 0 and evidence["parameter_update_l2"] > 0
        assert checkpoint["population_raw_utf8"].encode("utf-8") == case["population_raw"]
        assert checkpoint["population_sha256"] == sha(case["population_raw"])
        no_authority(checkpoint)
        no_authority(report)
    assert start["progress"] == {"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0}
    assert first["checkpoint"]["progress"] == {"optimizer_steps": 3, "epochs_completed": 0, "row_cursor": 3}
    final_progress = {"optimizer_steps": 5, "epochs_completed": 1, "row_cursor": 1}
    a, b = uninterrupted["checkpoint"], resumed["checkpoint"]
    assert a["progress"] == b["progress"] == final_progress
    assert a["model_state"] == b["model_state"] and a["weights_sha256"] == b["weights_sha256"] != start["weights_sha256"]
    assert a["optimizer_state"] == b["optimizer_state"]
    assert a["population_raw_utf8"] == b["population_raw_utf8"] == start["population_raw_utf8"]
    assert a["runtime"] == b["runtime"] == start["runtime"]
    assert a["parent_checkpoint_sha256"] == first["checkpoint"]["parent_checkpoint_sha256"] == digest(start)
    assert b["parent_checkpoint_sha256"] == digest(first["checkpoint"])
    assert a["parent_checkpoint_sha256"] != b["parent_checkpoint_sha256"] and digest(a) != digest(b)
    assert {key: value for key, value in a.items() if key != "parent_checkpoint_sha256"} == {
        key: value for key, value in b.items() if key != "parent_checkpoint_sha256"}
    assert len(updates) == len(gradients) == 10
    assert [row["stage"] for row in updates] == ["uninterrupted"] * 5 + ["split_first"] * 3 + ["resumed"] * 2
    for update, gradient in zip(updates, gradients):
        assert update["before"]["all_parameters_finite"] and update["after"]["all_parameters_finite"]
        assert update["before"]["parameters_sha256"] != update["after"]["parameters_sha256"]
        assert all(new == old + 1 for old, new in zip(update["before"]["state_steps"], update["after"]["state_steps"]))
        assert gradient["all_finite"] and math.isfinite(gradient["squared_norm"]) and gradient["squared_norm"] > 0
    assert len(scores) == 2 and scores[0]["logits"] == scores[1]["logits"]
    assert len(scores[0]["logits"]) == 537 and all(math.isfinite(number) for number in scores[0]["logits"])
    for checkpoint, score in zip((a, b), scores):
        assert score["checkpoint_sha256"] == digest(checkpoint) and score["weights_sha256"] == checkpoint["weights_sha256"]
        assert score["compact_training_steps"] == 5 and score["training_progress"] == final_progress
        assert score["prefix_ids"] == [1] and score["output_shape"] == [1, 1, 537]
        assert score["status"] == "scored" and score["runtime_verified"] is True
        assert score["numerical_forward_executed"] is score["model_restore_performed"] is True
        assert score["optimizer_constructed"] is score["optimizer_state_restored"] is score["optimizer_executed"] is False
        assert score["logits_sha256"] == digest(score["logits"])
        allowed = score["prefix_report"]["allowed_token_ids"]
        assert score["selection"]["selected_token_id"] == min(allowed, key=lambda token: (-score["logits"][token], token))
        no_authority(score)

    # Preserve complete evidence without replacing any prior fixture artifact.
    artifacts = {"population.json": case["population_raw"], "context.json": case["context_raw"],
        "signature.json": case["signature_raw"], "argument-roles.json": case["roles_raw"],
        "codec.json": wire(case["codec"]), "initial-parent-v1.json": wire(parent),
        "initial-training-v2.json": wire(start), "uninterrupted-result.json": wire(uninterrupted),
        "split-first-result.json": wire(first), "resumed-result.json": wire(resumed),
        "uninterrupted-bos-score.json": wire(scores[0]), "resumed-bos-score.json": wire(scores[1]),
        "observed-events.json": wire(events), "observed-updates.json": wire(updates),
        "observed-gradients.json": wire(gradients), "observed-cross-entropy.json": wire(losses),
        "authored-rows.json": wire([{"id": row["id"], "source_group": row["source_group"],
            "source_utf8": row["source_raw"].decode("utf-8"), "context_utf8": row["context_raw"].decode("utf-8"),
            "target_utf8": row["target_raw"].decode("utf-8"), "conditioning": row["conditioning"],
            "encoding": encoded} for row, encoded in zip(case["rows"], case["encodings"])])}
    references = {saved_path.name: {"path": str(saved_path), "bytes": len(saved_raw), "sha256": sha(saved_raw)}}
    for filename, raw in artifacts.items():
        path = tmp_path / filename
        write_exclusive(path, raw)
        references[filename] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    panel = {"schema": "authored-varied-compact-training-panel/v2", "artifacts": references,
        "counts": counts, "population_rows": 4, "source_groups": 4, "context_count": 1,
        "distinct_target_count": 4, "distinct_total_token_lengths": sorted({count + 1 for count in label_counts.values()}),
        "row_label_counts_including_eos": label_counts, "expected_row_sequences": expected_rows,
        "uninterrupted_steps": 5, "split_first_steps": 3, "resumed_steps": 2,
        "final_progress": final_progress, "checkpoint_values_equal_except_immediate_parent": True,
        "fixed_bos_score_rows": [ids[2], ids[2]], "saved_bos_logit_coordinates": 1074,
        "scope": {"origin": "authored_engineering_fixture", "partition": "engineering_training",
            "conditioning_profile": "caller_supplied_unverified384", "source_encoder_authenticated": False,
            "context_constructed_before_targets": True, "context_permission_verified": False,
            "strict_checkpoint_validation_reads_training_labels": True, "score_target_used_as_prefix": False,
            "model_only_score_optimizer_allocations": 0, "model_only_score_selector_calls": 2,
            "complete_free_running_generation_executed": False, "old_four_update_campaign_rerun": False,
            "training_gain_established": False, "heldout_evaluated": False, "statutory_meaning_verified": False,
            "reviewed_training_acceptance_closed": False, "Lean_executed": False,
            "training_mask": 0, "evaluation_gold_mask": 0}}
    write_exclusive(tmp_path / "authored-varied-compact-training-panel-v2.json", wire(panel))
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
