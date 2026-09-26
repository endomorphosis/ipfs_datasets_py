"""Bounded evidence joins for published U.S. Code vector shards.

The qualified publisher profile stores document CIDs and model labels but drops
the embedding input hash, projection configuration and backend receipt. A valid
row join therefore remains ineligible for corpus training. This module never
chooses a first vector per CID, fabricates chunk selectors, generates embeddings,
downloads weights, or equates corpus admission labels with Lean admission.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "autoencoder-uscode-embedding-join-audit-v1"
SUPPORTED_MODEL = "thenlper/gte-small"
SUPPORTED_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"
SUPPORTED_DIMENSION = 384
SUPPORTED_VECTOR_SPACE = f"gte-small@{SUPPORTED_REVISION}:d384:pool=mean:norm=l2"
_CID = re.compile(r"sha256:[0-9a-f]{64}")
_HASH = re.compile(r"[0-9a-f]{64}")
_FIELDS = frozenset({"entry_cid", "chunk_cid", "legal_id", "dimension", "model_id",
                     "model_revision", "vector_space_id", "embedding", "centroid_id", "shard_id", "family"})


class USCodeEmbeddingJoinError(ValueError):
    """A vector/source evidence request violates a bounded join contract."""


@dataclass(frozen=True)
class EmbeddingJoinLimits:
    max_source_rows: int = 4096
    max_vector_shards: int = 16
    max_vector_rows: int = 65536
    max_vector_bytes: int = 256 * 1024 * 1024
    max_model_bytes: int = 128 * 1024 * 1024

    def __post_init__(self):
        ceilings = {"max_source_rows": 4096, "max_vector_shards": 64, "max_vector_rows": 262144,
                    "max_vector_bytes": 1024 * 1024 * 1024, "max_model_bytes": 512 * 1024 * 1024}
        for name, ceiling in ceilings.items():
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= ceiling:
                raise USCodeEmbeddingJoinError(f"{name} is outside its qualified bounds")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not {"sha256", "bytes"} <= set(value):
        raise USCodeEmbeddingJoinError("artifact requires SHA-256 and byte length")
    ref = {key: value[key] for key in ("sha256", "bytes")}
    if not isinstance(ref["sha256"], str) or not _HASH.fullmatch(ref["sha256"]):
        raise USCodeEmbeddingJoinError("artifact requires a lowercase SHA-256")
    if type(ref["bytes"]) is not int or ref["bytes"] < 1:
        raise USCodeEmbeddingJoinError("artifact requires a positive byte length")
    return ref


def _verify_model_artifact(value: Mapping[str, Any], maximum: int) -> dict[str, Any]:
    ref = _reference(value)
    if set(value) != {"path", "sha256", "bytes"} or ref["bytes"] > maximum:
        raise USCodeEmbeddingJoinError("model artifact descriptor exceeds its qualified contract")
    path = Path(value["path"])
    if not path.is_absolute():
        raise USCodeEmbeddingJoinError("model artifact path must be absolute")
    digest = hashlib.sha256()
    count = 0
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != ref["bytes"]:
            raise USCodeEmbeddingJoinError("model artifact is not the declared regular file")
        while block := stream.read(min(1024 * 1024, ref["bytes"] - count + 1)):
            count += len(block)
            if count > ref["bytes"]:
                raise USCodeEmbeddingJoinError("model artifact grew beyond declared bytes")
            digest.update(block)
    if count != ref["bytes"] or digest.hexdigest() != ref["sha256"]:
        raise USCodeEmbeddingJoinError("model artifact SHA-256 or byte length mismatch")
    return {"artifact": ref, "bytes_verified": True,
            "model_revision_binding_authenticated": False,
            "scope": "supplied local artifact bytes only; tokenizer, producer run and vector derivation not authenticated"}


def _vector_evidence(payload: Mapping[str, Any], release: Any) -> dict[str, Any]:
    if set(payload) != _FIELDS:
        raise USCodeEmbeddingJoinError("unsupported published vector payload fields")
    if payload["family"] != "vectors":
        raise USCodeEmbeddingJoinError("vector payload family mismatch")
    for key in ("entry_cid", "chunk_cid"):
        if not isinstance(payload[key], str) or not _CID.fullmatch(payload[key]):
            raise USCodeEmbeddingJoinError("vector requires a qualified content identity")
    if payload["chunk_cid"] != payload["entry_cid"]:
        raise USCodeEmbeddingJoinError("publisher profile does not qualify a separate chunk-to-source join")
    if payload["legal_id"] is not None:
        raise USCodeEmbeddingJoinError("publisher profile expects absent vector legal_id")
    for key in ("centroid_id", "shard_id"):
        value = payload[key]
        if value is not None and (type(value) is not int or value < 0):
            raise USCodeEmbeddingJoinError("invalid vector locator label")
    for name in ("model_id", "model_revision", "vector_space_id"):
        if payload[name] != getattr(release, name):
            raise USCodeEmbeddingJoinError(f"vector {name} differs from the pinned release")
    if type(payload["dimension"]) is not int or payload["dimension"] != SUPPORTED_DIMENSION:
        raise USCodeEmbeddingJoinError("vector dimension is not 384")
    vector = payload["embedding"]
    if not isinstance(vector, list) or len(vector) != SUPPORTED_DIMENSION:
        raise USCodeEmbeddingJoinError("vector length does not match its dimension")
    if any(type(value) not in (float, int) or abs(value) > 1.00001 or not math.isfinite(value) for value in vector):
        raise USCodeEmbeddingJoinError("vector values must be finite normalized numbers")
    values = tuple(float(value) for value in vector)
    norm = math.sqrt(math.fsum(value * value for value in values))
    if not math.isclose(norm, 1.0, rel_tol=0, abs_tol=1e-5):
        raise USCodeEmbeddingJoinError("vector is not L2-normalized")
    return {"dimension": SUPPORTED_DIMENSION, "l2_norm": norm,
            "vector_float64_sha256": hashlib.sha256(struct.pack(f">{SUPPORTED_DIMENSION}d", *values)).hexdigest(),
            "chunk_cid": payload["chunk_cid"], "model_id": payload["model_id"],
            "model_revision": payload["model_revision"], "vector_space_id": payload["vector_space_id"]}


@dataclass(frozen=True)
class EmbeddingJoinAudit:
    _raw: bytes
    _diagnostic_vectors: tuple[tuple[str, tuple[float, ...]], ...] = field(default=(), repr=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._raw)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._raw).hexdigest()

    @property
    def status_counts(self) -> dict[str, int]:
        return self.to_dict()["status_counts"]

    @property
    def training_eligible_count(self) -> int:
        return 0

    def require_training_embeddings(self):
        raise USCodeEmbeddingJoinError("published profile lacks exact input and producer bindings; no eligible training embeddings")

    def diagnostic_vectors(self) -> dict[str, tuple[float, ...]]:
        """Return unique supplied vectors for explicitly diagnostic use only.

        Every returned CID retains ``missing_input_binding`` in the audit. This
        accessor supplies no EmbeddingProvenance and grants no training eligibility.
        """
        return dict(self._diagnostic_vectors)

    def save(self, destination: str | Path) -> dict[str, Any]:
        path = Path(destination)
        with path.open("xb") as stream:
            stream.write(self._raw)
            stream.flush()
            os.fsync(stream.fileno())
        return {"path": str(path.absolute()), "sha256": self.sha256, "bytes": len(self._raw)}


def audit_uscode_embedding_join(release: Any, source_rows: Sequence[Any], *,
                               vector_shards: Sequence[str], resolver: Callable[[Mapping[str, Any]], Any],
                               model_artifact: Mapping[str, Any] | None = None,
                               limits: EmbeddingJoinLimits = EmbeddingJoinLimits()) -> EmbeddingJoinAudit:
    """Verify selected-shard joins, without converting metadata into training eligibility.

    All rows of every supplied shard are inspected; selected source order is
    retained. Missing/duplicate statuses concern this supplied shard set, not a
    claim of absence or uniqueness across an unscanned release.
    """
    from .autoencoder_uscode_import import USCodeRelease, VerifiedUSCodeRow, read_wrapped_shard, verify_uscode_rows

    if not isinstance(release, USCodeRelease):
        raise USCodeEmbeddingJoinError("release must be a verified USCodeRelease")
    if (release.model_id, release.model_revision, release.vector_space_id) != (
            SUPPORTED_MODEL, SUPPORTED_REVISION, SUPPORTED_VECTOR_SPACE):
        raise USCodeEmbeddingJoinError("release vector model profile is not qualified")
    if not isinstance(source_rows, (tuple, list)) or not 1 <= len(source_rows) <= limits.max_source_rows:
        raise USCodeEmbeddingJoinError("source row count exceeds the bounded join contract")
    if any(not isinstance(row, VerifiedUSCodeRow) for row in source_rows):
        raise USCodeEmbeddingJoinError("source rows must be verified corpus rows")
    if len({row.entry_cid for row in source_rows}) != len(source_rows):
        raise USCodeEmbeddingJoinError("source selection contains duplicate entry identities")
    # Frozen dataclasses can still be constructed or replaced by a caller.
    # Revalidate manifest-bound shard membership instead of trusting the label.
    verify_uscode_rows(release, source_rows, resolver=resolver)
    for row in source_rows:
        bound = release.artifact(row.shard.relative_path)
        if (row.release_id != release.release_id or bound.family != "corpus"
                or row.shard_reference != bound.reference or not 0 <= row.row_index < bound.row_count):
            raise USCodeEmbeddingJoinError("source row is bound to another release or corpus artifact")
    if not isinstance(vector_shards, (tuple, list)) or len(vector_shards) > limits.max_vector_shards:
        raise USCodeEmbeddingJoinError("vector shard count exceeds the bounded join contract")
    if len(set(vector_shards)) != len(vector_shards):
        raise USCodeEmbeddingJoinError("duplicate vector shard selection")
    artifacts = [release.artifact(path) for path in vector_shards]
    if any(artifact.family != "vectors" or not artifact.relative_path.startswith("data/vectors/")
           or artifact.schema_id != "uscode-vector-row/v1" for artifact in artifacts):
        raise USCodeEmbeddingJoinError("selected artifact is not a vector shard")
    if sum(artifact.reference["bytes"] for artifact in artifacts) > limits.max_vector_bytes:
        raise USCodeEmbeddingJoinError("selected vector artifacts exceed aggregate byte bound")
    if sum(artifact.row_count for artifact in artifacts) > limits.max_vector_rows:
        raise USCodeEmbeddingJoinError("selected vector rows exceed aggregate bound")
    model_evidence = _verify_model_artifact(model_artifact, limits.max_model_bytes) if model_artifact is not None else {
        "artifact": None, "bytes_verified": False, "model_revision_binding_authenticated": False}
    wanted = {row.entry_cid for row in source_rows}
    matches: dict[str, list[dict[str, Any]]] = {cid: [] for cid in wanted}
    invalid_matches: dict[str, list[dict[str, Any]]] = {cid: [] for cid in wanted}
    diagnostic_vectors: dict[str, tuple[float, ...]] = {}
    dispositions = []
    wrapper_integrity_failed = False
    scanned = 0
    for artifact in artifacts:
        shard = read_wrapped_shard(release, artifact.relative_path, resolver=resolver)
        if not shard.complete:
            raise USCodeEmbeddingJoinError("vector shard scan must be complete to qualify duplicate detection")
        scanned += shard.rows_scanned
        for disposition in shard.dispositions:
            if disposition.status == "verified_wrapper":
                continue
            failure = {"artifact": dict(artifact.reference), "relative_path": artifact.relative_path,
                       **asdict(disposition)}
            dispositions.append(failure)
            if disposition.status == "duplicate_entry_cid":
                if disposition.entry_cid in wanted:
                    invalid_matches[disposition.entry_cid].append(failure)
            else:
                # A broken wrapper cannot safely identify which source is
                # affected, so this selected shard set cannot supply diagnostics.
                wrapper_integrity_failed = True
        for wrapped in shard.rows:
            locator = {"artifact": dict(artifact.reference), "relative_path": artifact.relative_path,
                       "row_index": wrapped.row_index, "record_sha256": wrapped.record_sha256}
            payload = wrapped.payload
            try:
                evidence = _vector_evidence(payload, release)
            except USCodeEmbeddingJoinError as exc:
                failure = {**locator, "entry_cid": wrapped.entry_cid, "status": "invalid_embedding_record", "reason": str(exc)}
                dispositions.append(failure)
                if wrapped.entry_cid in wanted:
                    invalid_matches[wrapped.entry_cid].append(failure)
                continue
            if wrapped.entry_cid in wanted:
                matches[wrapped.entry_cid].append({**locator, **evidence})
                diagnostic_vectors[wrapped.entry_cid] = tuple(float(value) for value in payload["embedding"])
    rows = []
    counts: dict[str, int] = {}
    for source in source_rows:
        valid, invalid = matches[source.entry_cid], invalid_matches[source.entry_cid]
        if wrapper_integrity_failed:
            status = "unverified_vector_shard"
        elif len(valid) + len(invalid) > 1:
            status = "ambiguous_embedding"
        elif invalid:
            status = "invalid_embedding_record"
        elif not valid:
            status = "missing_embedding"
        else:
            status = "missing_input_binding"
        counts[status] = counts.get(status, 0) + 1
        rows.append({"entry_cid": source.entry_cid, "legal_id": source.legal_id,
                     "source_record_sha256": source.record_sha256,
                     "source_text_sha256": hashlib.sha256(source.text.encode("utf-8")).hexdigest(),
                     "status": status, "training_eligible": False,
                     "published_identity_join_verified": status == "missing_input_binding",
                     "exact_input_binding_verified": False, "producer_binding_verified": False,
                     "matches": valid, "invalid_matches": invalid})
    report = {"schema_version": SCHEMA, "admitted": False, "formalized": False,
              "release_manifest": dict(release.manifest_reference), "release_id": release.release_id,
              "selection_scope": "supplied source rows and complete supplied vector shards; unscanned release rows are not qualified",
              "source_row_count": len(rows), "vector_rows_scanned": scanned,
              "vector_shards": [{"relative_path": item.relative_path, **dict(item.reference)} for item in artifacts],
              "status_counts": counts, "training_eligible_count": 0, "rows": rows,
              "vector_dispositions": dispositions, "model_artifact_evidence": model_evidence,
              "model_id_is_not_producer_evidence": True,
              "missing_producer_evidence": ["exact_embedding_input_hash", "input_projection_configuration",
                                            "actual_backend_receipt", "producer_model_artifact_binding"],
              "chunk_order_inferred": False, "source_selectors_inferred": False,
              "embedding_generation_performed": False, "weights_downloaded": False}
    diagnostics = tuple((row["entry_cid"], diagnostic_vectors[row["entry_cid"]])
                        for row in rows if row["status"] == "missing_input_binding")
    return EmbeddingJoinAudit(_bytes(report), diagnostics)


__all__ = ["EmbeddingJoinAudit", "EmbeddingJoinLimits", "USCodeEmbeddingJoinError", "audit_uscode_embedding_join"]
