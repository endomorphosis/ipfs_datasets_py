"""Completed-owner adapter controls, with an explicitly doubled issuing boundary.

The genuine live-result reader, SHA pins, source/token joins and defensive
receiving run normally. Native issuance is an explicit private test double.
No pretrained weights, encoder, subprocess, service or cgroup runs here; these
synthetic vectors never qualify native numerical execution or an IR lineage.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import pickle
import threading

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    source_embeddings_4096_full_owner as owner,
    source_embeddings_4096_verified as subject,
)


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def prohibit_native_execution(monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("completed source receipt control attempted native execution")
    monkeypatch.setattr(owner, "run_full_forward", forbidden)
    monkeypatch.setattr(owner.vocab, "run_vocab_probe", forbidden)
    monkeypatch.setattr(owner.subprocess, "Popen", forbidden)


@pytest.fixture
def issued_native(monkeypatch):
    rows = [{"id": "source:first", "source_text": "def add(value):\n    return value + 1\n"},
            {"id": "source:second", "source_text": "def twice(value):\n    return value * 2\n"}]
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


def _receive(case, **changes):
    return subject.receive_verified_source_embeddings(case["native"], **{
        "rows": case["rows"], "expected_producer": case["producer"], **changes})


def test_exact_completed_source_rows_tokens_producer_and_release_are_retained_without_authority(issued_native):
    case = issued_native
    handle = _receive(case)
    value = subject.read_verified_source_embeddings(handle)
    assert value["schema"] == subject.SCHEMA
    assert value["interpretation_scope"] == "historical_completed_native_source_embedding_outputs"
    assert value["dimension"] == 4096 and value["dimension_role"] == "source_input_representation_width"
    assert value["expected_producer"] == case["producer"]
    assert value["native_operation_receipt"] == case["receipt"]
    assert value["actual_execution_device"] == "cpu"
    assert value["pooling"] == "last" and value["normalization"] == "l2"
    assert value["full_native_tokens_retained"] is value["native_process_already_released"] is True
    assert value["source_bytes_reobserved_here"] is value["current_registry_head_observed_here"] is False
    assert value["ordinary_receipt_is_capability"] is False
    assert all(flag is False for flag in value["authority"].values())
    for row, original in zip(value["rows"], case["receipt"]["rows"]):
        assert row["schema"] == subject.RECEIPT_SCHEMA
        assert {key: row[key] for key in original} == original
        assert row["token_input_sha256"] == hashlib.sha256(owner._wire(original["token_ids"])).hexdigest()
        assert row["embedding_sha256"] == hashlib.sha256(owner._wire(original["embedding"])).hexdigest()
        assert all(row[key] is False for key in value["authority"])


def test_adapter_handle_is_reusable_defensive_and_keeps_native_handle_alive(issued_native):
    case = issued_native
    handle = _receive(case)
    original = subject.read_verified_source_embeddings(handle)
    changed = subject.read_verified_source_embeddings(handle)
    changed["rows"][0]["embedding"][0] = 123.
    changed["native_operation_receipt"]["cleanup"]["leader_reaped"] = False
    assert subject.read_verified_source_embeddings(handle) == original
    assert owner.require_live_result(case["native"])["rows"] == case["receipt"]["rows"]
    assert subject.read_verified_source_embeddings(_receive(case)) == original
    with pytest.raises(TypeError):
        pickle.dumps(handle)


def test_explicit_layer_reclaim_profile_preserves_native_token_buffer_and_mapping_reports(issued_native):
    case = issued_native
    receipt = deepcopy(case["receipt"])
    case["producer"]["profile"] = receipt["profile"] = owner.RECLAIM_PROFILE
    receipt.update(model_map_reclaim=True, model_map_reclaim_policy=owner.RECLAIM_POLICY,
        model_map_reclaim_observation_scope=(
            "pinned native-worker reports authenticated against held model FD; no per-layer Python /proc observation"),
        shared_filecache_eviction=False)
    page = os.sysconf("SC_PAGE_SIZE")
    identity = receipt["model_file_identity"]
    event = {"rss_before_bytes": 4096, "rss_after_bytes": 4096, "elapsed_seconds": .001, "syscalls": 1}
    reclaim = {"policy": owner.RECLAIM_POLICY, "expected_layers": 36, "completed_layers": list(range(36)),
        "mapping_intervals": [{"start": page, "end": 2 * page, "offset": 0,
            "device": identity["device"], "inode": identity["inode"], "permissions": "r--s"}],
        "page_size": page, "before_row": dict(event),
        "layer_events": [{**event, "layer": number} for number in range(36)], "shared_filecache_eviction": False}
    perf = {"policy": owner.PERF_POLICY, "backend_revision": owner.BACKEND_REVISION,
        "backend_context_sha256": owner.BACKEND_CONTEXT_SHA256, "raw_n_p_eval": 3, "raw_n_eval": 1,
        "raw_t_p_eval_ms": .1, "raw_t_eval_ms": 0., "dispatch": "prompt_batch",
        "accounted_prompt_tokens": 3, "accounted_single_tokens": 0}
    buffers = {"policy": owner.CPU_BUFFER_POLICY, "backend_revision": owner.BACKEND_REVISION,
        "backend_source_sha256": owner.BACKEND_BUFFER_SOURCE_SHA256, "registered_cpu_devices": ["CPU"],
        "cpu_device_pointer_nodes": 0, "canonical_cpu_buffer_type_nodes": 10,
        "canonical_cpu_buffer_type_null_device_nodes": 10, "unrecognized_buffer_type_nodes": 0}
    for row in receipt["rows"]:
        row.update(model_map_reclaim=deepcopy(reclaim), native_perf_accounting=deepcopy(perf),
                   cpu_buffer_observation=deepcopy(buffers))
    case["issue"](receipt)
    value = subject.read_verified_source_embeddings(_receive(case))
    assert value["profile"] == owner.RECLAIM_PROFILE
    assert value["native_operation_receipt"] == receipt
    assert value["rows"][0]["model_map_reclaim"] == reclaim
    assert value["rows"][0]["native_perf_accounting"] == perf
    assert value["rows"][0]["cpu_buffer_observation"] == buffers


@pytest.mark.parametrize("value", ({"complete": True}, object(), None))
def test_caller_data_cannot_substitute_for_the_issued_native_capability(issued_native, value):
    case = issued_native
    with pytest.raises(ValueError):
        subject.receive_verified_source_embeddings(value, rows=case["rows"], expected_producer=case["producer"])


def test_constructed_or_deserialized_adapter_data_cannot_issue_a_handle(issued_native):
    case = issued_native
    with pytest.raises(ValueError):
        subject.VerifiedSourceEmbeddings4096()
    for value in (object.__new__(subject.VerifiedSourceEmbeddings4096),
                  json.loads(subject._wire(subject.read_verified_source_embeddings(_receive(case))))):
        with pytest.raises(ValueError):
            subject.read_verified_source_embeddings(value)


@pytest.mark.parametrize("field", ("profile", "model_sha256", "worker_sha256", "worker_source_sha256",
    "owner_source_sha256", "vocabulary_owner_source_sha256", "library_sha256"))
def test_every_declared_native_producer_pin_is_independently_matched(issued_native, field):
    case = issued_native
    producer = deepcopy(case["producer"])
    producer[field] = (owner.RECLAIM_PROFILE if field == "profile" else
        {"/native/libllama.so": "f" * 64} if field == "library_sha256" else "f" * 64)
    with pytest.raises(ValueError):
        _receive(case, expected_producer=producer)


@pytest.mark.parametrize("change", ("source_bytes", "source_order", "target_channel", "omitted_row"))
def test_authored_literal_source_population_is_exact_and_source_only(issued_native, change):
    case = issued_native
    rows = deepcopy(case["rows"])
    if change == "source_bytes":
        rows[0]["source_text"] += "# changed\n"
    elif change == "source_order":
        rows.reverse()
    elif change == "target_channel":
        rows[0]["target"] = "prove the goal"
    else:
        rows.pop()
    with pytest.raises(ValueError):
        _receive(case, rows=rows)


@pytest.mark.parametrize("change", ("missing_tokens", "unevaluated_tokens", "wrong_width", "unknown_field",
    "unfinished_exit", "unreleased_child", "unreleased_scope", "proof_authority", "library_swap"))
def test_incomplete_or_changed_owner_data_never_becomes_an_adapter_receipt(issued_native, change):
    case = issued_native
    receipt = deepcopy(case["receipt"])
    if change == "missing_tokens":
        receipt["rows"][0]["token_ids"].pop()
    elif change == "unevaluated_tokens":
        receipt["rows"][0]["native_tokens_evaluated"] -= 1
    elif change == "wrong_width":
        receipt["rows"][0]["embedding"].pop()
    elif change == "unknown_field":
        receipt["current_registry_authority"] = True
    elif change == "unfinished_exit":
        receipt["protocol"]["exit_observed"] = False
    elif change == "unreleased_child":
        receipt["cleanup"]["live_group_processes"] = 1
    elif change == "unreleased_scope":
        receipt["resource_cgroup"]["only_owner_after_exit"] = False
    elif change == "proof_authority":
        receipt["proof_authority"] = True
    else:
        receipt["protocol"]["closing_mappings"]["/native/libllama.so"]["sha256"] = "f" * 64
    case["issue"](receipt)
    with pytest.raises(ValueError):
        _receive(case)


def test_same_process_native_thread_is_required_for_completed_output_reuse(issued_native, monkeypatch):
    case = issued_native
    handle = _receive(case)
    original_thread = threading.get_native_id()
    monkeypatch.setattr(subject.threading, "get_native_id", lambda: original_thread + 1)
    with pytest.raises(ValueError, match="thread"):
        subject.read_verified_source_embeddings(handle)


def test_underlying_native_receipt_change_withholds_an_existing_adapter_handle(issued_native):
    case = issued_native
    handle = _receive(case)
    receipt = deepcopy(case["receipt"])
    receipt["rows"][0]["embedding"] = [0., 1.] + [0.] * 4094
    case["issue"](receipt)
    with pytest.raises(ValueError, match="underlying"):
        subject.read_verified_source_embeddings(handle)


@pytest.mark.parametrize("target", ("rows", "producer"))
def test_late_authored_declaration_change_withholds_receiving_before_issuance(issued_native, monkeypatch, target):
    case = issued_native
    thread_id = threading.get_native_id()
    calls = []
    def observe_thread_then_mutate():
        calls.append(True)
        # The real owner reader observes the thread first; the adapter then
        # observes it while validating its already-detached inputs. Preserve
        # the real ID while explicitly injecting late declaration drift.
        if len(calls) == 2:
            if target == "rows":
                case["rows"][0]["source_text"] += "# late\n"
            else:
                case["producer"]["model_sha256"] = "f" * 64
        return thread_id
    monkeypatch.setattr(subject.threading, "get_native_id", observe_thread_then_mutate)
    with pytest.raises(ValueError, match="changed during"):
        _receive(case)


def test_passive_container_guard_refuses_hooks_before_iteration(issued_native):
    case = issued_native
    touched = []
    class HookedDict(dict):
        def items(self):
            touched.append(True)
            return super().items()
    producer = HookedDict(case["producer"])
    with pytest.raises(ValueError, match="exact passive"):
        _receive(case, expected_producer=producer)
    assert touched == []


def test_replacing_an_adapter_validator_cannot_bypass_issued_handle_checks(issued_native, monkeypatch):
    case = issued_native
    monkeypatch.setattr(subject, "_validate_native", lambda *_: None)
    with pytest.raises(ValueError, match="callable bindings"):
        _receive(case)
