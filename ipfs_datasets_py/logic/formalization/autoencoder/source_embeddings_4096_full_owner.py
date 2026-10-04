"""Operation-bound ownership of a private, CPU-only native 4096D forward.

This module does not accept a saved attestation as execution authority. Its
public operation hashes an open model FD, authenticates the running executable
and mapped libraries, and releases an explicit native load barrier only after
checking the child's actual cgroup. A successful live handle is distinct from
the diagnostic receipt. Neither is a proof, a semantic qualification, or a
permission to change the shared inference service.

The caller must first reserve resources and create a dedicated delegated cgroup containing only this owner.
This module does not reserve resources, download weights, configure a service,
or increase the fixed 512-token native context.
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import stat
import subprocess
import threading
import time
import weakref

from . import source_embeddings_4096_native_owner as vocab

SCHEMA = "leanstral-source4096-owned-full-forward/v1"
PROFILE = "leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2"
RECLAIM_PROFILE = "leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3"
RECLAIM_POLICY = "own_readonly_shared_madv_dontneed_after_each_completed_layer"
PERF_POLICY = "single_reset_decode_synchronize_with_clamped_idle_counter"
BACKEND_REVISION = "571d0d540df04f25298d0e159e520d9fc62ed121"
BACKEND_CONTEXT_SHA256 = "7e5a6656cf1b4b24c6bc825d90fcab4c0aab677c53a868f51a61c742b8361c76"
CPU_BUFFER_POLICY = "post_compute_cpu_device_or_exact_default_buffer_type"
BACKEND_BUFFER_SOURCE_SHA256 = "a96b54377e2b66732dcc5ed7ede82b6e0e873de53d515ac9fd6aa118b716bdd3"
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
DIMENSION = 4096
_TOKEN = object()
_ISSUED = weakref.WeakKeyDictionary()
_require, _wire, _decode = vocab._require, vocab._wire, vocab._decode


def _digest(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "sha256_pin_required")
    return value


def _check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("native_full_forward_deadline")


def _sha_fd(fd, deadline):
    """Hash the held inode without changing its shared file offset."""
    before = vocab._identity(os.fstat(fd))
    digest, position = hashlib.sha256(), 0
    while position < before["bytes"]:
        _check_deadline(deadline)
        block = os.pread(fd, min(8 * 1024 * 1024, before["bytes"] - position), position)
        _require(bool(block), "held_file_short_read")
        digest.update(block)
        position += len(block)
    _check_deadline(deadline)
    _require(vocab._identity(os.fstat(fd)) == before, "held_file_changed_while_hashing")
    return digest.hexdigest(), before


def _open_regular(path):
    path = Path(path)
    _require(path.is_absolute() and not path.is_symlink(), "absolute_nonsymlink_file_required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        identity = vocab._identity(os.fstat(fd))
        _require(identity == vocab._identity(path.stat()), "opened_file_identity_changed")
        return fd, identity
    except BaseException:
        os.close(fd)
        raise


def _check_leaf(path, fd, identity):
    _require(not Path(path).is_symlink() and vocab._identity(os.fstat(fd)) == identity
             == vocab._identity(Path(path).stat()), "held_file_or_leaf_changed")


def _proc_identity(identity, owner):
    current = vocab._process(identity["pid"])
    _require(current is not None and current["birth"] == identity["birth"]
             and current["parent_pid"] == owner["pid"]
             and current["group_pid"] == identity["pid"]
             and current["state"] not in {"Z", "X", "x"}, "native_child_identity_changed")
    return current


def _read_small(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(4097)
    _require(len(raw) <= 4096, "kernel_control_file_byte_bound")
    return raw.decode("ascii").strip()


def _events(path):
    result = {}
    for line in _read_small(Path(path) / "memory.events").splitlines():
        key, value = line.split()
        _require(key not in result and value.isdecimal(), "invalid_cgroup_memory_events")
        result[key] = int(value)
    _require({"oom", "oom_kill"} <= set(result), "cgroup_oom_events_required")
    return result


def _cgroup_controls(path, max_rss_bytes):
    """Validate actual kernel controls, not caller-supplied admission JSON."""
    path = Path(path)
    root = Path("/sys/fs/cgroup")
    _require(path.is_absolute() and not path.is_symlink() and path.resolve() == path
             and root in path.parents and path != root and len(path.relative_to(root).parts) >= 2,
             "dedicated_cgroup_leaf_required")
    _require(path.stat().st_uid == os.getuid(), "delegated_cgroup_owner_required")
    limit = _read_small(path / "memory.max")
    _require(limit.isdecimal() and 0 < int(limit) <= max_rss_bytes, "finite_cgroup_memory_limit_required")
    _require(_read_small(path / "memory.swap.max") == "0", "native_swap_must_be_disabled")
    _require(_read_small(path / "memory.oom.group") == "1", "native_cgroup_oom_group_required")
    pids = _read_small(path / "pids.max")
    _require(pids.isdecimal() and 1 <= int(pids) <= 64, "finite_native_pid_limit_required")
    _require(_read_small(path / "cgroup.type") == "domain", "domain_cgroup_required")
    return {"path": str(path), "memory_max_bytes": int(limit), "memory_swap_max_bytes": 0,
            "memory_oom_group": 1, "pids_max": int(pids), "type": "domain"}


def _join_cgroup(path, identity, owner, max_rss_bytes):
    controls = _cgroup_controls(path, max_rss_bytes)
    before = _events(path)
    _proc_identity(identity, owner)
    _check_cgroup(path, identity, controls, owner)
    return {**controls, "events_before": before}


def _check_cgroup(path, identity, controls, owner):
    _require(_cgroup_controls(path, controls["memory_max_bytes"]) ==
             {key: controls[key] for key in ("path", "memory_max_bytes", "memory_swap_max_bytes",
                                             "memory_oom_group", "pids_max", "type")},
             "native_cgroup_controls_changed")
    expected_pids = {str(owner["pid"])} | ({str(identity["pid"])} if identity is not None else set())
    _require(set(_read_small(Path(path) / "cgroup.procs").splitlines()) == expected_pids,
             "native_cgroup_contains_foreign_process")
    expected = "/" + str(Path(path).relative_to("/sys/fs/cgroup"))
    for pid in expected_pids:
        _require(_read_small(f"/proc/{pid}/cgroup") == "0::" + expected,
                 "native_cgroup_membership_changed")


def _map_entries(pid):
    raw = Path(f"/proc/{pid}/maps").read_bytes()
    _require(len(raw) <= 4 * 1024 * 1024, "native_maps_byte_bound")
    result = {}
    for line in raw.decode().splitlines():
        fields = line.split(maxsplit=5)
        _require(len(fields) >= 5, "invalid_native_mapping")
        if "x" not in fields[1] or fields[4] == "0":
            continue
        _require(len(fields) == 6 and fields[5].startswith("/") and not fields[5].endswith(" (deleted)"),
                 "unidentifiable_executable_mapping")
        path = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), fields[5])
        major, minor = fields[3].split(":")
        identity = {"device": os.makedev(int(major, 16), int(minor, 16)), "inode": int(fields[4])}
        _require(path not in result or result[path] == identity, "conflicting_native_map_inode")
        result[path] = identity
    _require(1 <= len(result) <= 64, "bounded_native_executable_mappings_required")
    return result


def _observe_maps(pid, worker, worker_identity, libraries, deadline):
    observed = _map_entries(pid)
    _require(set(observed) == {str(worker)} | set(libraries), "unexpected_or_missing_executable_mapping")
    records = {}
    for path, mapping in observed.items():
        _check_deadline(deadline)
        if path == str(worker):
            identity = worker_identity
            digest = None
        else:
            fd, identity, expected = libraries[path]
            _check_leaf(path, fd, identity)
            digest, after = _sha_fd(fd, deadline)
            _require(after == identity and digest == expected, "mapped_library_content_changed")
        _require(mapping == {key: identity[key] for key in ("device", "inode")},
                 "mapped_library_inode_differs_from_held_file")
        records[path] = {"identity": identity, "sha256": digest}
    return records


class VerifiedForwardResult:
    """A live operation result; dictionaries and deserialized files cannot issue it."""
    __slots__ = ("__weakref__",)

    def __init__(self, token=None):
        _require(token is _TOKEN, "only_completed_native_owner_can_issue_result")

    def __reduce__(self):
        raise TypeError("native_forward_capability_is_not_serializable")


def require_live_result(result):
    """Return owned vectors only from this process/thread's completed operation."""
    _require(type(result) is VerifiedForwardResult and result in _ISSUED,
             "live_verified_native_operation_required")
    value = _ISSUED[result]
    _require(value["owner"] == {"pid": os.getpid(), "thread_id": threading.get_native_id()},
             "native_result_owner_changed")
    _require(vocab._sha_file(__file__) == value["owner_source_sha256"], "native_owner_source_changed")
    receipt = _decode(value["serialized"])
    return {"rows": copy.deepcopy(receipt["rows"]), "provenance": {
        "receipt_sha256": value["receipt_sha256"], "owner": dict(value["owner"]),
        **{key: copy.deepcopy(receipt[key]) for key in ("profile", "model_sha256", "worker_sha256",
            "worker_source_sha256", "owner_source_sha256", "operation_nonce", "request_sha256",
            "full_forward_executed", "dimension", "sample_count")}}, "receipt": receipt}


verified_forward_rows = require_live_result


def _common_record(record, *, expected_keys, schema, context):
    _require(type(record) is dict and set(record) == expected_keys and record["schema"] == schema,
             "closed_full_forward_record_required")
    for key in ("nonce", "request_sha256", "worker_source_sha256"):
        _require(record[key] == context[key], "native_full_operation_binding_changed")
    for key in ("admitted", "qualified", "proof_authority", "source_semantics_verified"):
        _require(record[key] is False, "native_full_record_overclaims_authority")
    _require(_wire(record["process"]) == _wire(context["process"])
             and _wire(record["model_identity"]) == _wire(context["model_identity"]),
             "native_full_identity_changed")


COMMON = {"schema", "nonce", "request_sha256", "worker_source_sha256", "admitted", "qualified",
          "proof_authority", "source_semantics_verified", "process", "model_identity"}


def _entry(record, context, row_count, model_fd):
    _common_record(record, expected_keys=COMMON | {"mode", "model_fd", "requested_profile", "source_rows",
        "model_content_hash_verified_by_worker", "model_loaded", "authorization_required"},
        schema="native-source4096-worker-entry/v2", context=context)
    _require(record["mode"] == "embed-authorized" and type(record["model_fd"]) is int
             and record["model_fd"] == model_fd and type(record["source_rows"]) is int
             and record["source_rows"] == row_count and record["model_loaded"] is False
             and record["model_content_hash_verified_by_worker"] is False
             and record["authorization_required"] is True, "native_load_barrier_required")
    expected = {"schema": "native-source4096-worker-description/v2", "modes": ["embed-authorized"],
        "profile": PROFILE, "dimension": DIMENSION, "context_limit": 512, "batch_limit": 512,
        "ubatch_limit": 512, "sequence_count": 1, "threads": 1, "requested_gpu_layers": 0,
        "add_special": True, "parse_special": False, "request_source_only": True,
        "model_content_hash_verified_by_worker": False, "full_forward_executed": False,
        "model_loader_prefetch": False, "mmap_populate": False, "cpu_extra_buffers": False,
        "authorization_required": True, "closing_ack_required": True}
    if context.get("reclaim_model_mappings", False):
        expected.update(schema="native-source4096-worker-description/v3", profile=RECLAIM_PROFILE,
                        model_map_reclaim=RECLAIM_POLICY, required_architecture="deepseek2",
                        expected_layers=36, shared_filecache_eviction=False, native_perf_accounting=PERF_POLICY,
                        cpu_buffer_observation=CPU_BUFFER_POLICY)
    _require(_wire(record["requested_profile"]) == _wire(expected), "private_cpu_profile_changed")


def _geometry(value):
    _require(type(value) is dict, "native_full_geometry_required")
    architecture = value.get("metadata_architecture")
    _require(type(architecture) is str and re.fullmatch(r"[a-z0-9_]{1,64}", architecture), "native_architecture_required")
    vocabulary = value.get("vocabulary_size")
    _require(type(vocabulary) is int and 1 <= vocabulary <= 2**24, "native_vocabulary_size_required")
    out = value.get("metadata_embedding_length_out")
    _require(out is None or type(out) is int and out == DIMENSION, "native_metadata_output_width_changed")
    expected = {"native_input_dimension": DIMENSION, "native_output_dimension": DIMENSION,
        "metadata_architecture": architecture, "metadata_embedding_length": DIMENSION,
        "metadata_embedding_length_out": out, "metadata_embedding_length_key": architecture + ".embedding_length",
        "metadata_embedding_length_out_key": architecture + ".embedding_length_out", "vocabulary_size": vocabulary,
        "actual_context": 512, "actual_batch": 512, "actual_ubatch": 512, "actual_sequences": 1,
        "actual_pooling": "last", "context_created": True}
    _require(_wire(value) == _wire(expected), "native_executed_geometry_changed")
    return expected


def _forward_row(record, source, index, context, authorization_sha):
    keys = COMMON | {"index", "id", "source_sha256", "token_ids", "token_count", "add_special", "parse_special",
        "truncated", "chat_template_applied", "geometry", "full_forward_executed", "embedding", "normalization",
        "raw_output_l2_norm", "KV_reset_before_row", "synchronized_before_read", "native_prompt_tokens_evaluated",
        "native_single_tokens_evaluated", "native_tokens_evaluated", "actual_buffer_devices",
        "post_compute_nodes_observed", "nodes_without_observable_buffer", "device_observation_scope",
        "owner_authorization_sha256"}
    reclaim = context.get("reclaim_model_mappings", False)
    if reclaim:
        keys.update(("model_map_reclaim", "native_perf_accounting", "cpu_buffer_observation"))
    _common_record(record, expected_keys=keys, schema="native-source4096-worker-row/v2", context=context)
    _require(type(record["index"]) is int and record["index"] == index and record["id"] == source["id"]
             and record["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(),
             "native_forward_source_binding_changed")
    _require(record["owner_authorization_sha256"] == authorization_sha, "native_owner_authorization_changed")
    geometry = _geometry(record["geometry"])
    tokens = record["token_ids"]
    _require(type(tokens) is list and 1 <= len(tokens) <= 512
             and all(type(token) is int and 0 <= token < geometry["vocabulary_size"] for token in tokens)
             and type(record["token_count"]) is int and record["token_count"] == len(tokens), "native_full_token_inventory")
    _require(record["add_special"] is True and all(record[key] is False for key in
             ("parse_special", "truncated", "chat_template_applied")), "native_full_tokenizer_profile_changed")
    _require(all(record[key] is True for key in
             ("full_forward_executed", "KV_reset_before_row", "synchronized_before_read")), "actual_synchronized_forward_required")
    counts = [record[key] for key in ("native_prompt_tokens_evaluated", "native_single_tokens_evaluated",
                                     "native_tokens_evaluated", "post_compute_nodes_observed", "nodes_without_observable_buffer")]
    _require(all(type(value) is int and value >= 0 for value in counts) and counts[0] + counts[1] == counts[2] == len(tokens)
             and counts[3] > 0 and counts[4] < counts[3], "actual_native_evaluation_counters_required")
    devices = record["actual_buffer_devices"]
    _require(type(devices) is list and devices == ["CPU"], "only_observed_cpu_buffers_allowed")
    device_scope = ("post-compute tensor buffers; non-null CPU device or exact registered CPU default buffer type; offload disabled"
                    if reclaim else "post-compute tensor buffers; CPU-only registered backend and offload disabled")
    _require(record["device_observation_scope"] == device_scope, "native_device_scope_changed")
    vector = record["embedding"]
    _require(type(vector) is list and len(vector) == DIMENSION
             and all(type(number) in (int, float) and math.isfinite(number) for number in vector),
             "finite_native_4096_vector_required")
    norm = math.sqrt(math.fsum(float(number)**2 for number in vector))
    raw_norm = record["raw_output_l2_norm"]
    _require(record["normalization"] == "l2" and abs(norm - 1.) <= 2e-6
             and type(raw_norm) in (int, float) and math.isfinite(raw_norm) and raw_norm > 0,
             "native_l2_normalization_required")
    result = {"id": source["id"], "source_text": source["source_text"], "source_sha256": record["source_sha256"], "embedding": list(vector),
            "token_ids": list(tokens), "token_count": len(tokens), "native_tokens_evaluated": counts[2],
            "normalized_l2_norm": norm, "raw_output_l2_norm": raw_norm, "geometry": geometry}
    if reclaim:
        _require(geometry["metadata_architecture"] == "deepseek2", "layer_reclaim_architecture_changed")
        result["model_map_reclaim"] = _reclaim_record(record["model_map_reclaim"], context["model_identity"])
        result["native_perf_accounting"] = _perf_record(record["native_perf_accounting"], len(tokens), counts[0], counts[1])
        result["cpu_buffer_observation"] = _cpu_buffer_record(record["cpu_buffer_observation"], counts[3], counts[4])
    return result


def _cpu_buffer_record(value, total_nodes, missing_nodes):
    """Authenticate reported post-compute buffer evidence, never infer from a name.

    The pinned worker checks actual pointer identity against the CPU registry's
    default buffer type when that type has a null device pointer. Python retains
    those native observations separately from non-null device observations.
    """
    count_keys = ("cpu_device_pointer_nodes", "canonical_cpu_buffer_type_nodes",
                  "canonical_cpu_buffer_type_null_device_nodes", "unrecognized_buffer_type_nodes")
    _require(type(value) is dict and set(value) == {"policy", "backend_revision", "backend_source_sha256",
             "registered_cpu_devices", *count_keys}, "closed_native_cpu_buffer_observation_required")
    _require(value["policy"] == CPU_BUFFER_POLICY and value["backend_revision"] == BACKEND_REVISION
             and value["backend_source_sha256"] == BACKEND_BUFFER_SOURCE_SHA256,
             "pinned_native_cpu_buffer_policy_required")
    _require(type(value["registered_cpu_devices"]) is list and value["registered_cpu_devices"] == ["CPU"],
             "exact_native_cpu_registry_required")
    _require(all(type(value[key]) is int and value[key] >= 0 for key in count_keys)
             and type(total_nodes) is int and type(missing_nodes) is int and 0 <= missing_nodes < total_nodes,
             "native_cpu_buffer_counts_required")
    device = value["cpu_device_pointer_nodes"]
    canonical = value["canonical_cpu_buffer_type_nodes"]
    _require(value["canonical_cpu_buffer_type_null_device_nodes"] <= canonical
             and device + canonical > 0
             and device + canonical + value["unrecognized_buffer_type_nodes"] + missing_nodes == total_nodes,
             "native_cpu_buffer_coverage_required")
    return copy.deepcopy(value)


def _perf_record(value, tokens, prompt, single):
    """Retain public counters and interpret only the pinned single-decode case.

    This backend reports max(counter, 1), including the idle branch after a
    reset. Its timing and dispatch branch must agree; no general counter waiver.
    """
    _require(type(value) is dict and set(value) == {"policy", "backend_revision", "backend_context_sha256", "raw_n_p_eval", "raw_n_eval",
        "raw_t_p_eval_ms", "raw_t_eval_ms", "dispatch", "accounted_prompt_tokens", "accounted_single_tokens"},
        "closed_native_perf_accounting_required")
    _require(value["policy"] == PERF_POLICY and value["backend_revision"] == BACKEND_REVISION
             and value["backend_context_sha256"] == BACKEND_CONTEXT_SHA256,
             "pinned_native_perf_policy_required")
    _require(all(type(value[key]) is int and value[key] >= 0 for key in
             ("raw_n_p_eval", "raw_n_eval", "accounted_prompt_tokens", "accounted_single_tokens"))
             and all(type(value[key]) in (int, float) and math.isfinite(value[key]) and value[key] >= 0
                     for key in ("raw_t_p_eval_ms", "raw_t_eval_ms")), "finite_native_perf_values_required")
    _require(value["accounted_prompt_tokens"] == prompt and value["accounted_single_tokens"] == single
             and prompt + single == tokens, "accounted_native_tokens_differ")
    if tokens > 1:
        _require(value["dispatch"] == "prompt_batch" and value["raw_n_p_eval"] == tokens
                 and value["raw_n_eval"] == 1 and value["raw_t_p_eval_ms"] > 0 and value["raw_t_eval_ms"] == 0
                 and prompt == tokens and single == 0, "pinned_prompt_dispatch_counters_differ")
    else:
        _require(tokens == 1 and value["dispatch"] == "single_token" and value["raw_n_p_eval"] == 1
                 and value["raw_n_eval"] == 1 and value["raw_t_p_eval_ms"] == 0 and value["raw_t_eval_ms"] > 0
                 and prompt == 0 and single == 1, "pinned_single_dispatch_counters_differ")
    return copy.deepcopy(value)


def _reclaim_record(value, model_identity):
    """Validate pinned native-worker reports, not claim independent /proc sampling.

    The worker checks its own held-file mappings at each synchronized callback.
    Python binds reported ranges to that same held FD and exact native profile.
    """
    _require(type(value) is dict and set(value) == {"policy", "expected_layers", "completed_layers",
        "mapping_intervals", "page_size", "before_row", "layer_events", "shared_filecache_eviction"},
        "closed_layer_reclaim_report_required")
    _require(value["policy"] == RECLAIM_POLICY and type(value["expected_layers"]) is int
             and value["expected_layers"] == 36 and value["shared_filecache_eviction"] is False,
             "layer_reclaim_policy_changed")
    layers = value["completed_layers"]
    _require(type(layers) is list and all(type(x) is int for x in layers) and layers == list(range(36)),
             "complete_ordered_layer_reclaim_required")
    page = value["page_size"]
    _require(type(page) is int and page == os.sysconf("SC_PAGE_SIZE"), "native_reclaim_page_size_changed")
    intervals = value["mapping_intervals"]
    _require(type(intervals) is list and 1 <= len(intervals) <= 64, "bounded_model_map_intervals_required")
    upper = ((model_identity["bytes"] + page - 1) // page) * page
    for interval in intervals:
        _require(type(interval) is dict and set(interval) == {"start", "end", "offset", "device", "inode", "permissions"}
                 and all(type(interval[key]) is int for key in ("start", "end", "offset", "device", "inode")),
                 "closed_model_map_interval_required")
        start, end, offset = (interval[key] for key in ("start", "end", "offset"))
        _require(0 < start < end and offset >= 0 and all(x % page == 0 for x in (start, end, offset))
                 and offset + end - start <= upper and interval["permissions"] == "r--s"
                 and interval["device"] == model_identity["device"] and interval["inode"] == model_identity["inode"],
                 "reclaim_only_held_readonly_shared_model_ranges")
    addresses = sorted((row["start"], row["end"]) for row in intervals)
    offsets = sorted((row["offset"], row["offset"] + row["end"] - row["start"]) for row in intervals)
    _require(all(a[1] <= b[0] for ranges in (addresses, offsets) for a, b in zip(ranges, ranges[1:])),
             "overlapping_model_reclaim_ranges")
    events = value["layer_events"]
    _require(type(events) is list and len(events) == 36, "all_native_layer_reclaim_events_required")
    for index, event in enumerate([value["before_row"], *events]):
        keys = {"rss_before_bytes", "rss_after_bytes", "elapsed_seconds", "syscalls"} | ({"layer"} if index else set())
        _require(type(event) is dict and set(event) == keys and all(type(event[key]) is int and event[key] >= 0
                 for key in ("rss_before_bytes", "rss_after_bytes", "syscalls"))
                 and event["syscalls"] == len(intervals)
                 and type(event["elapsed_seconds"]) in (int, float) and math.isfinite(event["elapsed_seconds"])
                 and event["elapsed_seconds"] >= 0, "complete_native_reclaim_event_required")
        if index:
            _require(type(event["layer"]) is int and event["layer"] == index - 1, "ordered_layer_event_required")
    return copy.deepcopy(value)


def _closing(record, context, rows, authorization_sha):
    _common_record(record, expected_keys=COMMON | {"mode", "complete", "rows_emitted", "native_tokens_evaluated",
        "geometry", "model_and_context_freed", "inherited_fd_still_parent_owned", "full_forward_executed",
        "model_content_hash_verified_by_worker", "owner_authorization_sha256", "closing_ack_required"},
        schema="native-source4096-worker-closing/v2", context=context)
    _require(record["mode"] == "embed-authorized" and all(record[key] is True for key in
             ("complete", "model_and_context_freed", "inherited_fd_still_parent_owned", "full_forward_executed", "closing_ack_required"))
             and record["model_content_hash_verified_by_worker"] is False
             and type(record["rows_emitted"]) is int and record["rows_emitted"] == len(rows)
             and type(record["native_tokens_evaluated"]) is int
             and record["native_tokens_evaluated"] == sum(row["native_tokens_evaluated"] for row in rows)
             and record["owner_authorization_sha256"] == authorization_sha, "native_full_closing_incomplete")
    _require(_wire(_geometry(record["geometry"])) == _wire(rows[0]["geometry"])
             and all(_wire(row["geometry"]) == _wire(rows[0]["geometry"]) for row in rows), "native_row_geometry_changed")


def _exit(record, context, authorization_sha, ack_sha):
    _common_record(record, expected_keys=COMMON | {"mode", "complete", "owner_authorization_sha256",
        "owner_closing_ack_sha256", "model_and_context_freed"}, schema="native-source4096-worker-exit/v1", context=context)
    _require(record["mode"] == "embed-authorized" and record["complete"] is True
             and record["model_and_context_freed"] is True
             and record["owner_authorization_sha256"] == authorization_sha
             and record["owner_closing_ack_sha256"] == ack_sha, "native_closing_ack_not_observed")


class _NativeWorkerError(ValueError):
    """An authenticated owned worker reported failure, never a usable result."""


def _worker_error(record, context, rows, entry_observed):
    keys = {"schema", "nonce", "complete", "error", "entry_emitted", "rows_emitted",
            "native_tokens_evaluated", "model_and_context_freed", "production_cache_allowed",
            "admitted", "qualified", "proof_authority", "source_semantics_verified", "worker_source_sha256"}
    _require(type(record) is dict and set(record) == keys
             and record["schema"] == "native-source4096-worker-error/v1", "closed_native_error_required")
    _require(record["nonce"] == context["nonce"]
             and record["worker_source_sha256"] == context["worker_source_sha256"], "native_error_identity_changed")
    _require(all(record[key] is False for key in ("complete", "production_cache_allowed", "admitted",
             "qualified", "proof_authority", "source_semantics_verified"))
             and record["model_and_context_freed"] is True, "native_error_overclaims_or_lacks_cleanup")
    _require(type(record["entry_emitted"]) is bool and record["entry_emitted"] == entry_observed
             and type(record["rows_emitted"]) is int and record["rows_emitted"] == len(rows)
             and type(record["native_tokens_evaluated"]) is int
             and record["native_tokens_evaluated"] == sum(row["native_tokens_evaluated"] for row in rows),
             "native_error_progress_differs")
    _require(type(record["error"]) is str and 0 < len(record["error"].encode("utf-8")) <= 256
             and "\0" not in record["error"], "bounded_native_error_message_required")
    return copy.deepcopy(record)


def _send_control(fd, message, deadline):
    raw = _wire(message) + b"\n"
    _require(len(raw) < 4096, "native_control_byte_bound")
    _check_deadline(deadline)
    _require(os.write(fd, raw) == len(raw), "native_control_not_consumed")
    return hashlib.sha256(raw).hexdigest()


class _CombinedRSSLimitExceeded(ValueError):
    """Retain the rejecting sample without weakening the existing RSS limit."""

    def __init__(self, observation):
        super().__init__("combined_owner_native_rss_limit")
        self.observation = dict(observation)


def _rss_sample(identity, owner, maximum):
    parent = vocab._process(owner["pid"])
    _require(parent is not None and parent["state"] not in {"Z", "X", "x"}, "native_owner_process_missing")
    current = vocab._process(identity["pid"])
    if current is not None:
        _require(current["birth"] == identity["birth"], "native_child_pid_reused")
    child_rss = current["rss_bytes"] if current is not None else 0
    combined = parent["rss_bytes"] + child_rss
    observation = {"owner_rss_bytes": parent["rss_bytes"], "native_child_rss_bytes": child_rss,
                   "combined_rss_bytes": combined}
    if combined > maximum:
        raise _CombinedRSSLimitExceeded(observation)
    return observation, current


def _failure_resource_snapshot(path, controls, owner, identity):
    """Read the already admitted kernel scope before cleanup; never alter it."""
    if controls is None:
        return {"available": False, "captured_before_cleanup": True, "reason": "scope_not_admitted"}
    observed_controls = _cgroup_controls(path, controls["memory_max_bytes"])
    _require(observed_controls == controls, "native_failure_cgroup_controls_changed")
    result = {"available": True, "captured_before_cleanup": True, "controls": observed_controls,
              "errors": {}, "scope": "bounded read-only kernel files before owned-process cleanup"}
    for filename, key in (("memory.current", "memory_current_bytes"), ("memory.peak", "memory_peak_bytes"),
                          ("memory.stat", "memory_stat"), ("memory.events", "memory_events")):
        try:
            raw = _read_small(Path(path) / filename)
            if filename in {"memory.current", "memory.peak"}:
                _require(raw.isdecimal(), "invalid_failure_memory_counter")
                result[key] = int(raw)
            else:
                counters = {}
                for line in raw.splitlines():
                    name, value = line.split()
                    _require(re.fullmatch(r"[a-z0-9_]+", name) and name not in counters
                             and value.isdecimal(), "invalid_failure_memory_counters")
                    counters[name] = int(value)
                result[key] = counters
        except Exception as error:
            result[key] = None
            result["errors"][filename] = type(error).__name__
    members = _read_small(Path(path) / "cgroup.procs").splitlines()
    _require(all(value.isdecimal() for value in members), "invalid_failure_cgroup_members")
    owned = {str(owner["pid"])} | ({str(identity["pid"])} if identity is not None else set())
    result.update(owner_present=str(owner["pid"]) in members,
                  native_child_present=identity is not None and str(identity["pid"]) in members,
                  foreign_process_count=len(set(members) - owned), process_count=len(set(members)))
    return result


def _exchange(child, request, deadline, on_line, sample, outputs):
    pending, written = bytearray(), 0
    with selectors.DefaultSelector() as selector:
        for stream, label, event in ((child.stdin, "stdin", selectors.EVENT_WRITE),
                                     (child.stdout, "stdout", selectors.EVENT_READ),
                                     (child.stderr, "stderr", selectors.EVENT_READ)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event, label)
        while selector.get_map():
            _check_deadline(deadline)
            sample()
            for key, _ in selector.select(min(.05, max(0., deadline - time.monotonic()))):
                stream, label = key.fileobj, key.data
                if label == "stdin":
                    try:
                        written += os.write(stream.fileno(), request[written:written + 65536])
                    except BrokenPipeError:
                        raise ValueError("native_request_not_consumed") from None
                    if written == len(request):
                        selector.unregister(stream); stream.close()
                    continue
                block = os.read(stream.fileno(), 65536)
                if not block:
                    selector.unregister(stream); stream.close()
                    continue
                outputs[label].extend(block)
                _require(len(outputs[label]) <= (MAX_OUTPUT_BYTES if label == "stdout" else MAX_LOG_BYTES),
                         "bounded_native_output_required")
                if label == "stdout":
                    pending.extend(block)
                    while b"\n" in pending:
                        boundary = pending.index(b"\n") + 1
                        _require(boundary <= MAX_LINE_BYTES, "native_record_byte_bound")
                        raw = bytes(pending[:boundary]); del pending[:boundary]
                        on_line(_decode(raw), raw)
                    _require(len(pending) <= MAX_LINE_BYTES, "native_record_byte_bound")
    _require(not pending and written == len(request), "incomplete_native_protocol")
    _check_deadline(deadline)
    return child.wait(timeout=deadline - time.monotonic()), {key: bytes(value) for key, value in outputs.items()}


def run_full_forward(rows, *, worker_path, worker_sha256, worker_source_path, worker_source_sha256,
                     model_path, expected_model_sha256, expected_library_sha256, resource_cgroup,
                     output_directory, deadline_seconds, max_rss_bytes, reclaim_model_mappings=False):
    """Execute and issue vectors only after a complete, authenticated native run.

    Requires an external resource reservation and a dedicated delegated
    cgroup containing only this owner with finite memory/pid limits, zero swap and group OOM kill. The model
    hash is computed from the held FD on every operation; it is not a cached
    attestation. All executable mapped DSOs must be explicitly digest-pinned.
    """
    rows = vocab.validate_rows(rows)
    _require(type(reclaim_model_mappings) is bool, "explicit_model_reclaim_boolean_required")
    _require(type(deadline_seconds) in (int, float) and math.isfinite(deadline_seconds)
             and 0 < deadline_seconds <= 3600, "bounded_full_forward_deadline_required")
    _require(type(max_rss_bytes) is int and 1024**2 <= max_rss_bytes <= 64 * 1024**3,
             "bounded_native_memory_required")
    for digest in (worker_sha256, worker_source_sha256, expected_model_sha256):
        _digest(digest)
    _require(type(expected_library_sha256) is dict and 1 <= len(expected_library_sha256) <= 63,
             "complete_mapped_library_allowlist_required")
    for path, digest in expected_library_sha256.items():
        _require(type(path) is str and Path(path).is_absolute() and str(Path(path).resolve()) == path,
                 "canonical_library_path_required")
        _digest(digest)
    worker, source, model, output = map(Path, (worker_path, worker_source_path, model_path, output_directory))
    _require(all(path.is_absolute() for path in (worker, source, model, output)), "absolute_native_paths_required")
    _require(not output.exists() and not output.is_symlink(), "fresh_native_output_required")
    output.mkdir()
    started = time.monotonic(); deadline = started + float(deadline_seconds)
    owner = {"pid": os.getpid(), "thread_id": threading.get_native_id()}
    source_pin, vocabulary_owner_pin = vocab._sha_file(__file__), vocab._sha_file(vocab.__file__)
    nonce = secrets.token_hex(32)
    request = _wire({"schema": "native-source4096-worker-request/v1", "nonce": nonce, "rows": rows}) + b"\n"
    child = identity = cleanup = cgroup = controls = None
    held = []; control_read = control_write = None
    streams = {"stdout": bytearray(), "stderr": bytearray()}; verified = []; protocol = {}; observations = []
    verified_model_digest = model_hash_seconds = native_worker_error = None
    try:
        # Validate the owner's real kernel scope before the full model hash cost.
        controls = _cgroup_controls(resource_cgroup, max_rss_bytes)
        _check_cgroup(resource_cgroup, None, controls, owner)
        worker_fd, worker_identity = _open_regular(worker); held.append(worker_fd)
        _require(worker_identity["bytes"] <= 32 * 1024 * 1024, "native_binary_byte_bound")
        _require(_sha_fd(worker_fd, deadline)[0] == worker_sha256, "native_binary_pin_changed")
        source_fd, source_identity = _open_regular(source); held.append(source_fd)
        _require(_sha_fd(source_fd, deadline)[0] == worker_source_sha256, "native_worker_source_changed")
        libraries = {}
        for path, digest in expected_library_sha256.items():
            fd, file_identity = _open_regular(path); held.append(fd)
            _require(file_identity["bytes"] <= 512 * 1024 * 1024, "native_library_byte_bound")
            libraries[path] = (fd, file_identity, digest)
        model_fd, model_identity = _open_regular(model); held.append(model_fd)
        _require(0 < model_identity["bytes"] <= 1024**4, "bounded_model_file_required")
        hash_started = time.monotonic()
        computed_model_sha, after = _sha_fd(model_fd, deadline)
        model_hash_seconds = time.monotonic() - hash_started
        _require(after == model_identity and computed_model_sha == expected_model_sha256, "full_model_content_pin_changed")
        verified_model_digest = computed_model_sha
        control_read, control_write = os.pipe2(os.O_CLOEXEC)
        os.set_blocking(control_write, False)
        command = [f"/proc/self/fd/{worker_fd}", "--model-fd", str(model_fd), "--mode", "embed-authorized",
            "--nonce", nonce, "--deadline-seconds", str(max(1, math.ceil(deadline - time.monotonic()))),
            "--control-fd", str(control_read)]
        _check_deadline(deadline)
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "CUDA_VISIBLE_DEVICES": "",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, pass_fds=(worker_fd, model_fd, control_read), start_new_session=True)
        child_started = time.monotonic()
        os.close(control_read); control_read = None
        identity = vocab._process(child.pid)
        _require(identity is not None, "native_child_identity_unavailable")
        _proc_identity(identity, owner)
        cgroup = _join_cgroup(resource_cgroup, identity, owner, max_rss_bytes)
        process = {"pid": child.pid, "ppid": owner["pid"], "birth_ticks": identity["birth"],
                   "executable": str(worker.resolve()), "thread_id": child.pid}
        native_model = {key: model_identity[key] for key in ("device", "inode", "bytes")}
        for field in ("mtime", "ctime"):
            native_model[field + "_seconds"], native_model[field + "_nanoseconds"] = divmod(model_identity[field + "_ns"], 10**9)
        context = {"nonce": nonce, "request_sha256": hashlib.sha256(request).hexdigest(),
                   "worker_source_sha256": worker_source_sha256, "process": process, "model_identity": native_model,
                   "reclaim_model_mappings": reclaim_model_mappings}

        def identity_checks():
            _check_deadline(deadline); _proc_identity(identity, owner)
            _check_cgroup(resource_cgroup, identity, controls, owner)
            for path, fd, file_identity in ((worker, worker_fd, worker_identity), (source, source_fd, source_identity),
                                             (model, model_fd, model_identity)):
                _check_leaf(path, fd, file_identity)
            fd = os.open(f"/proc/{child.pid}/exe", os.O_RDONLY | os.O_CLOEXEC)
            try:
                digest, executed = _sha_fd(fd, deadline)
                _require(executed == worker_identity and digest == worker_sha256, "actual_executed_binary_changed")
            finally:
                os.close(fd)
            _require(owner == {"pid": os.getpid(), "thread_id": threading.get_native_id()}
                     and vocab._sha_file(__file__) == source_pin and vocab._sha_file(vocab.__file__) == vocabulary_owner_pin,
                     "native_owner_or_sources_changed")

        def on_line(record, raw):
            nonlocal native_worker_error
            if type(record) is dict and record.get("schema") == "native-source4096-worker-error/v1":
                native_worker_error = _worker_error(record, context, verified, "entry_sha256" in protocol)
                protocol["native_error_record_sha256"] = hashlib.sha256(raw).hexdigest()
                raise _NativeWorkerError("native_worker_failed: " + native_worker_error["error"])
            if not protocol:
                _entry(record, context, len(rows), model_fd)
                identity_checks()
                maps = _observe_maps(child.pid, worker.resolve(), worker_identity, libraries, deadline)
                entry_sha = hashlib.sha256(raw).hexdigest()
                authorization_sha = _send_control(control_write, {"schema": "native-source4096-owner-authorization/v1",
                    "nonce": nonce, "request_sha256": context["request_sha256"], "entry_sha256": entry_sha,
                    "model_sha256": computed_model_sha}, deadline)
                protocol.update(entry_sha256=entry_sha, authorization_sha256=authorization_sha, entry_mappings=maps)
            elif len(verified) < len(rows):
                observed = _forward_row(record, rows[len(verified)], len(verified), context, protocol["authorization_sha256"])
                if reclaim_model_mappings and verified:
                    _require(observed["model_map_reclaim"]["mapping_intervals"] == verified[0]["model_map_reclaim"]["mapping_intervals"],
                             "model_reclaim_intervals_changed_between_rows")
                verified.append(observed)
            elif "closing_sha256" not in protocol:
                _closing(record, context, verified, protocol["authorization_sha256"])
                identity_checks()
                maps = _observe_maps(child.pid, worker.resolve(), worker_identity, libraries, deadline)
                _require(maps == protocol["entry_mappings"], "native_mapped_libraries_changed")
                closing_sha = hashlib.sha256(raw).hexdigest()
                ack_sha = _send_control(control_write, {"schema": "native-source4096-owner-close-ack/v1",
                    "nonce": nonce, "request_sha256": context["request_sha256"], "closing_sha256": closing_sha}, deadline)
                protocol.update(closing_sha256=closing_sha, closing_ack_sha256=ack_sha, closing_mappings=maps)
            else:
                _require("exit_observed" not in protocol, "extra_native_record")
                _exit(record, context, protocol["authorization_sha256"], protocol["closing_ack_sha256"])
                protocol["exit_observed"] = True

        def sample():
            try:
                observed, current = _rss_sample(identity, owner, max_rss_bytes)
            except _CombinedRSSLimitExceeded as error:
                observations.append({**error.observation, "rejected": True})
                raise
            observations.append(observed)
            if current is not None and current["state"] not in {"Z", "X", "x"}:
                _check_cgroup(resource_cgroup, identity, controls, owner)

        code, streams = _exchange(child, request, deadline, on_line, sample, streams)
        _require(code == 0 and protocol.get("exit_observed") is True and len(verified) == len(rows),
                 "native_full_operation_incomplete")
        cleanup = vocab._cleanup(child, identity)
        _check_cgroup(resource_cgroup, None, controls, owner)
        events_after = _events(resource_cgroup)
        _require(all(events_after[key] == cgroup["events_before"][key] for key in ("oom", "oom_kill")),
                 "native_operation_oom_event")
        _check_leaf(model, model_fd, model_identity)
        receipt = {"schema": SCHEMA, "complete": True, "owner": owner, "child": identity,
            "operation_nonce": nonce, "owner_source_sha256": source_pin, "vocabulary_owner_source_sha256": vocabulary_owner_pin,
            "worker_sha256": worker_sha256, "worker_source_sha256": worker_source_sha256,
            "model_file_identity": model_identity, "model_sha256": computed_model_sha,
            "model_content_hash_verified": True, "model_content_hash_seconds": model_hash_seconds,
            "full_forward_executed": True, "native_tokens_evaluated": sum(row["native_tokens_evaluated"] for row in verified),
            "vectors_produced": len(verified), "dimension": DIMENSION,
            "profile": RECLAIM_PROFILE if reclaim_model_mappings else PROFILE,
            "request_sha256": context["request_sha256"], "protocol": protocol,
            "resource_cgroup": {**cgroup, "events_after": events_after, "only_owner_after_exit": True},
            "sampled_native_child_max_rss_bytes": max((row["native_child_rss_bytes"] for row in observations), default=0),
            "sampled_owner_max_rss_bytes": max((row["owner_rss_bytes"] for row in observations), default=0),
            "sampled_combined_max_rss_bytes": max((row["combined_rss_bytes"] for row in observations), default=0),
            "rss_observation_count": len(observations), "combined_owner_child_rss_limit_bytes": max_rss_bytes,
            "rss_scope": "sampled owner plus native process RSS sum; actual kernel memory.max additionally enforced",
            "native_child_elapsed_seconds": time.monotonic() - child_started,
            "elapsed_seconds": time.monotonic() - started, "sample_count": len(rows), "cleanup": cleanup,
            "wall_time_scope": "complete model hash plus native load/forward and ownership verification",
            "bridge_names": [], "legal_ir_evaluate_provers": False, "metric_disk_cache_used": False,
            "workers": 1, "temperature": 0, "context_tokens": 512, "operating_system_page_cache": "uncontrolled",
            "training_executed": False, "qualified": False, "admitted": False, "proof_authority": False,
            "source_semantics_verified": False, "native_service_mutated": False, "downloads_performed": False,
            "persisted_receipt_is_execution_authority": False, "rows": verified}
        if reclaim_model_mappings:
            receipt.update(model_map_reclaim=True, model_map_reclaim_policy=RECLAIM_POLICY,
                model_map_reclaim_observation_scope="pinned native-worker reports authenticated against held model FD; no per-layer Python /proc observation",
                shared_filecache_eviction=False)
        for name, raw in streams.items():
            with (output / (name + ".log")).open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        vocab._save(output / "receipt.json", receipt)
        result = VerifiedForwardResult(_TOKEN)
        _ISSUED[result] = {"owner": owner, "owner_source_sha256": source_pin, "serialized": _wire(receipt),
                           "receipt_sha256": hashlib.sha256(_wire(receipt) + b"\n").hexdigest()}
        return result
    except BaseException as error:
        # Telemetry must precede cleanup, which can immediately release mapped
        # pages. Observation failure never prevents cleanup or replaces its cause.
        try:
            failure_resources = _failure_resource_snapshot(resource_cgroup, controls, owner, identity)
        except BaseException as observation_error:
            failure_resources = {"available": False, "captured_before_cleanup": True,
                                 "error_type": type(observation_error).__name__}
        cleanup_error = None
        if child is not None and identity is not None:
            try:
                cleanup = vocab._cleanup(child, identity)
            except BaseException as exception:
                cleanup_error = type(exception).__name__
        elif child is not None:
            child.kill(); child.wait(timeout=3)
            cleanup = {"leader_reaped": True, "load_authorization_sent": False}
        failure = {"schema": SCHEMA, "complete": False, "error_type": type(error).__name__, "error": str(error)[:512],
            "owner": owner, "child": identity, "cleanup": cleanup, "cleanup_error": cleanup_error,
            "model_content_hash_verified": verified_model_digest is not None, "model_sha256": verified_model_digest,
            "model_content_hash_seconds": model_hash_seconds,
            "profile": RECLAIM_PROFILE if reclaim_model_mappings else PROFILE,
            "reclaim_model_mappings": reclaim_model_mappings,
            "native_worker_error": native_worker_error,
            "operation_verified": False, "protocol_progress": protocol, "rows_observed": len(verified),
            "rejected_rss_observation": next((row for row in reversed(observations) if row.get("rejected")), None),
            "rss_observation_count": len(observations),
            "sampled_native_child_max_rss_bytes": max((row["native_child_rss_bytes"] for row in observations), default=0),
            "sampled_owner_max_rss_bytes": max((row["owner_rss_bytes"] for row in observations), default=0),
            "sampled_combined_max_rss_bytes": max((row["combined_rss_bytes"] for row in observations), default=0),
            "combined_owner_child_rss_limit_bytes": max_rss_bytes,
            "resource_snapshot_before_cleanup": failure_resources,
            "training_executed": False, "qualified": False, "admitted": False,
            "persisted_receipt_is_execution_authority": False, "elapsed_seconds": time.monotonic() - started}
        for name, raw in streams.items():
            if not (output / (name + ".log")).exists():
                with (output / (name + ".log")).open("xb") as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        vocab._save(output / "failure.json", failure)
        raise
    finally:
        for fd in (control_read, control_write):
            if fd is not None:
                os.close(fd)
        for fd in reversed(held):
            os.close(fd)
        if child is not None:
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
