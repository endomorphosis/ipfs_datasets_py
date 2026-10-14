"""Historical source receipts from an authenticated, completed Leanstral owner.

This additive adapter consumes the existing live full-forward capability. It
starts no encoder, service, worker or resource reservation. Exact source rows,
producer pins, native tokens and the completed operation's CPU/release evidence
are retained together. Its reusable process/thread-bound handle cannot be
reconstructed from JSON. Neither the handle nor its ordinary receipt observes
a current repository/model head or authorizes training, scanning or execution.

The existing closed ``source_embeddings_4096.embed_rows`` and decoder/training
profiles remain separate. A new family/task codec and numerical lineage are
required before these source-width4096 inputs can enter CodebaseIR inference.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import PurePosixPath, Path
import re
import threading
import weakref

from . import source_embeddings_4096_full_owner as owner

SCHEMA = "leanstral-completed-source4096-embedding-production/v1"
RECEIPT_SCHEMA = "leanstral-completed-source4096-embedding-receipt/v1"
DIMENSION = 4096
MAX_ROWS = 128
MAX_BYTES = 64 * 1024 * 1024
TOKENIZER_POLICY = "native-model-vocabulary:add-special:no-parse-special:no-chat-template:untruncated:tokens512"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PRODUCER_FIELDS = {"profile", "model_sha256", "worker_sha256", "worker_source_sha256",
    "owner_source_sha256", "vocabulary_owner_source_sha256", "library_sha256"}
_NATIVE_RECEIPT_FIELDS = {"schema", "complete", "owner", "child", "operation_nonce",
    "owner_source_sha256", "vocabulary_owner_source_sha256", "worker_sha256", "worker_source_sha256",
    "model_file_identity", "model_sha256", "model_content_hash_verified", "model_content_hash_seconds",
    "full_forward_executed", "native_tokens_evaluated", "vectors_produced", "dimension", "profile",
    "request_sha256", "protocol", "resource_cgroup", "sampled_native_child_max_rss_bytes",
    "sampled_owner_max_rss_bytes", "sampled_combined_max_rss_bytes", "rss_observation_count",
    "combined_owner_child_rss_limit_bytes", "rss_scope", "native_child_elapsed_seconds", "elapsed_seconds",
    "sample_count", "cleanup", "wall_time_scope", "bridge_names", "legal_ir_evaluate_provers",
    "metric_disk_cache_used", "workers", "temperature", "context_tokens", "operating_system_page_cache",
    "training_executed", "qualified", "admitted", "proof_authority", "source_semantics_verified",
    "native_service_mutated", "downloads_performed", "persisted_receipt_is_execution_authority", "rows"}
_FALSE = {"training_executed": False, "download_executed": False,
    "source_semantics_verified": False, "proof_authority": False,
    "registry_authority": False, "current_head_authority": False,
    "current_model_authority": False, "scan_admission_authority": False,
    "execution_authority": False, "completion_authority": False,
    "publication_authority": False, "production_activation": False}
_TOKEN = object()
_ISSUED = weakref.WeakKeyDictionary()
_OWNER_READER = owner.require_live_result
_OWNER_RESULT_CLASS = owner.VerifiedForwardResult
_ROW_VALIDATOR = owner.vocab.validate_rows
_GEOMETRY_VALIDATOR = owner._geometry


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _passive(value, *, depth=0, budget=None):
    """Guard builtin data before serializers can reach arbitrary callbacks."""
    if budget is None:
        budget = [2_000_000]
    budget[0] -= 1
    _need(budget[0] >= 0 and depth <= 64, "bounded passive native receipt required")
    kind = type(value)
    if kind in {str, int, bool, type(None)}:
        return
    if kind is float:
        _need(math.isfinite(value), "finite passive native receipt required")
        return
    if kind is dict:
        for key, item in value.items():
            _need(type(key) is str, "native receipt keys must be builtin strings")
            _passive(item, depth=depth + 1, budget=budget)
        return
    if kind in {list, tuple}:
        for item in value:
            _passive(item, depth=depth + 1, budget=budget)
        return
    raise ValueError("exact passive native receipt containers required")


def _wire(value):
    _passive(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")
    _need(len(raw) <= MAX_BYTES, "completed native source receipt exceeds byte bound")
    return raw


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "canonical producer SHA256 required")
    return value


def _implementation():
    _need(owner.require_live_result is _OWNER_READER
          and owner.VerifiedForwardResult is _OWNER_RESULT_CLASS
          and owner.vocab.validate_rows is _ROW_VALIDATOR and owner._geometry is _GEOMETRY_VALIDATOR,
          "completed native source adapter owner bindings changed")
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ("verified_adapter", __file__), ("full_owner", owner.__file__),
        ("vocabulary_owner", owner.vocab.__file__))}


_IMPLEMENTATION = _implementation()


def _current_implementation():
    _need(_implementation() == _IMPLEMENTATION, "completed native source adapter implementation changed")
    _need(all(globals().get(name) is function for name, function in _LOCAL_BINDINGS.items())
          and VerifiedSourceEmbeddings4096.__init__ is _HANDLE_METHODS[0]
          and VerifiedSourceEmbeddings4096.__reduce__ is _HANDLE_METHODS[1],
          "completed native source adapter callable bindings changed")


def _producer(value):
    _passive(value)
    _need(type(value) is dict and set(value) == _PRODUCER_FIELDS,
          "closed completed native source producer declaration required")
    _need(type(value["profile"]) is str and value["profile"] in {owner.PROFILE, owner.RECLAIM_PROFILE},
          "explicit completed native CPU owner profile required")
    for key in _PRODUCER_FIELDS - {"profile", "library_sha256"}:
        _sha(value[key])
    libraries = value["library_sha256"]
    _need(type(libraries) is dict and 1 <= len(libraries) <= 63,
          "complete bounded native library declaration required")
    for path, digest in libraries.items():
        name = PurePosixPath(path)
        _need(name.is_absolute() and name.as_posix() == path and ".." not in name.parts,
              "canonical native library declaration path required")
        _sha(digest)
    return json.loads(_wire(value))


def _authored_rows(rows):
    _passive(rows)
    _need(type(rows) is list and 1 <= len(rows) <= MAX_ROWS,
          "bounded exact authored native source rows required")
    # This original source-only validator rejects targets and vector channels.
    return _ROW_VALIDATOR(rows)


def _producer_matches(receipt, producer):
    for key in _PRODUCER_FIELDS - {"library_sha256"}:
        _need(receipt.get(key) == producer[key], "completed native source producer pin differs: " + key)
    protocol = receipt.get("protocol")
    fields = {"entry_sha256", "authorization_sha256", "entry_mappings", "closing_sha256",
              "closing_ack_sha256", "closing_mappings", "exit_observed"}
    _need(type(protocol) is dict and set(protocol) == fields and protocol["exit_observed"] is True,
          "complete native entry authorization closing and exit records required")
    for key in {"entry_sha256", "authorization_sha256", "closing_sha256", "closing_ack_sha256"}:
        _sha(protocol[key])
    entry = protocol["entry_mappings"]
    _need(type(entry) is dict and _wire(entry) == _wire(protocol["closing_mappings"]),
          "completed native executable mappings changed before closing")
    executable = receipt.get("child", {}).get("pid")
    _need(type(executable) is int and executable > 0, "completed native child identity required")
    worker_paths = []
    observed_libraries = {}
    for path, item in entry.items():
        _need(type(item) is dict and set(item) == {"identity", "sha256"},
              "closed native executable mapping evidence required")
        identity = item["identity"]
        _need(type(identity) is dict and set(identity) == {"device", "inode", "bytes", "mtime_ns", "ctime_ns"}
              and all(type(number) is int and number >= 0 for number in identity.values())
              and identity["bytes"] > 0, "complete native executable mapping identity required")
        if item["sha256"] is None:
            worker_paths.append(path)
        else:
            observed_libraries[path] = _sha(item["sha256"])
    _need(len(worker_paths) == 1 and observed_libraries == producer["library_sha256"],
          "completed native library closure differs from exact producer pins")


def _validate_native(value, rows, producer):
    _passive(value)
    _need(type(value) is dict and set(value) == {"rows", "provenance", "receipt"},
          "exact live native owner result required")
    receipt, provenance, observed = value["receipt"], value["provenance"], value["rows"]
    expected_fields = _NATIVE_RECEIPT_FIELDS | ({"model_map_reclaim", "model_map_reclaim_policy",
        "model_map_reclaim_observation_scope", "shared_filecache_eviction"}
        if producer["profile"] == owner.RECLAIM_PROFILE else set())
    _need(type(receipt) is dict and set(receipt) == expected_fields and receipt.get("schema") == owner.SCHEMA
          and receipt.get("complete") is True and receipt.get("model_content_hash_verified") is True
          and receipt.get("full_forward_executed") is True and type(receipt.get("dimension")) is int
          and receipt["dimension"] == DIMENSION,
          "authenticated completed full native4096 forward required")
    _need(all(receipt.get(key) is False for key in ("qualified", "admitted", "proof_authority",
        "source_semantics_verified", "training_executed", "native_service_mutated",
        "downloads_performed", "persisted_receipt_is_execution_authority")),
        "completed native source receipt cannot grant authority")
    _producer_matches(receipt, producer)
    own = {"pid": os.getpid(), "thread_id": threading.get_native_id()}
    _need(type(provenance) is dict and provenance.get("owner") == receipt.get("owner") == own,
          "completed native source result changed receiving process or thread")
    _need(provenance.get("receipt_sha256") == hashlib.sha256(_wire(receipt) + b"\n").hexdigest(),
          "completed native source ordinary receipt bytes differ")
    for key in ("profile", "model_sha256", "worker_sha256", "worker_source_sha256",
                "owner_source_sha256", "operation_nonce", "request_sha256",
                "full_forward_executed", "dimension", "sample_count"):
        _need(provenance.get(key) == receipt.get(key), "completed native source provenance projection differs")
    _sha(receipt.get("operation_nonce"))
    request = {"schema": "native-source4096-worker-request/v1",
               "nonce": receipt["operation_nonce"], "rows": rows}
    _need(receipt.get("request_sha256") == hashlib.sha256(_wire(request) + b"\n").hexdigest(),
          "completed native source request differs from exact authored rows")
    _need(type(observed) is list and _wire(observed) == _wire(receipt.get("rows"))
          and len(observed) == len(rows)
          and type(receipt.get("sample_count")) is int and receipt["sample_count"] == len(rows)
          and type(receipt.get("vectors_produced")) is int and receipt["vectors_produced"] == len(rows),
          "complete completed native source row population required")
    cleanup, resource = receipt.get("cleanup"), receipt.get("resource_cgroup")
    _need(type(cleanup) is dict and cleanup.get("leader_reaped") is True
          and type(cleanup.get("returncode")) is int and cleanup["returncode"] == 0
          and type(cleanup.get("live_group_processes")) is int and cleanup["live_group_processes"] == 0,
          "completed native source process cleanup required")
    _need(type(resource) is dict and resource.get("only_owner_after_exit") is True,
          "completed native source resource release observation required")
    _need(receipt.get("workers") == 1 and type(receipt["workers"]) is int
          and receipt.get("context_tokens") == 512 and type(receipt["context_tokens"]) is int
          and receipt.get("bridge_names") == [] and receipt.get("legal_ir_evaluate_provers") is False
          and receipt.get("metric_disk_cache_used") is False,
          "completed native source operation profile differs")
    reclaim = producer["profile"] == owner.RECLAIM_PROFILE
    if reclaim:
        _need(receipt["model_map_reclaim"] is True and receipt["model_map_reclaim_policy"] == owner.RECLAIM_POLICY
              and receipt["shared_filecache_eviction"] is False
              and receipt["model_map_reclaim_observation_scope"] ==
                  "pinned native-worker reports authenticated against held model FD; no per-layer Python /proc observation",
              "completed native source mapping release policy differs")
    total_tokens = 0
    for authored, row in zip(rows, observed):
        row_fields = {"id", "source_text", "source_sha256", "embedding", "token_ids", "token_count",
                      "native_tokens_evaluated", "normalized_l2_norm", "raw_output_l2_norm", "geometry"}
        if reclaim:
            row_fields.update({"model_map_reclaim", "native_perf_accounting", "cpu_buffer_observation"})
        _need(type(row) is dict and set(row) == row_fields and row.get("id") == authored["id"]
              and row.get("source_text") == authored["source_text"]
              and row.get("source_sha256") == hashlib.sha256(authored["source_text"].encode("utf-8")).hexdigest(),
              "completed native source row identity or literal bytes differ")
        geometry, tokens, vector = row.get("geometry"), row.get("token_ids"), row.get("embedding")
        _need(type(geometry) is dict and _wire(_GEOMETRY_VALIDATOR(geometry)) == _wire(geometry),
              "closed completed native source geometry required")
        _need(type(geometry) is dict and all(type(geometry.get(key)) is int and geometry[key] == number
            for key, number in (("native_input_dimension", DIMENSION), ("native_output_dimension", DIMENSION),
                ("actual_context", 512), ("actual_batch", 512), ("actual_ubatch", 512), ("actual_sequences", 1)))
            and geometry.get("actual_pooling") == "last" and geometry.get("context_created") is True,
            "completed native source geometry or last pooling differs")
        vocabulary = geometry.get("vocabulary_size")
        _need(type(vocabulary) is int and 1 <= vocabulary <= 2**24
              and type(tokens) is list and 1 <= len(tokens) <= 512
              and all(type(token) is int and 0 <= token < vocabulary for token in tokens)
              and type(row.get("token_count")) is int and row["token_count"] == len(tokens)
              and type(row.get("native_tokens_evaluated")) is int and row["native_tokens_evaluated"] == len(tokens),
              "completed native source requires every untruncated evaluated token")
        _need(type(vector) is list and len(vector) == DIMENSION
              and all(type(number) in {int, float} and abs(number) <= 1.000002
                      and math.isfinite(number) for number in vector),
              "complete finite native4096 source vector required")
        norm = math.sqrt(math.fsum(number * number for number in vector))
        _need(abs(norm - 1.0) <= 2e-6 and type(row.get("normalized_l2_norm")) in {int, float}
              and math.isfinite(row["normalized_l2_norm"]) and abs(row["normalized_l2_norm"] - norm) <= 1e-12
              and type(row.get("raw_output_l2_norm")) in {int, float}
              and math.isfinite(row["raw_output_l2_norm"]) and row["raw_output_l2_norm"] > 0,
              "completed native source l2 normalization differs")
        total_tokens += len(tokens)
    _need(type(receipt.get("native_tokens_evaluated")) is int
          and receipt["native_tokens_evaluated"] == total_tokens,
          "complete completed native source token population required")


class VerifiedSourceEmbeddings4096:
    """Reusable completed-output custody; construction and deserialization refuse."""
    __slots__ = ("__weakref__",)

    def __init__(self, token=None):
        _need(token is _TOKEN, "only verified native source receiving can issue a handle")

    def __reduce__(self):
        raise TypeError("completed native source handle is not serializable")


def receive_verified_source_embeddings(result, *, rows, expected_producer):
    """Retain exact completed outputs from an existing live native capability.

    Producer declarations choose an exact expected identity; they cannot issue
    a capability. The underlying owner's handle remains reusable in its own
    process/native thread. This adapter supplies no persistent freshness token.
    """
    _current_implementation()
    authored_rows = rows
    rows, producer = _authored_rows(authored_rows), _producer(expected_producer)
    rows_wire, producer_wire = _wire(rows), _wire(producer)
    value = _OWNER_READER(result)
    captured = _wire(value)
    _validate_native(value, rows, producer)
    record = {"schema": SCHEMA, "receipt_schema": RECEIPT_SCHEMA,
        "interpretation_scope": "historical_completed_native_source_embedding_outputs",
        "dimension": DIMENSION, "dimension_role": "source_input_representation_width",
        "profile": producer["profile"], "expected_producer": producer,
        "tokenizer_policy": TOKENIZER_POLICY, "actual_execution_device": "cpu",
        "embedding_mode": True, "pooling": "last", "normalization": "l2",
        "full_native_tokens_retained": True, "input_rows": len(rows),
        "authored_source_rows_sha256": hashlib.sha256(rows_wire).hexdigest(),
        "native_provenance": value["provenance"], "native_operation_receipt": value["receipt"],
        "rows": [{"schema": RECEIPT_SCHEMA, **row,
            "token_input_sha256": hashlib.sha256(_wire(row["token_ids"])).hexdigest(),
            "embedding_sha256": hashlib.sha256(_wire(row["embedding"])).hexdigest(),
            **_FALSE} for row in value["rows"]],
        "source_bytes_reobserved_here": False, "current_registry_head_observed_here": False,
        "native_process_already_released": True,
        "capability_policy": "reusable_same_owner_pid_native_thread_not_serializable",
        "ordinary_receipt_is_capability": False, "authority": dict(_FALSE),
        "implementation": dict(_IMPLEMENTATION)}
    record_wire = _wire(record)
    _need(_wire(_OWNER_READER(result)) == captured
          and _wire(_authored_rows(authored_rows)) == rows_wire and _wire(_producer(expected_producer)) == producer_wire,
          "completed native source inputs changed during receiving")
    _current_implementation()
    handle = VerifiedSourceEmbeddings4096(_TOKEN)
    _ISSUED[handle] = {"native": result, "native_wire": captured, "record_wire": record_wire,
        "owner": {"pid": os.getpid(), "thread_id": threading.get_native_id()}}
    return handle


def read_verified_source_embeddings(handle):
    """Read defensive ordinary data while retaining the underlying live handle."""
    _current_implementation()
    _need(type(handle) is VerifiedSourceEmbeddings4096 and handle in _ISSUED,
          "issued completed native source handle required")
    value = _ISSUED[handle]
    _need(value["owner"] == {"pid": os.getpid(), "thread_id": threading.get_native_id()},
          "completed native source handle changed process or native thread")
    _need(_wire(_OWNER_READER(value["native"])) == value["native_wire"],
          "underlying completed native source capability changed")
    result = json.loads(value["record_wire"])
    _current_implementation()
    return result


_LOCAL_BINDINGS = {name: globals()[name] for name in (
    "_need", "_passive", "_wire", "_sha", "_implementation", "_current_implementation",
    "_producer", "_authored_rows", "_producer_matches", "_validate_native",
    "receive_verified_source_embeddings", "read_verified_source_embeddings", "VerifiedSourceEmbeddings4096")}
_HANDLE_METHODS = (VerifiedSourceEmbeddings4096.__init__, VerifiedSourceEmbeddings4096.__reduce__)


__all__ = ["SCHEMA", "RECEIPT_SCHEMA", "DIMENSION", "MAX_ROWS", "TOKENIZER_POLICY",
    "VerifiedSourceEmbeddings4096", "receive_verified_source_embeddings",
    "read_verified_source_embeddings"]
