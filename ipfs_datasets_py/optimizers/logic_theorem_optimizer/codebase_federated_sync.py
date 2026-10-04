"""Typed CodebaseIR work declarations and an optional gradient-sync boundary.

Federation is the default.  These declarations perform no fitting, queue
submission, transport, collective operation, or source observation.  A lease
attempt/fence is a recorded binding; only the native registry owner can decide
whether that lease is still live.  Gradient synchronization requires the
existing controller's independently qualified injected backend, without a
fallback to local training or FedAvg.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
from typing import Any

from .autoencoder_federated import ClientSpec, FederatedRound, ParameterSpec
from .autoencoder_training_sync import (
    GradientBucketSpec, TrainingMode, TrainingRoundBinding, TrainingSyncController, TrainingSyncError,
)

WORK_SCHEMA = "codebase-federated-work-binding@1"
WORK_PROFILE = "source-bound-codebase-federation-work@1"
TASK_SCHEMA = "codebase-federated-artifact-task-declaration@1"
CODEBASE_RUNTIME_PROFILE = "codebase_ir/source_bound_feature_v1"
CODEBASE_ARCHITECTURE = "codebase-source-feature-float64@1"
_MAX_BYTES = 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
    "proof_authority": False, "source_runtime_semantics_verified": False,
    "admission_authority": False, "completion_authority": False,
    "promotion_performed": False, "network_authority": False}
_FIELDS = {"schema", "profile", "round", "round_sha256", "model_id", "lineage_id",
    "base_version_id", "base_sha256", "source_head", "client_id", "local_target_sha256",
    "sample_count", "attempt", "fence", "authority"}


class CodebaseFederatedSyncError(TrainingSyncError):
    """A declaration differs from its native numerical/source/work binding."""


def _require(condition, message):
    if not condition:
        raise CodebaseFederatedSyncError(message)


def _text(value, name, maximum=512):
    _require(type(value) is str and value and value == value.strip()
        and len(value.encode("utf-8")) <= maximum
        and all(ord(char) >= 32 and ord(char) != 127 for char in value), "invalid bounded " + name)
    return value


def _sha(value, name):
    _require(type(value) is str and _SHA.fullmatch(value) is not None, "invalid SHA-256 " + name)
    return value


def _integer(value, name, minimum=1):
    _require(type(value) is int and minimum <= value < 2**63, "invalid exact bounded " + name)
    return value


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodebaseFederatedSyncError("bounded inert native JSON required") from exc
    _require(len(raw) <= _MAX_BYTES, "CodebaseIR work declaration exceeds its byte bound")
    return raw


def _round_from_manifest(value):
    _require(type(value) is dict, "native round manifest required")
    try:
        fields = {name: value[name] for name in FederatedRound.__dataclass_fields__}
        fields["parameters"] = tuple(ParameterSpec(**row) for row in value["parameters"])
        fields["clients"] = tuple(ClientSpec(**row) for row in value["clients"])
        result = FederatedRound(**fields)
    except (KeyError, TypeError, ValueError) as exc:
        raise CodebaseFederatedSyncError("malformed native round manifest") from exc
    _require(_wire(value) == _wire(result.manifest), "native round fields/layout/authority differ")
    _require(result.dimension == 8 and result.runtime_profile == CODEBASE_RUNTIME_PROFILE
        and result.architecture == CODEBASE_ARCHITECTURE, "exact 8D source-bound CodebaseIR profile required")
    _require(len(result.parameters) == 4 and all(spec.dtype == "float64" for spec in result.parameters),
             "four native float64 CodebaseIR parameters required")
    shapes = sorted(spec.shape for spec in result.parameters)
    widths = {shape[0] for shape in shapes if len(shape) == 2 and shape[1] == 8}
    _require(any(1 <= width <= 4096 and shapes == sorted(((width, 8), (8,), (8, width), (width,)))
                 for width in widths), "CodebaseIR encoder/decoder layout differs")
    actual = {spec.name: spec.shape for spec in result.parameters}
    _require(any(actual == {"encoder.weight": (width, 8), "encoder.bias": (8,),
                           "decoder.weight": (8, width), "decoder.bias": (width,)} for width in widths),
             "exact CodebaseIR parameter names and shapes required")
    _require(len(result.clients) <= 4096, "bounded synchronization membership required")
    for client in result.clients:
        _text(client.client_id, "synchronization participant", 128)
    for spec in result.parameters:
        # The native synchronization owner has a stricter bucket ID bound.
        _text(spec.name, "parameter bucket", 128)
        GradientBucketSpec(spec.name, spec.shape, spec.dtype)
    return result


def _validate(value):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    _require(type(value) is dict and set(value) == _FIELDS
        and value["schema"] == WORK_SCHEMA and value["profile"] == WORK_PROFILE,
        "closed versioned CodebaseIR work binding required")
    _require(type(value["authority"]) is dict and set(value["authority"]) == set(_FALSE)
        and all(flag is False for flag in value["authority"].values()), "work declarations cannot grant authority")
    round_spec = _round_from_manifest(value["round"])
    try:
        head = CodebaseHead.from_dict(value["source_head"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CodebaseFederatedSyncError("native complete source head required") from exc
    _require(head.to_dict() == value["source_head"], "source head reconstruction differs")
    for name in ("model_id", "lineage_id", "base_version_id", "client_id"):
        _text(value[name], name)
    for name in ("round_sha256", "base_sha256", "local_target_sha256"):
        _sha(value[name], name)
    for name in ("sample_count", "attempt", "fence"):
        _integer(value[name], name)
    _require(value["round_sha256"] == round_spec.round_sha256
        and value["model_id"] == round_spec.model_id and value["lineage_id"] == round_spec.lineage_id
        and value["base_sha256"] == round_spec.base_sha256, "work differs from the exact round/model lineage")
    client = next((client for client in round_spec.clients if client.client_id == value["client_id"]), None)
    _require(client is not None and client.sample_count == value["sample_count"]
        and client.local_data_sha256 == value["local_target_sha256"], "work differs from approved client payload/count")
    return round_spec


@dataclass(frozen=True, slots=True)
class CodebaseFederatedWorkBinding:
    """Immutable recorded binding, without lease liveness or execution trust."""
    canonical_bytes: bytes

    def __post_init__(self):
        _require(type(self.canonical_bytes) is bytes and len(self.canonical_bytes) <= _MAX_BYTES,
                 "bounded immutable work bytes required")
        try:
            value = json.loads(self.canonical_bytes)
        except (ValueError, UnicodeError) as exc:
            raise CodebaseFederatedSyncError("invalid work JSON") from exc
        _validate(value)
        _require(_wire(value) == self.canonical_bytes, "canonical work bytes required")

    @classmethod
    def from_dict(cls, value, *, expected_sha256=None):
        _require(type(value) is dict, "exact work mapping required")
        raw = _wire(value)
        if expected_sha256 is not None:
            _sha(expected_sha256, "expected work")
            _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "work differs from its expected SHA-256")
        return cls(raw)

    def to_dict(self):
        # Revalidate even a frozen object altered by unsafe setter bypasses.
        return json.loads(type(self)(self.canonical_bytes).canonical_bytes)

    @property
    def sha256(self):
        return hashlib.sha256(type(self)(self.canonical_bytes).canonical_bytes).hexdigest()

    def validate_round(self, round_spec):
        _require(type(round_spec) is FederatedRound, "native FederatedRound required")
        normalized = _round_from_manifest(round_spec.manifest)
        _require(normalized.manifest == self.to_dict()["round"], "work belongs to another exact round")
        return normalized


def bind_codebase_federated_work(round_spec: FederatedRound, *, base_version_id: str, source_head: Any,
    client_id: str, local_target_sha256: str, sample_count: int, attempt: int, fence: int) -> CodebaseFederatedWorkBinding:
    """Bind one registered worker attempt to approved source-local payload data.

    ``local_target_sha256`` is the approved ClientSpec.local_data_sha256 of the
    complete source/head/targets/count/tuning/configuration payload.  It is not
    merely a target-list digest.  The coordinator must verify its actual bytes
    and native lease liveness before executing or completing work.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    _require(type(round_spec) is FederatedRound and type(source_head) is CodebaseHead,
             "native round and complete source head required")
    round_spec = _round_from_manifest(round_spec.manifest)
    return CodebaseFederatedWorkBinding.from_dict({"schema": WORK_SCHEMA, "profile": WORK_PROFILE,
        "round": round_spec.manifest, "round_sha256": round_spec.round_sha256,
        "model_id": round_spec.model_id, "lineage_id": round_spec.lineage_id,
        "base_version_id": base_version_id, "base_sha256": round_spec.base_sha256,
        "source_head": source_head.to_dict(), "client_id": client_id, "local_target_sha256": local_target_sha256,
        "sample_count": sample_count, "attempt": attempt, "fence": fence, "authority": dict(_FALSE)})


def _work(value):
    _require(type(value) is CodebaseFederatedWorkBinding, "native CodebaseFederatedWorkBinding required")
    return CodebaseFederatedWorkBinding(value.canonical_bytes)


def derive_codebase_sync_binding(work: CodebaseFederatedWorkBinding, *, membership_epoch: int = 0) -> TrainingRoundBinding:
    """Derive common-peer session identity; work attempts remain separately bound."""
    work = _work(work)
    data = work.to_dict()
    round_spec = _validate(data)
    _integer(membership_epoch, "membership_epoch", minimum=0)
    return TrainingRoundBinding("codebase-sync:" + round_spec.round_sha256,
        "codebase-round:" + round_spec.round_sha256, round_spec.base_sha256, round_spec.layout_sha256,
        "codebase-feature-float64-local-adam@1", membership_epoch,
        tuple(client.client_id for client in round_spec.clients))


def derive_codebase_gradient_buckets(work: CodebaseFederatedWorkBinding) -> tuple[GradientBucketSpec, ...]:
    round_spec = _validate(_work(work).to_dict())
    return tuple(GradientBucketSpec(spec.name, spec.shape, spec.dtype) for spec in round_spec.parameters)


def create_codebase_sync_controller(work: CodebaseFederatedWorkBinding, *, mode: TrainingMode = TrainingMode.FEDERATED,
    backend=None, verify_backend=None, clock=time.time) -> TrainingSyncController:
    """Construct the existing optional controller; do not join or dispatch work."""
    work = _work(work)
    derive_codebase_sync_binding(work)
    derive_codebase_gradient_buckets(work)
    qualifier = verify_backend
    if mode is TrainingMode.GRADIENT_SYNCHRONIZED and callable(verify_backend):
        def qualifier(selected, capabilities):
            return "float64" in capabilities.dtypes and verify_backend(selected, capabilities) is True
    return TrainingSyncController(mode=mode, backend=backend, verify_backend=qualifier, clock=clock)


@dataclass(frozen=True, slots=True)
class CodebaseArtifactReference:
    """Inert raw-file CID/SHA/size assertion; actual bytes are not fetched."""
    sha256: str
    cidv1: str
    bytes: int

    def __post_init__(self):
        from ipfs_datasets_py.logic.software_contracts.content import validate_cid
        from multiformats import CID
        _sha(self.sha256, "artifact")
        _integer(self.bytes, "artifact bytes")
        _require(self.bytes <= 512 * 1024 * 1024, "artifact size exceeds declared profile")
        try:
            validate_cid(self.cidv1, codecs={"raw"})
            _require(CID.decode(self.cidv1).raw_digest.hex() == self.sha256,
                     "raw artifact CID differs from SHA-256")
        except (TypeError, ValueError) as exc:
            raise CodebaseFederatedSyncError("invalid raw artifact reference") from exc

    def to_dict(self):
        copied = type(self)(self.sha256, self.cidv1, self.bytes)
        return {"sha256": copied.sha256, "cidv1": copied.cidv1, "bytes": copied.bytes}

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == {"sha256", "cidv1", "bytes"}, "closed artifact reference required")
        return cls(**value)


def make_codebase_federated_task(work: CodebaseFederatedWorkBinding, *, round_artifact: CodebaseArtifactReference,
    base_artifact: CodebaseArtifactReference, local_payload_artifact: CodebaseArtifactReference) -> dict[str, Any]:
    """Describe a future existing task route using artifact references only.

    No peer address, queue, MCP server, worker handler or tensor transport is
    activated.  Route existence does not mean this worker type is deployed.
    """
    work = _work(work)
    data = work.to_dict()
    references = {}
    for name, reference, expected in (("round", round_artifact, data["round_sha256"]),
        ("base_checkpoint", base_artifact, data["base_sha256"]),
        ("local_payload", local_payload_artifact, data["local_target_sha256"])):
        _require(type(reference) is CodebaseArtifactReference, "native artifact reference required")
        references[name] = reference.to_dict()
        _require(references[name]["sha256"] == expected, "artifact reference differs from bound " + name)
    result = {"schema": TASK_SCHEMA, "route": {"tool_category": "p2p", "tool_name": "p2p_taskqueue_submit",
        "implementation": "ipfs_accelerate_py.mcp_server.tools.p2p.native_p2p_tools.p2p_taskqueue_submit",
        "client": "ipfs_accelerate_py.p2p_tasks.client.submit_task_with_info",
        "task_type": "codebase_ir.federated_local_update@1", "model_name": data["model_id"]},
        "payload": {"work_binding": data, "work_sha256": work.sha256, "artifacts": references},
        "transport": "artifact_references_only_no_inline_tensors",
        "network_executed": False, "worker_dispatch_qualified": False,
        "gradient_backend_qualified": False, "authority": dict(_FALSE)}
    _wire(result)
    return result


__all__ = ["WORK_SCHEMA", "WORK_PROFILE", "TASK_SCHEMA", "CODEBASE_RUNTIME_PROFILE", "CODEBASE_ARCHITECTURE",
    "CodebaseFederatedSyncError", "CodebaseFederatedWorkBinding", "CodebaseArtifactReference",
    "bind_codebase_federated_work", "derive_codebase_sync_binding", "derive_codebase_gradient_buckets",
    "create_codebase_sync_controller", "make_codebase_federated_task"]
