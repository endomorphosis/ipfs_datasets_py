"""Explicit local-process MCP++ transport for immutable federation work.

The native TaskQueue remains the only claim/completion owner. This adapter
launches one bounded peer per delivery; private request receipts make a retry
idempotent across peer restarts. No remote discovery or numerical authority is
provided by transport. The datasets federation owner replays all result bytes.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import sysconfig
import threading
import time
import uuid

from .codebase_federated_dispatch import _require, _wire, TASK_TYPE, codebase_dispatch_request_sha256
from ipfs_accelerate_py.mcp_server.mcplusplus.p2p_framing import encode_jsonrpc_frame, decode_jsonrpc_frame

SCHEMA = "codebase-local-peer-transport@1"
TOOL = "codebase_federated_artifact"
MAX_FRAME = 2 * 1024 * 1024
FALSE = {"numerical_authority": False, "proof_authority": False,
         "model_admission": False, "remote_transport_qualified": False}


def pins():
    names = (__name__, "ipfs_accelerate_py.p2p_tasks.codebase_peer_worker",
             "ipfs_accelerate_py.p2p_tasks.mcp_p2p",
             "ipfs_accelerate_py.mcp_server.mcplusplus.p2p_framing",
             "ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch",
             "ipfs_datasets_py.logic.backends.codebase_process",
             "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler")
    return {name: hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
            for name in names}


def _sha(value):
    return hashlib.sha256(_wire(value, MAX_FRAME)).hexdigest()


def frames(raw):
    """Decode a bounded complete stream; reject duplicate keys and nonfinite JSON."""
    _require(type(raw) is bytes and len(raw) <= 2 * MAX_FRAME + 8, "bounded peer frames required")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate peer frame key")
            result[key] = value
        return result
    result = []
    while raw:
        value, consumed = decode_jsonrpc_frame(raw, max_frame_bytes=MAX_FRAME)
        strict = json.loads(raw[4:consumed], object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite frame")))
        _require(strict == value, "peer frame representation differs")
        _wire(strict, MAX_FRAME)
        result.append(strict)
        _require(len(result) <= 2, "unexpected extra peer frame")
        raw = raw[consumed:]
    return result


def messages(task, profile_id, nonce):
    return [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "profile": "mcp++/p2p-transport", "peer_profile": profile_id, "nonce": nonce}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": TOOL, "arguments": {"task": task, "nonce": nonce}}}]


class _RawExecutor:
    """Preserve bounded binary stdout while the canonical runner owns lifecycle."""
    def __init__(self):
        from ipfs_datasets_py.logic.backends.codebase_process import SubprocessExecutor
        self.native = SubprocessExecutor()
        self.stdout = b""

    def execute(self, invocation, cancellation=None):
        result = self.native.execute(invocation, cancellation)
        self.stdout = result.stdout
        return result


class CodebasePeerWorker:
    """An explicit profile, native CAS and private receipt directory; no listener.

    Each call requires an owner execution context. The inherited parent must
    reserve capacity for control plus a peer and its numerical subprocess.
    No lease keys are retained in public transport receipts.
    """
    def __init__(self, artifacts, receipt_root, *, profile_id):
        from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
        _require(type(artifacts) is ImmutableCAS, "native immutable artifact store required")
        _require(type(profile_id) is str and 0 < len(profile_id) <= 96
                 and all(c.isascii() and (c.isalnum() or c in "-._") for c in profile_id),
                 "explicit bounded local peer identity required")
        root = Path(receipt_root)
        _require(root.is_absolute() and root.resolve() == root, "canonical peer receipt directory required")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require(root.stat().st_uid == os.getuid() and root.stat().st_mode & 0o077 == 0,
                 "owner-private peer receipt directory required")
        self.artifacts, self.receipt_root, self.profile_id = artifacts, root, profile_id
        self._context = ContextVar("codebase-peer-context:" + profile_id, default=None)
        self._lock = threading.Lock()
        self.receipts = []

    @contextmanager
    def execution_context(self, *, parent_lease, cancel_event, remaining, memory_mb, limits):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLease, get_global_resource_scheduler
        from ipfs_datasets_py.logic.software_contracts.codebase_source_training import CodebaseFeatureTrainingLimits
        _require(type(parent_lease) is ResourceLease and parent_lease.token.state_path == str(get_global_resource_scheduler().state_path)
                 and callable(remaining) and callable(getattr(cancel_event, "is_set", None))
                 and type(memory_mb) is int and memory_mb >= 1024 and type(limits) is CodebaseFeatureTrainingLimits,
                 "live default-host parent and explicit bounded execution context required")
        token = self._context.set((parent_lease, cancel_event, remaining, memory_mb, limits))
        try:
            yield self
        finally:
            self._context.reset(token)

    def __call__(self, task):
        _require(self._lock.acquire(blocking=False), "peer already has an active delivery")
        try:
            return self._deliver(task)
        finally:
            self._lock.release()

    def _deliver(self, task):
        from ipfs_datasets_py.logic.backends.codebase_process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
        from ipfs_datasets_py.logic.software_contracts import codebase_federated_artifacts as artifacts
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
        context = self._context.get()
        _require(context is not None, "peer delivery requires live owner resource context")
        _require(len(self.receipts) < 128, "peer receipt inventory exhausted")
        parent, signal, remaining, memory_mb, limits = context
        task = json.loads(_wire(task, MAX_FRAME))
        _require(set(task) == {"task_id", "task_type", "model_name", "payload", "assigned_worker", "dispatch"}
                 and task["task_type"] == TASK_TYPE, "closed native queue task required")
        request = codebase_dispatch_request_sha256(task["payload"], task["model_name"])
        dispatch = task["dispatch"]
        _require(dispatch["request_sha256"] == request and dispatch["queue_task_id"] == task["task_id"]
                 and dispatch["worker_id"] == task["assigned_worker"], "queue claim/task identity differs")
        timeout = min(remaining(), dispatch["deadline_unix_s"] - time.time(), 300.0)
        _require(timeout > 0 and not signal.is_set(), "peer delivery expired or cancelled")
        deadline = min(time.time() + timeout, dispatch["deadline_unix_s"])
        before_pins, artifact_pins = pins(), artifacts.codebase_artifact_implementation()
        nonce = uuid.uuid4().hex
        expected = messages(task, self.profile_id, nonce)
        raw = b"".join(encode_jsonrpc_frame(message, max_frame_bytes=MAX_FRAME) for message in expected)
        script = Path(__file__).with_name("codebase_peer_worker.py")
        import ipfs_datasets_py
        libraries = [str(Path(__file__).resolve().parents[2]), str(Path(ipfs_datasets_py.__file__).resolve().parent.parent),
                     str(Path(sysconfig.get_path("purelib")).resolve())]
        torch = importlib.util.find_spec("torch")
        _require(torch is not None and torch.origin is not None, "installed native numerical dependency required")
        libraries.append(str(Path(torch.origin).resolve().parent.parent))
        with parent.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=2, memory_mb=memory_mb + 512,
                child_process_slots=2, timeout=timeout, cancel_event=signal,
                request_id="codebase-local-peer:" + self.profile_id) as lease:
            timeout = min(remaining(), deadline - time.time())
            _require(timeout > 0 and not signal.is_set(), "peer deadline exceeded during admission")
            config = {"schema": SCHEMA, "profile_id": self.profile_id, "nonce": nonce,
                "messages_sha256": _sha(expected), "task_sha256": _sha(task), "implementation": before_pins,
                "artifact_implementation": artifact_pins, "artifacts": str(self.artifacts.root.resolve()),
                "max_object_bytes": self.artifacts.max_object_bytes, "receipt_root": str(self.receipt_root),
                "parent_token": asdict(lease.token), "deadline_unix_s": deadline,
                "memory_mb": memory_mb, "limits": asdict(limits)}
            executor = _RawExecutor()
            runner = BoundedToolRunner(executor=executor, executable_roots=(Path(sys.executable).resolve().parent,),
                base_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                    "CUDA_VISIBLE_DEVICES": "", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                    # The runner isolates TMPDIR; preserve the admitted host
                    # authority instead of creating a per-workspace scheduler.
                    "IPFS_DATASETS_RESOURCE_SCHEDULER_PATH": lease.token.state_path})
            timeout = min(remaining(), deadline - time.time())
            _require(timeout > 0 and not signal.is_set(), "peer deadline exceeded before launch")
            process = runner.run(ToolRunRequest(argv=(str(Path(sys.executable).resolve()), "-I", "-B", str(script),
                    json.dumps(list(dict.fromkeys(libraries))), "{workspace}/peer.json"),
                stdin=raw, input_files={"peer.json": _wire(config, MAX_FRAME)},
                limits=ToolRunLimits(timeout_seconds=timeout, resident_memory_bytes=(memory_mb + 512) * 1024**2,
                    max_input_bytes=3 * MAX_FRAME, max_output_bytes=3 * MAX_FRAME,
                    max_workspace_bytes=max(4 * MAX_FRAME, 2 * limits.max_candidate_bytes)),
                secrets=(lease.token.lease_key, nonce)), cancellation=lease.combined_cancellation_signal(signal))
            receipt = {"schema": SCHEMA, "profile_id": self.profile_id, "task_sha256": _sha(task),
                "request_sha256": request, "queue_dispatch": dispatch, "implementation": before_pins,
                "parent_lease_id": parent.lease_id, "delivery_lease_id": lease.lease_id,
                "process": process.to_dict(), "authority": dict(FALSE), "transport": "local-process-mcp++-framed-stdio"}
            # stdout contains private handshake nonce; retain only its digest.
            receipt["process"]["stdout"] = "[bounded binary protocol; digest retained]"
            receipt["response_sha256"] = hashlib.sha256(executor.stdout).hexdigest()
            self.receipts.append(receipt)
            _require(process.ok and process.workspace_cleaned and not process.output_truncated,
                     "local peer process unavailable, cancelled, or failed: " + process.error + " " + process.stderr[-1024:])
            responses = frames(executor.stdout)
            receipt["protocol_errors"] = [r["error"] for r in responses if "error" in r]
            _require(len(responses) == 2 and responses[0].get("id") == 1
                     and responses[0].get("result", {}).get("server", {}).get("peer_id") == self.profile_id
                     and responses[1].get("id") == 2 and "result" in responses[1],
                     "peer handshake or tool result failed: " + str(receipt["protocol_errors"]) + " " + process.stderr[-1024:])
            result = responses[1]["result"]["content"]
            _require(set(result) == {"schema", "profile_id", "nonce", "task_sha256", "peer_pid", "peer_lease_id",
                         "numerical_invocations", "result", "implementation", "authority"}
                     and result["schema"] == SCHEMA and result["profile_id"] == self.profile_id and result["nonce"] == nonce
                     and result["peer_pid"] == process.pid and result["task_sha256"] == _sha(task)
                     and result["implementation"] == before_pins and result["authority"] == FALSE,
                     "peer response custody binding differs")
            _require(type(result["numerical_invocations"]) is int and result["numerical_invocations"] in (0, 1),
                     "bounded peer invocation count required")
            artifacts.validate_codebase_artifact_result(task["payload"], result["result"], self.artifacts, limits=limits)
            _require(pins() == before_pins and artifacts.codebase_artifact_implementation() == artifact_pins,
                     "peer producer changed during execution")
            remaining()
            _require(not signal.is_set(), "peer completed after owner cancellation")
            receipt.update(peer_pid=result["peer_pid"], peer_lease_id=result["peer_lease_id"],
                           numerical_invocations=result["numerical_invocations"], result_sha256=_sha(result["result"]),
                           delivery_verified=True)
            return result["result"]
