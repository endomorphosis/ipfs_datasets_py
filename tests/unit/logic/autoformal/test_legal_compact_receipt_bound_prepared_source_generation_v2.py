"""Retained native receipt -> full selected population -> prepared consumer.

The admitted harness supplies one independently pinned, completed native
fixture. This suite never runs an encoder, allocates Adam, fits a model, or
fabricates positive producer evidence. One cached outer preparation and its
public validation exercise original and mandatory adapter replay at64 new IDs.
Four fresh prepared model restores serve at most256 full-prefix GRU calls. Serialized
missing-input controls are explicitly counterfactual and have no native credit.
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
import struct

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as contexts
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_source_binding_v1 as binding
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_prepared_runtime_v3 as runtime
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as legacy_runtime
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_receipt_bound_prepared_source_generation_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_prepared_source_generation_v3 as trained_source
from ipfs_datasets_py.logic.syntax_core import signatures
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_RETAINED_BYTES = 24 * 1024 * 1024
MAX_GRU_CALLS = 256
MAX_NEW_TOKENS = 64


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def receipt_wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def snapshot(path):
    path = Path(path)
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
        assert 0 < before.st_size <= MAX_FILE_BYTES
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
        item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    assert len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat())
    return raw


def reference(path):
    raw = snapshot(path)
    return {"path": str(Path(path)), "bytes": len(raw), "sha256": sha(raw)}


def read_reference(value):
    assert set(value) == {"path", "bytes", "sha256"}
    assert type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_FILE_BYTES
    raw = snapshot(value["path"])
    assert len(raw) == value["bytes"] and sha(raw) == value["sha256"]
    return raw


def write_new(path, raw):
    assert 0 < len(raw) <= MAX_FILE_BYTES
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert snapshot(path) == raw


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


@pytest.fixture(scope="module", autouse=True)
def no_encoder_optimizer_or_training():
    """Prohibit productive encoder/trainer paths, without changing runtime policy."""
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append("encoder, optimizer, or training")
        pytest.fail("receipt reuse reached an encoder, optimizer, or training path")
    # The native owner/harness establishes one-thread CPU execution. Do not
    # silently change global runtime policy to make a checkpoint acceptable.
    assert torch.get_num_threads() == 1
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(producer, "produce_native_embedding_receipt", forbidden)
        patch.setattr(torch.optim.Optimizer, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "step", forbidden)
        patch.setattr(numerical, "_optimizer", forbidden)
        patch.setattr(trainer, "_restore", forbidden)
        patch.setattr(trainer, "build_compact_content_training_v2", forbidden)
        patch.setattr(trainer, "train_compact_content_v2", forbidden)
        yield attempts
    assert attempts == []


@pytest.fixture(scope="module")
def retained(no_encoder_optimizer_or_training):
    spelling = os.environ.get("LEGAL_COMPACT_RECEIPT_BOUND_TRAINED_FIXTURE")
    commitment = os.environ.get("LEGAL_COMPACT_RECEIPT_BOUND_TRAINED_FIXTURE_SHA256")
    assert spelling and commitment, "one admitted completed native fixture is required; no fallback or skip"
    path = Path(spelling)
    raw = snapshot(path)
    assert sha(raw) == commitment
    packet = json.loads(raw)
    assert set(packet) == {"schema", "native_fixture", "native_evidence", "native_qualification",
        "checkpoint", "checkpoint_sha256"}
    assert packet["schema"] == "legal-receipt-bound-trained-source-fixture/v1"
    bodies = {key: read_reference(packet[key]) for key in (
        "native_fixture", "native_evidence", "native_qualification", "checkpoint")}
    fixture, evidence, qualification, checkpoint = (json.loads(bodies[key]) for key in (
        "native_fixture", "native_evidence", "native_qualification", "checkpoint"))
    assert qualification["passed"] is True
    assert fixture["schema"] == "legal-compact-source-binding-native-fixture/v1"
    assert evidence["schema"] == "legal-compact-source-binding-native-evidence/v1"
    assert evidence["actual_native_producer_call_count"] == evidence["actual_encoder_forward_count"] == 1
    assert evidence["actual_untruncated_tokenization_call_count"] == 4
    assert evidence["training_executed"] is evidence["optimizer_executed"] is False
    assert evidence["input_fixture"] == packet["native_fixture"]
    requests = fixture["embedded_requests"] + [fixture["oversized_request"]]
    assert evidence["source_requests"] == requests and len(requests) == 4
    assert evidence["receipt_status_counts"] == {"embedded": 3, "token_limit_exceeded": 1, "missing_input": 0}
    assert evidence["source_artifacts"] == fixture["source_artifacts"]
    for artifact in fixture["source_artifacts"]:
        read_reference(artifact)
    receipt_raw = read_reference(evidence["native_receipt"])
    receipt = json.loads(receipt_raw)
    assert receipt["inputs"] == evidence["receipt_inputs"]
    assert receipt["results"] == evidence["receipt_results"]
    assert receipt["status_counts"] == evidence["receipt_status_counts"]
    assert len(receipt["inputs"]) == len(receipt["results"]) == 4
    assert [row["status"] for row in receipt["results"]] == ["embedded"] * 3 + ["token_limit_exceeded"]
    assert requests[1]["input"]["text"] == requests[2]["input"]["text"]
    assert requests[1]["input"]["source"] != requests[2]["input"]["source"]
    assert len({row["occurrence_id"] for row in requests}) == len({row["input"]["input_id"] for row in requests}) == 4
    assert digest(checkpoint) == packet["checkpoint_sha256"]
    assert checkpoint["progress"]["optimizer_steps"] == 2
    index = {row["sha256"]: row for row in fixture["source_artifacts"]}
    def resolver(value):
        artifact = index[value["sha256"]]
        assert value == {key: artifact[key] for key in ("bytes", "sha256")}
        return Path(artifact["path"])
    return {"packet": packet, "packet_ref": reference(path), "checkpoint": checkpoint,
        "requests": requests, "receipt": receipt, "receipt_ref": evidence["native_receipt"],
        "native_evidence": evidence, "resolver": resolver, "bodies": bodies}


def catalog(entries, identity):
    """Fixed authored lexical choices; no formula/reference/target is consulted."""
    obj = signatures.LogicSort("Object")
    signature = signatures.LogicSignature(identity, family="tdfol", profile="tdfol_default",
        sorts=(obj,), symbols=tuple(signatures.declare_predicate(name, (obj, obj)) for name, _ in entries))
    return {"schema": "legal-compact-source-catalog/v1", "signature": signature.to_dict(),
        "argument_roles": [{"symbol": name, "roles": ["actor", "object"]} for name, _ in entries],
        "aliases": [{"symbol": name, "forms": list(forms)} for name, forms in entries]}


def authored_case(retained):
    entries = [[("Assign", ("assigned",))],
        [("Retain", ("retain",)), ("Inspect", ("retain",))],
        [("Unavailable", ("zz_no_matching_vocabulary_zz",))],
        [("Record", ("record",))]]
    rows = []
    for index, request in enumerate(retained["requests"]):
        raw = request["input"]["text"].encode("utf-8")
        catalog_raw = wire(catalog(entries[index], "receipt-bound-authored-catalog-" + str(index)))
        rows.append({"id": request["occurrence_id"], "source_raw": raw, "catalog_raw": catalog_raw,
            "expected_source_sha256": sha(raw), "expected_catalog_sha256": sha(catalog_raw),
            "source_request": deepcopy(request), "expected_source_request_sha256": digest(request),
            "input_id": request["input"]["input_id"], "receipt_ref": deepcopy(retained["receipt_ref"])})
    population = {"schema": "legal-relational-batch-population/v1",
        "partition": "authored-receipt-bound-prepared-source-engineering",
        "selection_sha256": sha(b"All four original native occurrences, declared before trained generation"),
        "rows": [{"id": row["id"], "source_sha256": row["expected_source_sha256"],
            "context_sha256": row["expected_catalog_sha256"]} for row in rows]}
    return {"population": population, "population_raw": wire(population) + b"\n", "rows": rows}


def prepare(case, retained, **changes):
    options = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_checkpoint_sha256": digest(retained["checkpoint"]), "max_new_tokens": MAX_NEW_TOKENS,
        "source_resolver": retained["resolver"]}
    options.update(changes)
    return subject.prepare_receipt_bound_prepared_source_generation_v2(
        case["population_raw"], case["rows"], retained["checkpoint"], **options)


def validate(report, case, retained, **changes):
    options = {"expected_report_sha256": digest(report),
        "expected_population_sha256": sha(case["population_raw"]),
        "expected_checkpoint_sha256": digest(retained["checkpoint"]), "max_new_tokens": MAX_NEW_TOKENS,
        "source_resolver": retained["resolver"]}
    options.update(changes)
    return subject.validate_receipt_bound_prepared_source_generation_v2(
        report, case["population_raw"], case["rows"], retained["checkpoint"], **options)


def forbid_numerical(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a pure refusal or unavailable population reached numerical dispatch")
    monkeypatch.setattr(runtime, "generate_compact_content_prepared_v3", forbidden)
    monkeypatch.setattr(runtime._PreparedModel, "__init__", forbidden)
    monkeypatch.setattr(runtime._PreparedModel, "forward", forbidden)
    monkeypatch.setattr(legacy_runtime, "generate_compact_content_trained_v2", forbidden)
    monkeypatch.setattr(legacy_runtime, "_forward", forbidden)
    monkeypatch.setattr(numerical, "_model", forbidden)
    monkeypatch.setattr(torch.nn.GRU, "forward", forbidden)


def retain_evidence(directory, retained, case, report, validated, events):
    public_calls = [row for row in events if row["event"] == "trained_forward"]
    gru_calls = [row for row in events if row["event"] == "gru_forward"]
    by_phase = {phase: sum(row["phase"] == phase for row in public_calls) for phase in ("prepare", "validate")}
    constructions = [row for row in events if row["event"] == "model_constructed"]
    restores = [row for row in events if row["event"] == "model_weights_loaded"]
    generations = [row for row in events if row["event"] == "prepared_generation_started"]
    scope = {"schema": "legal-receipt-bound-prepared-source-engineering-scope/v2",
        "original_outer_selected_count": 4, "receipt_embedded_count": 3,
        "receipt_token_limit_exceeded_count": 1, "receipt_missing_input_count": 0,
        "inner_selected_count": 3, "inner_source_context_counts": {"nominated": 1, "ambiguous": 1, "unavailable": 1},
        "positive_outer_preparations": 1, "positive_public_outer_validations": 1,
        "public_model_forward_count": len(public_calls), "actual_gru_forward_count": len(gru_calls),
        "forward_count_by_outer_operation": by_phase, "public_and_gru_counters_overlap": True,
        "maximum_actual_gru_forward_count": MAX_GRU_CALLS,
        "actual_model_constructions": len(constructions), "actual_model_restores": len(restores),
        "public_prepared_generation_calls": len(generations), "model_restore_count_by_outer_operation": {
            phase: sum(row["phase"] == phase for row in restores) for phase in ("prepare", "validate")},
        "restore_and_generation_counters_overlap": True, "max_new_tokens": MAX_NEW_TOKENS,
        "fresh_native_producer_calls": 0, "fresh_encoder_forwards": 0,
        "optimizer_allocations": 0, "optimizer_updates": 0, "training_calls": 0,
        "historical_checkpoint_optimizer_steps": retained["checkpoint"]["progress"]["optimizer_steps"],
        "catalog_origin": "independently authored before this inference; permission and exposure unverified",
        "conditioning_origin": "exact retained receipt native raw384 bits; trained-space compatibility unverified",
        "complete_formula_required_for_custody_positive": False,
        "source_encoder_authenticated": False, "runtime_cryptographically_attested": False,
        "conditioning_space_training_compatibility_verified": False, "context_permission_verified": False,
        "source_semantics_verified": False, "held_out_accuracy_measured": False,
        "training_mask": 0, "evaluation_gold_mask": 0}
    artifacts = {"population.json": case["population_raw"], "positive-report.json": wire(report),
        "validated-report.json": wire(validated), "observed-calls.json": wire(events), "scope.json": wire(scope),
        "consumed-fixture-packet.json": wire(retained["packet"])}
    declarations = []
    for index, row in enumerate(case["rows"]):
        source_name, catalog_name = str(index) + "-source.txt", str(index) + "-catalog.json"
        artifacts[source_name], artifacts[catalog_name] = row["source_raw"], row["catalog_raw"]
        declarations.append({key: value for key, value in row.items() if key not in ("source_raw", "catalog_raw")}
            | {"source_file": source_name, "catalog_file": catalog_name})
    artifacts["input-rows.json"] = wire(declarations)
    assert len(artifacts) == 15 and sum(map(len, artifacts.values())) <= MAX_RETAINED_BYTES
    descriptors = {}
    for name, raw in artifacts.items():
        path = directory / name
        write_new(path, raw)
        descriptors[name] = reference(path)
    manifest = {"schema": "legal-receipt-bound-prepared-source-engineering-fixture/v2",
        "artifacts": descriptors, "consumed_fixture": retained["packet_ref"],
        "checkpoint_sha256": digest(retained["checkpoint"]), "native_receipt": retained["receipt_ref"],
        "summary": scope}
    path = directory / "manifest.json"
    write_new(path, wire(manifest))
    return reference(path)


@pytest.fixture(scope="module")
def inference(retained, tmp_path_factory):
    case, checkpoint = authored_case(retained), retained["checkpoint"]
    before = deepcopy((case, checkpoint))
    expected_pairs = {(row["expected_source_sha256"], row["expected_catalog_sha256"]) for row in case["rows"]}
    assert len(expected_pairs) == 4
    events, active, prepared_pairs, prepared_receipts = [], {"phase": "prepare", "inner_calls": 0}, set(), set()
    expected_ids = {row["id"] for row in case["rows"]}
    original_conditioning = binding.prepare_compact_source_conditioning_v1
    original_context = contexts.prepare_source_context_v1
    original_inner = trained_source.prepare_prepared_source_generation_v3
    original_forward, original_gru = runtime._PreparedModel.forward, torch.nn.GRU.forward
    original_model, original_load = numerical._model, torch.nn.Module.load_state_dict
    original_generate = runtime.generate_compact_content_prepared_v3
    models, generations = [], []

    def observe_conditioning(*args, **kwargs):
        result = original_conditioning(*args, **kwargs)
        prepared_receipts.add(result["occurrence_id"])
        events.append({"event": "source_receipt_prepared", "phase": active["phase"],
            "id": result["occurrence_id"], "report_sha256": digest(result), "status": result["status"],
            "receipt_input_index": result["receipt_input_index"]})
        return result

    def observe_context(*args, **kwargs):
        result = original_context(*args, **kwargs)
        pair = (kwargs["expected_source_sha256"], kwargs["expected_catalog_sha256"])
        prepared_pairs.add(pair)
        events.append({"event": "source_context_prepared", "phase": active["phase"],
            "source_sha256": pair[0], "catalog_sha256": pair[1], "status": result["status"]})
        return result

    def observe_inner(population_raw, rows, value, **kwargs):
        assert prepared_pairs == expected_pairs, "not every original outer context preceded the trained caller"
        assert prepared_receipts == expected_ids, "not every original receipt disposition preceded the trained caller"
        assert [row["id"] for row in rows] == [row["id"] for row in case["rows"][:3]]
        population = json.loads(population_raw)
        assert [row["id"] for row in population["rows"]] == [row["id"] for row in rows]
        for index, row in enumerate(rows):
            bits = bytes.fromhex(retained["receipt"]["results"][index]["vector"]["bits"])
            assert b"".join(struct.pack(">f", number) for number in row["conditioning"]) == bits
            assert row["expected_conditioning_sha256"] == digest(row["conditioning"])
        active["inner_calls"] += 1
        assert active["inner_calls"] <= 2
        events.append({"event": "trained_source_prepared", "phase": active["phase"],
            "population_sha256": sha(population_raw), "ordered_ids": [row["id"] for row in rows],
            "outer_receipt_ids_already_prepared": sorted(prepared_receipts),
            "outer_context_pairs_already_prepared": [list(pair) for pair in sorted(prepared_pairs)]})
        return original_inner(population_raw, rows, value, **kwargs)

    def observe_generation(value, conditioning, prefix_ids, context_raw, **kwargs):
        assert prepared_pairs == expected_pairs and prepared_receipts == expected_ids
        assert prefix_ids == [1] and kwargs["prefix_origin"] == "bos_seed"
        assert kwargs["max_new_tokens"] == MAX_NEW_TOKENS
        index = len(generations)
        assert index < 4
        generations.append(index)
        active["generation"] = index
        active["checkpoint"] = value
        active["conditioning"] = conditioning
        events.append({"event": "prepared_generation_started", "phase": active["phase"],
            "generation_index": index, "prefix_ids": list(prefix_ids),
            "checkpoint_sha256": digest(value), "conditioning_sha256": digest(conditioning)})
        result = original_generate(value, conditioning, prefix_ids, context_raw, **kwargs)
        assert result["preparation"] == {"checkpoint_inspection_count": 1, "model_restore_count": 1,
            "scope": "enclosing_public_operation", "full_prefix_each_step": True,
            "cross_call_model_cache": False, "incremental_hidden_state": False}
        events.append({"event": "prepared_generation_completed", "phase": active["phase"],
            "generation_index": index, "report_sha256": digest(result),
            "numerical_forward_count": result["numerical_forward_count"],
            "status": result["status"], "final_decoding_status": result["final_decoding"]["status"],
            "preparation": deepcopy(result["preparation"])})
        return result

    def observe_model(*args, **kwargs):
        assert prepared_pairs == expected_pairs and prepared_receipts == expected_ids
        model = original_model(*args, **kwargs)
        assert all(model is not known for known in models)
        models.append(model)
        events.append({"event": "model_constructed", "phase": active["phase"],
            "generation_index": active["generation"], "model_index": len(models) - 1,
            "parameter_count": sum(value.numel() for value in model.parameters())})
        assert len(models) <= 4
        return model

    def observe_load(model, *args, **kwargs):
        result = original_load(model, *args, **kwargs)
        if any(model is known for known in models):
            events.append({"event": "model_weights_loaded", "phase": active["phase"],
                "generation_index": active["generation"],
                "model_index": next(index for index, known in enumerate(models) if model is known),
                "state_sha256": digest({name: tensor.detach().tolist() for name, tensor in model.state_dict().items()})})
            assert sum(row["event"] == "model_weights_loaded" for row in events) <= 4
        return result

    def observe_forward(prepared, prefix_ids):
        assert prepared_pairs == expected_pairs and prepared_receipts == expected_ids
        assert any(prepared.model is known for known in models)
        active["prefix_ids"] = list(prefix_ids)
        result = original_forward(prepared, prefix_ids)
        events.append({"event": "trained_forward", "phase": active["phase"], "generation_index": active["generation"],
            "model_index": next(index for index, known in enumerate(models) if prepared.model is known),
            "prefix_ids": list(prefix_ids),
            "checkpoint_sha256": digest(active["checkpoint"]), "weights_sha256": active["checkpoint"]["weights_sha256"],
            "conditioning_sha256": digest(active["conditioning"]), "logits_sha256": digest(result["logits"]),
            "output_shape": result["output_shape"]})
        assert sum(row["event"] == "trained_forward" for row in events) <= MAX_GRU_CALLS
        return result

    def observe_gru(model, tensor, *args, **kwargs):
        assert prepared_pairs == expected_pairs and prepared_receipts == expected_ids
        result = original_gru(model, tensor, *args, **kwargs)
        events.append({"event": "gru_forward", "phase": active["phase"],
            "generation_index": active["generation"],
            "model_index": next(index for index, known in enumerate(models) if model is known.decoder),
            "prefix_ids": list(active["prefix_ids"]), "input_shape": list(tensor.shape),
            "output_shape": list(result[0].shape)})
        assert sum(row["event"] == "gru_forward" for row in events) <= MAX_GRU_CALLS
        return result

    rng, threads = torch.get_rng_state().clone(), torch.get_num_threads()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(binding, "prepare_compact_source_conditioning_v1", observe_conditioning)
        patch.setattr(contexts, "prepare_source_context_v1", observe_context)
        patch.setattr(trained_source, "prepare_prepared_source_generation_v3", observe_inner)
        patch.setattr(runtime, "generate_compact_content_prepared_v3", observe_generation)
        patch.setattr(numerical, "_model", observe_model)
        patch.setattr(torch.nn.Module, "load_state_dict", observe_load)
        patch.setattr(runtime._PreparedModel, "forward", observe_forward)
        patch.setattr(torch.nn.GRU, "forward", observe_gru)
        report = prepare(case, retained)
        active["phase"] = "validate"
        prepared_pairs.clear()
        prepared_receipts.clear()
        validated = validate(report, case, retained)
    assert (case, checkpoint) == before
    counts = Counter(row["event"] for row in events)
    assert counts["prepared_generation_started"] == counts["prepared_generation_completed"] == 4
    assert counts["model_constructed"] == counts["model_weights_loaded"] == 4
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == threads == 1
    directory = tmp_path_factory.mktemp("receipt-bound-prepared-source-v2")
    manifest = retain_evidence(directory, retained, case, report, validated, events)
    return {"case": case, "report": report, "validated": validated, "events": events, "manifest": manifest}


def test_receipt_prepared_actual_receipt_reuse_preserves_full_outer_and_exact_inner_mapping(inference, retained, record_property):
    record_property("receipt_bound_prepared_source_fixture", json.dumps(inference["manifest"], sort_keys=True))
    report, case = inference["report"], inference["case"]
    assert report["schema"] == "legal-compact-receipt-bound-prepared-source-generation/v2"
    assert report["profile"] == "full-selected-native-receipt-prepared-bos-generation-384/v2"
    assert report["population"] == case["population"] and report["population_sha256"] == sha(case["population_raw"])
    assert report["mapping"] == {"outer_to_inner": [0, 1, 2, None], "inner_to_outer": [0, 1, 2]}
    assert report["inner_population"] == json.loads(report["inner_population_utf8"])
    assert sha(report["inner_population_utf8"].encode("utf-8")) == report["inner_population_sha256"]
    assert [row["id"] for row in report["slots"]] == [row["id"] for row in case["rows"]]
    assert [row["embedding_status"] for row in report["slots"]] == ["embedded"] * 3 + ["token_limit_exceeded"]
    assert [row["source_context_status"] for row in report["slots"]] == ["nominated", "ambiguous", "unavailable", "nominated"]
    assert [row["inner_index"] for row in report["slots"]] == [0, 1, 2, None]
    assert report["trained_source_report"]["population"] == report["inner_population"]
    assert len(report["receipt_inventory"]) == 1
    inventory = report["receipt_inventory"][0]
    assert inventory["receipt"] == retained["receipt_ref"]
    assert inventory["inputs"] == retained["receipt"]["inputs"] and inventory["input_count"] == 4
    assert inventory["status_counts"] == retained["receipt"]["status_counts"]
    assert [row["index"] for row in inventory["results"]] == list(range(4))
    assert [row["input_id"] for row in inventory["results"]] == [row["input_id"] for row in retained["receipt"]["results"]]
    assert inventory["native_execution_record_present"] is True and inventory["encoder_executed_by_adapter"] is False
    for index, entry in enumerate(report["source_conditionings"]):
        value = entry["report"]
        assert entry["id"] == case["rows"][index]["id"]
        assert entry["report_sha256"] == digest(value)
        assert value["input"] == retained["requests"][index]["input"]
        assert value["receipt_input_index"] == index and value["receipt_input_count"] == 4
        assert value["receipt_status_counts"] == retained["receipt"]["status_counts"]
        if index < 3:
            assert value["native_vector"] == retained["receipt"]["results"][index]["vector"]
            assert value["tokens"] == retained["receipt"]["results"][index]["tokens"]
            assert value["source_receipt_binding_verified"] is value["source_bytes_verified"] is True
        else:
            assert value["conditioning"] is value["conditioning_sha256"] is None
            assert value["source_receipt_binding_verified"] is False
        no_authority(value)
    # Equal text stays two physical origins and two separately retained slots.
    first, second = (row["report"] for row in report["source_conditionings"][1:3])
    assert first["source_sha256"] == second["source_sha256"] and first["input_id"] != second["input_id"]
    assert first["source_span"] != second["source_span"]
    for index, entry in enumerate(report["source_reports"]):
        value, row = entry["report"], case["rows"][index]
        assert entry["id"] == row["id"] and entry["report_sha256"] == digest(value)
        assert value["source_sha256"] == row["expected_source_sha256"]
        assert value["catalog_sha256"] == row["expected_catalog_sha256"]
        expected_context = digest(value["context"]) if value["context"] is not None else None
        assert report["slots"][index]["compact_context_sha256"] == expected_context
        assert report["slots"][index]["compact_context_raw_sha256"] == expected_context
        assert expected_context != row["expected_catalog_sha256"]
        no_authority(value)
    assert report["pre_generation_sha256"] == digest({key: report[key] for key in (
        "population", "population_sha256", "checkpoint_sha256", "checkpoint_preflight", "receipt_inventory",
        "source_conditionings", "source_reports", "mapping", "inner_population", "inner_population_utf8",
        "inner_population_sha256", "settings")})
    assert inference["validated"] == report
    assert subject.receipt_bound_prepared_source_generation_sha256(report) == digest(report)
    no_authority(report)


def test_receipt_prepared_only_one_nominated_embedded_row_generates_and_replays(inference, retained):
    report = inference["report"]
    counts = report["counts"]
    assert {key: counts[key] for key in ("selected", "embedded", "missing_input", "token_limit_exceeded", "inner_selected")} == {
        "selected": 4, "embedded": 3, "missing_input": 0, "token_limit_exceeded": 1, "inner_selected": 3}
    assert {key: counts[key] for key in ("source_context_nominated", "source_context_ambiguous", "source_context_unavailable")} == {
        "source_context_nominated": 2, "source_context_ambiguous": 1, "source_context_unavailable": 1}
    assert counts["generated"] == 1 and counts["comparison_eligible"] == 0
    assert report["checkpoint_sha256"] == digest(retained["checkpoint"])
    assert report["trained_source_report"]["compact_training_steps"] == 2
    nested = report["trained_source_report"]
    assert nested["predictions"]["generation"]["encoder_sha256"] is None
    assert [slot["status"] for slot in nested["slots"]] == ["generated", "abstained", "abstained"]
    assert report["slots"][-1]["inner_slot"] is None
    generated = nested["slots"][0]["generation"]
    assert nested["schema"] == "legal-compact-prepared-source-generation/v3"
    assert nested["profile"] == "full-selected-source-nomination-prepared-trained-bos-generation-384/v3"
    assert generated["schema"] == "legal-compact-content-generation/v3"
    assert generated["settings"]["max_new_tokens"] == MAX_NEW_TOKENS
    assert generated["preparation"]["model_restore_count"] == 1
    assert generated["initial_prefix_ids"] == [1]
    assert generated["exposure"]["teacher_forcing"] is generated["exposure"]["target_access"] is False
    assert generated["status"] in ("complete", "blocked", "step_budget_exhausted")
    original = counts["original_numerical_forward_count"]
    assert 1 <= original <= MAX_NEW_TOKENS and counts["adapter_replay_numerical_forward_count"] == original
    assert counts["total_numerical_forward_count"] == 2 * original <= 2 * MAX_NEW_TOKENS
    assert counts["complete"] == int(generated["final_decoding"]["status"] == "valid_candidate")
    for step in generated["trace"]:
        assert len(step["logits"]) == 537 and all(type(value) is float and math.isfinite(value) for value in step["logits"])
        allowed = step["prefix_report"]["allowed_token_ids"]
        assert step["selection"]["selected_token_id"] == min(allowed, key=lambda token: (-step["logits"][token], token))
        assert step["optimizer_constructed"] is step["optimizer_state_restored"] is step["optimizer_executed"] is False
        no_authority(step)
    for value in (nested, generated): no_authority(value)


def test_receipt_prepared_contexts_precede_all_real_forwards_and_counts_do_not_add_observers(inference):
    events, report = inference["events"], inference["report"]
    forwards = [row for row in events if row["event"] == "trained_forward"]
    grus = [row for row in events if row["event"] == "gru_forward"]
    inner = [row for row in events if row["event"] == "trained_source_prepared"]
    assert len(inner) == 2 and all(len(row["outer_context_pairs_already_prepared"]) == 4
        and len(row["outer_receipt_ids_already_prepared"]) == 4 for row in inner)
    assert len(grus) == len(forwards) == 2 * report["counts"]["total_numerical_forward_count"] <= MAX_GRU_CALLS
    assert Counter(row["phase"] for row in forwards) == Counter(row["phase"] for row in grus)
    assert Counter(row["phase"] for row in forwards) == {"prepare": len(forwards) // 2, "validate": len(forwards) // 2}
    first = [row for row in forwards if row["phase"] == "prepare"]
    second = [row for row in forwards if row["phase"] == "validate"]
    assert [{key: value for key, value in row.items() if key not in ("phase", "generation_index", "model_index")} for row in first] == [
        {key: value for key, value in row.items() if key not in ("phase", "generation_index", "model_index")} for row in second]


def test_receipt_prepared_four_fresh_restores_cover_four_whole_generation_lifetimes(inference):
    events = inference["events"]
    started = [row for row in events if row["event"] == "prepared_generation_started"]
    completed = [row for row in events if row["event"] == "prepared_generation_completed"]
    constructed = [row for row in events if row["event"] == "model_constructed"]
    restored = [row for row in events if row["event"] == "model_weights_loaded"]
    assert len(started) == len(completed) == len(constructed) == len(restored) == 4
    assert [row["generation_index"] for row in started] == list(range(4))
    assert [row["generation_index"] for row in completed] == list(range(4))
    assert [row["model_index"] for row in constructed] == list(range(4))
    assert [row["model_index"] for row in restored] == list(range(4))
    assert [row["generation_index"] for row in constructed] == [row["generation_index"] for row in restored] == list(range(4))
    for phase in ("prepare", "validate"):
        assert sum(row["phase"] == phase for row in restored) == sum(row["phase"] == phase for row in started) == 2
    assert sum(row["numerical_forward_count"] for row in completed) == sum(row["event"] == "gru_forward" for row in events)
    for index, generation in enumerate(completed):
        scored = [row for row in events if row["event"] == "trained_forward" and row["generation_index"] == index]
        grus = [row for row in events if row["event"] == "gru_forward" and row["generation_index"] == index]
        assert len(scored) == len(grus) == generation["numerical_forward_count"]
        assert all(row["model_index"] == index for row in scored + grus)
        assert [row["prefix_ids"] for row in scored] == [row["prefix_ids"] for row in grus]
        assert scored[0]["prefix_ids"] == [1]
        assert all(len(right["prefix_ids"]) == len(left["prefix_ids"]) + 1
            and right["prefix_ids"][:-1] == left["prefix_ids"] for left, right in zip(scored, scored[1:]))
    assert all(1 <= row["numerical_forward_count"] <= MAX_NEW_TOKENS for row in completed)
    assert completed[0]["report_sha256"] == completed[1]["report_sha256"] == completed[2]["report_sha256"] == completed[3]["report_sha256"]
    assert all(row["preparation"]["model_restore_count"] == 1 for row in completed)
    assert len({row["state_sha256"] for row in restored}) == 1


def test_receipt_prepared_returned_full_report_is_detached(inference, retained):
    original = deepcopy((inference["case"], retained["requests"], retained["receipt"], retained["checkpoint"]))
    value, saved = inference["report"], deepcopy(inference["report"])
    try:
        value["source_conditionings"][0]["report"]["conditioning"][0] += .25
        value["mapping"]["outer_to_inner"][0] = None
        value["slots"][0]["id"] += ":modified-result"
        assert (inference["case"], retained["requests"], retained["receipt"], retained["checkpoint"]) == original
        assert inference["validated"] == saved
    finally:
        value.clear()
        value.update(saved)


def test_receipt_prepared_public_api_has_no_vector_target_reference_or_prefix_override():
    assert list(inspect.signature(subject.prepare_receipt_bound_prepared_source_generation_v2).parameters) == [
        "population_raw", "rows", "checkpoint", "expected_population_sha256", "expected_checkpoint_sha256",
        "max_new_tokens", "source_resolver"]


@pytest.mark.parametrize("pin", ["population", "checkpoint", "source", "catalog", "source_request", "receipt"])
def test_receipt_prepared_independent_pins_refuse_before_neural_work(retained, monkeypatch, pin):
    case, changes = authored_case(retained), {}
    if pin in ("population", "checkpoint"):
        changes["expected_" + pin + "_sha256"] = "0" * 64
    elif pin == "receipt":
        case["rows"][0]["receipt_ref"]["sha256"] = "0" * 64
    else:
        case["rows"][0]["expected_" + pin + "_sha256"] = "0" * 64
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained, **changes)


@pytest.mark.parametrize("damage", ["missing", "extra", "reordered", "duplicate", "population_order", "population_duplicate",
    "source_join", "catalog_join", "injected_conditioning", "injected_target"])
def test_receipt_prepared_whole_ordered_population_and_closed_rows(retained, monkeypatch, damage):
    case = authored_case(retained)
    if damage == "missing": case["rows"].pop()
    elif damage == "extra": case["rows"].append(deepcopy(case["rows"][0]))
    elif damage == "reordered": case["rows"].reverse()
    elif damage == "duplicate": case["rows"][2] = deepcopy(case["rows"][1])
    elif damage == "population_order":
        case["population"]["rows"].reverse()
        case["population_raw"] = wire(case["population"])
    elif damage == "population_duplicate":
        case["population"]["rows"][2] = deepcopy(case["population"]["rows"][1])
        case["population_raw"] = wire(case["population"])
    elif damage == "source_join":
        case["rows"][0]["source_raw"] += b" Changed caller source."
        case["rows"][0]["expected_source_sha256"] = sha(case["rows"][0]["source_raw"])
    elif damage == "catalog_join":
        case["rows"][0]["catalog_raw"] += b" "
        case["rows"][0]["expected_catalog_sha256"] = sha(case["rows"][0]["catalog_raw"])
    elif damage == "injected_conditioning": case["rows"][0]["conditioning"] = [0.] * 384
    else: case["rows"][0]["target_ids"] = [1, 2]
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained)


@pytest.mark.parametrize("budget", [True, 0, -1, 65, 1.0, None])
def test_receipt_prepared_sixty_four_token_bound_is_not_repaired(retained, monkeypatch, budget):
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(authored_case(retained), retained, max_new_tokens=budget)


@pytest.mark.parametrize("kind", ["empty", "invalid_utf8", "nul", "overbound"])
def test_receipt_prepared_final_outer_source_is_checked_before_any_generation(retained, monkeypatch, kind):
    raw = {"empty": b"", "invalid_utf8": b"\xff", "nul": b"source\x00text", "overbound": b"x" * 65537}[kind]
    case = authored_case(retained)
    row = case["rows"][-1]
    row["source_raw"] = raw
    row["expected_source_sha256"] = case["population"]["rows"][-1]["source_sha256"] = sha(raw)
    case["population_raw"] = wire(case["population"])
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained)


@pytest.mark.parametrize("damage", ["selected_input", "request_input", "occurrence", "physical_origin"])
def test_receipt_prepared_equal_text_does_not_replace_physical_identity(retained, monkeypatch, damage):
    case = authored_case(retained)
    row = case["rows"][1]
    if damage == "selected_input": row["input_id"] = case["rows"][2]["input_id"]
    elif damage == "request_input": row["source_request"]["input"]["input_id"] = case["rows"][2]["input_id"]
    elif damage == "occurrence": row["source_request"]["occurrence_id"] = case["rows"][2]["id"]
    else: row["source_request"]["input"]["source"]["byte_start"] += 1
    row["expected_source_request_sha256"] = digest(row["source_request"])
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained)


@pytest.mark.parametrize("damage", ["producer", "assets", "profile", "tokens", "vector_bits"])
def test_receipt_prepared_resealed_corrupt_receipt_is_not_native_producer_evidence(retained, monkeypatch, tmp_path, damage):
    case, value = authored_case(retained), deepcopy(retained["receipt"])
    if damage == "producer": value["producer"]["code_sha256"] = "0" * 64
    elif damage == "assets": value["model_assets"][0]["sha256"] = "0" * 64
    elif damage == "profile": value["execution"]["device"] = "cuda"
    elif damage == "tokens": value["results"][0]["tokens"]["attention_mask"][0] = True
    else:
        # Length/signature inconsistency is an invalid transport control, not
        # a claim that receipt hashes independently attest model computation.
        value["results"][0]["vector"]["bits"] = "00"
    path = tmp_path / "explicit-corrupt-receipt.json"
    write_new(path, receipt_wire(value))
    for row in case["rows"]: row["receipt_ref"] = reference(path)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained)


def test_receipt_prepared_resolver_mutation_refuses_without_neural_work(retained, monkeypatch):
    case, seen = authored_case(retained), []
    def changed(value):
        seen.append(deepcopy(value))
        case["rows"][-1]["source_request"]["occurrence_id"] += ":changed-during-resolver"
        return retained["resolver"](value)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained, source_resolver=changed)
    assert seen


def test_receipt_prepared_context_callback_cannot_change_an_original_catalog(retained, monkeypatch):
    case, seen = authored_case(retained), []
    original = contexts.prepare_source_context_v1
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        seen.append(result["status"])
        case["rows"][-1]["catalog_raw"] += b" "
        return result
    monkeypatch.setattr(contexts, "prepare_source_context_v1", changed)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(case, retained)
    assert seen


def test_receipt_prepared_source_callback_failure_propagates(retained, monkeypatch):
    case, failure = authored_case(retained), RuntimeError("authored receipt resolver failure")
    def refused(*args, **kwargs):
        raise failure
    forbid_numerical(monkeypatch)
    with pytest.raises(RuntimeError) as observed:
        prepare(case, retained, source_resolver=refused)
    assert observed.value is failure


@pytest.mark.parametrize("damage", ["outer_map", "inner_map", "inner_population", "receipt_index", "source_report", "authority", "training_mask", "encoder_flag"])
def test_receipt_prepared_resealed_pure_inventory_or_authority_forgery_refuses_before_replay(inference, retained, monkeypatch, damage):
    value = deepcopy(inference["report"])
    if damage == "outer_map": value["mapping"]["outer_to_inner"][1] = 2
    elif damage == "inner_map": value["mapping"]["inner_to_outer"].reverse()
    elif damage == "inner_population": value["inner_population"]["rows"].pop()
    elif damage == "receipt_index": value["source_conditionings"][1]["report"]["receipt_input_index"] = 2
    elif damage == "source_report": value["source_reports"][1]["report"]["status"] = "nominated"
    elif damage == "authority": value["authority"][next(iter(value["authority"]))] = True
    elif damage == "training_mask": value["training_mask"] = 1
    else: value["encoder_executed_by_adapter"] = True
    # This is an independently resealed offered report. The real public
    # validator must check its pure original-bound inventory before dispatch.
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        validate(value, inference["case"], retained)


def test_receipt_prepared_independent_report_pin_refuses_before_public_preparation(inference, retained, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("public preparation preceded independent offered report commitment")
    monkeypatch.setattr(subject, "_prepare", forbidden)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        validate(inference["report"], inference["case"], retained, expected_report_sha256="0" * 64)


@pytest.fixture(scope="module")
def serialized_unavailable(retained, tmp_path_factory):
    """Valid record-consistency control, never a producer-emitted disposition."""
    case, value = authored_case(retained), deepcopy(retained["receipt"])
    for row in value["results"][:3]:
        row.update(status="missing_input", tokens=None, vector=None)
    value["status_counts"] = {"embedded": 0, "missing_input": 3, "token_limit_exceeded": 1}
    directory = tmp_path_factory.mktemp("serialized-counterfactual-no-native-credit")
    path = directory / "counterfactual-missing-receipt.json"
    write_new(path, receipt_wire(value))
    for row in case["rows"]: row["receipt_ref"] = reference(path)
    with pytest.MonkeyPatch.context() as patch:
        forbid_numerical(patch)
        report = prepare(case, retained)
    label = {"schema": "legal-receipt-bound-serialized-counterfactual-control/v1",
        "serialized_counterfactual": True, "native_producer_emitted_these_dispositions": False,
        "positive_native_inference_evidence": False,
        "actual_native_status_counts": retained["receipt"]["status_counts"],
        "counterfactual_status_counts": value["status_counts"], "report": report}
    write_new(directory / "counterfactual-control.json", wire(label))
    return {"case": case, "report": report, "label": label}


def test_receipt_prepared_serialized_missing_and_overlimit_keep_all_rows_null_without_model(serialized_unavailable, retained, monkeypatch):
    report = serialized_unavailable["report"]
    forbid_numerical(monkeypatch)
    assert report["mapping"] == {"outer_to_inner": [None] * 4, "inner_to_outer": []}
    assert report["inner_population"] is report["inner_population_utf8"] is report["inner_population_sha256"] is None
    assert report["trained_source_report"] is None
    assert [row["embedding_status"] for row in report["slots"]] == ["missing_input"] * 3 + ["token_limit_exceeded"]
    assert [row["source_context_status"] for row in report["slots"]] == ["nominated", "ambiguous", "unavailable", "nominated"]
    assert all(row["inner_index"] is row["inner_slot"] is None for row in report["slots"])
    assert report["counts"]["selected"] == 4 and report["counts"]["embedded"] == report["counts"]["inner_selected"] == 0
    assert report["counts"]["missing_input"] == 3 and report["counts"]["token_limit_exceeded"] == 1
    assert report["counts"]["generated"] == report["counts"]["total_numerical_forward_count"] == 0
    assert report["checkpoint_preflight"]["checkpoint_inspection_performed"] is True
    assert report["model_executed"] is False
    for entry in report["source_conditionings"]:
        assert entry["report"]["conditioning"] is entry["report"]["conditioning_sha256"] is None
        assert entry["report"]["source_receipt_binding_verified"] is False
    assert validate(report, serialized_unavailable["case"], retained) == report
    assert serialized_unavailable["label"]["native_producer_emitted_these_dispositions"] is False
    no_authority(report)


@pytest.mark.parametrize("damage", ["drop_slot", "inner_slot", "reason", "denominator", "null_to_zero"])
def test_receipt_prepared_counterfactual_full_report_replay_refuses_resealed_result_forgery(serialized_unavailable, retained, monkeypatch, damage):
    value = deepcopy(serialized_unavailable["report"])
    if damage == "drop_slot": value["slots"].pop()
    elif damage == "inner_slot": value["slots"][0]["inner_slot"] = {"invented_generation": True}
    elif damage == "reason": value["slots"][0]["reason"] = "invented_permitted_generation"
    elif damage == "denominator": value["counts"]["selected"] = 3
    else: value["source_conditionings"][0]["report"]["conditioning"] = [0.] * 384
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        validate(value, serialized_unavailable["case"], retained)


def test_receipt_prepared_all_unavailable_still_refuses_invalid_complete_checkpoint(serialized_unavailable, retained, monkeypatch):
    broken = {**retained, "checkpoint": deepcopy(retained["checkpoint"])}
    broken["checkpoint"]["weights_sha256"] = "0" * 64
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(serialized_unavailable["case"], broken)


def test_receipt_prepared_final_serialization_cannot_hide_source_pin_change(serialized_unavailable, retained, monkeypatch):
    original, changed = subject._detach, []
    def mutate(value, maximum):
        result = original(value, maximum)
        if type(value) is dict and value.get("schema") == subject.SCHEMA:
            changed.append(True)
            monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
        return result
    monkeypatch.setattr(subject, "_detach", mutate)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError):
        prepare(serialized_unavailable["case"], retained)
    assert changed
