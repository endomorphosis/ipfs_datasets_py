"""Owned native tokenizer preflight for the separate 4096D source lineage.

This invokes a locally built, digest-pinned worker in ``vocab`` mode only. It
opens the existing model read-only and never allocates model weight tensors or
requests embeddings. The native model's vocabulary/metadata are real; this is
not content verification of the 67 GB model, an embedding witness, or a training
admission. Full forward execution remains closed in source_embeddings_4096.

Call inside the campaign resource guardian. The child has a separate process
group, a bounded wall deadline and output, and is reaped on every exit path.
No shared inference service is started, stopped, or reconfigured here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import stat
import subprocess
import threading
import time

SCHEMA = "leanstral-source4096-owned-vocabulary-preflight/v1"
MAX_ROWS = 1024
MAX_SOURCE_BYTES = 65536
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_native_json_key")
        result[key] = value
    return result


def _decode(raw):
    def constant(value):
        raise ValueError("nonfinite_native_json")
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=constant)


def _sha_file(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _identity(info):
    _require(stat.S_ISREG(info.st_mode), "regular_file_required")
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _process(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    _require(len(fields) >= 22, "invalid_child_identity")
    return {"pid": pid, "state": fields[0], "parent_pid": int(fields[1]),
            "group_pid": int(fields[2]), "birth": fields[19],
            "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE")}


def _group_members(identity):
    leader = _process(identity["pid"])
    _require(leader is None or leader["birth"] == identity["birth"], "child_pid_reused")
    entries = list(Path("/proc").iterdir())
    _require(len(entries) <= 100000, "process_inventory_bound")
    members = []
    for entry in entries:
        if entry.name.isdecimal():
            process = _process(int(entry.name))
            if process and process["group_pid"] == identity["pid"] and process["state"] not in {"Z", "X", "x"}:
                members.append(process)
    return members


def _cleanup(child, identity):
    """Signal only this operation's birth-checked, isolated process group."""
    events = []
    for sig, grace in ((signal.SIGTERM, 2.), (signal.SIGKILL, 3.)):
        if not _group_members(identity):
            break
        try:
            os.killpg(identity["pid"], sig)
            events.append(sig.name)
        except ProcessLookupError:
            pass
        until = time.monotonic() + grace
        while _group_members(identity) and time.monotonic() < until:
            time.sleep(.02)
    _require(not _group_members(identity), "owned_native_group_survived_cleanup")
    code = child.wait(timeout=3)
    return {"leader_reaped": True, "returncode": code, "signals": events,
            "live_group_processes": 0, "gpu_execution_requested": False}


def validate_rows(rows):
    """Closed source-only input: no gold formula, embedding or target channel."""
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "bounded_source_rows_required")
    seen = set()
    clean = []
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text"}, "closed_source_row_required")
        key, source = row["id"], row["source_text"]
        _require(type(key) is str and 0 < len(key.encode()) <= 256 and key not in seen,
                 "unique_bounded_source_id_required")
        _require(type(source) is str and 0 < len(source.encode()) <= MAX_SOURCE_BYTES
                 and "\0" not in source, "bounded_literal_source_required")
        seen.add(key)
        clean.append(dict(row))
    _require(len(_wire(clean)) <= MAX_REQUEST_BYTES - 1024, "source_request_byte_bound")
    return clean


def _exchange(child, request, deadline, observations=None):
    """Bound writes and both output streams under the same monotonic deadline."""
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    position = 0
    with selectors.DefaultSelector() as selector:
        for stream, label, event in ((child.stdin, "stdin", selectors.EVENT_WRITE),
                                     (child.stdout, "stdout", selectors.EVENT_READ),
                                     (child.stderr, "stderr", selectors.EVENT_READ)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event, label)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("native_vocabulary_deadline")
            observed = _process(child.pid)
            if observed is not None:
                _require(observed["rss_bytes"] <= 1024**3, "native_vocabulary_rss_limit")
                if observations is not None:
                    observations.append({"monotonic_seconds": time.monotonic(), "rss_bytes": observed["rss_bytes"]})
            for key, _ in selector.select(min(.1, remaining)):
                stream, label = key.fileobj, key.data
                if label == "stdin":
                    try:
                        position += os.write(stream.fileno(), request[position:position + 65536])
                    except BrokenPipeError:
                        selector.unregister(stream); stream.close()
                        raise ValueError("native_request_not_consumed") from None
                    if position == len(request):
                        selector.unregister(stream); stream.close()
                else:
                    block = os.read(stream.fileno(), 65536)
                    if not block:
                        selector.unregister(stream); stream.close()
                        continue
                    outputs[label].extend(block)
                    maximum = MAX_OUTPUT_BYTES if label == "stdout" else MAX_LOG_BYTES
                    _require(len(outputs[label]) <= maximum, "native_" + label + "_byte_bound")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("native_vocabulary_deadline")
    return child.wait(timeout=remaining), {key: bytes(value) for key, value in outputs.items()}


def _save(path, value):
    with Path(path).open("xb") as stream:
        stream.write(_wire(value) + b"\n"); stream.flush(); os.fsync(stream.fileno())


def run_vocab_probe(rows, *, worker_path, worker_sha256, worker_source_sha256, model_path,
                    output_directory, deadline_seconds=120.):
    """Run real metadata/tokenization, retaining no training authority.

    ``worker_sha256`` is a build artifact pin, not a caller-provided model or
    resource attestation. The outer resource guardian must reserve this process.
    A successful receipt cannot be passed to ``embed_rows`` to enable training.
    """
    rows = validate_rows(rows)
    _require(type(deadline_seconds) in {int, float} and math.isfinite(deadline_seconds)
             and 0 < deadline_seconds <= 300, "bounded_native_deadline_required")
    for digest in (worker_sha256, worker_source_sha256):
        _require(type(digest) is str and len(digest) == 64
                 and all(c in "0123456789abcdef" for c in digest), "worker_digest_required")
    worker, model, output = Path(worker_path), Path(model_path), Path(output_directory)
    _require(worker.is_absolute() and model.is_absolute() and output.is_absolute(), "absolute_native_paths_required")
    _require(not worker.is_symlink() and not model.is_symlink(), "native_leaf_symlink_refused")
    worker_identity = _identity(worker.stat())
    _require(worker_identity["bytes"] <= 32 * 1024 * 1024, "worker_binary_byte_bound")
    _require(_sha_file(worker) == worker_sha256, "worker_build_digest_changed")
    source_pin = _sha_file(__file__)
    output.mkdir(exist_ok=False)
    owner = {"pid": os.getpid(), "thread_id": threading.get_native_id()}
    nonce = secrets.token_hex(32)
    request = _wire({"schema": "native-source4096-worker-request/v1", "nonce": nonce, "rows": rows}) + b"\n"
    started = time.monotonic()
    deadline = started + float(deadline_seconds)
    child = identity = cleanup = None
    model_fd = None
    try:
        model_fd = os.open(model, os.O_RDONLY | os.O_NOFOLLOW)
        model_identity = _identity(os.fstat(model_fd))
        command = [str(worker), "--model-fd", str(model_fd), "--mode", "vocab", "--nonce", nonce,
                   "--deadline-seconds", str(math.ceil(deadline_seconds))]
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "CUDA_VISIBLE_DEVICES": "",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, pass_fds=(model_fd,), start_new_session=True)
        identity = _process(child.pid)
        _require(identity and identity["parent_pid"] == owner["pid"] and identity["group_pid"] == child.pid,
                 "native_child_not_owned")
        _require(_sha_file(f"/proc/{child.pid}/exe") == worker_sha256, "executed_binary_changed")
        observations = []
        code, streams = _exchange(child, request, deadline, observations)
        for name, raw in streams.items():
            with (output / (name + ".log")).open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        _require(code == 0, "native_vocabulary_exit_nonzero")
        _require(streams["stdout"].endswith(b"\n"), "native_closing_line_incomplete")
        records = [_decode(line) for line in streams["stdout"].splitlines()]
        validated = validate_vocab_records(records, rows=rows, nonce=nonce,
            request_sha256=hashlib.sha256(request).hexdigest(), worker_source_sha256=worker_source_sha256,
            pid=child.pid, parent_pid=owner["pid"], birth=identity["birth"],
            executable=str(worker.resolve()), model_identity=model_identity)
        _require(owner == {"pid": os.getpid(), "thread_id": threading.get_native_id()}, "native_owner_changed")
        _require(model_identity == _identity(os.fstat(model_fd)) == _identity(model.stat()), "native_model_file_changed")
        _require(worker_identity == _identity(worker.stat()) and _sha_file(worker) == worker_sha256,
                 "native_worker_changed")
        _require(_sha_file(__file__) == source_pin, "native_owner_source_changed")
        cleanup = _cleanup(child, identity)
        receipt = {"schema": SCHEMA, "complete": True, "owner": owner, "child": identity,
            "operation_nonce": nonce, "source_owner_sha256": source_pin,
            "worker_sha256": worker_sha256, "worker_source_sha256": worker_source_sha256,
            "worker_file_identity": worker_identity,
            "model_file_identity": model_identity, "model_content_hash_verified": False,
            "model_weights_allocated": False, "vectors_produced": 0, "training_executed": False,
            "qualified": False, "admitted": False, "proof_authority": False,
            "production_embedding_allowed": False, "native_service_mutated": False,
            "native_child_rss_limit_bytes": 1024**3,
            "sampled_native_child_max_rss_bytes": max((row["rss_bytes"] for row in observations), default=0),
            "native_child_rss_observation_count": len(observations), "rss_scope": "sampled, not allocator peak",
            "elapsed_seconds": time.monotonic() - started, "cleanup": cleanup, **validated}
        _save(output / "receipt.json", receipt)
        return receipt
    except BaseException as error:
        cleanup_error = None
        if child is not None and identity is not None:
            try: cleanup = _cleanup(child, identity)
            except BaseException as exc: cleanup_error = type(exc).__name__
        elif child is not None:
            # No request bytes were sent before identity capture. The worker
            # cannot enter native model loading on this path.
            child.kill(); child.wait(timeout=3)
            cleanup = {"leader_reaped": True, "request_sent": False}
        _save(output / "failure.json", {"schema": SCHEMA, "complete": False,
            "error_type": type(error).__name__, "error": str(error)[:512], "owner": owner,
            "child": identity, "cleanup": cleanup, "cleanup_error": cleanup_error,
            "elapsed_seconds": time.monotonic() - started, "training_executed": False,
            "production_embedding_allowed": False})
        raise
    finally:
        if model_fd is not None: os.close(model_fd)
        if child is not None:
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None and not stream.closed: stream.close()


def validate_vocab_records(records, *, rows, nonce, request_sha256, worker_source_sha256,
                           pid, parent_pid, birth, executable, model_identity):
    """Validate metadata/token IDs only; a dictionary never grants execution."""
    rows = validate_rows(rows)
    _require(type(records) is list and len(records) == len(rows) + 2, "native_record_count")
    common = {"schema", "nonce", "request_sha256", "worker_source_sha256",
              "admitted", "qualified", "proof_authority", "source_semantics_verified"}
    entry_keys = common | {"mode", "model_fd", "model_identity", "process", "requested_profile",
                           "source_rows", "model_content_hash_verified_by_worker", "model_loaded"}
    row_keys = common | {"index", "id", "source_sha256", "token_ids", "token_count", "add_special",
                         "parse_special", "truncated", "chat_template_applied", "geometry",
                         "full_forward_executed", "model_identity", "process"}
    closing_keys = common | {"mode", "complete", "rows_emitted", "native_tokens_evaluated", "geometry",
                             "model_identity", "process", "model_and_context_freed",
                             "inherited_fd_still_parent_owned", "full_forward_executed",
                             "model_content_hash_verified_by_worker"}
    expected_model = {key: model_identity[key] for key in ("device", "inode", "bytes")}
    for field in ("mtime", "ctime"):
        expected_model[field + "_seconds"], expected_model[field + "_nanoseconds"] = divmod(model_identity[field + "_ns"], 10**9)
    expected_process = {"pid": pid, "ppid": parent_pid, "birth_ticks": birth, "executable": executable}
    for index, record in enumerate(records):
        keys = entry_keys if index == 0 else closing_keys if index == len(records) - 1 else row_keys
        _require(type(record) is dict and set(record) == keys, "closed_native_record_required")
        _require(record["nonce"] == nonce and record["request_sha256"] == request_sha256
                 and record["worker_source_sha256"] == worker_source_sha256, "native_operation_binding_changed")
        _require(all(record[key] is False for key in ("admitted", "qualified", "proof_authority", "source_semantics_verified")),
                 "native_record_overclaims_authority")
        # JSON booleans cannot stand in for integer process or model fields.
        _require(_wire(record["model_identity"]) == _wire(expected_model)
                 and _wire(record["process"]) == _wire(expected_process), "native_identity_fence_changed")
    entry, closing = records[0], records[-1]
    _require(entry["schema"] == "native-source4096-worker-entry/v1"
             and entry["mode"] == "vocab" and type(entry["model_fd"]) is int and entry["model_fd"] >= 3
             and type(entry["source_rows"]) is int and entry["source_rows"] == len(rows)
             and entry["model_loaded"] is False and entry["model_content_hash_verified_by_worker"] is False,
             "native_vocabulary_entry")
    expected_profile = {"schema": "native-source4096-worker-description/v1", "modes": ["vocab", "embed"],
        "profile": "leanstral4096:cpu1:last:l2:single-sequence:tokens512:v1",
        "dimension": 4096, "context_limit": 512, "batch_limit": 512, "ubatch_limit": 512,
        "sequence_count": 1, "threads": 1, "requested_gpu_layers": 0, "add_special": True,
        "parse_special": False, "request_source_only": True,
        "model_content_hash_verified_by_worker": False, "full_forward_executed": False}
    _require(_wire(entry["requested_profile"]) == _wire(expected_profile), "native_requested_profile_changed")
    geometry = closing["geometry"]
    _require(type(geometry) is dict and type(geometry.get("vocabulary_size")) is int
             and 1 <= geometry["vocabulary_size"] <= 2**24, "native_vocabulary_geometry")
    architecture = geometry.get("metadata_architecture")
    _require(type(architecture) is str and re.fullmatch(r"[a-z0-9_]{1,64}", architecture), "native_metadata_architecture")
    output_width = geometry.get("metadata_embedding_length_out")
    _require(output_width is None or type(output_width) is int and output_width == 4096,
             "native_declared_output_width_differs")
    expected_geometry = {"native_input_dimension": None, "native_output_dimension": None,
        "metadata_architecture": architecture, "metadata_embedding_length": 4096,
        "metadata_embedding_length_out": output_width,
        "metadata_embedding_length_key": architecture + ".embedding_length",
        "metadata_embedding_length_out_key": architecture + ".embedding_length_out",
        "vocabulary_size": geometry["vocabulary_size"], "actual_context": None, "actual_batch": None,
        "actual_ubatch": None, "actual_sequences": None, "actual_pooling": None, "context_created": False}
    _require(_wire(geometry) == _wire(expected_geometry), "native_vocabulary_context_created_or_width_changed")
    observations = []
    for index, (source, record) in enumerate(zip(rows, records[1:-1])):
        _require(record["schema"] == "native-source4096-worker-row/v1" and type(record["index"]) is int
                 and record["index"] == index and record["id"] == source["id"]
                 and record["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(),
                 "native_literal_source_binding_changed")
        _require(record["add_special"] is True and all(record[key] is False for key in
                 ("parse_special", "truncated", "chat_template_applied", "full_forward_executed")),
                 "native_tokenizer_profile_changed")
        tokens = record["token_ids"]
        _require(type(tokens) is list and 1 <= len(tokens) <= 512
                 and all(type(token) is int and 0 <= token < geometry["vocabulary_size"] for token in tokens)
                 and type(record["token_count"]) is int and record["token_count"] == len(tokens),
                 "native_untruncated_token_count")
        _require(_wire(record["geometry"]) == _wire(geometry), "native_row_geometry_changed")
        observations.append({"id": source["id"], "source_sha256": record["source_sha256"],
            "token_ids": tokens, "token_count": len(tokens), "token_input_sha256": hashlib.sha256(_wire(tokens)).hexdigest()})
    _require(closing["schema"] == "native-source4096-worker-closing/v1" and closing["mode"] == "vocab"
             and closing["complete"] is True and type(closing["rows_emitted"]) is int and closing["rows_emitted"] == len(rows)
             and type(closing["native_tokens_evaluated"]) is int and closing["native_tokens_evaluated"] == 0
             and closing["model_and_context_freed"] is True and closing["inherited_fd_still_parent_owned"] is True
             and closing["full_forward_executed"] is False and closing["model_content_hash_verified_by_worker"] is False,
             "native_vocabulary_closing_incomplete")
    return {"sample_count": len(rows), "geometry": geometry, "rows": observations,
            "native_tokenizer_executed": True, "native_tokens_evaluated": 0,
            "min_source_tokens": min(row["token_count"] for row in observations),
            "max_source_tokens": max(row["token_count"] for row in observations)}
