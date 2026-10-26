"""Pure native4096 span-custody tests with an explicitly doubled issuance boundary.

The genuine live-result reader and completed-source adapter run unchanged.
Only the private native issuance registry is doubled; the vectors and execution
observations are fictional and do not establish actual native forward execution,
statutory fidelity or numerical consumer support. No native/model calls run.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import pickle
import threading

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_4096_full_owner as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_native4096_binding as subject


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return base._guard(value).sha256


@pytest.fixture(autouse=True)
def prohibit_native_execution(monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("completed source receipt control attempted native execution")
    monkeypatch.setattr(owner, "run_full_forward", forbidden)
    monkeypatch.setattr(owner.vocab, "run_vocab_probe", forbidden)
    monkeypatch.setattr(owner.subprocess, "Popen", forbidden)


@pytest.fixture
def issued_native(monkeypatch):
    rows = [{"id": "fictional-agency", "source_text": "The agency shall disclose records."},
            {"id": "fictional-board", "source_text": "The board may retain notices."}]
    producer = {"profile": owner.PROFILE, "model_sha256": "a" * 64,
        "worker_sha256": "b" * 64, "worker_source_sha256": "c" * 64,
        "owner_source_sha256": _sha_file(owner.__file__),
        "vocabulary_owner_source_sha256": _sha_file(owner.vocab.__file__),
        "library_sha256": {"/native/libllama.so": "d" * 64}}
    own = {"pid": os.getpid(), "thread_id": threading.get_native_id()}
    identity = {"device": 1, "inode": 2, "bytes": 3, "mtime_ns": 4, "ctime_ns": 5}
    maps = {"/native/worker": {"identity": deepcopy(identity), "sha256": None},
        "/native/libllama.so": {"identity": deepcopy(identity), "sha256": "d" * 64}}
    geometry = {"native_input_dimension": 4096, "native_output_dimension": 4096,
        "metadata_architecture": "deepseek2", "metadata_embedding_length": 4096,
        "metadata_embedding_length_out": None, "metadata_embedding_length_key": "deepseek2.embedding_length",
        "metadata_embedding_length_out_key": "deepseek2.embedding_length_out", "vocabulary_size": 131072,
        "actual_context": 512, "actual_batch": 512, "actual_ubatch": 512, "actual_sequences": 1,
        "actual_pooling": "last", "context_created": True}
    observed = []
    for number, row in enumerate(rows):
        vector = [0.] * 4096
        vector[number] = 1.
        observed.append({**row, "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "embedding": vector, "token_ids": [1, 40 + number, 2], "token_count": 3,
            "native_tokens_evaluated": 3, "normalized_l2_norm": 1., "raw_output_l2_norm": 2.,
            "geometry": deepcopy(geometry)})
    nonce = "e" * 64
    request = {"schema": "native-source4096-worker-request/v1", "nonce": nonce, "rows": rows}
    receipt = {"schema": owner.SCHEMA, "complete": True, "owner": own,
        "child": {"pid": 9001, "birth": "9002", "parent_pid": own["pid"], "group_pid": 9001},
        "operation_nonce": nonce, **{key: producer[key] for key in producer if key != "library_sha256"},
        "model_file_identity": deepcopy(identity), "model_content_hash_verified": True,
        "model_content_hash_seconds": .5, "full_forward_executed": True, "native_tokens_evaluated": 6,
        "vectors_produced": 2, "dimension": 4096,
        "request_sha256": hashlib.sha256(owner._wire(request) + b"\n").hexdigest(),
        "protocol": {"entry_sha256": "1" * 64, "authorization_sha256": "2" * 64,
            "entry_mappings": maps, "closing_sha256": "3" * 64, "closing_ack_sha256": "4" * 64,
            "closing_mappings": deepcopy(maps), "exit_observed": True},
        "resource_cgroup": {"memory_max_bytes": 8 * 1024**3, "memory_swap_max_bytes": 0,
            "memory_oom_group": 1, "pids_max": 8, "only_owner_after_exit": True},
        "sampled_native_child_max_rss_bytes": 4096, "sampled_owner_max_rss_bytes": 8192,
        "sampled_combined_max_rss_bytes": 12288, "rss_observation_count": 2,
        "combined_owner_child_rss_limit_bytes": 8 * 1024**3, "rss_scope": "synthetic owner-boundary double",
        "native_child_elapsed_seconds": .1, "elapsed_seconds": .7, "sample_count": 2,
        "cleanup": {"leader_reaped": True, "returncode": 0, "live_group_processes": 0},
        "wall_time_scope": "synthetic owner-boundary double", "bridge_names": [],
        "legal_ir_evaluate_provers": False, "metric_disk_cache_used": False,
        "workers": 1, "temperature": 0, "context_tokens": 512,
        "operating_system_page_cache": "uncontrolled", "training_executed": False,
        "qualified": False, "admitted": False, "proof_authority": False,
        "source_semantics_verified": False, "native_service_mutated": False,
        "downloads_performed": False, "persisted_receipt_is_execution_authority": False,
        "rows": observed}
    result = owner.VerifiedForwardResult(owner._TOKEN)
    case = {"rows": rows, "producer": producer, "receipt": receipt, "native": result}

    def issue(value=None):
        selected = receipt if value is None else value
        raw = owner._wire(selected)
        # Explicitly controlled private native boundary. Caller-facing JSON
        # and unissued handles remain unable to enter the real live reader.
        monkeypatch.setitem(owner._ISSUED, result, {"owner": own,
            "owner_source_sha256": producer["owner_source_sha256"], "serialized": raw,
            "receipt_sha256": hashlib.sha256(raw + b"\n").hexdigest()})
    case["issue"] = issue
    issue()
    return case


def _case(native, operation="training"):
    atoms = (("O", "agency", "disclose", "records"), ("P", "board", "retain", "notices"))
    rows = [{**source, "canonical_ir": {"rules": [{"modality": modality, "actor": actor,
        "action": action, "object": obj, "conditions": [], "exceptions": [], "temporal": []}]}}
        for source, (modality, actor, action, obj) in zip(native["rows"], atoms)]
    manifest = splits.LegalIRSplitManifest(examples=tuple(
        splits.LegalIRSplitExample.from_sample({"sample_id": r["id"], "text": r["source_text"]}) for r in rows),
        assignments={r["id"]: "train" if operation == "training" else "validation" for r in rows},
        config_digest="a" * 64).to_dict()
    eligibility, exposure = [], []
    for row in rows:
        exact = {"id": row["id"], "source_text_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                 "canonical_ir_sha256": digest(row["canonical_ir"])}
        eligibility.append({**exact, "target_origin": "authored_engineering_fixture", "status": "eligible",
            "allowed_operations": [operation], "reason": "Fictional custody fixture; no reviewed legal meaning."})
        exposure.append({**exact, "target_exposure": "declared_supervised_training" if operation == "training"
            else "declared_validation_scoring", "provenance_ref": "fixture:fictional-native4096"})
    return rows, dict(expected_rows_sha256=digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=digest(manifest), eligibility_records=eligibility,
        expected_eligibility_sha256=digest(eligibility), exposure_records=exposure,
        expected_exposure_sha256=digest(exposure), operation=operation, native_result=native["native"],
        expected_producer=deepcopy(native["producer"]), expected_producer_sha256=digest(native["producer"]),
        expected_native_receipt_sha256=hashlib.sha256(owner._wire(native["receipt"]) + b"\n").hexdigest())


def _validation(options):
    return {key: options[key] for key in ("split_manifest", "eligibility_records", "exposure_records",
                                         "native_result", "expected_producer")}


def _prepare(native, operation="training"):
    rows, options = _case(native, operation)
    return subject.prepare_native4096_span_binding(rows, **options), rows, options


@pytest.mark.parametrize("operation", ["training", "hparam_selection"])
def test_exact_native_contexts_join_whole_eligible_batch_without_enabling_numeric_consumers(issued_native, operation):
    binding, rows, options = _prepare(issued_native, operation)
    receipt = binding.receipt()
    contexts = [{"id": row["id"], "source_sha256": row["source_sha256"], "context": row["embedding"]}
                for row in issued_native["receipt"]["rows"]]
    assert receipt["status"] == "ready" and receipt["row_count"] == receipt["ready_row_count"] == 2
    assert receipt["rows_discarded"] == receipt["blocked_row_count"] == 0
    assert receipt["context_contract"] == {"dimension": 4096,
        "representation_id": issued_native["producer"]["profile"],
        "producer_sha256": digest(issued_native["producer"]), "training_index_sha256": digest(contexts)}
    for field in ("numerical_consumer_supported", "native_training_enabled", "training_executed",
                  "semantic_authority", "training_gold_authority", "evaluation_gold_authority"):
        assert receipt[field] is False
    original = deepcopy(rows)
    received = []
    marker = object()

    def consume(detached):
        received.append(deepcopy(detached))
        detached[0]["latent"].clear()
        detached[0]["canonical_ir"]["rules"][0]["modality"] = "F"
        return marker

    assert subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=consume) is marker
    assert received == [[{**row, "latent": native["embedding"]}
                         for row, native in zip(rows, issued_native["receipt"]["rows"])]]
    assert rows == original
    receipt.clear()
    assert binding.receipt()["status"] == "ready"
    assert subject.validate_native4096_span_binding(binding, rows, **_validation(options)) == binding.receipt()


def test_context_identity_excludes_targets_while_whole_binding_pins_targets(issued_native):
    first, rows, options = _prepare(issued_native)
    rows[0]["canonical_ir"]["rules"][0]["modality"] = "P"
    options["expected_rows_sha256"] = digest(rows)
    for field in ("eligibility", "exposure"):
        options[field + "_records"][0]["canonical_ir_sha256"] = digest(rows[0]["canonical_ir"])
        options["expected_" + field + "_sha256"] = digest(options[field + "_records"])
    second = subject.prepare_native4096_span_binding(rows, **options)
    assert first.receipt()["context_contract"] == second.receipt()["context_contract"]
    assert first.receipt()["input_sha256s"]["rows"] != second.receipt()["input_sha256s"]["rows"]
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.validate_native4096_span_binding(first, rows, **_validation(options))


@pytest.mark.parametrize("field", ["expected_rows_sha256", "expected_split_manifest_sha256",
    "expected_eligibility_sha256", "expected_exposure_sha256", "expected_producer_sha256",
    "expected_native_receipt_sha256"])
def test_independent_expected_commitments_are_required(issued_native, field):
    rows, options = _case(issued_native)
    options[field] = "0" * 64
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


@pytest.mark.parametrize("field", ["profile", "model_sha256", "worker_sha256", "worker_source_sha256",
    "owner_source_sha256", "vocabulary_owner_source_sha256", "library_sha256"])
def test_rehashing_a_different_producer_does_not_relabel_native_output(issued_native, field):
    rows, options = _case(issued_native)
    options["expected_producer"][field] = (owner.RECLAIM_PROFILE if field == "profile" else
        {"/native/another.so": "f" * 64} if field == "library_sha256" else "f" * 64)
    options["expected_producer_sha256"] = digest(options["expected_producer"])
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


@pytest.mark.parametrize("damage", ["source", "target", "eligibility", "exposure", "split", "producer"])
def test_mutated_offered_inputs_are_rejected_before_callback(issued_native, damage):
    binding, rows, options = _prepare(issued_native)
    if damage == "source": rows[0]["source_text"] += " changed"
    elif damage == "target": rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif damage == "eligibility": options["eligibility_records"][0]["status"] = "ineligible"
    elif damage == "exposure": options["exposure_records"][0]["target_exposure"] = "unknown"
    elif damage == "split": options["split_manifest"]["assignments"][rows[0]["id"]] = "holdout"
    else: options["expected_producer"]["model_sha256"] = "f" * 64
    calls = []
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=calls.append)
    assert calls == []


@pytest.mark.parametrize("reason", ["ineligible", "unknown", "holdout", "exposure", "operation", "grammar"])
def test_blocked_row_prevents_all_dispatch_and_is_never_filtered(issued_native, reason):
    rows, options = _case(issued_native)
    if reason in ("ineligible", "unknown"):
        options["eligibility_records"][0]["status"] = reason
    elif reason == "holdout":
        manifest = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
        manifest.assignments[rows[0]["id"]] = "holdout"
        options["split_manifest"] = manifest.to_dict()
    elif reason == "exposure":
        options["exposure_records"][0]["target_exposure"] = "unknown"
    elif reason == "operation":
        options["eligibility_records"][0]["allowed_operations"] = []
    else:
        rows[0]["canonical_ir"]["rules"][0]["actor"] = "unsupported non-source actor"
        for field in ("eligibility_records", "exposure_records"):
            options[field][0]["canonical_ir_sha256"] = digest(rows[0]["canonical_ir"])
    for field, value in (("rows", rows), ("split_manifest", options["split_manifest"]),
            ("eligibility", options["eligibility_records"]), ("exposure", options["exposure_records"])):
        options["expected_" + field + "_sha256"] = digest(value)
    binding = subject.prepare_native4096_span_binding(rows, **options)
    receipt = binding.receipt()
    assert receipt["status"] == "blocked" and receipt["row_count"] == 2
    assert receipt["rows_discarded"] == 0 and receipt["blocked_row_count"] >= 1
    calls = []
    with pytest.raises(subject.Native4096SpanBindingError) as error:
        subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=calls.append)
    assert error.value.receipt["status"] == "blocked" and calls == []


def test_native_capability_cannot_admit_reviewed_statutory_origin(issued_native):
    rows, options = _case(issued_native)
    options["eligibility_records"][0]["target_origin"] = "reviewed_statutory"
    options["expected_eligibility_sha256"] = digest(options["eligibility_records"])
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


@pytest.mark.parametrize("damage", ["source_bytes", "source_order", "missing_source", "missing_tokens",
    "unevaluated_tokens", "wrong_width", "wrong_norm", "boolean_vector", "vector_source_swap", "unfinished",
    "no_forward", "unfinished_exit", "unreleased_child", "unreleased_scope", "authority", "library_swap"])
def test_independently_rehashed_incomplete_private_issuance_is_still_rejected(issued_native, damage):
    rows, options = _case(issued_native)
    receipt = deepcopy(issued_native["receipt"])
    if damage == "source_bytes": receipt["rows"][0]["source_text"] += " changed"
    elif damage == "source_order": receipt["rows"].reverse()
    elif damage == "missing_source": receipt["rows"].pop()
    elif damage == "missing_tokens": receipt["rows"][0]["token_ids"].pop()
    elif damage == "unevaluated_tokens": receipt["rows"][0]["native_tokens_evaluated"] -= 1
    elif damage == "wrong_width": receipt["rows"][0]["embedding"].pop()
    elif damage == "wrong_norm": receipt["rows"][0]["embedding"][0] = 2.
    elif damage == "boolean_vector": receipt["rows"][0]["embedding"][0] = True
    elif damage == "vector_source_swap": receipt["rows"][0]["source_sha256"] = receipt["rows"][1]["source_sha256"]
    elif damage == "unfinished": receipt["complete"] = False
    elif damage == "no_forward": receipt["full_forward_executed"] = False
    elif damage == "unfinished_exit": receipt["protocol"]["exit_observed"] = False
    elif damage == "unreleased_child": receipt["cleanup"]["live_group_processes"] = 1
    elif damage == "unreleased_scope": receipt["resource_cgroup"]["only_owner_after_exit"] = False
    elif damage == "authority": receipt["proof_authority"] = True
    else: receipt["protocol"]["closing_mappings"]["/native/libllama.so"]["sha256"] = "f" * 64
    issued_native["issue"](receipt)
    options["expected_native_receipt_sha256"] = hashlib.sha256(owner._wire(receipt) + b"\n").hexdigest()
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


@pytest.mark.parametrize("replacement", [None, {}, {"complete": True}, "serialized", "unissued"])
def test_caller_data_and_unissued_objects_cannot_substitute_for_native_capability(issued_native, replacement):
    rows, options = _case(issued_native)
    if replacement == "serialized": replacement = deepcopy(issued_native["receipt"])
    elif replacement == "unissued": replacement = object.__new__(owner.VerifiedForwardResult)
    options["native_result"] = replacement
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


@pytest.mark.parametrize("change", ["changed_vector", "revoked", "other_handle", "thread", "process"])
def test_retained_binding_rechecks_exact_live_capability_before_consumption(issued_native, monkeypatch, change):
    binding, rows, options = _prepare(issued_native)
    if change == "changed_vector":
        receipt = deepcopy(issued_native["receipt"])
        receipt["rows"][0]["embedding"] = [0., 1.] + [0.] * 4094
        issued_native["issue"](receipt)
    elif change == "revoked":
        monkeypatch.delitem(owner._ISSUED, issued_native["native"])
    elif change == "other_handle":
        replacement = owner.VerifiedForwardResult(owner._TOKEN)
        monkeypatch.setitem(owner._ISSUED, replacement, deepcopy(owner._ISSUED[issued_native["native"]]))
        options["native_result"] = replacement
    elif change == "thread":
        original = threading.get_native_id()
        monkeypatch.setattr(threading, "get_native_id", lambda: original + 1)
    else:
        original = os.getpid()
        monkeypatch.setattr(os, "getpid", lambda: original + 1)
    calls = []
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=calls.append)
    assert calls == []


def test_binding_and_receipt_cannot_be_deserialized_into_capability(issued_native):
    binding, rows, options = _prepare(issued_native)
    with pytest.raises(TypeError):
        pickle.dumps(binding)
    for forged in (None, binding.receipt(), json.loads(json.dumps(binding.receipt()))):
        with pytest.raises(subject.Native4096SpanBindingError):
            subject.validate_native4096_span_binding(forged, rows, **_validation(options))


def test_consumer_exception_propagates_exactly_once(issued_native):
    binding, rows, options = _prepare(issued_native)
    calls = []
    marker = RuntimeError("deliberate downstream fixture failure")
    def consume(detached):
        calls.append(detached)
        raise marker
    with pytest.raises(RuntimeError) as error:
        subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=consume)
    assert error.value is marker and len(calls) == 1


def test_same_issued_binding_is_reusable_only_while_original_handle_remains_live(issued_native):
    binding, rows, options = _prepare(issued_native)
    first = subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=lambda value: value)
    first[0]["latent"].clear()
    second = subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=lambda value: value)
    assert len(second[0]["latent"]) == 4096


def test_late_producer_mutation_inside_real_reader_does_not_escape_whole_input_guard(issued_native, monkeypatch):
    rows, options = _case(issued_native)
    original_thread = threading.get_native_id()
    calls = []
    def observe_thread_then_mutate():
        calls.append(True)
        if len(calls) == 2:
            options["expected_producer"]["model_sha256"] = "f" * 64
        return original_thread
    monkeypatch.setattr(threading, "get_native_id", observe_thread_then_mutate)
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


def test_closed_producer_schema_has_no_target_or_authority_channel(issued_native):
    rows, options = _case(issued_native)
    options["expected_producer"]["canonical_ir"] = rows[0]["canonical_ir"]
    options["expected_producer_sha256"] = digest(options["expected_producer"])
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


@pytest.mark.parametrize("change", ["subset", "order", "source"])
def test_complete_native_operation_cannot_be_reused_for_different_source_population(issued_native, change):
    rows, options = _case(issued_native)
    if change == "subset":
        rows.pop()
        options["eligibility_records"].pop()
        options["exposure_records"].pop()
    elif change == "order":
        rows.reverse()
        options["eligibility_records"].reverse()
        options["exposure_records"].reverse()
    else:
        rows[0]["source_text"] = "The agency shall disclose records promptly."
        source_sha = hashlib.sha256(rows[0]["source_text"].encode()).hexdigest()
        options["eligibility_records"][0]["source_text_sha256"] = source_sha
        options["exposure_records"][0]["source_text_sha256"] = source_sha
        options["split_manifest"] = splits.LegalIRSplitManifest(examples=tuple(
            splits.LegalIRSplitExample.from_sample({"sample_id": r["id"], "text": r["source_text"]}) for r in rows),
            assignments={r["id"]: "train" for r in rows}, config_digest="a" * 64).to_dict()
    for field, value in (("rows", rows), ("split_manifest", options["split_manifest"]),
            ("eligibility", options["eligibility_records"]), ("exposure", options["exposure_records"])):
        options["expected_" + field + "_sha256"] = digest(value)
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)


def test_dimensional_record_validation_cannot_mutate_detached_rows_before_binding(issued_native, monkeypatch):
    rows, options = _case(issued_native)
    original_rows = deepcopy(rows)
    original_validator = subject.span._records
    calls = []
    def mutate_only_native_rows(examples, dimension, **kwargs):
        validated = original_validator(examples, dimension, **kwargs)
        if dimension == 4096:
            calls.append(True)
            examples[0]["latent"][0] = .25
        return validated
    monkeypatch.setattr(subject.span, "_records", mutate_only_native_rows)
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.prepare_native4096_span_binding(rows, **options)
    assert calls == [True] and rows == original_rows


@pytest.mark.parametrize("target", ["rows", "producer"])
def test_original_input_mutation_during_consumption_replay_never_reaches_callback(issued_native, monkeypatch, target):
    binding, rows, options = _prepare(issued_native)
    original_thread = threading.get_native_id()
    reads, dispatched = [], []
    def observe_thread_then_mutate():
        reads.append(True)
        if len(reads) == 2:
            if target == "rows": rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
            else: options["expected_producer"]["model_sha256"] = "f" * 64
        return original_thread
    monkeypatch.setattr(threading, "get_native_id", observe_thread_then_mutate)
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.consume_native4096_span_binding(binding, rows, **_validation(options), consumer=dispatched.append)
    assert len(reads) >= 2 and dispatched == []


def test_changed_native_owner_source_pin_invalidates_retained_capability(issued_native, monkeypatch):
    binding, rows, options = _prepare(issued_native)
    value = deepcopy(owner._ISSUED[issued_native["native"]])
    value["owner_source_sha256"] = "0" * 64
    monkeypatch.setitem(owner._ISSUED, issued_native["native"], value)
    with pytest.raises(subject.Native4096SpanBindingError):
        subject.validate_native4096_span_binding(binding, rows, **_validation(options))

