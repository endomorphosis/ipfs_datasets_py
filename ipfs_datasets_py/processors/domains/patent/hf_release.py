"""Deterministic local JusticeDAO patent/legal Hugging Face release packaging.

:class:`PatentLegalHFReleaseBuilder` builds content-addressed public shards for
configurable CFR/USC/Public Law/FR/projected-rules and public patent
applications/claims/events/office-actions/citations/graph/BM25/vector-metadata
families.  Every staged artifact binds SHA-256, CIDv1, row count, source
lineage, classification, and rights review.

Default mode is **dry-run**: admission and in-memory packaging run, but the
filesystem is not mutated and no remote write path exists.  Explicit
``dry_run=False`` stages local files only.  This module never imports or calls
``HfApi.upload_file``; publication is a separate operator-approved action
(PATLAW-102).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final

from ....huggingface.publication_profile import (
    PATENT_LEGAL_CANONICAL_RELEASE_SCHEMA,
    PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    PATENT_LEGAL_PROGRAM_ID,
)
from ....huggingface.release import (
    DEFAULT_SHARD_ROWS,
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
)
from ....logic.ir_core.identity import cid_v1_from_digest
from .release_policy import (
    ARTIFACT_KINDS,
    BatchAdmission,
    PatentReleasePolicy,
    ReleaseCandidate,
    ReleasePolicyError,
)

HF_RELEASE_SCHEMA_VERSION: Final = PATENT_LEGAL_CANONICAL_RELEASE_SCHEMA
HF_RELEASE_PRODUCER: Final = "producer:patent-legal-hf-release"
HF_RELEASE_CONFIG: Final = "config:patent-legal-hf-release/v1"
DEFAULT_DATASET_REPO_ID: Final = PATENT_LEGAL_DEFAULT_REPOSITORY_ID
DEFAULT_MAX_ROWS_PER_SHARD: Final = min(DEFAULT_SHARD_ROWS, 1024)
MANIFEST_FILENAME: Final = "release-manifest.json"
DATASET_INFOS_FILENAME: Final = "dataset_infos.json"
README_FILENAME: Final = "README.md"
POLICY_RECEIPT_FILENAME: Final = "policy-admission.json"

_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PatentHFReleaseError(HuggingFaceReleaseError):
    """Raised when a patent/legal release cannot be built or validated."""


class PatentReleaseSafetyError(PatentHFReleaseError):
    """Raised when private/mixed input is detected before staging."""


class PatentReleaseIntegrityError(PatentHFReleaseError):
    """Raised when release artifacts do not match their descriptors."""


@dataclass(frozen=True, slots=True)
class PatentReleaseArtifact:
    """One immutable release file with full integrity and policy metadata."""

    relative_path: str
    content: bytes = field(repr=False)
    media_type: str
    row_count: int
    config_name: str
    source_lineage: tuple[Mapping[str, Any], ...]
    classifications: tuple[str, ...]
    rights_reviews: tuple[Mapping[str, Any], ...]
    sha256: str = ""
    content_cid: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        path = _safe_relative_path(self.relative_path)
        if not isinstance(self.content, (bytes, bytearray)):
            raise PatentHFReleaseError("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and self.sha256 != digest:
            raise PatentReleaseIntegrityError(
                f"artifact sha256 mismatch for {path}"
            )
        if self.content_cid and self.content_cid != cid:
            raise PatentReleaseIntegrityError(
                f"artifact content_cid mismatch for {path}"
            )
        if type(self.row_count) is not int or self.row_count < 0:
            raise PatentHFReleaseError("row_count must be a non-negative integer")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise PatentHFReleaseError("media_type is required")
        lineages = tuple(
            MappingProxyType(dict(item)) for item in self.source_lineage
        )
        rights = tuple(
            MappingProxyType(dict(item)) for item in self.rights_reviews
        )
        classes = tuple(sorted({str(item) for item in self.classifications if item}))
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "size_bytes", len(content))
        object.__setattr__(self, "source_lineage", lineages)
        object.__setattr__(self, "rights_reviews", rights)
        object.__setattr__(self, "classifications", classes)

    def descriptor(self) -> dict[str, Any]:
        """Full inventory entry: SHA-256/CID/rows/lineage/classification/rights."""

        return {
            "classifications": list(self.classifications),
            "config_name": self.config_name,
            "content_cid": self.content_cid,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "rights_reviews": [dict(item) for item in self.rights_reviews],
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_lineage": [dict(item) for item in self.source_lineage],
        }

    def to_file_descriptor(self) -> FileDescriptor:
        return FileDescriptor(
            relative_path=self.relative_path,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            content_cid=self.content_cid,
            media_type=self.media_type,
            schema_type=HF_RELEASE_SCHEMA_VERSION,
            producer_id=HF_RELEASE_PRODUCER,
            config_digest=HF_RELEASE_CONFIG,
            row_count=self.row_count,
            config_name=self.config_name,
            license_id=_primary_license(self.rights_reviews),
            review_status="reviewed",
            trust_decision="public_release_admitted",
            metadata={
                "classifications": list(self.classifications),
                "rights_reviews": [dict(item) for item in self.rights_reviews],
                "source_lineage": [dict(item) for item in self.source_lineage],
            },
        )


@dataclass(frozen=True, slots=True)
class PatentHuggingFaceRelease:
    """Complete in-memory local release (dry-run or staged)."""

    dataset_id: str
    release_root_cid: str
    schema_version: str
    policy_sha256: str
    policy_version: str
    batch_admission: BatchAdmission
    artifacts: tuple[PatentReleaseArtifact, ...]
    dry_run: bool
    staged_root: str | None = None

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise PatentHFReleaseError("dataset_id must be owner/name")
        if not self.artifacts:
            raise PatentHFReleaseError("release must contain artifacts")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise PatentReleaseIntegrityError("artifact paths must be unique")
        ordered = tuple(sorted(self.artifacts, key=lambda item: item.relative_path))
        object.__setattr__(self, "artifacts", ordered)
        if type(self.dry_run) is not bool:
            raise PatentHFReleaseError("dry_run must be boolean")

    def artifact(self, relative_path: str) -> PatentReleaseArtifact:
        for item in self.artifacts:
            if item.relative_path == relative_path:
                return item
        raise KeyError(relative_path)

    @property
    def parquet_artifacts(self) -> tuple[PatentReleaseArtifact, ...]:
        return tuple(
            item for item in self.artifacts if item.relative_path.endswith(".parquet")
        )

    @property
    def total_row_count(self) -> int:
        return sum(item.row_count for item in self.parquet_artifacts)

    def manifest_dict(self) -> dict[str, Any]:
        return json.loads(self.artifact(MANIFEST_FILENAME).content.decode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.descriptor() for item in self.artifacts],
            "dataset_id": self.dataset_id,
            "dry_run": self.dry_run,
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "program_id": PATENT_LEGAL_PROGRAM_ID,
            "release_root_cid": self.release_root_cid,
            "schema_version": self.schema_version,
            "staged_root": self.staged_root,
            "total_row_count": self.total_row_count,
        }


@dataclass(frozen=True, slots=True)
class PatentLegalHFReleaseBuilder:
    """Deterministic local builder for privacy-reviewed JusticeDAO artifacts."""

    dataset_id: str = DEFAULT_DATASET_REPO_ID
    max_rows_per_shard: int = DEFAULT_MAX_ROWS_PER_SHARD
    policy: PatentReleasePolicy = field(default_factory=PatentReleasePolicy)

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise PatentHFReleaseError("dataset_id must be owner/name")
        if (
            type(self.max_rows_per_shard) is not int
            or self.max_rows_per_shard <= 0
        ):
            raise PatentHFReleaseError("max_rows_per_shard must be a positive integer")
        if not isinstance(self.policy, PatentReleasePolicy):
            raise PatentHFReleaseError("policy must be PatentReleasePolicy")
        _assert_no_upload_shortcut()

    def build(
        self,
        candidates: Sequence[ReleaseCandidate | Mapping[str, Any]],
        *,
        dry_run: bool = True,
        output_dir: str | Path | None = None,
    ) -> PatentHuggingFaceRelease:
        """Build a deterministic release.

        Default ``dry_run=True`` validates privacy/rights and materializes the
        release entirely in memory without writing files.  Staging requires an
        explicit ``dry_run=False`` and ``output_dir``.  Private/mixed inputs are
        rejected before any staging path is considered.
        """

        _assert_no_upload_shortcut()
        if type(dry_run) is not bool:
            raise PatentHFReleaseError("dry_run must be boolean")

        # Privacy gate first — fail closed before staging.
        try:
            batch = self.policy.evaluate_batch(candidates)
        except ReleasePolicyError as exc:
            raise PatentReleaseSafetyError(str(exc)) from exc
        if not batch.admitted:
            raise PatentReleaseSafetyError(
                "private/mixed/unreviewed input rejected before staging: "
                + ", ".join(batch.reason_codes)
            )

        # Thaw mapping proxies so Parquet/JSON encoding sees plain dicts.
        projected = [_thaw_mapping(item) for item in batch.projected_records]
        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in projected:
            kind = str(row["artifact_kind"])
            by_kind[kind].append(row)

        data_artifacts: list[PatentReleaseArtifact] = []
        for kind in ARTIFACT_KINDS:
            rows = by_kind.get(kind)
            if not rows:
                continue
            # Stable sort for byte-identical rebuilds.
            ordered_rows = sorted(rows, key=lambda item: str(item["record_id"]))
            shards = shard_sequence(ordered_rows, max_rows=self.max_rows_per_shard)
            for shard_index, shard_rows in enumerate(shards):
                if not shard_rows:
                    continue
                content = _encode_parquet_shard(shard_rows)
                lineages = _unique_maps(
                    [dict(item["source_lineage"]) for item in shard_rows]
                )
                rights = _unique_maps(
                    [dict(item["rights_review"]) for item in shard_rows]
                )
                classes = tuple(
                    sorted({str(item["classification"]) for item in shard_rows})
                )
                relative = (
                    f"data/{kind}/part-{shard_index:06d}.parquet"
                )
                data_artifacts.append(
                    PatentReleaseArtifact(
                        relative_path=relative,
                        content=content,
                        media_type="application/vnd.apache.parquet",
                        row_count=len(shard_rows),
                        config_name=kind,
                        source_lineage=lineages,
                        classifications=classes,
                        rights_reviews=rights,
                    )
                )

        if not data_artifacts:
            raise PatentHFReleaseError("no public data shards were produced")

        support = _build_support_artifacts(
            dataset_id=self.dataset_id,
            data_artifacts=tuple(data_artifacts),
            batch=batch,
        )
        all_artifacts = tuple(data_artifacts) + support
        release_root_cid = _compute_release_root_cid(
            dataset_id=self.dataset_id,
            artifacts=tuple(
                item for item in all_artifacts if item.relative_path != MANIFEST_FILENAME
            ),
            policy_sha256=batch.policy_sha256,
        )
        # Rebind manifest with final release_root_cid.
        manifest_artifact = _build_manifest_artifact(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            data_artifacts=tuple(data_artifacts),
            support_artifacts=tuple(
                item
                for item in support
                if item.relative_path != MANIFEST_FILENAME
            ),
            batch=batch,
            dry_run=dry_run,
        )
        final_artifacts = tuple(
            item
            for item in all_artifacts
            if item.relative_path != MANIFEST_FILENAME
        ) + (manifest_artifact,)

        release = PatentHuggingFaceRelease(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            schema_version=HF_RELEASE_SCHEMA_VERSION,
            policy_sha256=batch.policy_sha256,
            policy_version=batch.policy_version,
            batch_admission=batch,
            artifacts=final_artifacts,
            dry_run=dry_run,
            staged_root=None,
        )
        validate_patent_hf_release(release)

        if dry_run:
            return release

        if output_dir is None:
            raise PatentHFReleaseError(
                "output_dir is required when dry_run is false"
            )
        staged = stage_patent_hf_release(release, output_dir, dry_run=False)
        return staged


def build_patent_hf_release(
    candidates: Sequence[ReleaseCandidate | Mapping[str, Any]],
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    max_rows_per_shard: int = DEFAULT_MAX_ROWS_PER_SHARD,
    policy: PatentReleasePolicy | None = None,
) -> PatentHuggingFaceRelease:
    """Build a deterministic JusticeDAO patent release (default dry-run)."""

    builder = PatentLegalHFReleaseBuilder(
        dataset_id=dataset_id,
        max_rows_per_shard=max_rows_per_shard,
        policy=policy or PatentReleasePolicy(),
    )
    return builder.build(
        candidates, dry_run=dry_run, output_dir=output_dir
    )


def stage_patent_hf_release(
    release: PatentHuggingFaceRelease,
    output_dir: str | Path,
    *,
    dry_run: bool = True,
) -> PatentHuggingFaceRelease:
    """Stage release bytes to a local directory.

    Default ``dry_run=True`` returns the release unchanged without writing.
    Remote Hub upload is intentionally unsupported in this module.
    """

    _assert_no_upload_shortcut()
    if not isinstance(release, PatentHuggingFaceRelease):
        raise PatentHFReleaseError("release must be PatentHuggingFaceRelease")
    if type(dry_run) is not bool:
        raise PatentHFReleaseError("dry_run must be boolean")
    if dry_run:
        return release

    # Re-check privacy gate before any filesystem mutation.
    if not release.batch_admission.admitted:
        raise PatentReleaseSafetyError(
            "cannot stage a non-admitted release: "
            + ", ".join(release.batch_admission.reason_codes)
        )

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for artifact in release.artifacts:
        target = root.joinpath(*PurePosixPath(artifact.relative_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.partial")
        temporary.write_bytes(artifact.content)
        os.replace(temporary, target)
        # Verify on-disk integrity immediately.
        descriptor = describe_file(
            target,
            root=root,
            media_type=artifact.media_type,
            schema_type=HF_RELEASE_SCHEMA_VERSION,
            producer_id=HF_RELEASE_PRODUCER,
            config_digest=HF_RELEASE_CONFIG,
            row_count=artifact.row_count,
            config_name=artifact.config_name,
            metadata={
                "classifications": list(artifact.classifications),
                "rights_reviews": [dict(item) for item in artifact.rights_reviews],
                "source_lineage": [dict(item) for item in artifact.source_lineage],
            },
        )
        if (
            descriptor.sha256 != artifact.sha256
            or descriptor.content_cid != artifact.content_cid
            or descriptor.size_bytes != artifact.size_bytes
        ):
            raise PatentReleaseIntegrityError(
                f"staged file integrity mismatch: {artifact.relative_path}"
            )

    return PatentHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        schema_version=release.schema_version,
        policy_sha256=release.policy_sha256,
        policy_version=release.policy_version,
        batch_admission=release.batch_admission,
        artifacts=release.artifacts,
        dry_run=False,
        staged_root=str(root),
    )


def validate_patent_hf_release(release: PatentHuggingFaceRelease) -> dict[str, Any]:
    """Side-effect-free validation of artifact inventory and policy bindings."""

    if not isinstance(release, PatentHuggingFaceRelease):
        raise PatentHFReleaseError("release must be PatentHuggingFaceRelease")
    if not release.batch_admission.admitted:
        raise PatentReleaseSafetyError("release batch was not admitted")

    required = {
        MANIFEST_FILENAME,
        DATASET_INFOS_FILENAME,
        README_FILENAME,
        POLICY_RECEIPT_FILENAME,
    }
    paths = {item.relative_path for item in release.artifacts}
    missing = required - paths
    if missing:
        raise PatentReleaseIntegrityError(
            "missing required artifacts: " + ", ".join(sorted(missing))
        )

    for artifact in release.artifacts:
        # Every artifact must expose the full acceptance metadata set.
        desc = artifact.descriptor()
        for key in (
            "sha256",
            "content_cid",
            "row_count",
            "source_lineage",
            "classifications",
            "rights_reviews",
        ):
            if key not in desc:
                raise PatentReleaseIntegrityError(
                    f"artifact {artifact.relative_path} missing {key}"
                )
        if not _SHA256_RE.fullmatch(desc["sha256"]):
            raise PatentReleaseIntegrityError(
                f"invalid sha256 on {artifact.relative_path}"
            )
        if not desc["content_cid"]:
            raise PatentReleaseIntegrityError(
                f"missing content_cid on {artifact.relative_path}"
            )
        if artifact.relative_path.endswith(".parquet"):
            if artifact.row_count <= 0:
                raise PatentReleaseIntegrityError(
                    f"parquet artifact requires positive row_count: "
                    f"{artifact.relative_path}"
                )
            if not artifact.source_lineage:
                raise PatentReleaseIntegrityError(
                    f"parquet artifact missing source_lineage: "
                    f"{artifact.relative_path}"
                )
            if not artifact.classifications:
                raise PatentReleaseIntegrityError(
                    f"parquet artifact missing classification: "
                    f"{artifact.relative_path}"
                )
            if not artifact.rights_reviews:
                raise PatentReleaseIntegrityError(
                    f"parquet artifact missing rights_review: "
                    f"{artifact.relative_path}"
                )
            # Parquet shards must only carry public classifications.
            for cls in artifact.classifications:
                if cls not in {"public_official", "public_user"}:
                    raise PatentReleaseSafetyError(
                        f"non-public classification in staged shard: {cls}"
                    )

    manifest = release.manifest_dict()
    reject_identity_contamination(manifest, label="release-manifest")
    if manifest.get("release_root_cid") != release.release_root_cid:
        raise PatentReleaseIntegrityError("manifest release_root_cid mismatch")
    if manifest.get("policy_sha256") != release.policy_sha256:
        raise PatentReleaseIntegrityError("manifest policy_sha256 mismatch")

    inventory = {
        item["relative_path"]: item for item in manifest.get("artifacts", [])
    }
    for artifact in release.artifacts:
        if artifact.relative_path == MANIFEST_FILENAME:
            continue
        expected = artifact.descriptor()
        observed = inventory.get(artifact.relative_path)
        if observed != expected:
            raise PatentReleaseIntegrityError(
                f"manifest inventory mismatch for {artifact.relative_path}"
            )

    return {
        "artifact_count": len(release.artifacts),
        "dry_run": release.dry_run,
        "release_root_cid": release.release_root_cid,
        "total_row_count": release.total_row_count,
        "valid": True,
    }


def releases_are_byte_identical(
    left: PatentHuggingFaceRelease,
    right: PatentHuggingFaceRelease,
) -> bool:
    """Return True when two builds produce identical artifact bytes and digests."""

    if left.release_root_cid != right.release_root_cid:
        return False
    if len(left.artifacts) != len(right.artifacts):
        return False
    for a, b in zip(left.artifacts, right.artifacts, strict=True):
        if (
            a.relative_path != b.relative_path
            or a.sha256 != b.sha256
            or a.content_cid != b.content_cid
            or a.content != b.content
            or a.row_count != b.row_count
        ):
            return False
    return True


def _encode_parquet_shard(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode projected public rows as deterministic ZSTD Parquet bytes."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise PatentHFReleaseError(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    record_ids: list[str] = []
    kinds: list[str] = []
    classifications: list[str] = []
    record_json: list[str] = []
    record_sha256: list[str] = []
    source_lineage_json: list[str] = []
    rights_review_json: list[str] = []
    for row in rows:
        record_ids.append(str(row["record_id"]))
        kinds.append(str(row["artifact_kind"]))
        classifications.append(str(row["classification"]))
        # Canonical JSON payload for identity binding.
        payload_json = canonical_json_bytes(row).decode("utf-8")
        record_json.append(payload_json)
        record_sha256.append(
            hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        )
        source_lineage_json.append(
            canonical_json_bytes(row["source_lineage"]).decode("utf-8")
        )
        rights_review_json.append(
            canonical_json_bytes(row["rights_review"]).decode("utf-8")
        )

    table = pa.table(
        {
            "record_id": record_ids,
            "artifact_kind": kinds,
            "classification": classifications,
            "record_sha256": record_sha256,
            "source_lineage_json": source_lineage_json,
            "rights_review_json": rights_review_json,
            "record_json": record_json,
        }
    )
    import io

    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=6,
        row_group_size=max(len(rows), 1),
        use_dictionary=True,
        write_statistics=True,
        write_page_index=False,
        data_page_version="1.0",
    )
    return buffer.getvalue()


def _build_support_artifacts(
    *,
    dataset_id: str,
    data_artifacts: tuple[PatentReleaseArtifact, ...],
    batch: BatchAdmission,
) -> tuple[PatentReleaseArtifact, ...]:
    lineages = _unique_maps(
        [
            dict(item)
            for artifact in data_artifacts
            for item in artifact.source_lineage
        ]
    )
    rights = _unique_maps(
        [
            dict(item)
            for artifact in data_artifacts
            for item in artifact.rights_reviews
        ]
    )
    classes = tuple(
        sorted(
            {
                cls
                for artifact in data_artifacts
                for cls in artifact.classifications
            }
        )
    )

    readme = _render_readme(dataset_id=dataset_id, data_artifacts=data_artifacts)
    readme_bytes = readme.encode("utf-8")
    readme_artifact = PatentReleaseArtifact(
        relative_path=README_FILENAME,
        content=readme_bytes,
        media_type="text/markdown; charset=utf-8",
        row_count=0,
        config_name="",
        source_lineage=lineages,
        classifications=classes,
        rights_reviews=rights,
    )

    infos = _dataset_infos(dataset_id=dataset_id, data_artifacts=data_artifacts)
    infos_bytes = canonical_json_bytes(infos) + b"\n"
    infos_artifact = PatentReleaseArtifact(
        relative_path=DATASET_INFOS_FILENAME,
        content=infos_bytes,
        media_type="application/json",
        row_count=0,
        config_name="",
        source_lineage=lineages,
        classifications=classes,
        rights_reviews=rights,
    )

    policy_receipt = {
        "admitted": batch.admitted,
        "classification_summary": dict(batch.classification_summary),
        "policy_sha256": batch.policy_sha256,
        "policy_version": batch.policy_version,
        "reason_codes": list(batch.reason_codes),
        "record_count": len(batch.record_admissions),
        "warning_codes": list(batch.warning_codes),
    }
    reject_identity_contamination(policy_receipt, label="policy-admission")
    policy_bytes = canonical_json_bytes(policy_receipt) + b"\n"
    policy_artifact = PatentReleaseArtifact(
        relative_path=POLICY_RECEIPT_FILENAME,
        content=policy_bytes,
        media_type="application/json",
        row_count=0,
        config_name="",
        source_lineage=lineages,
        classifications=classes,
        rights_reviews=rights,
    )

    # Placeholder manifest; rebuilt with release_root_cid after hashing.
    placeholder_manifest = _manifest_payload(
        dataset_id=dataset_id,
        release_root_cid="pending",
        data_artifacts=data_artifacts,
        support_artifacts=(readme_artifact, infos_artifact, policy_artifact),
        batch=batch,
        dry_run=True,
    )
    # Remove pending contamination check path for placeholder only.
    placeholder_bytes = canonical_json_bytes(placeholder_manifest) + b"\n"
    manifest_artifact = PatentReleaseArtifact(
        relative_path=MANIFEST_FILENAME,
        content=placeholder_bytes,
        media_type="application/json",
        row_count=0,
        config_name="",
        source_lineage=lineages,
        classifications=classes,
        rights_reviews=rights,
    )
    return (readme_artifact, infos_artifact, policy_artifact, manifest_artifact)


def _build_manifest_artifact(
    *,
    dataset_id: str,
    release_root_cid: str,
    data_artifacts: tuple[PatentReleaseArtifact, ...],
    support_artifacts: tuple[PatentReleaseArtifact, ...],
    batch: BatchAdmission,
    dry_run: bool,
) -> PatentReleaseArtifact:
    payload = _manifest_payload(
        dataset_id=dataset_id,
        release_root_cid=release_root_cid,
        data_artifacts=data_artifacts,
        support_artifacts=support_artifacts,
        batch=batch,
        dry_run=dry_run,
    )
    reject_identity_contamination(payload, label="release-manifest")
    content = canonical_json_bytes(payload) + b"\n"
    lineages = _unique_maps(
        [
            dict(item)
            for artifact in data_artifacts
            for item in artifact.source_lineage
        ]
    )
    rights = _unique_maps(
        [
            dict(item)
            for artifact in data_artifacts
            for item in artifact.rights_reviews
        ]
    )
    classes = tuple(
        sorted(
            {
                cls
                for artifact in data_artifacts
                for cls in artifact.classifications
            }
        )
    )
    return PatentReleaseArtifact(
        relative_path=MANIFEST_FILENAME,
        content=content,
        media_type="application/json",
        row_count=0,
        config_name="",
        source_lineage=lineages,
        classifications=classes,
        rights_reviews=rights,
    )


def _manifest_payload(
    *,
    dataset_id: str,
    release_root_cid: str,
    data_artifacts: tuple[PatentReleaseArtifact, ...],
    support_artifacts: tuple[PatentReleaseArtifact, ...],
    batch: BatchAdmission,
    dry_run: bool,
) -> dict[str, Any]:
    inventory = [
        item.descriptor()
        for item in sorted(
            (*data_artifacts, *support_artifacts),
            key=lambda artifact: artifact.relative_path,
        )
    ]
    return {
        "artifacts": inventory,
        "dataset_id": dataset_id,
        "dry_run": dry_run,
        "policy_sha256": batch.policy_sha256,
        "policy_version": batch.policy_version,
        "producer_id": HF_RELEASE_PRODUCER,
        "program_id": PATENT_LEGAL_PROGRAM_ID,
        "release_root_cid": release_root_cid,
        "schema_version": HF_RELEASE_SCHEMA_VERSION,
        "shard_configs": sorted({item.config_name for item in data_artifacts}),
        "total_data_rows": sum(item.row_count for item in data_artifacts),
        "upload_path": None,
        "uses_hf_api_upload_file": False,
    }


def _dataset_infos(
    *,
    dataset_id: str,
    data_artifacts: tuple[PatentReleaseArtifact, ...],
) -> dict[str, Any]:
    configs: dict[str, Any] = {}
    by_kind: dict[str, list[PatentReleaseArtifact]] = defaultdict(list)
    for artifact in data_artifacts:
        by_kind[artifact.config_name].append(artifact)
    for kind in sorted(by_kind):
        shards = sorted(by_kind[kind], key=lambda item: item.relative_path)
        configs[kind] = {
            "splits": {
                "train": {
                    "name": "train",
                    "num_examples": sum(item.row_count for item in shards),
                    "num_bytes": sum(item.size_bytes for item in shards),
                }
            },
            "dataset_name": dataset_id,
        }
    return {
        "configs": configs,
        "dataset_name": dataset_id,
        "schema_version": HF_RELEASE_SCHEMA_VERSION,
    }


def _render_readme(
    *,
    dataset_id: str,
    data_artifacts: tuple[PatentReleaseArtifact, ...],
) -> str:
    kinds = sorted({item.config_name for item in data_artifacts})
    lines = [
        "---",
        f"license: other",
        f"pretty_name: {dataset_id}",
        "tags:",
        "  - patent",
        "  - legal",
        "  - justicedao",
        "  - public-domain-us-government",
        "---",
        "",
        f"# {dataset_id}",
        "",
        "Deterministic, privacy-reviewed public patent and official-law shards",
        "for JusticeDAO. Built locally; publication requires a separate",
        "operator-approved append-only plan.",
        "",
        "## Configs",
        "",
    ]
    for kind in kinds:
        rows = sum(
            item.row_count for item in data_artifacts if item.config_name == kind
        )
        lines.append(f"- `{kind}`: {rows} rows")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "Every artifact binds SHA-256, CIDv1, row count, source lineage,",
            "disclosure classification, and rights review in `release-manifest.json`.",
            "",
            "Private or mixed disclosure inputs are rejected before staging.",
            "Remote Hub upload is intentionally out of scope for this builder.",
            "",
        ]
    )
    return "\n".join(lines)


def _compute_release_root_cid(
    *,
    dataset_id: str,
    artifacts: tuple[PatentReleaseArtifact, ...],
    policy_sha256: str,
) -> str:
    inventory = [
        {
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "content_cid": item.content_cid,
            "row_count": item.row_count,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(artifacts, key=lambda a: a.relative_path)
    ]
    payload = {
        "dataset_id": dataset_id,
        "inventory": inventory,
        "policy_sha256": policy_sha256,
        "schema_version": HF_RELEASE_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively convert mapping proxies to plain JSON-serializable dicts."""

    def convert(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): convert(item[key]) for key in item}
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return [convert(child) for child in item]
        return item

    if not isinstance(value, Mapping):
        raise PatentHFReleaseError("expected a mapping to thaw")
    return convert(value)


def _unique_maps(values: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    seen: dict[str, dict[str, Any]] = {}
    for value in values:
        plain = _thaw_mapping(value)
        encoded = canonical_json_bytes(plain).decode("utf-8")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen[digest] = plain
    return tuple(seen[key] for key in sorted(seen))


def _primary_license(rights: Sequence[Mapping[str, Any]]) -> str:
    if not rights:
        return ""
    expression = str(rights[0].get("license_expression") or "").strip()
    return expression


def _safe_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if (
        not text
        or text.startswith("/")
        or text.startswith("../")
        or "/../" in f"/{text}/"
    ):
        raise PatentHFReleaseError(f"unsafe relative path: {value!r}")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if ".." in parts or not parts:
        raise PatentHFReleaseError(f"unsafe relative path: {value!r}")
    return "/".join(parts)


def _assert_no_upload_shortcut() -> None:
    """Fail closed if this module source ever gains a direct upload path."""

    source_path = Path(__file__).resolve()
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError:
        return
    # Reject executable import/call patterns only (not prose that forbids them).
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.search(r"from\s+huggingface_hub\s+import\s+.*\bHfApi\b", stripped):
            raise PatentHFReleaseError(
                "huggingface_hub HfApi import is forbidden in patent hf_release"
            )
        if re.search(r"import\s+huggingface_hub", stripped):
            raise PatentHFReleaseError(
                "huggingface_hub import is forbidden in patent hf_release"
            )
        if re.search(r"\bHfApi\s*\(", stripped):
            raise PatentHFReleaseError(
                "HfApi construction is forbidden in patent hf_release"
            )
        if re.search(r"\.upload_file\s*\(", stripped):
            raise PatentHFReleaseError(
                "upload_file call path is forbidden in patent hf_release"
            )


__all__ = [
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_MAX_ROWS_PER_SHARD",
    "HF_RELEASE_CONFIG",
    "HF_RELEASE_PRODUCER",
    "HF_RELEASE_SCHEMA_VERSION",
    "MANIFEST_FILENAME",
    "PatentHFReleaseError",
    "PatentHuggingFaceRelease",
    "PatentLegalHFReleaseBuilder",
    "PatentReleaseArtifact",
    "PatentReleaseIntegrityError",
    "PatentReleaseSafetyError",
    "build_patent_hf_release",
    "releases_are_byte_identical",
    "stage_patent_hf_release",
    "validate_patent_hf_release",
]
