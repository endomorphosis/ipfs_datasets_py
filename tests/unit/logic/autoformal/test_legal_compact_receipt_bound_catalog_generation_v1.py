"""Finite receipt-to-catalog custody qualification; eight real GRU calls maximum.

One genuine retained native receipt supplies all conditioning. Authored catalogs
exercise engineering transport, not statutory meaning. A cached two-ID BOS
preparation and its public replay use one eligible row. The separate all-
ineligible selection keeps an unselected producer input and performs no model
work. No encoder, optimizer, training, provider or Lean execution is permitted.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import struct

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as contexts
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_trained_generation_v1 as continuation
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_source_binding_v1 as binding
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as runtime
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_receipt_bound_source_generation_v1 as legacy
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_receipt_source_inventory_v1 as inventory
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_receipt_bound_catalog_generation_v1 as subject
from ipfs_datasets_py.logic.syntax_core import signatures
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

MAX_FILE_BYTES = 4 * 1024 * 1024
CHECKPOINT_SHA = "0ba5bb1d941c83e4695b6ec7e971c042d6e0419f1dc8c24bfb5cc509b0c6bac0"


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


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
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append("forbidden productive path")
        pytest.fail("receipt reuse reached an encoder, optimizer, or training path")
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
    spelling = os.environ.get("LEGAL_COMPACT_RECEIPT_BOUND_CATALOG_FIXTURE")
    commitment = os.environ.get("LEGAL_COMPACT_RECEIPT_BOUND_CATALOG_FIXTURE_SHA256")
    assert spelling and commitment, "admission must supply the pinned retained native fixture; no fallback or skip"
    raw = snapshot(Path(spelling))
    assert sha(raw) == commitment
    packet = json.loads(raw)
    assert packet["schema"] == "legal-receipt-bound-catalog-fixture/v1"
    bodies = {row["path"]: read_reference(row) for row in packet["pin_files"]}
    assert len(bodies) == len(packet["pin_files"])
    def consume(ref):
        assert ref["path"] in bodies
        value = bodies[ref["path"]]
        assert len(value) == ref["bytes"] and sha(value) == ref["sha256"]
        return value
    fixture = json.loads(consume(packet["native_fixture"]))
    evidence = json.loads(consume(packet["native_evidence"]))
    qualification = json.loads(consume(packet["native_qualification"]))
    checkpoint = json.loads(consume(packet["checkpoint"]))
    receipt = json.loads(consume(packet["native_receipt"]))
    assert qualification["passed"] is True
    assert fixture["schema"] == "legal-compact-source-binding-native-fixture/v1"
    assert evidence["actual_native_producer_call_count"] == evidence["actual_encoder_forward_count"] == 1
    assert evidence["actual_untruncated_tokenization_call_count"] == 4
    assert evidence["training_executed"] is evidence["optimizer_executed"] is False
    assert evidence["native_receipt"] == packet["native_receipt"]
    assert evidence["input_fixture"] == packet["native_fixture"]
    assert receipt["inputs"] == evidence["receipt_inputs"]
    assert receipt["results"] == evidence["receipt_results"]
    assert receipt["status_counts"] == {"embedded": 3, "missing_input": 0, "token_limit_exceeded": 1}
    requests = fixture["embedded_requests"] + [fixture["oversized_request"]]
    assert requests == evidence["source_requests"] and len(requests) == 4
    assert [row["status"] for row in receipt["results"]] == ["embedded"] * 3 + ["token_limit_exceeded"]
    assert requests[1]["input"]["text"] == requests[2]["input"]["text"]
    assert requests[1]["input"]["source"] != requests[2]["input"]["source"]
    assert len({row["occurrence_id"] for row in requests}) == len({row["input"]["input_id"] for row in requests}) == 4
    assert sha(consume(packet["checkpoint"])) == digest(checkpoint) == packet["checkpoint_sha256"] == CHECKPOINT_SHA
    assert checkpoint["progress"]["optimizer_steps"] == 2
    index = {row["sha256"]: row for row in fixture["source_artifacts"]}
    assert fixture["source_artifacts"] == packet["source_artifacts"]
    def resolver(value):
        artifact = index[value["sha256"]]
        assert value == {key: artifact[key] for key in ("bytes", "sha256")}
        return Path(artifact["path"])
    return {"packet": packet, "packet_ref": reference(spelling), "checkpoint": checkpoint,
        "requests": requests, "receipt": receipt, "receipt_ref": packet["native_receipt"],
        "resolver": resolver, "bodies": bodies, "consume": consume}


def catalog(entries, identity):
    obj = signatures.LogicSort("Object")
    signature = signatures.LogicSignature(identity, family="tdfol", profile="tdfol_default",
        sorts=(obj,), symbols=tuple(signatures.declare_predicate(name, (obj, obj)) for name, _ in entries))
    return {"schema": "legal-compact-source-catalog/v1", "signature": signature.to_dict(),
        "argument_roles": [{"symbol": name, "roles": ["actor", "object"]} for name, _ in entries],
        "aliases": [{"symbol": name, "forms": list(forms)} for name, forms in entries]}


def authored_case(retained, selected=None):
    entries = [[("UnusedBefore", ("zz_no_match_before_zz",)), ("Transfer", ("transferred",)),
                ("Assign", ("assigned",)), ("UnusedAfter", ("zz_no_match_after_zz",))],
        [("Retain", ("retain",)), ("Inspect", ("retain",))],
        [("Unavailable", ("zz_no_matching_vocabulary_zz",))], [("Record", ("record",))]]
    rows = []
    for index, request in enumerate(retained["requests"]):
        raw = request["input"]["text"].encode("utf-8")
        catalog_raw = wire(catalog(entries[index], "receipt-catalog-authored-" + str(index)))
        rows.append({"id": request["occurrence_id"], "source_raw": raw, "catalog_raw": catalog_raw,
            "expected_source_sha256": sha(raw), "expected_catalog_sha256": sha(catalog_raw),
            "source_request": deepcopy(request), "expected_source_request_sha256": digest(request),
            "input_id": request["input"]["input_id"], "receipt_ref": deepcopy(retained["receipt_ref"])})
    if selected is not None:
        rows = [rows[index] for index in selected]
    population = {"schema": "legal-relational-batch-population/v1",
        "partition": "authored-receipt-bound-catalog-engineering",
        "selection_sha256": digest({"authored_selected_original_indices": list(range(4)) if selected is None else selected}),
        "rows": [{"id": row["id"], "source_sha256": row["expected_source_sha256"],
            "context_sha256": row["expected_catalog_sha256"]} for row in rows]}
    return {"population": population, "population_raw": wire(population) + b"\n", "rows": rows}


def prepare(case, retained, **changes):
    options = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_checkpoint_sha256": digest(retained["checkpoint"]), "max_new_tokens": 2,
        "source_resolver": retained["resolver"]}
    options.update(changes)
    return subject.prepare_receipt_bound_catalog_generation_v1(
        case["population_raw"], case["rows"], retained["checkpoint"], **options)


def validate(report, case, retained, **changes):
    options = {"expected_report_sha256": digest(report),
        "expected_population_sha256": sha(case["population_raw"]),
        "expected_checkpoint_sha256": digest(retained["checkpoint"]), "max_new_tokens": 2,
        "source_resolver": retained["resolver"]}
    options.update(changes)
    return subject.validate_receipt_bound_catalog_generation_v1(
        report, case["population_raw"], case["rows"], retained["checkpoint"], **options)


def forbid_numerical(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("pure refusal or ineligible population reached a model or numerical dispatch")
    monkeypatch.setattr(continuation, "generate_compact_catalog_trained_v1", forbidden)
    monkeypatch.setattr(runtime, "_forward", forbidden)
    monkeypatch.setattr(numerical, "_model", forbidden)
    monkeypatch.setattr(torch.nn.GRU, "forward", forbidden)


def retain_case(directory, retained, case, report, validation, events, kind, zero, parity):
    artifacts = {"population.json": case["population_raw"], "positive-report.json": wire(report),
        "validation.json": wire(validation), "observed-calls.json": wire(events),
        "consumed-fixture-packet.json": wire(retained["packet"])}
    declarations = []
    for index, row in enumerate(case["rows"]):
        source_name, catalog_name = str(index) + "-source.txt", str(index) + "-catalog.json"
        artifacts[source_name], artifacts[catalog_name] = row["source_raw"], row["catalog_raw"]
        declarations.append({key: value for key, value in row.items() if key not in ("source_raw", "catalog_raw")}
            | {"source_file": source_name, "catalog_file": catalog_name})
    artifacts["input-rows.json"] = wire(declarations)
    artifacts["zero-report.json"] = wire(zero["report"])
    artifacts["zero-validation.json"] = wire(zero["validation"])
    artifacts["zero-population.json"] = zero["case"]["population_raw"]
    artifacts["zero-input-rows.json"] = wire(declarations[1:])
    artifacts["old-pure-parity.json"] = wire(parity)
    scope = {"schema": "receipt-bound-catalog-qualification-scope/v1", "kind": kind,
        "selected": len(case["rows"]), "producer_receipt_input_count": 4,
        "eligible": report["counts"]["eligible"], "max_new_tokens": 2,
        "model_restore_count": sum(row["event"] == "model_restore" for row in events),
        "public_model_forward_count": sum(row["event"] == "trained_forward" for row in events),
        "actual_gru_forward_count": sum(row["event"] == "gru_forward" for row in events),
        "counts_overlap": True, "maximum_actual_gru_forward_count": 8 if kind == "mixed" else 0,
        "forward_count_by_outer_operation": {phase: sum(row["event"] == "gru_forward" and row["phase"] == phase
            for row in events) for phase in ("prepare", "validate")},
        "fresh_encoder_forwards": 0, "fresh_native_producer_calls": 0,
        "optimizer_allocations": 0, "optimizer_updates": 0, "training_calls": 0,
        "historical_checkpoint_optimizer_steps": 2, "complete_formula_required": False,
        "source_encoder_authenticated": False, "native_conditioning_training_compatibility_verified": False,
        "catalog_permission_verified": False, "statutory_accuracy_established": False,
        "comparison_credit": 0, "training_mask": 0, "evaluation_gold_mask": 0}
    artifacts["scope.json"] = wire(scope)
    descriptors = {}
    for name, raw in artifacts.items():
        path = directory / name
        write_new(path, raw)
        descriptors[name] = reference(path)
    manifest = {"schema": "legal-receipt-bound-catalog-fixture-evidence/v1", "artifacts": descriptors,
        "consumed_fixture": retained["packet_ref"], "checkpoint_sha256": CHECKPOINT_SHA,
        "native_receipt": retained["receipt_ref"], "summary": scope}
    path = directory / "manifest.json"
    write_new(path, wire(manifest))
    return reference(path)


@pytest.fixture(scope="module")
def inference(retained, tmp_path_factory, all_ineligible, content_parity):
    case, checkpoint = authored_case(retained), retained["checkpoint"]
    before = deepcopy((case, checkpoint))
    expected_pairs = {(row["expected_source_sha256"], row["expected_catalog_sha256"]) for row in case["rows"]}
    expected_ids = {row["id"] for row in case["rows"]}
    events, active, prepared_pairs, prepared_receipts, validated_pairs = [], {"phase": "prepare"}, set(), set(), set()
    original_conditioning, original_context = binding.prepare_compact_source_conditioning_v1, contexts.prepare_source_context_v1
    original_context_validation = contexts.validate_source_context_v1
    original_generation = continuation.generate_compact_catalog_trained_v1
    original_forward, original_gru, original_model = runtime._forward, torch.nn.GRU.forward, numerical._model
    def assert_prepared():
        assert prepared_pairs == validated_pairs == expected_pairs
        assert prepared_receipts == expected_ids
    def observe_conditioning(*args, **kwargs):
        result = original_conditioning(*args, **kwargs)
        prepared_receipts.add(result["occurrence_id"])
        events.append({"event": "source_receipt_prepared", "phase": active["phase"], "id": result["occurrence_id"],
            "status": result["status"], "receipt_input_index": result["receipt_input_index"], "report_sha256": digest(result)})
        return result
    def observe_context(*args, **kwargs):
        result = original_context(*args, **kwargs)
        pair = (kwargs["expected_source_sha256"], kwargs["expected_catalog_sha256"])
        prepared_pairs.add(pair)
        events.append({"event": "source_context_prepared", "phase": active["phase"], "source_sha256": pair[0],
            "catalog_sha256": pair[1], "status": result["status"]})
        return result
    def observe_context_validation(*args, **kwargs):
        result = original_context_validation(*args, **kwargs)
        pair = (kwargs["expected_source_sha256"], kwargs["expected_catalog_sha256"])
        validated_pairs.add(pair)
        events.append({"event": "source_context_validated", "phase": active["phase"], "source_sha256": pair[0],
            "catalog_sha256": pair[1], "status": result["status"]})
        return result
    def observe_generation(value, conditioning, prefix, context_raw, **kwargs):
        assert_prepared()
        assert prefix == [1] and kwargs["prefix_origin"] == "bos_seed"
        assert kwargs["catalog_context_origin"] == "caller_supplied_unverified"
        assert b"".join(struct.pack(">f", number) for number in conditioning).hex() == retained["receipt"]["results"][0]["vector"]["bits"]
        events.append({"event": "catalog_generation", "phase": active["phase"], "prefix_ids": list(prefix),
            "conditioning_sha256": digest(conditioning), "catalog_context_sha256": sha(context_raw),
            "prepared_ids": sorted(prepared_receipts), "validated_context_count": len(validated_pairs)})
        return original_generation(value, conditioning, prefix, context_raw, **kwargs)
    def observe_model(*args, **kwargs):
        assert_prepared()
        result = original_model(*args, **kwargs)
        events.append({"event": "model_restore", "phase": active["phase"]})
        assert sum(row["event"] == "model_restore" for row in events) <= 8
        return result
    def observe_forward(value, conditioning, prefix_ids):
        assert_prepared()
        active["prefix_ids"] = list(prefix_ids)
        result = original_forward(value, conditioning, prefix_ids)
        events.append({"event": "trained_forward", "phase": active["phase"], "prefix_ids": list(prefix_ids),
            "checkpoint_sha256": digest(value), "conditioning_sha256": digest(conditioning),
            "logits_sha256": digest(result["logits"]), "output_shape": result["output_shape"]})
        assert sum(row["event"] == "trained_forward" for row in events) <= 8
        return result
    def observe_gru(model, tensor, *args, **kwargs):
        assert_prepared()
        result = original_gru(model, tensor, *args, **kwargs)
        events.append({"event": "gru_forward", "phase": active["phase"], "prefix_ids": list(active["prefix_ids"]),
            "input_shape": list(tensor.shape), "output_shape": list(result[0].shape)})
        assert sum(row["event"] == "gru_forward" for row in events) <= 8
        return result
    rng, threads = torch.get_rng_state().clone(), torch.get_num_threads()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(binding, "prepare_compact_source_conditioning_v1", observe_conditioning)
        patch.setattr(contexts, "prepare_source_context_v1", observe_context)
        patch.setattr(contexts, "validate_source_context_v1", observe_context_validation)
        patch.setattr(continuation, "generate_compact_catalog_trained_v1", observe_generation)
        patch.setattr(runtime, "_forward", observe_forward)
        patch.setattr(numerical, "_model", observe_model)
        patch.setattr(torch.nn.GRU, "forward", observe_gru)
        report = prepare(case, retained)
        active["phase"] = "validate"
        prepared_pairs.clear()
        prepared_receipts.clear()
        validated_pairs.clear()
        validation = validate(report, case, retained)
    assert (case, checkpoint) == before
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == threads == 1
    directory = tmp_path_factory.getbasetemp() / "receipt-bound-catalog-v1"
    directory.mkdir()
    manifest = retain_case(directory, retained, case, report, validation, events, "mixed", all_ineligible, content_parity)
    return {"case": case, "report": report, "validation": validation, "events": events, "manifest": manifest}


@pytest.fixture(scope="module")
def all_ineligible(retained):
    case = authored_case(retained, [1, 2, 3])
    with pytest.MonkeyPatch.context() as patch:
        forbid_numerical(patch)
        report = prepare(case, retained)
        validation = validate(report, case, retained)
    return {"case": case, "report": report, "validation": validation}


def test_genuine_native_receipt_full_population_and_exact_vector_bits(inference, retained, record_property):
    record_property("receipt_bound_catalog_fixture_manifest", json.dumps(inference["manifest"], sort_keys=True))
    report, case = inference["report"], inference["case"]
    assert report["population"] == case["population"] and report["population_sha256"] == sha(case["population_raw"])
    assert report["checkpoint_sha256"] == CHECKPOINT_SHA
    source = report["source_inventory"]
    assert source["population"] == case["population"]
    assert len(source["receipt_inventory"]) == 1
    producer_inventory = source["receipt_inventory"][0]
    assert producer_inventory["receipt"] == retained["receipt_ref"]
    assert producer_inventory["inputs"] == retained["receipt"]["inputs"] and producer_inventory["input_count"] == 4
    assert producer_inventory["status_counts"] == retained["receipt"]["status_counts"]
    assert [row["input_id"] for row in producer_inventory["results"]] == [row["input_id"] for row in retained["receipt"]["results"]]
    assert [row["id"] for row in source["source_conditionings"]] == [row["id"] for row in case["rows"]]
    for index, item in enumerate(source["source_conditionings"]):
        value = item["report"]
        assert value["receipt_input_index"] == index and value["receipt_input_count"] == 4
        assert value["input_id"] == retained["requests"][index]["input"]["input_id"]
        assert value["native_vector"] == retained["receipt"]["results"][index]["vector"]
        if index < 3:
            assert b"".join(struct.pack(">f", number) for number in value["conditioning"]).hex() == value["native_vector"]["bits"]
        else:
            assert value["conditioning"] is value["conditioning_sha256"] is None
        no_authority(value)
    assert report["counts"]["selected"] == 4 and report["counts"]["eligible"] == 1
    assert subject.receipt_bound_catalog_generation_sha256(report) == digest(report)
    no_authority(report)


def test_nomination_order_full_catalog_exclusions_and_wrapper_identity(inference):
    report, case = inference["report"], inference["case"]
    source = report["source_inventory"]["source_reports"]
    assert [row["report"]["status"] for row in source] == ["nominated", "ambiguous", "unavailable", "nominated"]
    nominated = source[0]["report"]
    assert nominated["selected_symbols"] == ["Transfer", "Assign"]
    assert nominated["excluded_symbols"] == ["UnusedBefore", "UnusedAfter"]
    assert nominated["index_mapping"] == [{"symbol": "Transfer", "catalog_index": 1, "selected_index": 0},
        {"symbol": "Assign", "catalog_index": 2, "selected_index": 1}]
    assert [row["form"] for row in nominated["matches"]] == ["assigned", "transferred"]
    for index, row in enumerate(report["catalog_inventory"]):
        assert row["id"] == case["rows"][index]["id"]
        assert row["source_report_sha256"] == source[index]["report_sha256"]
        assert row["eligible"] is (index == 0)
        if row["catalog_context_utf8"] is not None:
            assert sha(row["catalog_context_utf8"].encode()) == row["catalog_context_sha256"]
            assert row["catalog_context_sha256"] != case["population"]["rows"][index]["context_sha256"]
            assert sha(row["signature_utf8"].encode()) == row["signature_sha256"]
            assert sha(row["argument_roles_utf8"].encode()) == row["argument_roles_sha256"]
            signature = json.loads(row["signature_utf8"])
            assert signature.pop("signature_id") == "receipt-bound-catalog-inference-v1"
            assert signature == source[index]["report"]["context"]["signature"]
            assert json.loads(row["argument_roles_utf8"]) == source[index]["report"]["context"]["argument_roles"]
            assert json.loads(row["catalog_context_utf8"])["catalog"] == source[index]["report"]["context"]
        else:
            assert row["catalog_context_sha256"] is None
    wrapper = json.loads(report["catalog_inventory"][0]["catalog_context_utf8"])
    assert [row["name"] for row in wrapper["catalog"]["signature"]["symbols"]] == ["Transfer", "Assign"]


def test_original_bos_and_adapter_replay_are_counted_once(inference):
    report, validation = inference["report"], inference["validation"]
    assert report["counts"]["generated"] == sum(row["status"] == "generated" for row in report["slots"]) == 1
    assert report["counts"]["abstained"] == sum(row["status"] == "abstained" for row in report["slots"]) == 3
    assert sum(row["generation"] is not None for row in report["slots"]) == 1
    assert report["counts"]["original_numerical_forward_count"] == 2
    assert report["counts"]["adapter_replay_numerical_forward_count"] == 2
    assert report["counts"]["total_numerical_forward_count"] == 4
    assert validation["generation_report"] == report
    assert validation["original_forward_count"] == 0
    assert validation["replay_forward_count"] == validation["numerical_forward_count"] == 4
    assert validation["original_generation_forward_count"] == 4
    calls = Counter(row["event"] for row in inference["events"])
    assert calls["trained_forward"] == calls["gru_forward"] == calls["model_restore"] == 8
    assert Counter(row["phase"] for row in inference["events"] if row["event"] == "gru_forward") == {"prepare": 4, "validate": 4}
    first = report["slots"][0]
    assert first["generation"] is not None and first["adapter"] is not None
    assert first["generation"]["initial_prefix_ids"] == [1]
    assert first["generation"]["prefix_origin"] == "bos_seed"
    assert first["generation"]["catalog_context_origin"] == "caller_supplied_unverified"
    assert all(row["generation"] is row["adapter"] is None for row in report["slots"][1:])


def test_every_source_disposition_is_prepared_and_replayed_before_model_restore(inference):
    for event in inference["events"]:
        if event["event"] == "catalog_generation":
            assert event["validated_context_count"] == 4
            assert set(event["prepared_ids"]) == {row["id"] for row in inference["case"]["rows"]}
    assert [row["embedding_status"] for row in inference["report"]["slots"]] == ["embedded"] * 3 + ["token_limit_exceeded"]
    assert [row["source_context_status"] for row in inference["report"]["slots"]] == ["nominated", "ambiguous", "unavailable", "nominated"]
    assert [row["index"] for row in inference["report"]["slots"]] == list(range(4))


def test_full_batch_denominator_retains_raw_dispositions_without_provenance_credit(inference):
    report = inference["report"]
    predictions, evaluation = report["predictions"], report["batch_evaluation"]
    expected_ids = [row["id"] for row in report["population"]["rows"]]
    assert [row["id"] for row in predictions["rows"]] == expected_ids
    assert predictions["generation"]["kind"] == "decoder_declared"
    assert predictions["generation"]["encoder_sha256"] is None
    assert [row["status"] for row in predictions["rows"]] == ["generated"] + ["abstained"] * 3
    assert evaluation["population"]["ordered_ids"] == expected_ids
    assert evaluation["coverage"]["expected_count"] == evaluation["coverage"]["prediction_row_count"] == 4
    assert evaluation["coverage"]["missing_ids"] == []
    assert evaluation["coverage"]["duplicate_ids"] == {}
    assert evaluation["terminal_counts"]["unverifiable_generation"] == 4
    assert sum(evaluation["terminal_counts"].values()) == 4
    assert [row["declared_status"] for row in evaluation["observation_ledger"]] == ["generated"] + ["abstained"] * 3
    assert evaluation["reference_availability"] == {"available": 0, "unavailable": 4, "total": 4, "fraction": 0.0}
    assert report["counts"]["comparison_credit"] == report["counts"]["comparison_eligible"] == 0
    no_authority(evaluation)


def test_equal_text_physical_occurrences_are_not_deduplicated(inference):
    report = inference["report"]
    a, b = report["source_inventory"]["source_conditionings"][1:3]
    assert a["report"]["input"]["text"] == b["report"]["input"]["text"]
    assert a["id"] != b["id"] and a["report"]["input_id"] != b["report"]["input_id"]
    assert a["report"]["source_span"] != b["report"]["source_span"]
    assert a["report"]["native_vector"] == b["report"]["native_vector"]
    assert report["slots"][1]["source_context_status"] == "ambiguous"
    assert report["slots"][2]["source_context_status"] == "unavailable"


def test_all_ineligible_retains_outside_window_input_and_zero_model_work(all_ineligible, retained):
    report, validation = all_ineligible["report"], all_ineligible["validation"]
    assert report["counts"]["selected"] == 3 and report["counts"]["eligible"] == report["counts"]["generated"] == 0
    assert report["counts"]["abstained"] == 3
    assert all(report["counts"][key] == 0 for key in ("original_numerical_forward_count", "adapter_replay_numerical_forward_count", "total_numerical_forward_count"))
    assert report["source_inventory"]["checkpoint_preflight"]["checkpoint_inspection_performed"] is True
    producer_inventory = report["source_inventory"]["receipt_inventory"][0]
    assert producer_inventory["inputs"] == retained["receipt"]["inputs"] and producer_inventory["input_count"] == 4
    assert len(report["slots"]) == 3
    assert retained["requests"][0]["occurrence_id"] not in {row["id"] for row in report["slots"]}
    assert [row["report"]["receipt_input_index"] for row in report["source_inventory"]["source_conditionings"]] == [1, 2, 3]
    assert all(row["generation"] is row["adapter"] is None for row in report["slots"])
    assert validation["generation_report"] == report
    assert validation["original_forward_count"] == validation["replay_forward_count"] == validation["numerical_forward_count"] == 0
    no_authority(report)


@pytest.fixture(scope="module")
def content_parity(retained):
    packet = retained["packet"]
    old = {name: retained["consume"](ref) for name, ref in packet["content_artifacts"].items()}
    declarations = json.loads(old["input-rows.json"])
    rows = []
    for declaration in declarations:
        row = {key: value for key, value in declaration.items() if key not in ("source_file", "catalog_file")}
        row["source_raw"], row["catalog_raw"] = old[declaration["source_file"]], old[declaration["catalog_file"]]
        rows.append(row)
    checkpoint = json.loads(retained["consume"](packet["content_checkpoint"]))
    original_report = json.loads(old["positive-report.json"])
    data = legacy._inputs(old["population.json"], rows, checkpoint, sha(old["population.json"]), digest(checkpoint), 12)
    with pytest.MonkeyPatch.context() as patch:
        forbid_numerical(patch)
        pure = legacy._operation(data, retained["resolver"], lambda data, loaded, fence, references, source_checks, frozen:
            inventory._prepare_inventory(data, loaded, fence, references, source_checks, frozen, retained["resolver"])[0])
    expected = {key: original_report[key] for key in legacy._PURE_FIELDS}
    assert pure == expected
    return {"schema": "receipt-source-pure-inventory-content-differential/v1",
        "actual": pure, "expected": expected, "byte_equal": wire(pure) == wire(expected),
        "original_report": packet["content_artifacts"]["positive-report.json"],
        "original_checkpoint": packet["content_checkpoint"], "model_forwards": 0,
        "encoder_forwards": 0, "optimizer_updates": 0, "comparison_credit": 0}


def test_pure_inventory_factor_matches_retained_content_report_without_content_generation(content_parity):
    assert content_parity["byte_equal"] is True
    assert content_parity["actual"] == content_parity["expected"]
    assert content_parity["model_forwards"] == content_parity["encoder_forwards"] == content_parity["optimizer_updates"] == 0


def test_public_api_has_no_target_prefix_vector_or_catalog_override():
    common = ["population_raw", "rows", "checkpoint", "expected_population_sha256", "expected_checkpoint_sha256", "max_new_tokens", "source_resolver"]
    assert list(inspect.signature(subject.prepare_receipt_bound_catalog_generation_v1).parameters) == common
    assert list(inspect.signature(subject.validate_receipt_bound_catalog_generation_v1).parameters) == ["report", *common[:3], "expected_report_sha256", *common[3:]]


@pytest.mark.parametrize("pin", ["population", "checkpoint", "source", "catalog", "source_request", "receipt"])
def test_independent_input_pins_refuse_before_neural_work(retained, monkeypatch, pin):
    case, changes = authored_case(retained), {}
    if pin in ("population", "checkpoint"):
        changes["expected_" + pin + "_sha256"] = "0" * 64
    elif pin == "receipt": case["rows"][0]["receipt_ref"]["sha256"] = "0" * 64
    else: case["rows"][0]["expected_" + pin + "_sha256"] = "0" * 64
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(case, retained, **changes)


@pytest.mark.parametrize("damage", ["omit", "duplicate", "reverse", "extra_field", "free_vector", "target", "source_id", "input_id"])
def test_closed_whole_population_and_physical_input_joins(retained, monkeypatch, damage):
    case = authored_case(retained)
    if damage == "omit": case["rows"].pop()
    elif damage == "duplicate": case["rows"][2] = deepcopy(case["rows"][1])
    elif damage == "reverse": case["rows"].reverse()
    elif damage == "extra_field": case["rows"][0]["undeclared"] = None
    elif damage == "free_vector": case["rows"][0]["conditioning"] = [0.] * 384
    elif damage == "target": case["rows"][0]["target"] = "unpermitted"
    elif damage == "source_id":
        case["rows"][0]["source_request"]["occurrence_id"] = "replacement"
        case["rows"][0]["expected_source_request_sha256"] = digest(case["rows"][0]["source_request"])
    else: case["rows"][0]["input_id"] = retained["requests"][1]["input"]["input_id"]
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(case, retained)


@pytest.mark.parametrize("budget", [0, 13, True, 1.0])
def test_exact_integer_token_budget_refuses_without_repair(retained, monkeypatch, budget):
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(authored_case(retained), retained, max_new_tokens=budget)


@pytest.mark.parametrize("damage", ["source_bytes", "physical_offset", "catalog_order", "catalog_alias"])
def test_last_selected_source_and_catalog_refuse_before_any_model(retained, monkeypatch, damage):
    case = authored_case(retained)
    row = case["rows"][-1]
    if damage == "source_bytes": row["source_raw"] += b" changed"
    elif damage == "physical_offset":
        row["source_request"]["input"]["source"]["byte_start"] += 1
        row["expected_source_request_sha256"] = digest(row["source_request"])
    else:
        row = case["rows"][0]
        value = json.loads(row["catalog_raw"])
        if damage == "catalog_order": value["signature"]["symbols"].reverse()
        else: value["aliases"][0]["forms"] = ["assigned"]
        row["catalog_raw"] = wire(value)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(case, retained)


def test_source_resolver_failure_preserves_original_exception(retained, monkeypatch):
    failure = RuntimeError("authored source resolver failure")
    def resolver(value): raise failure
    forbid_numerical(monkeypatch)
    with pytest.raises(RuntimeError) as seen: prepare(authored_case(retained), retained, source_resolver=resolver)
    assert seen.value is failure


def test_source_resolver_cannot_mutate_original_catalog(retained, monkeypatch):
    case, changed = authored_case(retained), []
    def resolver(value):
        if not changed:
            case["rows"][-1]["catalog_raw"] += b" "
            changed.append(True)
        return retained["resolver"](value)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(case, retained, source_resolver=resolver)
    assert changed


def test_original_owner_mutation_during_callback_refuses(retained, monkeypatch):
    changed = []
    def resolver(value):
        if not changed:
            monkeypatch.setattr(contexts, "_SELF_SHA", "0" * 64)
            changed.append(True)
        return retained["resolver"](value)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(authored_case(retained), retained, source_resolver=resolver)
    assert changed


@pytest.mark.parametrize("damage", ["source_map", "receipt_index", "context", "catalog", "authority", "training_mask"])
def test_resealed_pure_inventory_forgery_refuses_before_replay(inference, retained, monkeypatch, damage):
    value = deepcopy(inference["report"])
    if damage == "source_map": value["source_inventory"]["mapping"]["outer_to_inner"][0] = None
    elif damage == "receipt_index": value["source_inventory"]["source_conditionings"][1]["report"]["receipt_input_index"] = 2
    elif damage == "context": value["source_inventory"]["source_reports"][0]["report"]["selected_symbols"].reverse()
    elif damage == "catalog": value["catalog_inventory"][0]["catalog_context_utf8"] += " "
    elif damage == "authority": value["authority"][next(iter(value["authority"]))] = True
    else: value["training_mask"] = False
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): validate(value, inference["case"], retained)


def test_independent_outer_report_pin_refuses_before_public_replay(inference, retained, monkeypatch):
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): validate(inference["report"], inference["case"], retained, expected_report_sha256="0" * 64)


def test_all_ineligible_still_inspects_complete_checkpoint(all_ineligible, retained, monkeypatch):
    altered = {**retained, "checkpoint": deepcopy(retained["checkpoint"])}
    altered["checkpoint"]["weights_sha256"] = "0" * 64
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(all_ineligible["case"], altered)


def test_whole_report_preparation_bound_refuses_before_model(retained, monkeypatch):
    monkeypatch.setattr(subject, "MAX_REPORT_BYTES", 1)
    forbid_numerical(monkeypatch)
    with pytest.raises(ValueError): prepare(authored_case(retained), retained)


def test_report_is_detached_from_original_inputs(inference, retained):
    before = deepcopy((inference["case"], retained["requests"], retained["receipt"], retained["checkpoint"]))
    value = inference["report"]
    saved = deepcopy(value)
    try:
        value["source_inventory"]["source_conditionings"][0]["report"]["conditioning"][0] += 0.25
        value["population"]["rows"].pop()
        assert (inference["case"], retained["requests"], retained["receipt"], retained["checkpoint"]) == before
        assert len(inference["case"]["population"]["rows"]) == 4
    finally:
        value.clear()
        value.update(saved)
    assert digest(value) == digest(saved)
