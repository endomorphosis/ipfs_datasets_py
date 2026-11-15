"""Source-selected continuation of one retained authored trained checkpoint.

The fixed population has one nominated, one ambiguous and one unavailable
fictional source. Its sole numerical fixture enrolls twelve original trained
GRU forwards and twelve mandatory adapter-replay forwards. The two event
counters overlap those same twenty-four calls. Other controls refuse before
numerical dispatch; no optimizer allocation, new fitting or source encoder is
enrolled. A constructor choice is an engineering observation, not accuracy.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import stat

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as contexts
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as batch
from ipfs_datasets_py.logic.autoformal import legal_relational_content_context_evaluation_v1 as inventory_owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as runtime
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_trained_source_generation_v2 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

FIXTURE_SHA = "1c4b7c37eba6870c2a746cb3e3191013a1d25906cb75427d4f7be0ca6583dab7"
CHECKPOINT_SHA = "0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def snapshot(path):
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
        assert 0 < before.st_size <= MAX_ARTIFACT_BYTES
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        after = os.fstat(stream.fileno())
    witness = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                             value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    assert len(raw) == before.st_size and witness(before) == witness(after) == witness(path.lstat())
    return raw


def write_new(path, raw):
    assert 0 < len(raw) <= MAX_ARTIFACT_BYTES
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert snapshot(path) == raw


def no_authority(value):
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is int and value["training_mask"] == 0
    assert type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0


@pytest.fixture(scope="module", autouse=True)
def no_optimizer_or_training():
    attempts = []
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    def forbidden(*args, **kwargs):
        attempts.append("optimizer allocation, update, or training call")
        pytest.fail("source-selected inference attempted optimizer allocation, restoration, or training")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.optim.Optimizer, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "step", forbidden)
        patch.setattr(numerical, "_optimizer", forbidden)
        patch.setattr(trainer, "_restore", forbidden)
        patch.setattr(trainer, "build_compact_content_training_v2", forbidden)
        patch.setattr(trainer, "train_compact_content_v2", forbidden)
        try:
            yield attempts
        finally:
            torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def retained(no_optimizer_or_training):
    # One exact existing fixture is supplied and source-pinned by the native
    # owner. There is no cache search, alternate model or seeded fallback.
    spelling = os.environ.get("LEGAL_COMPACT_TRAINED_INFERENCE_FIXTURE")
    assert spelling, "the native harness must supply one exact retained fixture"
    path = Path(spelling)
    raw = snapshot(path)
    assert sha(raw) == FIXTURE_SHA
    manifest = json.loads(raw)
    assert manifest["schema"] == "authored-compact-training-fixture/v2"
    assert len(manifest["artifacts"]) == 27
    bodies, values = {}, {}
    for name, descriptor in manifest["artifacts"].items():
        selected = Path(descriptor["path"])
        assert selected.parent == path.parent and selected.name == name
        body = snapshot(selected)
        assert len(body) == descriptor["bytes"] and sha(body) == descriptor["sha256"]
        bodies[name] = body
        if name.endswith(".json"):
            values[name] = json.loads(body)
    checkpoint = values["resumed-checkpoint.json"]
    assert sha(bodies["resumed-checkpoint.json"]) == digest(checkpoint) == CHECKPOINT_SHA
    assert checkpoint["progress"] == {"optimizer_steps": 2, "epochs_completed": 1, "row_cursor": 0}
    assert checkpoint["initial_checkpoint"] == values["initial-parent-v1.json"]
    assert checkpoint["weights_sha256"] != checkpoint["initial_weights_sha256"]
    assert values["scope.json"]["actual_optimizer_updates"] == 4  # Historical fixture only.
    row = values["input-rows.json"][0]
    bound = values["population.json"]["rows"][0]
    assert row["id"] == bound["id"] == "fictional-retention"
    for kind in ("source", "context", "target"):
        assert sha(bodies[row[kind + "_file"]]) == bound[kind + "_sha256"]
    assert digest(row["conditioning"]) == bound["conditioning_sha256"]
    return {"manifest_path": path, "manifest_raw": raw, "manifest": manifest,
            "bodies": bodies, "values": values, "checkpoint": checkpoint,
            "conditioning": row["conditioning"], "source_raw": bodies[row["source_file"]]}


def authored_case(retained):
    # The retained fictional vocabulary precedes predictions. Add a fixed
    # shared alias solely to create a genuine ambiguous-source control.
    catalog = deepcopy(retained["values"]["fictional-retention-catalog.json"])
    aliases = {row["symbol"]: row["forms"] for row in catalog["aliases"]}
    assert "act" not in aliases["Retain"] and "act" not in aliases["Inspect"]
    aliases["Retain"].append("act")
    aliases["Inspect"].append("act")
    catalog_raw = wire(catalog)
    sources = [("unique", retained["source_raw"]),
               ("ambiguous", b"A fictional actor may act."),
               ("unavailable", b"There are no matching vocabulary words here.")]
    rows = [{"id": identity, "source_raw": raw, "catalog_raw": catalog_raw,
        "conditioning": deepcopy(retained["conditioning"]), "expected_source_sha256": sha(raw),
        "expected_catalog_sha256": sha(catalog_raw),
        "expected_conditioning_sha256": digest(retained["conditioning"])} for identity, raw in sources]
    population = {"schema": "legal-relational-batch-population/v1",
        "partition": "exposed-authored-trained-source-generation-engineering",
        "selection_sha256": sha(b"Fixed unique, ambiguous and unavailable fictional sources before inference"),
        "rows": [{"id": row["id"], "source_sha256": row["expected_source_sha256"],
                  "context_sha256": row["expected_catalog_sha256"]} for row in rows]}
    return {"population": population, "population_raw": wire(population) + b"\n", "rows": rows}


def prepare(case, checkpoint, **changes):
    options = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_checkpoint_sha256": digest(checkpoint), "max_new_tokens": 12}
    options.update(changes)
    return subject.prepare_trained_source_generation_v2(
        case["population_raw"], case["rows"], checkpoint, **options)


def unavailable_references(case):
    return {"schema": "legal-relational-batch-references/v1",
        "population_sha256": sha(case["population_raw"]), "rows": [
            {"id": row["id"], "status": "unavailable", "request_utf8": None,
             "request_sha256": None, "report": None, "report_sha256": None,
             "reason": "Exposed fictional engineering fixture; no independent legal reference supplied"}
            for row in case["population"]["rows"]]}


def evaluate(case, report):
    references_raw = wire(unavailable_references(case))
    predictions_raw, contexts_raw = wire(report["predictions"]), wire(report["context_inventory"])
    options = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_references_sha256": sha(references_raw), "expected_predictions_sha256": sha(predictions_raw)}
    original = batch.prepare_relational_content_token_batch_evaluation_v1(
        case["population_raw"], references_raw, predictions_raw, **options)
    companion = inventory_owner.prepare_relational_content_context_evaluation_v1(
        case["population_raw"], references_raw, predictions_raw, contexts_raw,
        **options, expected_contexts_sha256=sha(contexts_raw))
    assert companion["original_evaluation"] == original
    return original, companion


def retain_evidence(retained, case, report, evaluation, companion, events, scope, directory):
    artifacts = {"population.json": case["population_raw"], "checkpoint.json": wire(retained["checkpoint"]),
        "prior-training-manifest.json": retained["manifest_raw"],
        "references.json": wire(unavailable_references(case)), "result.json": wire(report),
        "predictions.json": wire(report["predictions"]), "context-inventory.json": wire(report["context_inventory"]),
        "batch-evaluation.json": wire(evaluation), "context-evaluation.json": wire(companion),
        "observed-calls.json": wire(events), "scope.json": wire(scope)}
    declarations = []
    for row in case["rows"]:
        identity = row["id"]
        source_file, catalog_file = identity + "-source.txt", identity + "-catalog.json"
        artifacts[source_file], artifacts[catalog_file] = row["source_raw"], row["catalog_raw"]
        declarations.append({key: value for key, value in row.items() if key not in ("source_raw", "catalog_raw")}
                            | {"source_file": source_file, "catalog_file": catalog_file})
    artifacts["input-rows.json"] = wire(declarations)
    assert len(artifacts) == 18 and sum(map(len, artifacts.values())) <= 8 * 1024 * 1024
    manifest = {}
    for name, raw in artifacts.items():
        path = directory / name
        write_new(path, raw)
        manifest[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    path = directory / "manifest.json"
    raw = wire({"schema": "authored-trained-source-generation-fixture/v2", "artifacts": manifest})
    write_new(path, raw)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"path": str(path), "sha256": sha(raw)}


@pytest.fixture(scope="module")
def inference(retained, no_optimizer_or_training, tmp_path_factory):
    case, checkpoint = authored_case(retained), retained["checkpoint"]
    before = deepcopy((case, checkpoint))
    directory = tmp_path_factory.mktemp("trained-source-generation-v2", numbered=False)
    expected_sources = {row["expected_source_sha256"] for row in case["rows"]}
    seen, events, generation_contexts = set(), [], []
    active = {"phase": None, "prefix_ids": None, "generate_calls": 0}
    real_prepare, real_generate, real_forward, real_gru = (
        contexts.prepare_source_context_v1, runtime.generate_compact_content_trained_v2,
        runtime._forward, torch.nn.GRU.forward)

    def observed_prepare(*args, **kwargs):
        result = real_prepare(*args, **kwargs)
        seen.add(kwargs["expected_source_sha256"])
        events.append({"event": "source_context_prepared", "source_sha256": kwargs["expected_source_sha256"],
                       "status": result["status"]})
        return result

    def observed_generate(*args, **kwargs):
        assert seen == expected_sources, "numerical generation preceded complete source nomination"
        assert args[2] == [1] and kwargs["prefix_origin"] == "bos_seed"
        assert kwargs["context_origin"] == "caller_supplied_unverified" and kwargs["max_new_tokens"] == 12
        active["generate_calls"] += 1
        assert active["generate_calls"] <= 2
        active["phase"] = "original" if active["generate_calls"] == 1 else "adapter_replay"
        generation_contexts.append(args[3])
        events.append({"event": "generation_called", "phase": active["phase"],
            "source_contexts_already_prepared": sorted(seen), "context_raw_sha256": sha(args[3])})
        return real_generate(*args, **kwargs)

    def observed_gru(model, tensor, *values, **options):
        assert seen == expected_sources and active["phase"] in ("original", "adapter_replay")
        result = real_gru(model, tensor, *values, **options)
        events.append({"event": "gru_forward", "phase": active["phase"],
            "prefix_ids": list(active["prefix_ids"]), "input_shape": list(tensor.shape),
            "output_shape": list(result[0].shape), "gru_output_sha256": digest(result[0].detach().tolist())})
        return result

    def observed_forward(value, conditioning, prefix_ids):
        assert seen == expected_sources and value["weights_sha256"] == checkpoint["weights_sha256"]
        active["prefix_ids"] = list(prefix_ids)
        result = real_forward(value, conditioning, prefix_ids)
        events.append({"event": "trained_forward", "phase": active["phase"], "prefix_ids": list(prefix_ids),
            "checkpoint_sha256": digest(value), "weights_sha256": value["weights_sha256"],
            "conditioning_sha256": digest(conditioning), "logits_sha256": digest(result["logits"]),
            "output_shape": result["output_shape"]})
        return result

    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(contexts, "prepare_source_context_v1", observed_prepare)
        patch.setattr(runtime, "generate_compact_content_trained_v2", observed_generate)
        patch.setattr(runtime, "_forward", observed_forward)
        patch.setattr(torch.nn.GRU, "forward", observed_gru)
        report = prepare(case, checkpoint)
    assert (case, checkpoint) == before
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert no_optimizer_or_training == []
    original, companion = evaluate(case, report)
    generated = report["slots"][0]["generation"]
    actual = report["counts"]["original_numerical_forward_count"]
    replay = report["counts"]["adapter_replay_numerical_forward_count"]
    grus = [row for row in events if row["event"] == "gru_forward"]
    forwards = [row for row in events if row["event"] == "trained_forward"]
    assert len(generation_contexts) == 2 and generation_contexts[0] == generation_contexts[1]
    branching = sum(len(step["prefix_report"]["allowed_token_ids"]) > 1 for step in generated["trace"])
    scope = {"source_origin": "exposed authored fictional engineering fixtures",
        "catalog_origin": "retained fictional catalog with a predeclared ambiguous alias",
        "conditioning_origin": "retained arbitrary caller-supplied384 vector",
        "source_encoder_verified": False, "reference_formulas_supplied": False,
        "optimizer_allocations": 0, "optimizer_updates": 0,
        "historical_checkpoint_optimizer_steps": 2,
        "original_forward_calls": actual, "adapter_replay_forward_calls": replay,
        "total_observed_forward_calls": len(forwards), "actual_gru_forward_count": len(grus),
        "numeric_event_counters_are_overlapping": True,
        "original_branching_score_count": branching, "adapter_replay_branching_score_count": branching,
        "total_branching_score_count": 2 * branching,
        "complete_formula_generated": generated["final_decoding"]["status"] == "valid_candidate",
        "statutory_meaning_verified": False, "held_out_accuracy_measured": False,
        "inference_permission_verified": False, "training_mask": 0, "evaluation_gold_mask": 0}
    manifest = retain_evidence(retained, case, report, original, companion, events, scope, directory)
    return {"case": case, "report": report, "evaluation": original, "companion": companion,
            "events": events, "scope": scope, "manifest": manifest,
            "generation_contexts": generation_contexts}


def test_complete_source_nomination_precedes_24_current_weight_forwards_and_replay(
        retained, inference, record_property):
    record_property("trained_source_generation_fixture", json.dumps(inference["manifest"], sort_keys=True))
    case, report, checkpoint = inference["case"], inference["report"], retained["checkpoint"]
    assert report["schema"] == "legal-compact-trained-source-generation/v2"
    assert report["profile"] == "full-selected-source-nomination-trained-bos-generation-384/v2"
    assert report["population"] == case["population"] and report["population_sha256"] == sha(case["population_raw"])
    assert report["checkpoint_sha256"] == CHECKPOINT_SHA
    assert report["current_weights_sha256"] == checkpoint["weights_sha256"] != checkpoint["initial_weights_sha256"]
    for name in ("initial_checkpoint_sha256", "initial_weights_sha256", "parent_checkpoint_sha256"):
        assert report[name] == checkpoint[name]
    assert report["training_progress"] == checkpoint["progress"] and report["compact_training_steps"] == 2
    assert report["checkpoint_inspection_performed"] is True
    assert report["optimizer_constructed"] is report["optimizer_state_restored"] is False
    assert report["model_executed"] is True and report["training_executed"] is report["compact_optimizer_executed"] is False
    counts = report["counts"]
    grus = [row for row in inference["events"] if row["event"] == "gru_forward"]
    forwards = [row for row in inference["events"] if row["event"] == "trained_forward"]
    # Require the enrolled population only after retaining actual outputs.
    # An earlier genuine block remains a failed control with intact evidence.
    assert len(grus) == len(forwards) == 24
    assert Counter(row["phase"] for row in grus) == {"original": 12, "adapter_replay": 12}
    assert Counter(row["phase"] for row in forwards) == {"original": 12, "adapter_replay": 12}
    assert [row["prefix_ids"] for row in forwards[:12]] == [row["prefix_ids"] for row in forwards[12:]]
    assert {name: counts[name] for name in ("selected", "nominated", "ambiguous", "unavailable")} == {
        "selected": 3, "nominated": 1, "ambiguous": 1, "unavailable": 1}
    for name in ("original", "adapter_replay"):
        assert counts[name + "_numerical_forward_count"] == 12
        assert counts[name + "_branching_score_count"] == inference["scope"][name + "_branching_score_count"] >= 1
    assert counts["total_numerical_forward_count"] == 24
    assert counts["total_branching_score_count"] == 2 * counts["original_branching_score_count"]
    selected = report["source_reports"][0]["report"]
    assert [row["id"] for row in report["source_reports"]] == ["unique", "ambiguous", "unavailable"]
    assert [row["report"]["status"] for row in report["source_reports"]] == ["nominated", "ambiguous", "unavailable"]
    assert selected["selected_symbols"] == ["Retain"]
    assert selected["context"]["argument_roles"] == [{"symbol": "Retain", "roles": ["holder", "record"]}]
    assert inference["generation_contexts"][0] == wire(selected["context"])
    for entry, row in zip(report["source_reports"], case["rows"]):
        assert entry["report_sha256"] == digest(entry["report"])
        assert entry["report"]["source_sha256"] == row["expected_source_sha256"]
        assert entry["report"]["catalog_sha256"] == row["expected_catalog_sha256"]
        no_authority(entry["report"])
    assert report["source_reports_sha256"] == digest(report["source_reports"])
    assert report["context_inventory_sha256"] == digest(report["context_inventory"])
    assert report["pre_generation_sha256"] == digest({key: report[key] for key in (
        "checkpoint_preflight", "population_sha256", "source_reports_sha256", "context_inventory_sha256")})
    assert subject.trained_source_generation_sha256(report) == digest(report)
    no_authority(report)


def test_bos_trace_reaches_a_real_constructor_choice_and_preserves_current_checkpoint(inference):
    report = inference["report"]
    slot = report["slots"][0]
    generated = slot["generation"]
    assert generated["initial_prefix_ids"] == [1] and generated["numerical_forward_count"] == 12
    assert generated["status"] == "step_budget_exhausted" and generated["reason"] == "max_new_tokens_reached"
    assert generated["final_decoding"]["status"] == "incomplete"
    assert slot["generation_sha256"] == digest(generated)
    assert slot["batch_adapter"]["generation_report_sha256"] == digest(generated)
    assert generated["exposure"]["teacher_forcing"] is generated["exposure"]["target_access"] is False
    assert generated["exposure"]["source_encoder_authenticated"] is False and generated["exposure"]["encoder_sha256"] is None
    assert generated["compact_training_steps"] == 2 and generated["checkpoint_sha256"] == CHECKPOINT_SHA
    trace = generated["trace"]
    assert len(trace) == 12 and all(len(row["prefix_report"]["allowed_token_ids"]) == 1 for row in trace[:8])
    assert len(trace[8]["prefix_report"]["allowed_token_ids"]) > 1
    vocabulary = report["predictions"]["codec"]["vocabulary"]
    assert vocabulary[trace[8]["selection"]["selected_token_id"]] in {
        '"predicate"', '"forall"', '"exists"', '"and"', '"or"', '"implies"', '"iff"', '"not"', '"extension"'}
    for index, row in enumerate(trace):
        assert row["checkpoint_sha256"] == CHECKPOINT_SHA and row["weights_sha256"] == report["current_weights_sha256"]
        assert row["numerical_forward_executed"] is row["runtime_verified"] is True
        assert row["optimizer_constructed"] is row["optimizer_state_restored"] is row["optimizer_executed"] is False
        assert row["prefix_ids"] == [1] + generated["selected_token_ids"][:index]
        assert len(row["logits"]) == 537 and all(type(item) is float and math.isfinite(item) for item in row["logits"])
        assert row["logits_sha256"] == digest(row["logits"])
        allowed = row["prefix_report"]["allowed_token_ids"]
        assert row["selection"]["selected_token_id"] == min(allowed, key=lambda token: (-row["logits"][token], token))
        no_authority(row)
    no_authority(generated)
    no_authority(slot["batch_adapter"])


def test_all_three_population_occurrences_and_context_dispositions_keep_zero_credit(inference):
    report, evaluation, companion = inference["report"], inference["evaluation"], inference["companion"]
    assert [row["status"] for row in report["context_inventory"]["rows"]] == ["available", "unsupported", "unavailable"]
    for slot, reason in zip(report["slots"][1:], ("source_context_ambiguous", "source_context_unavailable")):
        assert slot["status"] == "abstained" and slot["reason"] == reason
        assert slot["generation"] is slot["generation_sha256"] is slot["batch_adapter"] is None
        assert all(slot[key] == 0 for key in ("original_numerical_forward_count", "adapter_replay_numerical_forward_count",
            "total_numerical_forward_count", "original_branching_score_count", "adapter_replay_branching_score_count", "total_branching_score_count"))
    assert [row["status"] for row in report["predictions"]["rows"]] == ["generated", "abstained", "abstained"]
    assert report["predictions"]["generation"]["encoder_sha256"] is None
    assert report["predictions_sha256"] == digest(report["predictions"])
    assert evaluation["population"]["ordered_ids"] == ["unique", "ambiguous", "unavailable"]
    assert evaluation["coverage"]["expected_count"] == evaluation["coverage"]["prediction_row_count"] == 3
    assert evaluation["coverage"]["valid"] is True
    assert evaluation["terminal_counts"]["unverifiable_generation"] == sum(evaluation["terminal_counts"].values()) == 3
    assert evaluation["generation_issues"] == ["generation_decoder_encoder_invalid"]
    assert all(row["pair_diagnostic"] is None for row in evaluation["occurrences"])
    assert companion["original_evaluation"] == evaluation
    assert companion["availability_counts"]["available"] == companion["availability_counts"]["unsupported"] == companion["availability_counts"]["unavailable"] == 1
    assert companion["generated_context_binding_counts"]["matched"] == 1
    assert companion["generated_context_binding_counts"]["not_generated"] == 2
    no_authority(evaluation)
    no_authority(companion)


def forbid_dispatch(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("refused source-selected input reached numerical dispatch")
    monkeypatch.setattr(runtime, "generate_compact_content_trained_v2", forbidden)
    monkeypatch.setattr(runtime, "_forward", forbidden)
    monkeypatch.setattr(torch.nn.GRU, "forward", forbidden)


@pytest.mark.parametrize("pin", ["population", "checkpoint", "source", "catalog", "conditioning"])
def test_original_independent_pins_refuse_before_numerical_dispatch(retained, monkeypatch, pin):
    case, changes = authored_case(retained), {}
    if pin in ("population", "checkpoint"):
        changes["expected_" + pin + "_sha256"] = "0" * 64
    else:
        case["rows"][0]["expected_" + pin + "_sha256"] = "0" * 64
    forbid_dispatch(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained["checkpoint"], **changes)


@pytest.mark.parametrize("dimension", [8, 383, 385, 768])
def test_width_is_not_silently_projected_to_384(retained, monkeypatch, dimension):
    case = authored_case(retained)
    case["rows"][0]["conditioning"] = [0.] * dimension
    case["rows"][0]["expected_conditioning_sha256"] = digest(case["rows"][0]["conditioning"])
    forbid_dispatch(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained["checkpoint"])


@pytest.mark.parametrize("budget", [True, 0, -1, 13, 1.0, None])
def test_reviewed_twelve_token_bound_is_strict(retained, monkeypatch, budget):
    forbid_dispatch(monkeypatch)
    with pytest.raises(ValueError):
        prepare(authored_case(retained), retained["checkpoint"], max_new_tokens=budget)


@pytest.mark.parametrize("change", ["rows_missing", "rows_extra", "rows_reordered", "rows_duplicate",
    "population_duplicate", "population_reordered", "source_binding", "catalog_binding", "extra_target"])
def test_complete_ordered_population_and_no_target_override_are_required(retained, monkeypatch, change):
    case = authored_case(retained)
    if change == "rows_missing": case["rows"].pop()
    elif change == "rows_extra": case["rows"].append(deepcopy(case["rows"][0]))
    elif change == "rows_reordered": case["rows"].reverse()
    elif change == "rows_duplicate": case["rows"][2] = deepcopy(case["rows"][1])
    elif change == "population_duplicate":
        case["population"]["rows"][2] = deepcopy(case["population"]["rows"][1])
        case["population_raw"] = wire(case["population"])
    elif change == "population_reordered":
        case["population"]["rows"].reverse()
        case["population_raw"] = wire(case["population"])
    elif change == "source_binding":
        case["rows"][0]["source_raw"] = b"A different fictional holder may retain."
        case["rows"][0]["expected_source_sha256"] = sha(case["rows"][0]["source_raw"])
    elif change == "catalog_binding":
        catalog = json.loads(case["rows"][0]["catalog_raw"])
        catalog["aliases"][0]["forms"].append("keep")
        case["rows"][0]["catalog_raw"] = wire(catalog)
        case["rows"][0]["expected_catalog_sha256"] = digest(catalog)
    else: case["rows"][0]["expected_formula"] = {"not": "an admitted input field"}
    forbid_dispatch(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained["checkpoint"])


def test_invalid_final_source_cannot_allow_earlier_numerical_dispatch(retained, monkeypatch):
    case = authored_case(retained)
    case["rows"][-1]["source_raw"] = b"\xff"
    bad = sha(case["rows"][-1]["source_raw"])
    case["rows"][-1]["expected_source_sha256"] = case["population"]["rows"][-1]["source_sha256"] = bad
    case["population_raw"] = wire(case["population"])
    forbid_dispatch(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained["checkpoint"])


def test_nomination_callback_cannot_mutate_original_conditioning_before_dispatch(retained, monkeypatch):
    case = authored_case(retained)
    real, observed = contexts.prepare_source_context_v1, []
    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        observed.append(result["status"])
        if len(observed) == 1:
            case["rows"][0]["conditioning"][0] += .25
        return result
    monkeypatch.setattr(contexts, "prepare_source_context_v1", changed)
    forbid_dispatch(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained["checkpoint"])
    assert observed


def test_all_abstained_population_still_checks_trained_checkpoint_without_model_work(retained, monkeypatch):
    case = authored_case(retained)
    case["rows"][0]["source_raw"] = b"No recognized vocabulary."
    changed = sha(case["rows"][0]["source_raw"])
    case["rows"][0]["expected_source_sha256"] = case["population"]["rows"][0]["source_sha256"] = changed
    case["population_raw"] = wire(case["population"])
    forbid_dispatch(monkeypatch)
    report = prepare(case, retained["checkpoint"])
    assert report["checkpoint_inspection_performed"] is True and report["model_executed"] is False
    assert report["counts"]["selected"] == 3 and report["counts"]["nominated"] == 0
    assert report["counts"]["ambiguous"] == 1 and report["counts"]["unavailable"] == 2
    assert all(report["counts"][key] == 0 for key in ("original_numerical_forward_count",
        "adapter_replay_numerical_forward_count", "total_numerical_forward_count",
        "original_branching_score_count", "adapter_replay_branching_score_count", "total_branching_score_count"))
    assert all(row["status"] == "abstained" for row in report["slots"])
    broken = deepcopy(retained["checkpoint"])
    broken["weights_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepare(case, broken)
    no_authority(report)


def test_source_endpoint_failure_propagates_without_partial_success(retained, monkeypatch):
    failure = RuntimeError("authored source nomination failure")
    def refused(*args, **kwargs):
        raise failure
    monkeypatch.setattr(contexts, "prepare_source_context_v1", refused)
    forbid_dispatch(monkeypatch)
    with pytest.raises(RuntimeError) as observed:
        prepare(authored_case(retained), retained["checkpoint"])
    assert observed.value is failure


def test_public_source_caller_accepts_no_target_reference_context_or_prefix_override():
    assert list(inspect.signature(subject.prepare_trained_source_generation_v2).parameters) == [
        "population_raw", "rows", "checkpoint", "expected_population_sha256",
        "expected_checkpoint_sha256", "max_new_tokens"]
