"""Authored source-context selection through real bounded CPU generation.

The independent catalog and three fictional sources contain no reference AST
or expected output formula. The conditioning vector is arbitrary, the compact
head has zero training updates, and three initial syntax steps establish no
source encoder, complete formula, statutory interpretation or held-out accuracy.
All runtime execution belongs to the parent's owned native qualification.
"""
from copy import deepcopy
import hashlib
import inspect
import json

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as contexts
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as batch
from ipfs_datasets_py.logic.autoformal import legal_relational_content_context_evaluation_v1 as inventory_owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_generation_v1 as generation
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_source_generation_v1 as subject
from ipfs_datasets_py.logic.syntax_core import signatures


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def authored_catalog():
    """A fixed input vocabulary, independent of any reference or output tree."""
    obj = signatures.LogicSort("Object")
    entries = [("Retain", ["holder", "record"], ["retain", "act"]),
               ("Inspect", ["inspector", "record"], ["inspect", "act"]),
               ("Approve", ["approver", "request"], ["approve"])]
    signature = signatures.LogicSignature("authored-source-generation-catalog",
        family="tdfol", profile="tdfol_default", sorts=(obj,), symbols=tuple(
            signatures.declare_predicate(name, (obj,) * len(roles))
            for name, roles, _ in entries))
    return {"schema": "legal-compact-source-catalog/v1", "signature": signature.to_dict(),
        "argument_roles": [{"symbol": name, "roles": roles} for name, roles, _ in entries],
        "aliases": [{"symbol": name, "forms": forms} for name, _, forms in entries]}


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint():
    return head.create_compact_content_head_v1(config={"hidden_size": 8,
        "token_embedding_dim": 8, "projection_width": 4, "seed": 1729})


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def forbidden(*args, **kwargs):
    pytest.fail("refused or unavailable source context reached numerical generation")


def authored_case():
    catalog_raw = wire(authored_catalog())
    sources = [("unique", b"An auditor may inspect records."),
               ("ambiguous", b"A fictional actor may act."),
               ("unavailable", b"There are no matching vocabulary words here.")]
    conditioning = [.25, -.125] + [0.] * 382
    rows = [{"id": identity, "source_raw": raw, "catalog_raw": catalog_raw,
        "conditioning": list(conditioning), "expected_source_sha256": sha(raw),
        "expected_catalog_sha256": sha(catalog_raw),
        "expected_conditioning_sha256": digest(conditioning)} for identity, raw in sources]
    population = {"schema": "legal-relational-batch-population/v1",
        "partition": "authored-source-generation-controls",
        "selection_sha256": sha(b"Fixed three authored sources selected before any generation"),
        "rows": [{"id": row["id"], "source_sha256": row["expected_source_sha256"],
                  "context_sha256": row["expected_catalog_sha256"]} for row in rows]}
    return {"population": population, "population_raw": wire(population) + b"\n", "rows": rows}


def inputs(case, checkpoint, **changes):
    options = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_checkpoint_sha256": digest(checkpoint), "max_new_tokens": 3}
    options.update(changes)
    return (case["population_raw"], case["rows"], checkpoint), options


def prepare(case, checkpoint, **changes):
    values, options = inputs(case, checkpoint, **changes)
    return subject.prepare_source_generation_v1(*values, **options)


def unavailable_references(case):
    return {"schema": "legal-relational-batch-references/v1",
        "population_sha256": sha(case["population_raw"]), "rows": [
            {"id": row["id"], "status": "unavailable", "request_utf8": None,
             "request_sha256": None, "report": None, "report_sha256": None,
             "reason": "Authored engineering control; no expected formula or legal reference supplied"}
            for row in case["population"]["rows"]]}


def evaluate(case, report):
    refs_raw, predictions_raw = wire(unavailable_references(case)), wire(report["predictions"])
    contexts_raw = wire(report["context_inventory"])
    options = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_references_sha256": sha(refs_raw), "expected_predictions_sha256": sha(predictions_raw)}
    original = batch.prepare_relational_content_token_batch_evaluation_v1(
        case["population_raw"], refs_raw, predictions_raw, **options)
    companion = inventory_owner.prepare_relational_content_context_evaluation_v1(
        case["population_raw"], refs_raw, predictions_raw, contexts_raw,
        **options, expected_contexts_sha256=sha(contexts_raw))
    assert companion["original_evaluation"] == original
    return original, companion


def retain(case, checkpoint, report, evaluation, companion, events, directory, record_property):
    """Keep original bytes plus complete downstream records for saved-record audit."""
    directory.mkdir()
    artifacts = {"population.json": case["population_raw"], "checkpoint.json": wire(checkpoint),
        "references.json": wire(unavailable_references(case)), "result.json": wire(report),
        "predictions.json": wire(report["predictions"]), "context-inventory.json": wire(report["context_inventory"]),
        "batch-evaluation.json": wire(evaluation), "context-evaluation.json": wire(companion),
        "observed-calls.json": wire(events), "scope.json": wire({
            "source_origin": "authored engineering fixture", "catalog_origin": "independently authored fixture",
            "conditioning_origin": "arbitrary caller-supplied384 vector", "source_encoder_verified": False,
            "reference_formulas_supplied": False, "compact_optimizer_updates": 0,
            "original_forward_calls": 3, "adapter_replay_forward_calls": 3,
            "total_observed_forward_calls": 6, "complete_formula_generated": False,
            "statutory_meaning_verified": False, "held_out_accuracy_measured": False,
            "inference_permission_verified": False})}
    declarations = []
    for row in case["rows"]:
        identity = row["id"]
        source_file, catalog_file = identity + "-source.txt", identity + "-catalog.json"
        artifacts[source_file], artifacts[catalog_file] = row["source_raw"], row["catalog_raw"]
        declarations.append({key: value for key, value in row.items() if key not in ("source_raw", "catalog_raw")}
                            | {"source_file": source_file, "catalog_file": catalog_file})
    artifacts["input-rows.json"] = wire(declarations)
    manifest = {}
    for name, raw in artifacts.items():
        (directory / name).write_bytes(raw)
        manifest[name] = {"path": str(directory / name), "bytes": len(raw), "sha256": sha(raw)}
    raw = wire({"schema": "authored-source-generation-fixture/v1", "artifacts": manifest})
    path = directory / "manifest.json"
    path.write_bytes(raw)
    record_property("source_generation_fixture", json.dumps({"path": str(path), "sha256": sha(raw)}, sort_keys=True))


def test_all_source_contexts_precede_six_real_forward_calls_and_preserve_population(
        checkpoint, monkeypatch, tmp_path, record_property):
    case = authored_case()
    before_case, before_checkpoint = deepcopy(case), deepcopy(checkpoint)
    expected_sources = {row["expected_source_sha256"] for row in case["rows"]}
    seen, events, forward_calls, generation_contexts = set(), [], [], []
    real_prepare, real_generate, real_forward = (contexts.prepare_source_context_v1,
        generation.generate_compact_content_v1, head._forward)

    def observed_prepare(*args, **kwargs):
        result = real_prepare(*args, **kwargs)
        seen.add(kwargs["expected_source_sha256"])
        events.append({"event": "source_context_prepared", "source_sha256": kwargs["expected_source_sha256"],
                       "status": result["status"]})
        return result

    def observed_generate(*args, **kwargs):
        assert seen == expected_sources, "a numerical dispatch preceded complete source context preparation"
        assert args[2] == [1] and kwargs["prefix_origin"] == "bos_seed"
        assert kwargs["context_origin"] == "caller_supplied_unverified"
        generation_contexts.append(args[3])
        events.append({"event": "generation_called", "source_contexts_already_prepared": sorted(seen),
                       "context_raw_sha256": sha(args[3])})
        return real_generate(*args, **kwargs)

    def observed_forward(*args, **kwargs):
        assert seen == expected_sources
        forward_calls.append(list(args[2]))
        events.append({"event": "real_head_forward", "prefix_ids": list(args[2])})
        return real_forward(*args, **kwargs)

    monkeypatch.setattr(contexts, "prepare_source_context_v1", observed_prepare)
    monkeypatch.setattr(generation, "generate_compact_content_v1", observed_generate)
    monkeypatch.setattr(head, "_forward", observed_forward)
    rng = torch.get_rng_state().clone()
    report = prepare(case, checkpoint)
    assert case == before_case and checkpoint == before_checkpoint
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert report["schema"] == "legal-compact-source-generation/v1"
    assert report["profile"] == "full-selected-source-nomination-bos-generation-384/v1"
    assert report["population"] == case["population"]
    assert report["population_sha256"] == sha(case["population_raw"])
    assert report["checkpoint_sha256"] == digest(checkpoint)
    assert report["model_executed"] is True
    assert report["training_executed"] is report["compact_optimizer_executed"] is False
    assert checkpoint["compact_training_steps"] == 0 and checkpoint["optimizer_state_included"] is False
    assert report["counts"] == {"selected": 3, "nominated": 1, "ambiguous": 1, "unavailable": 1,
        "original_numerical_forward_count": 3, "adapter_replay_numerical_forward_count": 3,
        "total_numerical_forward_count": 6}
    assert len(forward_calls) == 6 and forward_calls[:3] == forward_calls[3:]
    assert len(generation_contexts) == 2 and generation_contexts[0] == generation_contexts[1]
    assert [row["id"] for row in report["source_reports"]] == ["unique", "ambiguous", "unavailable"]
    assert [row["report"]["status"] for row in report["source_reports"]] == ["nominated", "ambiguous", "unavailable"]
    selected = report["source_reports"][0]["report"]
    assert selected["selected_symbols"] == ["Inspect"] and selected["excluded_symbols"] == ["Retain", "Approve"]
    assert selected["context"]["argument_roles"] == [{"symbol": "Inspect", "roles": ["inspector", "record"]}]
    assert generation_contexts[0] == wire(selected["context"])
    for row, source in zip(report["source_reports"], case["rows"]):
        assert row["report_sha256"] == digest(row["report"])
        assert row["report"]["source_sha256"] == source["expected_source_sha256"]
        assert row["report"]["catalog_sha256"] == source["expected_catalog_sha256"]
        no_authority(row["report"])
    inventory = report["context_inventory"]
    assert inventory["population_sha256"] == sha(case["population_raw"])
    assert [row["id"] for row in inventory["rows"]] == ["unique", "ambiguous", "unavailable"]
    assert [row["status"] for row in inventory["rows"]] == ["available", "unsupported", "unavailable"]
    assert inventory["rows"][0]["content_context_utf8"].encode() == generation_contexts[0]
    assert inventory["rows"][0]["content_context_origin"] == "caller_supplied_unverified"
    assert all(row["content_context_utf8"] is row["content_context_sha256"] is row["content_context_origin"] is None
               for row in inventory["rows"][1:])
    assert report["source_reports_sha256"] == digest(report["source_reports"])
    assert report["context_inventory_sha256"] == digest(inventory)
    assert report["pre_generation_sha256"] == digest({key: report[key] for key in (
        "population_sha256", "source_reports_sha256", "context_inventory_sha256")})
    first = report["slots"][0]
    assert first["id"] == "unique" and first["status"] == "generated"
    assert first["source_context_status"] == "nominated"
    actual = first["generation"]
    assert first["generation_sha256"] == digest(actual)
    assert actual["status"] == "step_budget_exhausted" and actual["reason"] == "max_new_tokens_reached"
    assert actual["initial_prefix_ids"] == [1] and actual["numerical_forward_count"] == 3
    assert actual["final_decoding"]["status"] == "incomplete" and actual["final_decoding"]["prediction"] is None
    assert actual["exposure"]["teacher_forcing"] is actual["exposure"]["target_access"] is False
    assert actual["exposure"]["encoder_sha256"] is None
    assert actual["exposure"]["source_encoder_authenticated"] is False
    assert report["settings_sha256"] == digest(report["settings"])
    assert report["generation_settings_sha256"] == actual["settings_sha256"]
    assert report["settings_sha256"] != report["generation_settings_sha256"]
    assert len(actual["trace"]) == 3 and all(step["context_raw_sha256"] == sha(generation_contexts[0])
                                             for step in actual["trace"])
    assert first["batch_adapter"]["generation_report_sha256"] == digest(actual)
    for slot, reason in zip(report["slots"][1:], ("source_context_ambiguous", "source_context_unavailable")):
        assert slot["status"] == "abstained" and slot["reason"] == reason
        assert slot["generation"] is slot["batch_adapter"] is slot["generation_sha256"] is None
        assert slot["original_numerical_forward_count"] == slot["adapter_replay_numerical_forward_count"] == slot["total_numerical_forward_count"] == 0
    predictions = report["predictions"]
    assert predictions["generation"]["kind"] == "decoder_declared"
    assert predictions["generation"]["encoder_sha256"] is None
    assert predictions["generation"]["settings_sha256"] == report["generation_settings_sha256"]
    assert [row["status"] for row in predictions["rows"]] == ["generated", "abstained", "abstained"]
    assert report["predictions_sha256"] == digest(predictions)
    assert subject.source_generation_sha256(report) == digest(report)
    no_authority(report)
    original, companion = evaluate(case, report)
    assert original["population"]["ordered_ids"] == ["unique", "ambiguous", "unavailable"]
    assert original["coverage"]["expected_count"] == original["coverage"]["prediction_row_count"] == 3
    assert original["coverage"]["valid"] is True
    assert original["terminal_counts"]["unverifiable_generation"] == sum(original["terminal_counts"].values()) == 3
    assert original["generation_issues"] == ["generation_decoder_encoder_invalid"]
    assert [row["declared_status"] for row in original["occurrences"]] == ["generated", "abstained", "abstained"]
    assert original["observation_ledger"][0]["content_decoding"]["status"] == "incomplete"
    assert original["reference_availability"] == {"available": 0, "unavailable": 3, "total": 3, "fraction": 0.0}
    assert all(row["pair_diagnostic"] is None for row in original["occurrences"])
    assert companion["coverage"]["expected_count"] == companion["coverage"]["context_row_count"] == 3
    assert companion["coverage"]["valid"] is True
    assert companion["availability_counts"]["available"] == companion["availability_counts"]["unsupported"] == companion["availability_counts"]["unavailable"] == 1
    assert sum(companion["availability_counts"].values()) == 3
    assert companion["generated_context_binding_counts"]["matched"] == 1
    assert companion["generated_context_binding_counts"]["not_generated"] == 2
    assert len(forward_calls) == 6, "symbolic evaluation unexpectedly performed numerical work"
    for item in (actual, first["batch_adapter"], original, companion):
        no_authority(item)
    retain(case, checkpoint, report, original, companion, events, tmp_path / "authored-source-generation", record_property)


@pytest.mark.parametrize("pin", ["population", "checkpoint", "source", "catalog", "conditioning"])
def test_independent_pins_refuse_before_numerical_dispatch(checkpoint, monkeypatch, pin):
    case = authored_case()
    changes = {}
    if pin in ("population", "checkpoint"):
        changes["expected_" + pin + "_sha256"] = "0" * 64
    else:
        case["rows"][0]["expected_" + pin + "_sha256"] = "0" * 64
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    with pytest.raises(ValueError):
        prepare(case, checkpoint, **changes)


@pytest.mark.parametrize("change", ["rows_missing", "rows_extra", "rows_reordered", "rows_duplicate",
    "population_duplicate", "population_reordered", "source_binding", "catalog_binding",
    "conditioning_shape", "extra_target"])
def test_complete_population_and_input_bindings_refuse_before_numerical_dispatch(checkpoint, monkeypatch, change):
    case = authored_case()
    if change == "rows_missing":
        case["rows"].pop()
    elif change == "rows_extra":
        case["rows"].append(deepcopy(case["rows"][0]))
    elif change == "rows_reordered":
        case["rows"].reverse()
    elif change == "rows_duplicate":
        case["rows"][2] = deepcopy(case["rows"][1])
    elif change == "population_duplicate":
        case["population"]["rows"][2] = deepcopy(case["population"]["rows"][1])
        case["population_raw"] = wire(case["population"])
    elif change == "population_reordered":
        case["population"]["rows"].reverse()
        case["population_raw"] = wire(case["population"])
    elif change == "source_binding":
        case["rows"][0]["source_raw"] = b"A different actor may inspect."
        case["rows"][0]["expected_source_sha256"] = sha(case["rows"][0]["source_raw"])
    elif change == "catalog_binding":
        changed = authored_catalog()
        changed["aliases"][0]["forms"].append("keep")
        case["rows"][0]["catalog_raw"] = wire(changed)
        case["rows"][0]["expected_catalog_sha256"] = digest(changed)
    elif change == "conditioning_shape":
        case["rows"][0]["conditioning"].pop()
        case["rows"][0]["expected_conditioning_sha256"] = digest(case["rows"][0]["conditioning"])
    else:
        case["rows"][0]["expected_formula"] = {"not": "a permitted caller field"}
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    with pytest.raises(ValueError):
        prepare(case, checkpoint)


def test_every_context_is_preflighted_even_when_last_source_is_invalid(checkpoint, monkeypatch):
    case = authored_case()
    case["rows"][-1]["source_raw"] = b"\xff"
    bad_sha = sha(case["rows"][-1]["source_raw"])
    case["rows"][-1]["expected_source_sha256"] = bad_sha
    case["population"]["rows"][-1]["source_sha256"] = bad_sha
    case["population_raw"] = wire(case["population"])
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    with pytest.raises(ValueError):
        prepare(case, checkpoint)


@pytest.mark.parametrize("change", ["source_hash", "ordered_roles", "authority"])
def test_altered_nomination_cannot_bypass_public_raw_source_replay(checkpoint, monkeypatch, change):
    case = authored_case()
    original = contexts.prepare_source_context_v1
    calls = []

    def altered_once(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            if change == "source_hash":
                result["source_sha256"] = "0" * 64
            elif change == "ordered_roles":
                result["context"]["argument_roles"][0]["roles"].reverse()
                result["context_sha256"] = digest(result["context"])
            else:
                result["authority"]["accepted"] = True
        return result

    monkeypatch.setattr(contexts, "prepare_source_context_v1", altered_once)
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    with pytest.raises(ValueError):
        prepare(case, checkpoint)


def test_all_ambiguous_or_unavailable_sources_keep_slots_without_any_generation(checkpoint, monkeypatch):
    case = authored_case()
    case["rows"][0]["source_raw"] = b"No recognized vocabulary."
    new_sha = sha(case["rows"][0]["source_raw"])
    case["rows"][0]["expected_source_sha256"] = new_sha
    case["population"]["rows"][0]["source_sha256"] = new_sha
    case["population_raw"] = wire(case["population"])
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    report = prepare(case, checkpoint)
    assert report["model_executed"] is False
    assert report["counts"] == {"selected": 3, "nominated": 0, "ambiguous": 1, "unavailable": 2,
        "original_numerical_forward_count": 0, "adapter_replay_numerical_forward_count": 0,
        "total_numerical_forward_count": 0}
    assert [row["id"] for row in report["slots"]] == ["unique", "ambiguous", "unavailable"]
    assert all(row["status"] == "abstained" and row["generation"] is row["batch_adapter"] is None for row in report["slots"])
    assert all(row["status"] == "abstained" for row in report["predictions"]["rows"])
    assert report["predictions"]["generation"]["encoder_sha256"] is None
    no_authority(report)


def test_numerical_failure_propagates_without_becoming_source_abstention(checkpoint, monkeypatch):
    error = RuntimeError("authored numerical failure control")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(head, "_forward", fail)
    with pytest.raises(RuntimeError) as caught:
        prepare(authored_case(), checkpoint)
    assert caught.value is error


@pytest.mark.parametrize("budget", [True, 0, 9])
def test_additive_caller_budget_refuses_before_dispatch(checkpoint, monkeypatch, budget):
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    with pytest.raises(ValueError):
        prepare(authored_case(), checkpoint, max_new_tokens=budget)


def test_selected_population_limit_refuses_instead_of_clipping(checkpoint, monkeypatch):
    case = authored_case()
    first = case["rows"][0]
    case["rows"] = [dict(deepcopy(first), id="row-" + str(index)) for index in range(17)]
    case["population"]["rows"] = [{"id": row["id"], "source_sha256": row["expected_source_sha256"],
        "context_sha256": row["expected_catalog_sha256"]} for row in case["rows"]]
    case["population_raw"] = wire(case["population"])
    monkeypatch.setattr(generation, "generate_compact_content_v1", forbidden)
    monkeypatch.setattr(head, "_forward", forbidden)
    with pytest.raises(ValueError):
        prepare(case, checkpoint)


def test_public_caller_accepts_no_target_reference_context_override_or_assisted_prefix():
    assert list(inspect.signature(subject.prepare_source_generation_v1).parameters) == [
        "population_raw", "rows", "checkpoint", "expected_population_sha256",
        "expected_checkpoint_sha256", "max_new_tokens"]
