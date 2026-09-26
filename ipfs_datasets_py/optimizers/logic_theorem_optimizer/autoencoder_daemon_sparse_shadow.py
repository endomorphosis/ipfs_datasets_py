"""Diagnostic complete-state sparse replay between immutable full checkpoints.

The full final checkpoint remains authoritative. This endpoint comparison does
not intercept training, infer accepted optimizer steps, publish a sparse model,
or establish owner/lease authority. Its caller supplies resource isolation and
the trusted source of the two artifact descriptors.
"""
from __future__ import annotations

import gc
import hashlib
import os
from pathlib import Path
import threading
import time
from typing import Any, Mapping

from .autoencoder_daemon_invocation_contracts import (
    MAX_CHECKPOINT_BYTES, MAX_RESULT_BYTES, METRIC_LINEAGE, canonical, load_full_checkpoint,
    parse_json, reference, safe_path, verify, write_new,
)
from .modal_autoencoder_checkpoint import serialize_checkpoint
from .modal_autoencoder_patch_codec import MAX_PATCH_BYTES, decode_patch, replay_patch
from .modal_autoencoder_sparse_checkpoint import canonical_checkpoint_bytes
from .modal_autoencoder_state_diff import capture_endpoint_patch, exact_state_snapshot

SCHEMA = "autoencoder-daemon-sparse-shadow-v1"


class SparseShadowError(ValueError):
    """An immutable endpoint or its exact reconstruction did not agree."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SparseShadowError(message)


def _hash(raw: bytes) -> dict:
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _content(ref: Mapping[str, Any]) -> dict:
    return {key: ref[key] for key in ("sha256", "bytes")}


class _VerifiedCheckpointEndpoints:
    """One-use ownership transfer from this process's full checkpoint loader.

    This private holder is not an artifact capability or an authentication
    mechanism for arbitrary Python objects. The verifier may inspect its native
    endpoints, then must drop its own references before transferring them. The
    shadow still independently reloads the base and reproduces final bytes.
    """

    def __init__(self, base_ref: Mapping[str, Any]):
        self._pid, self._thread = os.getpid(), threading.get_ident()
        self._closed = False
        self._base = self._final = None
        self._base_ref = self._final_ref = None
        self._load_seconds = 0.0
        try:
            from . import autoencoder_daemon_invocation_contracts as contracts
            self._base_ref = reference(dict(base_ref), MAX_CHECKPOINT_BYTES, with_path=True)
            started = time.perf_counter()
            self._base = contracts.load_full_checkpoint(self._base_ref)
            self._load_seconds = time.perf_counter() - started
            self._base_revision, self._base_manifest = self._endpoint_identity(self._base)
        except BaseException:
            self.close()
            raise

    def _require_open(self) -> None:
        _require(os.getpid() == self._pid and threading.get_ident() == self._thread,
                 "endpoint handoff requires its creating process and thread")
        _require(not self._closed, "endpoint handoff is closed or already consumed")

    @staticmethod
    def _endpoint_identity(loaded: Any, *, compact_only: bool = False) -> tuple[int, bytes]:
        from .modal_autoencoder import ModalAutoencoderTrainingState
        from .modal_autoencoder_checkpoint import CheckpointLoadResult, CheckpointManifest
        _require(type(loaded) is CheckpointLoadResult
                 and type(loaded.state) is ModalAutoencoderTrainingState
                 and type(loaded.manifest) is CheckpointManifest,
                 "endpoint handoff requires exact native checkpoint results")
        _require(loaded.format in ({"compact"} if compact_only else {"json", "compact"})
                 and loaded.manifest.kind == "full" and loaded.manifest.float_precision == "float64",
                 "endpoint handoff requires full float64 checkpoints")
        _require(type(loaded.applied_delta_count) is int and loaded.applied_delta_count == 0
                 and type(loaded.recovered_tail_bytes) is int and loaded.recovered_tail_bytes == 0
                 and type(loaded.delta_manifests) is tuple and not loaded.delta_manifests,
                 "endpoint handoff cannot contain delta replay or recovery")
        _require(loaded.state._active_state_transaction is None,
                 "endpoint handoff has an active state transaction")
        revision = loaded.state.state_revision
        _require(type(revision) is int and 0 <= revision < 2**63
                 and type(loaded.manifest.revision) is int and loaded.manifest.revision == revision,
                 "endpoint handoff revision differs from its loaded manifest")
        return revision, canonical({"format": loaded.format, "manifest": loaded.manifest.to_dict()})

    @property
    def base(self):
        self._require_open()
        return self._base

    def load_final(self, final_ref: Mapping[str, Any]):
        try:
            self._require_open()
            _require(self._final is None, "endpoint handoff already loaded its final checkpoint")
            from . import autoencoder_daemon_invocation_contracts as contracts
            self._final_ref = reference(dict(final_ref), MAX_CHECKPOINT_BYTES, with_path=True)
            started = time.perf_counter()
            self._final = contracts.load_full_checkpoint(self._final_ref, compact_only=True)
            self._load_seconds += time.perf_counter() - started
            self._final_revision, self._final_manifest = self._endpoint_identity(self._final, compact_only=True)
            return self._final
        except BaseException:
            self.close()
            raise

    def consume(self, base_ref: Mapping[str, Any], final_ref: Mapping[str, Any]):
        # Clear the holder even if a boundary check fails. Caller-held exception
        # tracebacks may still retain these locals; errors are not rewritten.
        base, final = self._base, self._final
        self._base = self._final = None
        try:
            self._require_open()
            _require(base is not None and final is not None, "endpoint handoff is incomplete")
            base_ref = reference(dict(base_ref), MAX_CHECKPOINT_BYTES, with_path=True)
            final_ref = reference(dict(final_ref), MAX_CHECKPOINT_BYTES, with_path=True)
            _require(canonical(base_ref) == canonical(self._base_ref)
                     and canonical(final_ref) == canonical(self._final_ref),
                     "endpoint handoff artifact descriptors differ")
            verify(base_ref, MAX_CHECKPOINT_BYTES)
            verify(final_ref, MAX_CHECKPOINT_BYTES)
            _require(self._endpoint_identity(base) == (self._base_revision, self._base_manifest)
                     and self._endpoint_identity(final, compact_only=True) == (
                         self._final_revision, self._final_manifest),
                     "endpoint handoff changed after checkpoint loading")
            return base, final
        finally:
            self.close()

    def close(self) -> None:
        """Drop owned graphs without IO, revalidation or exception masking."""
        self._base = self._final = None
        self._closed = True


def _publish_receipt(path: Path, value: Any) -> dict:
    """Remove this call's own receipt if durable publication fails.

    Cleanup failures remain explicit notes on the primary exception. A replaced
    path is never deleted. Callers must still require successful return; this
    local operation is not a transaction with an arbitrary concurrent reader.
    """
    path = safe_path(path, exists=False)
    raw = canonical(value)
    _require(0 < len(raw) <= MAX_RESULT_BYTES, "shadow receipt exceeds byte bound")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    identity = None
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            created = os.fstat(stream.fileno())
            identity = (created.st_dev, created.st_ino)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    except BaseException as exc:
        if identity is not None:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == identity:
                    path.unlink()
                    os.fsync(directory)
                else:
                    exc.add_note("receipt path was replaced; replacement was not removed")
            except FileNotFoundError:
                pass
            except BaseException as cleanup:
                exc.add_note(f"receipt publication cleanup failed: {type(cleanup).__name__}")
        raise
    finally:
        os.close(directory)
    return {"path": str(path), **_hash(raw)}


def write_checkpoint_shadow(base_ref: Mapping[str, Any], final_ref: Mapping[str, Any], *,
        base_version_id: str, output_directory: str | Path,
        provenance: Mapping[str, Any] | None = None) -> dict:
    """Build and independently replay a net patch; write diagnostic evidence.

    Both inputs must be complete legacy JSON or full float64 compact states,
    with exact byte/SHA descriptors. The existing empty output directory is
    exclusive to this call. There is no overwrite, retry or rollback of output
    files after publication failure. A lone patch without a verified receipt
    grants no checkpoint or registry authority.

    Legacy artifacts retain their original byte identities; comparison uses
    the native loader's schema/default upgrades rather than reproducing legacy
    JSON formatting. Compact final artifacts must be reproduced byte-for-byte
    with their original metadata, lineage and revision.
    """
    return _write_checkpoint_shadow(base_ref, final_ref, base_version_id=base_version_id,
        output_directory=output_directory, provenance=provenance)


def _write_checkpoint_shadow_from_verified_endpoints(handoff, base_ref, final_ref, *,
        base_version_id: str, output_directory: str | Path,
        provenance: Mapping[str, Any] | None = None) -> dict:
    """Consume loader-owned endpoints only after mandatory worker validation."""
    try:
        _require(type(handoff) is _VerifiedCheckpointEndpoints,
                 "shadow requires an exact loader-origin endpoint handoff")
        return _write_checkpoint_shadow(base_ref, final_ref, base_version_id=base_version_id,
            output_directory=output_directory, provenance=provenance, handoff=handoff)
    finally:
        if type(handoff) is _VerifiedCheckpointEndpoints:
            handoff.close()


def _write_checkpoint_shadow(base_ref, final_ref, *, base_version_id, output_directory,
        provenance=None, handoff=None):
    started = time.perf_counter()
    base_ref = reference(dict(base_ref), MAX_CHECKPOINT_BYTES, with_path=True)
    final_ref = reference(dict(final_ref), MAX_CHECKPOINT_BYTES, with_path=True)
    _require(type(base_version_id) is str and 0 < len(base_version_id) <= 256,
             "base version must be a bounded nonempty string")
    context_bytes = canonical({} if provenance is None else dict(provenance))
    _require(len(context_bytes) <= 65536, "shadow provenance exceeds byte bound")
    context = parse_json(context_bytes)
    output = safe_path(output_directory)
    _require(output.is_dir() and not any(output.iterdir()), "shadow output must be an existing empty directory")
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    tree = require_workspace_logic_tree()
    bound = {"schema": SCHEMA, "capture_kind": "complete_checkpoint_endpoint_difference",
             "base_artifact": _content(base_ref), "final_artifact": _content(final_ref),
             "context": context, "optimizer_acceptance_asserted": False,
             "registered_base_authority_verified": False}
    timings = {}
    phase = time.perf_counter()
    if handoff is None:
        base = load_full_checkpoint(base_ref)
        final = load_full_checkpoint(final_ref)
        timings["load_endpoints_seconds"] = time.perf_counter() - phase
    else:
        base, final = handoff.consume(base_ref, final_ref)
        timings["endpoint_handoff_check_seconds"] = time.perf_counter() - phase
        timings["reused_endpoint_load_seconds"] = handoff._load_seconds
        timings["reused_endpoint_count"] = 2
    base_format, final_format = base.format, final.format
    phase = time.perf_counter()
    captured = capture_endpoint_patch(base.state, final.state,
        base_version_id=base_version_id, sequence=0, provenance=bound)
    timings["capture_seconds"] = time.perf_counter() - phase
    segment = decode_patch(captured.data)
    _require(canonical(segment.provenance) == canonical(bound), "patch endpoint provenance differs")
    _require(segment.base_version_id == base_version_id and segment.sequence == 0,
             "patch version or sequence differs")
    # Do not keep three decoded weight graphs resident. Reopen the immutable
    # base for replay instead of reusing the object supplied to the builder.
    del base
    phase = time.perf_counter()
    gc.collect()
    replayed = load_full_checkpoint(base_ref)
    _require(exact_state_snapshot(replayed.state) == captured.report["base_snapshot"],
             "independently loaded base differs from capture")
    timings["reload_base_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    replay_report = replay_patch(replayed.state, segment,
        expected_base_version_id=base_version_id, expected_sequence=0)
    timings["replay_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    rebuilt_snapshot = exact_state_snapshot(replayed.state)
    final_snapshot = exact_state_snapshot(final.state)
    _require(rebuilt_snapshot == final_snapshot == captured.report["result_snapshot"],
             "complete raw native state differs after replay")
    rebuilt_json = canonical_checkpoint_bytes(replayed.state)
    final_json = canonical_checkpoint_bytes(final.state)
    _require(rebuilt_json == final_json, "complete canonical native checkpoint differs")
    canonical_identity = _hash(final_json)
    del rebuilt_json, final_json
    rebuilt_metric = replayed.state.state_identity_record(metric_lineage=METRIC_LINEAGE).to_dict()
    final_metric = final.state.state_identity_record(metric_lineage=METRIC_LINEAGE).to_dict()
    _require(canonical(rebuilt_metric) == canonical(final_metric), "metric-lineage state differs")
    checks = {"all_native_components_exact": True, "canonical_native_state_exact": True,
              "metric_lineage_identity_exact": True, "revision_exact": True,
              "patch_endpoint_binding_exact": True, "independent_base_reload": True}
    timings["verify_complete_state_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    compact_identity = None
    if final_format != "json":
        regenerated = serialize_checkpoint(replayed.state, float_precision="float64",
            metric_lineage=final.manifest.metric_lineage, metadata=final.manifest.metadata,
            revision=final.manifest.revision)
        compact_identity = _hash(regenerated)
        _require(regenerated == verify(final_ref, MAX_CHECKPOINT_BYTES),
                 "compact checkpoint bytes differ after replay")
        del regenerated
        checks["compact_final_bytes_exact"] = True
    timings["verify_compact_bytes_seconds"] = time.perf_counter() - phase
    for ref in (base_ref, final_ref):
        verify(ref, MAX_CHECKPOINT_BYTES)
    checks["source_artifacts_unchanged"] = True
    # The existing codec and artifact writer share canonical JSON framing.
    # Verify that fact rather than silently adopting newly serialized bytes.
    phase = time.perf_counter()
    patch_ref = write_new(output / "patch.json", parse_json(captured.data), MAX_PATCH_BYTES)
    _require(_content(patch_ref) == _hash(captured.data)
             and verify(patch_ref, MAX_PATCH_BYTES) == captured.data,
             "published patch bytes differ from verified replay")
    checks["published_patch_bytes_exact"] = True
    timings["write_patch_seconds"] = time.perf_counter() - phase
    for ref in (base_ref, final_ref):
        verify(ref, MAX_CHECKPOINT_BYTES)
    result = {"schema": SCHEMA, "passed": True, "mode": "diagnostic_only",
        "base_artifact": base_ref, "final_artifact": final_ref, "base_version_id": base_version_id,
        "base_format": base_format, "final_format": final_format, "patch_ref": patch_ref,
        "provenance": bound, "capture_report": captured.report, "replay_report": replay_report,
        "checks": checks, "canonical_native_checkpoint": canonical_identity,
        "regenerated_compact_checkpoint": compact_identity,
        "metric_state_identity": final_metric, "tree_pin": tree, "timings": timings,
        "full_checkpoint_authoritative": True, "registered_base_authority_verified": False,
        "legacy_raw_bytes_reproduction_required": False,
        "intermediate_mutations_replayed": False, "optimizer_acceptance_asserted": False,
        "admitted": False, "promoted": False, "publication_performed": False}
    result["timings"]["elapsed_seconds_before_receipt_write"] = time.perf_counter() - started
    receipt_ref = _publish_receipt(output / "receipt.json", result)
    return {**result, "receipt_ref": receipt_ref}
