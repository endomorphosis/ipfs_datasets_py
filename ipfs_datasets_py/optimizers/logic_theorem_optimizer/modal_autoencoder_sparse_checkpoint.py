"""Bounded, immutable sparse checkpoints over trusted content-addressed inputs.

A manifest contains only hashes, sizes and ordered accepted postimage patches.
The caller supplies the trusted hash-to-local-path resolver; artifacts cannot
choose paths, import classes or fetch a network resource. Each manifest edge is
one training job. Its parent undergoes normal JSON reload semantics (including
revision zero) before that job's patches, with no within-job revision rebasing.

Canonical checkpoint hashing uses the existing C-backed ``to_json`` encoding.
It avoids writing a full candidate, but still allocates its temporary JSON and
the dictionary used by ``to_dict``. This is sparse persistence, not zero-copy
checkpoint reconstruction. No publication, promotion or Lean admission occurs.
"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from .modal_autoencoder_patch_codec import (
    IDENTITY_PROFILE, MAX_PATCH_BYTES, PatchCodecError, decode_patch, replay_patch,
)


SCHEMA = "modal-autoencoder-sparse-checkpoint/v1"
RELOAD_SEMANTICS = "legacy-json-from-dict-revision-zero"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class SparseCheckpointError(ValueError):
    """Malformed, corrupt, untrusted, unsupported or over-budget checkpoint."""


@dataclass(frozen=True)
class ResolutionLimits:
    max_depth: int = 8
    max_manifest_bytes: int = 1024 * 1024
    max_checkpoint_bytes: int = 512 * 1024 * 1024
    max_patch_bytes: int = MAX_PATCH_BYTES
    max_total_patch_bytes: int = 256 * 1024 * 1024
    max_artifacts: int = 4096
    max_total_bytes: int = 4 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        ceilings = {"max_depth": 64, "max_manifest_bytes": 16 * 1024 * 1024,
                    "max_checkpoint_bytes": 4 * 1024 * 1024 * 1024,
                    "max_patch_bytes": MAX_PATCH_BYTES,
                    "max_total_patch_bytes": 4 * 1024 * 1024 * 1024,
                    "max_artifacts": 65536, "max_total_bytes": 16 * 1024 * 1024 * 1024}
        for name, ceiling in ceilings.items():
            value = getattr(self, name)
            if type(value) is not int or not (0 if name == "max_depth" else 1) <= value <= ceiling:
                raise SparseCheckpointError(f"{name} exceeds its supported bound")


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise SparseCheckpointError(f"{name} must be a lowercase SHA-256")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value < 2**63:
        raise SparseCheckpointError(f"{name} must be a bounded integer")
    return value


def artifact_ref(value: Any) -> dict[str, Any]:
    """Strip caller-owned path/metadata, retaining only immutable byte identity."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if not isinstance(value, Mapping):
        raise SparseCheckpointError("artifact reference must be a mapping")
    return {"sha256": _sha(value.get("sha256"), "artifact.sha256"),
            "bytes": _int(value.get("bytes"), "artifact.bytes", 1)}


def _strict_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"sha256", "bytes"}:
        raise SparseCheckpointError("manifest artifact reference has unknown or missing fields")
    return artifact_ref(value)


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise SparseCheckpointError("invalid bounded JSON value") from exc


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SparseCheckpointError("duplicate JSON field")
        result[key] = value
    return result


def _parse(raw: bytes) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(SparseCheckpointError("non-finite JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise SparseCheckpointError("invalid checkpoint JSON") from exc


def canonical_checkpoint_bytes(state: Any) -> bytes:
    """Exact existing candidate format, including its single trailing newline."""
    try:
        return (state.to_json() + "\n").encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise SparseCheckpointError("checkpoint cannot be canonically serialized") from exc


def checkpoint_identity(state: Any) -> dict[str, Any]:
    """Hash canonical JSON without writing it; temporary full serialization remains."""
    raw = canonical_checkpoint_bytes(state)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


_FIELDS = {"schema", "schema_version", "identity_profile", "reload_semantics", "parent", "base_version_id",
           "patches", "materialized_checkpoint", "state_identity", "result_revision", "provenance"}


def _validate_manifest(value: Any, limits: ResolutionLimits) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise SparseCheckpointError("manifest has unknown or missing fields")
    if value["schema"] != SCHEMA or value["schema_version"] != SCHEMA or value["identity_profile"] != IDENTITY_PROFILE:
        raise SparseCheckpointError("unsupported sparse checkpoint schema or identity profile")
    if value["reload_semantics"] != RELOAD_SEMANTICS:
        raise SparseCheckpointError("unsupported checkpoint reload semantics")
    _strict_ref(value["parent"])
    if not isinstance(value["base_version_id"], str) or not 1 <= len(value["base_version_id"]) <= 256:
        raise SparseCheckpointError("base_version_id must be a bounded nonempty string")
    patches = value["patches"]
    if not isinstance(patches, list) or len(patches) > limits.max_artifacts:
        raise SparseCheckpointError("patch reference count exceeds bound")
    seen: set[str] = set()
    total = 0
    for patch in patches:
        ref = _strict_ref(patch)
        if ref["bytes"] > limits.max_patch_bytes:
            raise SparseCheckpointError("patch exceeds byte bound")
        if ref["sha256"] in seen:
            raise SparseCheckpointError("duplicate patch reference")
        seen.add(ref["sha256"])
        total += ref["bytes"]
    if total > limits.max_total_patch_bytes:
        raise SparseCheckpointError("total patch bytes exceed bound")
    if _strict_ref(value["materialized_checkpoint"])["bytes"] > limits.max_checkpoint_bytes:
        raise SparseCheckpointError("materialized checkpoint exceeds byte bound")
    _sha(value["state_identity"], "state_identity")
    _int(value["result_revision"], "result_revision")
    if not isinstance(value["provenance"], dict):
        raise SparseCheckpointError("provenance must be a JSON object")
    if not patches and value["result_revision"] != 0:
        raise SparseCheckpointError("empty job cannot advance the reload revision")
    return value


def encode_manifest(*, parent: Any, base_version_id: str, patches: Any,
                    materialized_checkpoint: Any, state_identity: str,
                    result_revision: int, provenance: Mapping[str, Any] | None = None,
                    limits: ResolutionLimits = ResolutionLimits()) -> bytes:
    """Encode an immutable job manifest; replay qualification remains mandatory."""
    # Legacy full-state loaders inspect schema_version. Keep this additional
    # marker mandatory so they reject a sparse manifest instead of silently
    # normalizing its unknown fields into an empty/default full model.
    value = {"schema": SCHEMA, "schema_version": SCHEMA, "identity_profile": IDENTITY_PROFILE,
             "reload_semantics": RELOAD_SEMANTICS, "parent": artifact_ref(parent),
             "base_version_id": base_version_id, "patches": [artifact_ref(patch) for patch in patches],
             "materialized_checkpoint": artifact_ref(materialized_checkpoint),
             "state_identity": state_identity, "result_revision": result_revision,
             "provenance": dict(provenance or {})}
    raw = _json(_validate_manifest(value, limits))
    if len(raw) > limits.max_manifest_bytes:
        raise SparseCheckpointError("manifest exceeds byte bound")
    # Reparse to reject non-string keys that JSON would silently normalize.
    if _parse(raw) != value:
        raise SparseCheckpointError("manifest contains noncanonical JSON values")
    return raw


def decode_manifest(raw: bytes, *, limits: ResolutionLimits = ResolutionLimits()) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limits.max_manifest_bytes:
        raise SparseCheckpointError("manifest must be bounded nonempty bytes")
    value = _validate_manifest(_parse(raw), limits)
    if _json(value) != raw:
        raise SparseCheckpointError("manifest is not canonically encoded")
    return value


@dataclass(frozen=True)
class ResolvedCheckpoint:
    state: Any
    materialized_checkpoint: Mapping[str, Any]
    state_identity: str
    replayed_revision: int
    depth: int
    total_patch_bytes: int
    manifest: Mapping[str, Any] | None
    anchor_checkpoint: Mapping[str, Any]
    artifacts: tuple[Mapping[str, Any], ...]

    @property
    def anchor_checkpoint_bytes(self) -> int:
        return self.anchor_checkpoint["bytes"]


@dataclass(frozen=True)
class CheckpointInventory:
    """Verified artifact structure, explicitly not a reconstructed candidate.

    Sparse ``declared_materialized_checkpoint`` bytes and logical identities
    remain declarations until ``resolve_checkpoint`` replays the weights. A
    legacy full root retains its original, verified physical byte identity.
    """

    root: Mapping[str, Any]
    declared_materialized_checkpoint: Mapping[str, Any]
    depth: int
    total_patch_bytes: int
    total_bytes: int
    manifest: Mapping[str, Any] | None
    anchor_checkpoint: Mapping[str, Any]
    artifacts: tuple[Mapping[str, Any], ...]

    @property
    def semantic_replay_verified(self) -> bool:
        return False

    @property
    def weights_constructed(self) -> bool:
        return False


def _validate_legacy_inventory(data: Any) -> None:
    """Check legacy framing without normalizing or constructing model weights.

    Nested component value semantics deliberately remain the full loader's
    responsibility. JSON syntax, duplicate fields and nonfinite values have
    already been checked; this inventories the known top-level state schema.
    """
    from .modal_autoencoder import (
        MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS,
        MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
        MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS,
        MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    )

    if not isinstance(data, dict):
        raise SparseCheckpointError("checkpoint must be a JSON object")
    if str(data.get("schema_version") or MODAL_AUTOENCODER_STATE_SCHEMA_VERSION) != MODAL_AUTOENCODER_STATE_SCHEMA_VERSION:
        raise SparseCheckpointError("inventory supports qualified legacy JSON checkpoint schema only")
    if str(data.get("architecture_version") or MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION) not in MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS:
        raise SparseCheckpointError("unsupported legacy checkpoint architecture")
    if set(data) - MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS:
        raise SparseCheckpointError("full checkpoint contains unknown fields")


def _read_artifact(path: Any, ref: Mapping[str, Any], maximum: int) -> bytes:
    if ref["bytes"] > maximum:
        raise SparseCheckpointError("artifact exceeds byte bound")
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise SparseCheckpointError("trusted resolver must return an absolute local path")
        fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != ref["bytes"]:
                raise SparseCheckpointError("artifact is not a regular file of the declared size")
            raw = stream.read(ref["bytes"] + 1)
    except (OSError, TypeError) as exc:
        raise SparseCheckpointError("trusted artifact could not be read") from exc
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise SparseCheckpointError("artifact byte identity mismatch")
    return raw


def inventory_checkpoint(reference: Any, *, resolver: Callable[[Mapping[str, Any]], Any],
                         limits: ResolutionLimits = ResolutionLimits()) -> CheckpointInventory:
    """Verify a bounded immutable closure without reconstructing model weights.

    This checks every file's bytes, closed manifest and patch schemas, ordered
    segment bindings, job-local revision continuity and manifest provenance.
    It does not replay before/postimages, recompute model identities or verify
    the declared materialized checkpoint bytes. Use ``resolve_checkpoint`` in
    workers and at owner acceptance for those mandatory semantic checks.

    Legacy JSON is still parsed into ordinary Python data to validate its
    framing. No tracked state, copy-on-write overlay or full candidate JSON is
    constructed here, and the inventory does not cache trust between calls.
    """
    seen: dict[str, dict[str, Any]] = {}
    active: set[str] = set()
    total_bytes = 0
    patch_bytes = 0

    def read(ref: dict[str, Any], maximum: int) -> bytes:
        nonlocal total_bytes
        previous = seen.get(ref["sha256"])
        if previous is not None and previous != ref:
            raise SparseCheckpointError("same artifact digest has inconsistent sizes")
        if previous is None:
            if len(seen) >= limits.max_artifacts:
                raise SparseCheckpointError("artifact closure count exceeds bound")
            total_bytes += ref["bytes"]
            if total_bytes > limits.max_total_bytes:
                raise SparseCheckpointError("artifact closure bytes exceed bound")
            seen[ref["sha256"]] = ref
        try:
            path = resolver(dict(ref))
        except (KeyError, ValueError, OSError) as exc:
            raise SparseCheckpointError("artifact missing from trusted resolver") from exc
        return _read_artifact(path, ref, maximum)

    def visit(ref: dict[str, Any], ancestry: int) -> CheckpointInventory:
        nonlocal patch_bytes
        if ref["sha256"] in active:
            raise SparseCheckpointError("checkpoint parent cycle detected")
        if ancestry > limits.max_depth:
            raise SparseCheckpointError("checkpoint manifest depth exceeds bound")
        active.add(ref["sha256"])
        try:
            raw = read(ref, max(limits.max_checkpoint_bytes, limits.max_manifest_bytes))
            data = _parse(raw)
            if not isinstance(data, dict):
                raise SparseCheckpointError("checkpoint must be a JSON object")
            if data.get("schema") == SCHEMA:
                manifest = decode_manifest(raw, limits=limits)
                if ancestry == limits.max_depth:
                    raise SparseCheckpointError("checkpoint manifest depth exceeds bound")
                parent = visit(manifest["parent"], ancestry + 1)
                previous_identity = None
                previous_revision = 0
                for sequence, patch_ref in enumerate(manifest["patches"]):
                    patch_bytes += patch_ref["bytes"]
                    if patch_bytes > limits.max_total_patch_bytes:
                        raise SparseCheckpointError("total patch bytes exceed bound")
                    try:
                        segment = decode_patch(read(patch_ref, limits.max_patch_bytes))
                    except PatchCodecError as exc:
                        raise SparseCheckpointError(f"invalid inventory patch: {exc}") from exc
                    if segment.sequence != sequence or segment.base_version_id != manifest["base_version_id"]:
                        raise SparseCheckpointError("inventory patch sequence or base version mismatch")
                    if segment.patch.base_revision != previous_revision:
                        raise SparseCheckpointError("inventory patch base revision mismatch")
                    if previous_identity is not None and segment.base_state_identity != previous_identity:
                        raise SparseCheckpointError("inventory patch identity chain mismatch")
                    for name in ("job_id", "run_id", "job_spec_sha256"):
                        if name in manifest["provenance"] and segment.provenance.get(name) != manifest["provenance"][name]:
                            raise SparseCheckpointError(f"patch provenance mismatch: {name}")
                    previous_revision = segment.patch.result_revision
                    previous_identity = segment.result_state_identity
                if previous_revision != manifest["result_revision"]:
                    raise SparseCheckpointError("inventory manifest result revision mismatch")
                if previous_identity is not None and previous_identity != manifest["state_identity"]:
                    raise SparseCheckpointError("inventory manifest result identity mismatch")
                depth = parent.depth + 1
                materialized = manifest["materialized_checkpoint"]
                anchor = parent.anchor_checkpoint
            else:
                if ref["bytes"] > limits.max_checkpoint_bytes:
                    raise SparseCheckpointError("full checkpoint exceeds byte bound")
                _validate_legacy_inventory(data)
                manifest = None
                depth = 0
                materialized = ref
                anchor = ref
            return CheckpointInventory(dict(ref), dict(materialized), depth, patch_bytes, total_bytes,
                                       manifest, dict(anchor), tuple(seen.values()))
        finally:
            active.remove(ref["sha256"])

    return visit(artifact_ref(reference), 0)


def resolve_checkpoint(reference: Any, *, resolver: Callable[[Mapping[str, Any]], Any],
                       limits: ResolutionLimits = ResolutionLimits(),
                       reset_revision: bool = True) -> ResolvedCheckpoint:
    """Verify a complete bounded closure and reconstruct its exact candidate.

    Full legacy roots preserve their physical file byte identity for bindings
    such as Arrow. Sparse manifests declare canonical materialized bytes. The
    default returned state is normal ``from_dict`` reload state (revision zero);
    ``reset_revision=False`` preserves terminal patch revision for owner checks.
    """
    from .modal_autoencoder import (
        MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS, ModalAutoencoderTrainingState,
    )

    if type(reset_revision) is not bool:
        raise SparseCheckpointError("reset_revision must be boolean")
    seen: dict[str, dict[str, Any]] = {}
    active: set[str] = set()
    total_bytes = 0
    patch_bytes = 0

    def read(ref: dict[str, Any], maximum: int) -> bytes:
        nonlocal total_bytes
        previous = seen.get(ref["sha256"])
        if previous is not None and previous != ref:
            raise SparseCheckpointError("same artifact digest has inconsistent sizes")
        if previous is None:
            if len(seen) >= limits.max_artifacts:
                raise SparseCheckpointError("artifact closure count exceeds bound")
            total_bytes += ref["bytes"]
            if total_bytes > limits.max_total_bytes:
                raise SparseCheckpointError("artifact closure bytes exceed bound")
            seen[ref["sha256"]] = ref
        try:
            path = resolver(dict(ref))
        except (KeyError, ValueError, OSError) as exc:
            raise SparseCheckpointError("artifact missing from trusted resolver") from exc
        return _read_artifact(path, ref, maximum)

    def visit(ref: dict[str, Any], ancestry: int, reload_result: bool) -> ResolvedCheckpoint:
        nonlocal patch_bytes
        if ref["sha256"] in active:
            raise SparseCheckpointError("checkpoint parent cycle detected")
        if ancestry > limits.max_depth:
            raise SparseCheckpointError("checkpoint manifest depth exceeds bound")
        active.add(ref["sha256"])
        try:
            raw = read(ref, max(limits.max_checkpoint_bytes, limits.max_manifest_bytes))
            data = _parse(raw)
            if not isinstance(data, dict):
                raise SparseCheckpointError("checkpoint must be a JSON object")
            if data.get("schema") == SCHEMA:
                manifest = decode_manifest(raw, limits=limits)
                if ancestry == limits.max_depth:
                    raise SparseCheckpointError("checkpoint manifest depth exceeds bound")
                parent = visit(manifest["parent"], ancestry + 1, True)
                state = parent.state
                for sequence, patch_ref in enumerate(manifest["patches"]):
                    patch_bytes += patch_ref["bytes"]
                    if patch_bytes > limits.max_total_patch_bytes:
                        raise SparseCheckpointError("total patch bytes exceed bound")
                    patch_raw = read(patch_ref, limits.max_patch_bytes)
                    try:
                        segment = decode_patch(patch_raw)
                        for name in ("job_id", "run_id", "job_spec_sha256"):
                            if name in manifest["provenance"] and segment.provenance.get(name) != manifest["provenance"][name]:
                                raise SparseCheckpointError(f"patch provenance mismatch: {name}")
                        replay_patch(state, segment, expected_base_version_id=manifest["base_version_id"],
                                     expected_sequence=sequence)
                    except PatchCodecError as exc:
                        raise SparseCheckpointError(f"sparse checkpoint patch replay failed: {exc}") from exc
                replayed_revision = state.state_revision
                identity = state.state_identity()
                if replayed_revision != manifest["result_revision"] or identity != manifest["state_identity"]:
                    raise SparseCheckpointError("manifest result state identity or revision mismatch")
                if checkpoint_identity(state) != manifest["materialized_checkpoint"]:
                    raise SparseCheckpointError("manifest materialized checkpoint byte identity mismatch")
                depth = parent.depth + 1
                materialized = manifest["materialized_checkpoint"]
                anchor = parent.anchor_checkpoint
                if reload_result:
                    state = ModalAutoencoderTrainingState.from_dict(state.to_dict())
            else:
                if ref["bytes"] > limits.max_checkpoint_bytes:
                    raise SparseCheckpointError("full checkpoint exceeds byte bound")
                if str(data.get("schema_version", "")).startswith("modal-autoencoder-tensor-state-"):
                    raise SparseCheckpointError("sparse resolver supports qualified legacy JSON checkpoints only")
                try:
                    state = ModalAutoencoderTrainingState.from_dict(data)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise SparseCheckpointError("invalid full legacy checkpoint") from exc
                if set(data) - MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS:
                    raise SparseCheckpointError("full checkpoint contains unknown fields")
                manifest = None
                replayed_revision = 0
                identity = state.state_identity()
                depth = 0
                materialized = ref
                anchor = ref
            return ResolvedCheckpoint(state, dict(materialized), identity, replayed_revision, depth,
                                      patch_bytes, manifest, dict(anchor), tuple(seen.values()))
        finally:
            active.remove(ref["sha256"])

    return visit(artifact_ref(reference), 0, reset_revision)


def write_checkpoint(state: Any, destination: str | Path, *,
                     expected_identity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Explicit exclusive full materialization, with a temporary full JSON buffer."""
    raw = canonical_checkpoint_bytes(state)
    identity = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    if expected_identity is not None and identity != artifact_ref(expected_identity):
        raise SparseCheckpointError("materialization differs from expected canonical checkpoint")
    path = Path(destination)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path.absolute()), **identity}


def materialize_checkpoint(resolved: ResolvedCheckpoint, destination: str | Path) -> dict[str, Any]:
    """Write a verified sparse candidate or canonicalize a legacy full anchor.

    Resolve sparse candidates with ``reset_revision=False`` before compaction:
    this preserves the exact terminal candidate even if JSON reload normalizes
    a component. Default reloaded results are rejected if canonical bytes differ.
    """
    expected = resolved.materialized_checkpoint if resolved.manifest is not None else None
    return write_checkpoint(resolved.state, destination, expected_identity=expected)


__all__ = ["SCHEMA", "RELOAD_SEMANTICS", "SparseCheckpointError", "ResolutionLimits",
           "ResolvedCheckpoint", "CheckpointInventory", "artifact_ref", "canonical_checkpoint_bytes", "checkpoint_identity",
           "encode_manifest", "decode_manifest", "inventory_checkpoint", "resolve_checkpoint", "write_checkpoint", "materialize_checkpoint"]
