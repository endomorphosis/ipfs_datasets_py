"""Owner-exported immutable corpus inputs for the native local daemon.

The explicit descriptor is a trusted local handoff, not an authenticated issuer
identity. An offline consumer verifies bytes and bindings; it neither opens the
owner database nor acquires a run lease, checkpoint authority, or promotion right.
No training settings are inherited from the archived worker job.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
import threading
import time
from typing import Any

from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from . import autoencoder_training_coordinator as coordinator
from .autoencoder_training_worker import (
    ARROW_INPUT_SCHEMA_VERSION, CAMPAIGN_SCHEMA_VERSION, MAX_ARROW_EMBEDDING_INPUT_BYTES, PRODUCED_SCHEMA_VERSION,
    TrainingJobSpec, _verify_corpus_job_inputs,
)


SCHEMA_VERSION = "autoencoder-daemon-corpus-inputs-v1"
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_JOB_BYTES = 64 * 1024 * 1024
_FIELDS = {"schema_version", "run_id", "variant_id", "job_spec_sha256", "job_spec_artifact",
           "variant_manifest", "variant_manifest_sha256", "artifact_root"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CAMPAIGN_ARTIFACT_FIELDS = {
    "source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
    "produced_record_projection_artifact", "embedding_receipt_artifacts",
    "corpus_manifest_artifact", "corpus_source_artifacts",
}
_CAMPAIGN_VERIFICATION_FIELDS = {
    "source_campaign_verified", "source_campaign_verification",
    "produced_record_projection_verified", "produced_record_projection_verification",
}


class DaemonCorpusInputError(ValueError):
    """An explicit immutable input binding failed; live fallback is forbidden."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _reference(value, maximum):
    if (type(value) is not dict or set(value) != {"sha256", "bytes"}
            or not _digest(value["sha256"]) or type(value["bytes"]) is not int
            or not 1 <= value["bytes"] <= maximum):
        raise DaemonCorpusInputError("invalid bounded artifact reference")
    return value


def _parse_snapshot(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_SNAPSHOT_BYTES:
        raise DaemonCorpusInputError("input snapshot exceeds byte bound")
    try:
        data = coordinator._read_json(raw)
        if type(data) is not dict or set(data) != _FIELDS or data["schema_version"] != SCHEMA_VERSION:
            raise DaemonCorpusInputError("unknown input snapshot schema or fields")
        if canonical_json_bytes(data) != raw:
            raise DaemonCorpusInputError("input snapshot must use exact canonical JSON")
        for key in ("run_id", "variant_id"):
            if type(data[key]) is not str or not data[key] or len(data[key]) > 256:
                raise DaemonCorpusInputError("invalid input snapshot identity")
        if not _digest(data["job_spec_sha256"]) or not _digest(data["variant_manifest_sha256"]):
            raise DaemonCorpusInputError("invalid input snapshot digest")
        _reference(data["job_spec_artifact"], MAX_JOB_BYTES)
        if (type(data["variant_manifest"]) is not dict
                or _sha(canonical_json_bytes(data["variant_manifest"])) != data["variant_manifest_sha256"]):
            raise DaemonCorpusInputError("registered variant manifest digest mismatch")
        root = data["artifact_root"]
        if type(root) is not str or not root or not Path(root).is_absolute() or str(Path(root).resolve()) != root:
            raise DaemonCorpusInputError("artifact root must be an absolute unaliased path")
        return data
    except (TypeError, ValueError, UnicodeError, RecursionError, OSError) as exc:
        if isinstance(exc, DaemonCorpusInputError):
            raise
        raise DaemonCorpusInputError("invalid strict input snapshot") from exc


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_bound(path, reference, *, retain=False):
    """Hash one regular file and pin its pathname/stat identity at both ends."""
    path = Path(path)
    try:
        if not path.is_absolute() or path.resolve() != path:
            raise DaemonCorpusInputError("input artifact path must not contain symlink aliases")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != reference["bytes"]:
                raise DaemonCorpusInputError("input artifact is not a regular file of the declared size")
            digest, count = hashlib.sha256(), 0
            blocks = [] if retain else None
            while block := stream.read(min(1024 * 1024, reference["bytes"] + 1 - count)):
                count += len(block)
                if count > reference["bytes"]:
                    raise DaemonCorpusInputError("input artifact grew during verification")
                digest.update(block)
                if retain:
                    blocks.append(block)
            after = os.fstat(stream.fileno())
            named = path.stat(follow_symlinks=False)
        if (_identity(before) != _identity(after) or _identity(before) != _identity(named)
                or path.resolve() != path or count != reference["bytes"]
                or digest.hexdigest() != reference["sha256"]):
            raise DaemonCorpusInputError("input artifact bytes or pathname changed")
        return _identity(before), b"".join(blocks) if retain else None
    except OSError as exc:
        raise DaemonCorpusInputError("input artifact is missing or unreadable") from exc


@dataclass(frozen=True)
class DaemonCorpusInputDescriptor:
    path: str
    sha256: str
    bytes: int

    def __post_init__(self):
        if type(self.path) is not str or not self.path or not Path(self.path).is_absolute():
            raise DaemonCorpusInputError("input snapshot path must be absolute")
        _reference({"sha256": self.sha256, "bytes": self.bytes}, MAX_SNAPSHOT_BYTES)

    @classmethod
    def from_options(cls, path=None, sha256=None, bytes=None):
        values = (path, sha256, bytes)
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise DaemonCorpusInputError("all three corpus input descriptor options are required")
        return cls(path, sha256, bytes)

    def to_dict(self):
        return asdict(self)


def export_daemon_corpus_inputs(registry, run_id: str, *, operation_id: str):
    """Verify, stage and durably register inputs through the already-open owner.

    No timestamps or owner generation enter the exported bytes. Repeating the
    same operation after restart therefore resolves the same immutable artifact.
    V6 and v8 retain list vectors; an exact v7 job opts into its bound Arrow input.
    """
    resolved = coordinator.registered_corpus_job_inputs(registry, run_id)
    spec = resolved["spec"]
    if spec.schema_version not in (PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, CAMPAIGN_SCHEMA_VERSION):
        raise DaemonCorpusInputError("daemon corpus inputs require exactly a v6, v7 or v8 job")
    variant = resolved["variant"]
    payload = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id,
        "variant_id": resolved["run"]["variant_id"],
        "job_spec_sha256": spec.canonical_sha256,
        "job_spec_artifact": resolved["job_spec_artifact"],
        "variant_manifest": variant, "variant_manifest_sha256": _sha(canonical_json_bytes(variant)),
        "artifact_root": str(registry.artifact_root),
    }
    raw = canonical_json_bytes(payload)
    _parse_snapshot(raw)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=registry.artifact_root, prefix=".input-snapshot-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        artifact = registry.stage_artifact(temporary, expected_sha256=_sha(raw))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    descriptor = DaemonCorpusInputDescriptor(str(registry.artifact_path(artifact)), **artifact)
    # Consumer verification includes the stricter unaliased CAS path contract.
    with VerifiedDaemonCorpusInputs(descriptor):
        pass
    registration = registry.register_input_snapshot(
        operation_id, run_id, artifact, payload["job_spec_sha256"], payload["variant_manifest_sha256"])
    return {"descriptor": descriptor.to_dict(), "registration": registration}


def corpus_input_checkpoint_provenance(descriptor: dict, summary: dict) -> dict:
    """Return detached checkpoint bindings, retaining the exact v6 wire shape.

    V7 transport claims come from the verified Arrow summary, never from sample
    counters or a best-effort fallback. This is not issuer or model authority.
    """
    if (summary.get("job_schema_version") == CAMPAIGN_SCHEMA_VERSION
            or _CAMPAIGN_ARTIFACT_FIELDS.intersection(summary)
            or _CAMPAIGN_VERIFICATION_FIELDS.intersection(summary.get("corpus_verification", {}))):
        return _campaign_checkpoint_provenance(descriptor, summary)
    try:
        verification = summary["corpus_verification"]
        producer = verification["embedding_production_verification"]
        result = {
            "descriptor": dict(descriptor), "job_spec_sha256": summary["job_spec_sha256"],
            "variant_manifest_sha256": summary["variant_manifest_sha256"],
            "dataset_snapshot_id": verification["dataset_snapshot_id"],
            "split_snapshot_id": verification["split_snapshot_id"],
            "index_sha256": verification["corpus_index_verification"]["index_sha256"],
            "embedding_production_artifact": {"sha256": producer["sha256"], "bytes": producer["bytes"]},
            "binding": "owner_snapshot_transitive_input_identity", "checkpoint_authority_verified": False,
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise DaemonCorpusInputError("incomplete verified corpus input provenance") from exc
    arrow_keys = {"job_schema_version", "embedding_input_storage", "arrow_embedding_inputs_artifact",
                  "arrow_embedding_inputs_statistics"}
    if (arrow_keys.intersection(summary) or "arrow_embedding_inputs_verified" in verification
            or "arrow_embedding_inputs_verification" in verification):
        from .autoencoder_arrow_inputs import DIMENSION, MAX_RECORDS, SCHEMA_VERSION as arrow_schema
        try:
            artifact = _reference(summary["arrow_embedding_inputs_artifact"], MAX_ARROW_EMBEDDING_INPUT_BYTES)
            arrow = verification["arrow_embedding_inputs_verification"]
            fields = {"schema_version", "artifact_sha256", "artifact_bytes", "production_sha256",
                "production_bytes", "ordered_record_ids_sha256", "row_count", "dimension",
                "mapped_numeric_bytes", "zero_copy_numeric_buffers_verified", "read_only", "whole_training_zero_copy"}
            if (summary["job_schema_version"] != ARROW_INPUT_SCHEMA_VERSION
                    or summary["embedding_input_storage"] != "arrow_mapped_float32"
                    or verification["arrow_embedding_inputs_verified"] is not True
                    or type(arrow) is not dict or set(arrow) != fields
                    or arrow["schema_version"] != arrow_schema
                    or arrow["artifact_sha256"] != artifact["sha256"]
                    or type(arrow["artifact_bytes"]) is not int or arrow["artifact_bytes"] != artifact["bytes"]
                    or arrow["production_sha256"] != producer["sha256"]
                    or type(arrow["production_bytes"]) is not int or arrow["production_bytes"] != producer["bytes"]
                    or not _digest(arrow["ordered_record_ids_sha256"])
                    or type(arrow["row_count"]) is not int or not 1 <= arrow["row_count"] <= MAX_RECORDS
                    or type(summary["row_count"]) is not int or arrow["row_count"] != summary["row_count"]
                    or type(arrow["dimension"]) is not int or arrow["dimension"] != DIMENSION
                    or type(arrow["mapped_numeric_bytes"]) is not int
                    or arrow["mapped_numeric_bytes"] != arrow["row_count"] * DIMENSION * 4
                    or arrow["zero_copy_numeric_buffers_verified"] is not True
                    or arrow["read_only"] is not True or arrow["whole_training_zero_copy"] is not False):
                raise DaemonCorpusInputError("invalid verified v7 input provenance")
            result.update(arrow_embedding_inputs_artifact=dict(artifact),
                embedding_input_storage="arrow_mapped_float32", arrow_embedding_inputs_verification=dict(arrow))
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, DaemonCorpusInputError):
                raise
            raise DaemonCorpusInputError("incomplete verified v7 input provenance") from exc
    return json.loads(json.dumps(result))


def _campaign_checkpoint_provenance(descriptor, summary):
    """Keep campaign roots and selected leaf identity distinct from v6/v7."""
    try:
        if (type(descriptor) is not dict
                or DaemonCorpusInputDescriptor(**descriptor).to_dict() != summary["descriptor"]
                or summary["input_integrity_verified"] is not True):
            raise DaemonCorpusInputError("v8 provenance requires the verified exact input descriptor")
        verification = summary["corpus_verification"]
        campaign = verification["source_campaign_verification"]
        partition = campaign["source_partition_verification"]
        receipt_set = campaign["receipt_set_verification"]
        projection = verification["produced_record_projection_verification"]
        forbidden = {"corpus_index_verification", "corpus_index_membership_verified",
            "embedding_production_verification", "embedding_production_verified",
            "arrow_embedding_inputs_verification", "arrow_embedding_inputs_verified"}
        if (summary["job_schema_version"] != CAMPAIGN_SCHEMA_VERSION
                or summary["embedding_input_storage"] != "python_list"
                or forbidden.intersection(verification)
                or {"arrow_embedding_inputs_artifact", "arrow_embedding_inputs_statistics"}.intersection(summary)
                or verification["source_campaign_verified"] is not True
                or verification["produced_record_projection_verified"] is not True
                or verification["dataset_and_split_identity_verified"] is not True
                or verification["global_holdout_verified"] is not False):
            raise DaemonCorpusInputError("invalid verified v8 input provenance")
        refs = {key: dict(_reference(summary[key], MAX_JOB_BYTES)) for key in (
            "source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
            "produced_record_projection_artifact", "corpus_manifest_artifact")}
        for key in ("embedding_receipt_artifacts", "corpus_source_artifacts"):
            values = summary[key]
            if type(values) is not list or not 1 <= len(values) <= 256:
                raise DaemonCorpusInputError("invalid selected v8 artifact closure")
            refs[key] = [dict(_reference(value, MAX_JOB_BYTES)) for value in values]
            if len({value["sha256"] for value in values}) != len(values):
                raise DaemonCorpusInputError("duplicate selected v8 artifact closure")
        selected = projection["selected_artifacts"]
        if (campaign["source_inventory"] != refs["source_inventory_artifact"]
                or campaign["source_partitions"] != refs["source_partitions_artifact"]
                or campaign["embedding_receipt_set"] != refs["embedding_receipt_set_artifact"]
                or partition["inventory_sha256"] != refs["source_inventory_artifact"]["sha256"]
                or partition["source_partitions_sha256"] != refs["source_partitions_artifact"]["sha256"]
                or type(partition["source_partitions_bytes"]) is not int
                or partition["source_partitions_bytes"] != refs["source_partitions_artifact"]["bytes"]
                or receipt_set["receipt_set_sha256"] != refs["embedding_receipt_set_artifact"]["sha256"]
                or type(receipt_set["receipt_set_bytes"]) is not int
                or receipt_set["receipt_set_bytes"] != refs["embedding_receipt_set_artifact"]["bytes"]
                or receipt_set["source_partitions_sha256"] != refs["source_partitions_artifact"]["sha256"]
                or projection["projection_sha256"] != refs["produced_record_projection_artifact"]["sha256"]
                or type(projection["projection_bytes"]) is not int
                or projection["projection_bytes"] != refs["produced_record_projection_artifact"]["bytes"]
                or projection["receipt_set"] != refs["embedding_receipt_set_artifact"]
                or projection["source_partitions"] != refs["source_partitions_artifact"]
                or projection["corpus_manifest"] != refs["corpus_manifest_artifact"]
                or type(selected) is not dict or set(selected) != {"leaf_receipts", "source_artifacts"}
                or selected["leaf_receipts"] != sorted(refs["embedding_receipt_artifacts"], key=lambda value: value["sha256"])
                or selected["source_artifacts"] != sorted(refs["corpus_source_artifacts"], key=lambda value: value["sha256"])):
            raise DaemonCorpusInputError("v8 provenance differs from exact campaign or selected closure")
        if (type(summary["row_count"]) is not int or not 1 <= summary["row_count"] <= 256
                or any(type(projection[key]) is not int or projection[key] != summary["row_count"]
                       for key in ("record_count", "supplied_records_verified"))
                or any(projection[key] is not True for key in (
                    "supplied_manifest_verified", "current_selected_leaf_bytes_verified",
                    "current_selected_source_bytes_verified", "native_execution_profile"))
                or any(projection[key] is not False for key in (
                    "runtime_cryptographically_attested", "source_authority_authenticated", "global_holdout_verified",
                    "corpus_complete", "training_eligible", "admitted"))
                or any(projection[key] != verification[key] for key in ("dataset_snapshot_id", "split_snapshot_id"))):
            raise DaemonCorpusInputError("invalid verified v8 projection provenance")
        if (partition["complete_declared_inventory_bound"] is not True
                or partition["source_group_partition_disjoint_verified"] is not True
                or receipt_set["native_execution_profile"] is not True
                or any(partition[key] is not False for key in (
                    "source_authority_authenticated", "embedding_producer_authenticated", "global_holdout_verified", "admitted"))
                or any(receipt_set[key] is not False for key in (
                    "runtime_cryptographically_attested", "source_authority_authenticated", "global_holdout_verified", "admitted"))):
            raise DaemonCorpusInputError("invalid verified v8 campaign provenance claims")
        for key in ("job_spec_sha256", "variant_manifest_sha256"):
            if not _digest(summary[key]):
                raise DaemonCorpusInputError("invalid v8 job provenance digest")
        result = {
            "descriptor": dict(descriptor), "job_schema_version": CAMPAIGN_SCHEMA_VERSION,
            "job_spec_sha256": summary["job_spec_sha256"],
            "variant_manifest_sha256": summary["variant_manifest_sha256"],
            "dataset_snapshot_id": verification["dataset_snapshot_id"],
            "split_snapshot_id": verification["split_snapshot_id"],
            **refs, "embedding_input_storage": "python_list",
            "binding": "owner_snapshot_source_campaign_projection_identity",
            "checkpoint_authority_verified": False, "source_authority_authenticated": False,
            "embedding_producer_authenticated": False, "runtime_cryptographically_attested": False,
            "global_holdout_verified": False, "admitted": False,
        }
        return json.loads(json.dumps(result))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, DaemonCorpusInputError):
            raise
        raise DaemonCorpusInputError("incomplete verified v8 input provenance") from exc


class VerifiedDaemonCorpusInputs:
    """Bounded offline input session; snapshots and files must remain immutable.

    Boundary hashes detect persistent changes and pathname replacement. They do
    not detect a concurrent writer that changes and restores bytes between checks.
    No database handle is retained. V6 and v8 samples own ordinary lists. V7 samples
    borrow this session's verified mapping; asynchronous copies detach their
    vectors before crossing the snapshot publication boundary.
    """

    def __init__(self, descriptor: DaemonCorpusInputDescriptor):
        if type(descriptor) is not DaemonCorpusInputDescriptor:
            raise TypeError("descriptor must be DaemonCorpusInputDescriptor")
        self._descriptor = descriptor
        self._resources = ExitStack()
        self._mapped_inputs = None
        self._arrow_artifact = None
        self._campaign_artifacts = None
        self._thread = threading.get_ident()
        self._closed = self._poisoned = False
        self._verified = False
        self._failure = None
        self._guards = {}
        self._records = ()
        self._indices = {}
        self._sample_digests = {}
        self._counts = {"boundary_checks": 0, "samples_built": 0, "selected_checks": 0}
        self._guard_seconds = 0.0
        try:
            from ...logic.autoformal.tree_pin import require_workspace_logic_tree
            self._resolved_paths = require_workspace_logic_tree()
            reference = {"sha256": descriptor.sha256, "bytes": descriptor.bytes}
            raw = self._bind(descriptor.path, reference, retain=True)
            self._snapshot = _parse_snapshot(raw)
            root = Path(self._snapshot["artifact_root"])
            if Path(descriptor.path) != root / descriptor.sha256[:2] / descriptor.sha256:
                raise DaemonCorpusInputError("snapshot must name its owner-staged CAS artifact")
            job_ref = self._snapshot["job_spec_artifact"]
            job_path = root / job_ref["sha256"][:2] / job_ref["sha256"]
            job_raw = self._bind(job_path, job_ref, retain=True)
            spec = TrainingJobSpec.from_dict(coordinator._read_json(job_raw))
            if spec.schema_version not in (PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, CAMPAIGN_SCHEMA_VERSION):
                raise DaemonCorpusInputError("daemon corpus inputs require exactly a v6, v7 or v8 job")
            if (spec.run_id != self._snapshot["run_id"]
                    or spec.canonical_sha256 != self._snapshot["job_spec_sha256"]):
                raise DaemonCorpusInputError("snapshot differs from exact registered job identity")
            variant = self._snapshot["variant_manifest"]
            coordinator._verify_variant_source_campaign_binding(variant, spec)
            coordinator._verify_variant_index_binding(variant, spec)
            coordinator._verify_variant_embedding_production_binding(variant, spec)
            if any(variant.get(name) != value for name, value in asdict(spec.variant).items()):
                raise DaemonCorpusInputError("snapshot variant differs from job variant")
            if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
                metadata = (spec.corpus_manifest_artifact, spec.source_inventory_artifact,
                    spec.source_partitions_artifact, spec.embedding_receipt_set_artifact,
                    spec.produced_record_projection_artifact)
                artifacts = (*metadata, *spec.embedding_receipt_artifacts, *spec.corpus_source_artifacts)
                self._campaign_artifacts = {
                    key: {"sha256": getattr(spec, key).sha256, "bytes": getattr(spec, key).bytes}
                    for key in _CAMPAIGN_ARTIFACT_FIELDS - {"embedding_receipt_artifacts", "corpus_source_artifacts"}}
                self._campaign_artifacts.update({
                    key: [{"sha256": item.sha256, "bytes": item.bytes} for item in getattr(spec, key)]
                    for key in ("embedding_receipt_artifacts", "corpus_source_artifacts")})
            else:
                metadata = None
                artifacts = (spec.corpus_manifest_artifact, spec.corpus_index_artifact,
                             spec.embedding_production_artifact, *spec.corpus_source_artifacts)
            if spec.schema_version == ARROW_INPUT_SCHEMA_VERSION:
                artifacts += (spec.arrow_embedding_inputs_artifact,)
                self._arrow_artifact = {"sha256": spec.arrow_embedding_inputs_artifact.sha256,
                                        "bytes": spec.arrow_embedding_inputs_artifact.bytes}
            for artifact in artifacts:
                path = root / artifact.sha256[:2] / artifact.sha256
                if artifact.path != str(path):
                    raise DaemonCorpusInputError("corpus inputs must name the exact owner-staged CAS path")
                # V8's worker authorizes every frozen role before source/leaf
                # access. Do not pre-read these files in the daemon handoff.
                if metadata is None or artifact in metadata:
                    self._bind(path, {"sha256": artifact.sha256, "bytes": artifact.bytes})
            self._verification, self._mapped_inputs = _verify_corpus_job_inputs(spec, self._resources)
            if metadata is not None:
                for artifact in (*spec.embedding_receipt_artifacts, *spec.corpus_source_artifacts):
                    self._bind(artifact.path, {"sha256": artifact.sha256, "bytes": artifact.bytes})
            from .autoencoder_corpus_manifest import load_corpus_manifest
            manifest = load_corpus_manifest(
                spec.corpus_manifest_artifact.path, expected_sha256=spec.corpus_manifest_artifact.sha256,
                expected_size_bytes=spec.corpus_manifest_artifact.bytes)
            self._records = manifest.records
            positions = {record.record_id: index for index, record in enumerate(self._records)}
            self._indices = {
                "train": tuple(positions[key] for key in self._verification["training_record_ids"]),
                "validation": tuple(positions[key] for key in self._verification["validation_record_ids"]),
            }
            self.verify_boundary("open")
            self._verified = True
        except BaseException as exc:
            try:
                self.close()
            except BaseException as cleanup:
                exc.add_note(f"input session cleanup also failed: {type(cleanup).__name__}")
            raise

    def _bind(self, path, reference, *, retain=False):
        identity, raw = _read_bound(path, reference, retain=retain)
        key = str(path)
        previous = self._guards.get(key)
        bound = (dict(reference), identity)
        if previous is not None and previous != bound:
            raise DaemonCorpusInputError("conflicting immutable input artifact bindings")
        self._guards[key] = bound
        return raw

    def _usable(self):
        if self._closed:
            raise DaemonCorpusInputError("corpus input session is closed")
        if threading.get_ident() != self._thread:
            raise DaemonCorpusInputError("corpus input session must remain on its owning thread")
        if self._poisoned:
            raise DaemonCorpusInputError("corpus input session is poisoned; start a fresh session")

    def _record(self, index):
        self._usable()
        if type(index) is not int or not 0 <= index < len(self._records):
            raise DaemonCorpusInputError("invalid corpus row index")
        return self._records[index]

    @property
    def row_count(self):
        self._usable()
        return len(self._records)

    def indices_for(self, role):
        self._usable()
        if type(role) is not str or role not in self._indices:
            raise DaemonCorpusInputError("only train and validation roles are available")
        return self._indices[role]

    def record_id(self, index):
        return self._record(index).record_id

    def text_length(self, index):
        return len(self._record(index).sample.text)

    def build_sample(self, index):
        record = self._record(index)
        from .legal_samples import build_us_code_sample
        if self._mapped_inputs is None:
            sample = build_us_code_sample(**asdict(record.sample))
        else:
            row = record.sample
            sample = build_us_code_sample(title=row.title, section=row.section, text=row.text,
                citation=row.citation, embedding_model=row.embedding_model,
                embedding_vector=self._mapped_inputs.row(record.record_id))
        digest = self._sample_digest(sample, record)
        previous = self._sample_digests.get(index)
        if previous is not None and previous != digest:
            self._poisoned = True
            self._failure = {"phase": "build_sample", "error_type": "DaemonCorpusInputError"}
            raise DaemonCorpusInputError("native sample identity changed for the same immutable row")
        self._sample_digests[index] = digest
        self._counts["samples_built"] += 1
        return sample

    def _sample_digest(self, sample, record):
        from .legal_samples import LegalSample
        if type(sample) is not LegalSample:
            raise DaemonCorpusInputError("verified inputs require an exact native LegalSample")
        expected = record.sample
        # V6 requires corpus mode: its explicit, nonempty source citation must
        # equal SampleRecord.citation. The native fallback for None never applies.
        fields = ("title", "section", "text", "citation", "embedding_model")
        if any(type(getattr(sample, key)) is not str or getattr(sample, key) != getattr(expected, key)
               for key in fields):
            raise DaemonCorpusInputError("selected sample source fields differ from the exact corpus row")
        vector = sample.embedding_vector
        if self._mapped_inputs is None:
            if type(vector) is not list:
                raise DaemonCorpusInputError("selected sample requires the exact native list vector")
        else:
            from .autoencoder_arrow_inputs import MappedEmbeddingVector
            if (type(vector) is not MappedEmbeddingVector or vector._owner is not self._mapped_inputs
                    or vector.record_id != record.record_id):
                raise DaemonCorpusInputError("selected sample requires its session-owned mapped record vector")
        if (len(vector) != len(expected.embedding_vector)
                or any(type(value) is not float for value in vector)):
            raise DaemonCorpusInputError("selected sample vector shape or scalar type differs")
        bits = b"".join(struct.pack("!d", value) for value in vector)
        expected_bits = b"".join(struct.pack("!d", value) for value in expected.embedding_vector)
        if bits != expected_bits:
            raise DaemonCorpusInputError("selected sample vector bits differ from the exact corpus row")
        payload = {key: getattr(sample, key) for key in (*fields, "sample_id", "source", "normalized_text")}
        if any(type(value) is not str or not value for value in payload.values()) or sample.source != "us_code":
            raise DaemonCorpusInputError("invalid native sample identity fields")
        payload["vector_float64_bits"] = bits.hex()
        return _sha(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False).encode("utf-8"))

    def verify_selected(self, indices, samples, *, role):
        """Check consumed source/vector identity, without reparsing or sealing IR."""
        self._usable()
        try:
            allowed = frozenset(self.indices_for(role))
            if (type(indices) not in (list, tuple) or type(samples) not in (list, tuple)
                    or len(indices) != len(samples) or len(indices) > len(allowed)
                    or any(type(index) is not int for index in indices)
                    or len(set(indices)) != len(indices)):
                raise DaemonCorpusInputError("selection must be a bounded unique ordered row/sample sequence")
            for index, sample in zip(indices, samples):
                if index not in allowed:
                    raise DaemonCorpusInputError("selected row is outside its frozen role partition")
                expected = self._sample_digests.get(index)
                if expected is None or self._sample_digest(sample, self._record(index)) != expected:
                    raise DaemonCorpusInputError("selected sample differs from the native factory input identity")
            self._counts["selected_checks"] += 1
        except BaseException as exc:
            self._poisoned = True
            self._failure = {"phase": "verify_selected", "error_type": type(exc).__name__}
            raise

    def verify_boundary(self, phase):
        self._usable()
        if type(phase) is not str or not phase or len(phase) > 128:
            raise DaemonCorpusInputError("boundary phase must be a bounded nonempty string")
        started = time.perf_counter()
        try:
            for path, (reference, expected_identity) in self._guards.items():
                identity, _ = _read_bound(path, reference)
                if identity != expected_identity:
                    raise DaemonCorpusInputError("immutable input artifact identity changed")
            if self._mapped_inputs is not None:
                self._mapped_inputs.verify_unchanged()
            self._counts["boundary_checks"] += 1
        except BaseException as exc:
            self._poisoned = True
            self._failure = {"phase": phase, "error_type": type(exc).__name__}
            raise
        finally:
            self._guard_seconds += time.perf_counter() - started

    def summary(self):
        result = {
            "schema_version": SCHEMA_VERSION, "descriptor": self._descriptor.to_dict(),
            "input_identity": {"sha256": self._descriptor.sha256, "bytes": self._descriptor.bytes},
            "run_id": self._snapshot["run_id"], "variant_id": self._snapshot["variant_id"],
            "job_spec_sha256": self._snapshot["job_spec_sha256"],
            "variant_manifest_sha256": self._snapshot["variant_manifest_sha256"],
            "resolved_paths": dict(self._resolved_paths),
            # After close this records the last completed verification, not a
            # fresh availability check; closed sessions cannot consume inputs.
            "input_integrity_verified": self._verified and not self._poisoned,
            "row_count": len(self._records),
            "partition_counts": {role: len(indices) for role, indices in self._indices.items()},
            "corpus_verification": json.loads(json.dumps(self._verification)),
            "counts": dict(self._counts), "guard_seconds": self._guard_seconds,
            "closed": self._closed, "poisoned": self._poisoned,
            "failure": None if self._failure is None else dict(self._failure),
            "handoff": "explicit_trusted_local_descriptor", "issuer_authenticated": False,
            "live_owner_lease_verified": False, "checkpoint_authority_verified": False,
            "promotion_authorized": False, "admitted": False,
        }
        if self._mapped_inputs is not None:
            result.update(job_schema_version=ARROW_INPUT_SCHEMA_VERSION,
                embedding_input_storage="arrow_mapped_float32",
                arrow_embedding_inputs_artifact=dict(self._arrow_artifact),
                arrow_embedding_inputs_statistics=dict(self._mapped_inputs.statistics))
        if self._campaign_artifacts is not None:
            result.update(job_schema_version=CAMPAIGN_SCHEMA_VERSION, embedding_input_storage="python_list",
                          **json.loads(json.dumps(self._campaign_artifacts)))
        return result

    def close(self):
        if not self._closed:
            self._closed = True
            self._resources.close()

    def __enter__(self):
        self._usable()
        return self

    def __exit__(self, *_):
        self.close()
