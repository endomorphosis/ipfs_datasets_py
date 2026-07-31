"""Deterministic, local-only release staging for Solidity CPT artifacts.

The release gate consumes a verified evaluation receipt and emits only
source-free candidate metadata plus data/model cards.  It performs no network
access and has no upload or publication operation.  A passing evaluation is a
release-quality prerequisite, not proof or transaction authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1
from .evaluation import (
    EvaluationContractError,
    EvaluationPromotionError,
    SolidityFormalEvaluation,
    verify_evaluation_receipt,
)
from .release_policy import (
    PINNED_SOURCE_PROFILE,
    RELEASE_POLICY_SHA256,
    PublicationKind,
    evaluate_publication_admission,
)

SOLIDITY_CPT_RELEASE_MANIFEST_VERSION: Final = (
    "solidity-cpt-source-free-release/v1"
)
SOLIDITY_CPT_RELEASE_PRODUCER: Final = (
    "producer:solidity-cpt-source-free-release-v1"
)
LOCAL_OBSERVATION_MODE: Final = "observation_shadow_only"
MAX_CANDIDATES: Final = 100_000
MAX_CANDIDATE_METADATA_BYTES: Final = 16 * 1024 * 1024

_CID_LENGTH: Final = 59
_SOURCE_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "body",
        "bytecode",
        "code",
        "contract_body",
        "contract_source",
        "raw",
        "raw_body",
        "raw_source",
        "source",
        "source_body",
        "source_code",
        "text",
    }
)
_FORBIDDEN_AUTHORITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "allow",
        "allowed",
        "approval",
        "approved",
        "enforcement_authority",
        "proof",
        "proof_authority",
        "safety_verdict",
        "transaction_authority",
        "transaction_verdict",
        "upload",
        "upload_enabled",
    }
)
_CANDIDATE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "bridge_id",
        "candidate_id",
        "formalization_cid",
        "obligation_ids",
        "review_ids",
        "rule_ids",
        "semantic_prerequisites",
        "source_cids",
    }
)


class SolidityCPTReleaseError(ValueError):
    """Raised when a release cannot be staged or verified safely."""


class SolidityCPTReleaseIntegrityError(SolidityCPTReleaseError):
    """Raised when content does not match its manifest binding."""


class SolidityCPTReleaseAuthorityError(SolidityCPTReleaseError):
    """Raised when a release input claims forbidden authority."""


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SolidityCPTReleaseError(f"{name} must be a string")
    if value != value.strip() or (not allow_empty and not value):
        raise SolidityCPTReleaseError(
            f"{name} must be a{' non-empty' if not allow_empty else ''} trimmed string"
        )
    return value


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    if (
        len(text) != _CID_LENGTH
        or not text.startswith("b")
        or any(ch not in "abcdefghijklmnopqrstuvwxyz234567" for ch in text)
    ):
        raise SolidityCPTReleaseError(
            f"{name} must be a canonical raw SHA-256 CIDv1"
        )
    return text


def _sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise SolidityCPTReleaseError(f"{name} must be lowercase SHA-256 hex")
    return text


def _unique_texts(
    values: Sequence[str], name: str, *, require_non_empty: bool = False
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise SolidityCPTReleaseError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name} item") for item in values)
    if len(result) != len(set(result)):
        raise SolidityCPTReleaseError(f"{name} values must be unique")
    if require_non_empty and not result:
        raise SolidityCPTReleaseError(f"{name} must be non-empty")
    return result


def _safe_relative_path(value: Any) -> str:
    text = _text(value, "relative_path")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise SolidityCPTReleaseError(
            "artifact relative_path must stay within the release root"
        )
    return path.as_posix()


def _reject_source_or_authority(value: Any, *, location: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold()
            child = f"{location}.{raw_key}"
            if key in _SOURCE_BODY_KEYS:
                raise SolidityCPTReleaseAuthorityError(
                    f"source body field is forbidden in staged metadata: {child}"
                )
            if key in _FORBIDDEN_AUTHORITY_KEYS and item not in (
                False,
                None,
                "",
            ):
                raise SolidityCPTReleaseAuthorityError(
                    f"authority field is forbidden in staged metadata: {child}"
                )
            _reject_source_or_authority(item, location=child)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _reject_source_or_authority(item, location=f"{location}[{index}]")


def _normalize_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SolidityCPTReleaseError("candidate metadata must be a mapping")
    unknown = sorted(set(value) - _CANDIDATE_FIELDS)
    if unknown:
        raise SolidityCPTReleaseError(
            "candidate metadata contains unsupported field(s): "
            + ", ".join(unknown)
        )
    _reject_source_or_authority(value)
    candidate_id = _text(value.get("candidate_id", ""), "candidate_id")
    bridge_id = _cid(value.get("bridge_id", ""), "bridge_id")
    formalization_cid = _cid(
        value.get("formalization_cid", ""), "formalization_cid"
    )
    result = {
        "bridge_id": bridge_id,
        "candidate_id": candidate_id,
        "formalization_cid": formalization_cid,
        "obligation_ids": list(
            _unique_texts(
                tuple(value.get("obligation_ids", ())),
                "obligation_ids",
                require_non_empty=True,
            )
        ),
        "review_ids": list(
            _unique_texts(
                tuple(value.get("review_ids", ())),
                "review_ids",
                require_non_empty=True,
            )
        ),
        "rule_ids": list(
            _unique_texts(
                tuple(value.get("rule_ids", ())),
                "rule_ids",
                require_non_empty=True,
            )
        ),
        "semantic_prerequisites": list(
            _unique_texts(
                tuple(value.get("semantic_prerequisites", ())),
                "semantic_prerequisites",
                require_non_empty=True,
            )
        ),
        "source_cids": list(
            _unique_texts(
                tuple(value.get("source_cids", ())),
                "source_cids",
                require_non_empty=True,
            )
        ),
    }
    for source_cid in result["source_cids"]:
        _cid(source_cid, "source_cid")
    return result


def candidate_metadata_from_bridge(bridge: Any) -> dict[str, Any]:
    """Project a bridge result to the source-free release metadata schema."""

    required = (
        "bridge_id",
        "formalization_cid",
        "obligations",
        "rules",
        "bindings",
        "semantic_prerequisites",
        "source_cids",
    )
    if any(not hasattr(bridge, name) for name in required):
        raise SolidityCPTReleaseError(
            "bridge object does not expose the reviewed bridge contract"
        )
    return _normalize_candidate(
        {
            "bridge_id": bridge.bridge_id,
            "candidate_id": f"candidate:{bridge.bridge_id[-24:]}",
            "formalization_cid": bridge.formalization_cid,
            "obligation_ids": [
                item.obligation_id for item in bridge.obligations
            ],
            "review_ids": sorted(
                {item.review_id for item in bridge.bindings}
            ),
            "rule_ids": [item.rule_id for item in bridge.rules],
            "semantic_prerequisites": sorted(
                set(bridge.semantic_prerequisites)
            ),
            "source_cids": sorted(set(bridge.source_cids)),
        }
    )


@dataclass(frozen=True, slots=True)
class ReleaseArtifactDescriptor:
    """Content descriptor for one locally staged, source-free artifact."""

    relative_path: str
    media_type: str
    byte_length: int
    sha256: str
    cid: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_path", _safe_relative_path(self.relative_path)
        )
        object.__setattr__(self, "media_type", _text(self.media_type, "media_type"))
        if (
            type(self.byte_length) is not int
            or self.byte_length < 0
            or self.byte_length > MAX_CANDIDATE_METADATA_BYTES
        ):
            raise SolidityCPTReleaseError(
                "artifact byte_length is outside the release budget"
            )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        object.__setattr__(self, "cid", _cid(self.cid, "cid"))

    @classmethod
    def from_bytes(
        cls, relative_path: str, media_type: str, content: bytes
    ) -> ReleaseArtifactDescriptor:
        return cls(
            relative_path=relative_path,
            media_type=media_type,
            byte_length=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            cid=cid_v1(content),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "cid": self.cid,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReleaseArtifactDescriptor:
        if not isinstance(value, Mapping):
            raise SolidityCPTReleaseError(
                "release artifact descriptor must be a mapping"
            )
        allowed = {
            "byte_length",
            "cid",
            "media_type",
            "relative_path",
            "sha256",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SolidityCPTReleaseError(
                "unknown release artifact descriptor field(s): "
                + ", ".join(unknown)
            )
        return cls(
            relative_path=value.get("relative_path", ""),
            media_type=value.get("media_type", ""),
            byte_length=value.get("byte_length", -1),
            sha256=value.get("sha256", ""),
            cid=value.get("cid", ""),
        )


@dataclass(frozen=True, slots=True)
class SolidityCPTReleaseManifest:
    """Content-addressed release gate binding every governed input."""

    source_cid: str
    graph_cid: str
    index_cid: str
    partition_cid: str
    model_cid: str
    evaluation_cid: str
    license_cid: str
    config_cid: str
    promotion_gate_id: str
    artifacts: tuple[ReleaseArtifactDescriptor, ...]
    candidate_count: int
    release_policy_sha256: str = RELEASE_POLICY_SHA256
    source_profile_sha256: str = PINNED_SOURCE_PROFILE.sha256
    producer_id: str = SOLIDITY_CPT_RELEASE_PRODUCER
    integration_mode: str = LOCAL_OBSERVATION_MODE
    publication_enabled: bool = False
    upload_enabled: bool = False
    proof_authority: bool = False
    transaction_authority: bool = False
    schema_version: str = SOLIDITY_CPT_RELEASE_MANIFEST_VERSION
    manifest_cid: str = ""

    def __post_init__(self) -> None:
        for name in (
            "source_cid",
            "graph_cid",
            "index_cid",
            "partition_cid",
            "model_cid",
            "evaluation_cid",
            "license_cid",
            "config_cid",
            "promotion_gate_id",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        object.__setattr__(
            self,
            "release_policy_sha256",
            _sha256(self.release_policy_sha256, "release_policy_sha256"),
        )
        object.__setattr__(
            self,
            "source_profile_sha256",
            _sha256(self.source_profile_sha256, "source_profile_sha256"),
        )
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self,
            "integration_mode",
            _text(self.integration_mode, "integration_mode"),
        )
        normalized = tuple(
            item
            if isinstance(item, ReleaseArtifactDescriptor)
            else ReleaseArtifactDescriptor.from_dict(item)
            for item in self.artifacts
        )
        normalized = tuple(sorted(normalized, key=lambda item: item.relative_path))
        if len({item.relative_path for item in normalized}) != len(normalized):
            raise SolidityCPTReleaseError(
                "artifact relative paths must be unique"
            )
        object.__setattr__(self, "artifacts", normalized)
        if (
            type(self.candidate_count) is not int
            or self.candidate_count < 0
            or self.candidate_count > MAX_CANDIDATES
        ):
            raise SolidityCPTReleaseError(
                "candidate_count is outside the release budget"
            )
        if (
            self.release_policy_sha256 != RELEASE_POLICY_SHA256
            or self.source_profile_sha256 != PINNED_SOURCE_PROFILE.sha256
        ):
            raise SolidityCPTReleaseIntegrityError(
                "release policy/source profile differs from the reviewed pin"
            )
        if (
            self.integration_mode != LOCAL_OBSERVATION_MODE
            or self.publication_enabled is not False
            or self.upload_enabled is not False
            or self.proof_authority is not False
            or self.transaction_authority is not False
        ):
            raise SolidityCPTReleaseAuthorityError(
                "release manifests are local observation/shadow-only and grant "
                "no publication, upload, proof, or transaction authority"
            )
        if self.schema_version != SOLIDITY_CPT_RELEASE_MANIFEST_VERSION:
            raise SolidityCPTReleaseError(
                "unsupported Solidity CPT release manifest schema"
            )
        computed = cid_v1(canonical_json_bytes(self.deterministic_dict()))
        if self.manifest_cid and self.manifest_cid != computed:
            raise SolidityCPTReleaseIntegrityError(
                "manifest_cid does not match rehashed release manifest"
            )
        object.__setattr__(self, "manifest_cid", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "candidate_count": self.candidate_count,
            "config_cid": self.config_cid,
            "evaluation_cid": self.evaluation_cid,
            "graph_cid": self.graph_cid,
            "index_cid": self.index_cid,
            "integration_mode": self.integration_mode,
            "license_cid": self.license_cid,
            "model_cid": self.model_cid,
            "partition_cid": self.partition_cid,
            "producer_id": self.producer_id,
            "proof_authority": False,
            "promotion_gate_id": self.promotion_gate_id,
            "publication_enabled": False,
            "release_policy_sha256": self.release_policy_sha256,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "source_profile_sha256": self.source_profile_sha256,
            "transaction_authority": False,
            "upload_enabled": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"manifest_cid": self.manifest_cid, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SolidityCPTReleaseManifest:
        if not isinstance(value, Mapping):
            raise SolidityCPTReleaseError("release manifest must be a mapping")
        allowed = {
            "artifacts",
            "candidate_count",
            "config_cid",
            "evaluation_cid",
            "graph_cid",
            "index_cid",
            "integration_mode",
            "license_cid",
            "manifest_cid",
            "model_cid",
            "partition_cid",
            "producer_id",
            "proof_authority",
            "promotion_gate_id",
            "publication_enabled",
            "release_policy_sha256",
            "schema_version",
            "source_cid",
            "source_profile_sha256",
            "transaction_authority",
            "upload_enabled",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SolidityCPTReleaseError(
                "unknown release manifest field(s): " + ", ".join(unknown)
            )
        return cls(
            source_cid=value.get("source_cid", ""),
            graph_cid=value.get("graph_cid", ""),
            index_cid=value.get("index_cid", ""),
            partition_cid=value.get("partition_cid", ""),
            model_cid=value.get("model_cid", ""),
            evaluation_cid=value.get("evaluation_cid", ""),
            license_cid=value.get("license_cid", ""),
            config_cid=value.get("config_cid", ""),
            promotion_gate_id=value.get("promotion_gate_id", ""),
            artifacts=tuple(value.get("artifacts", ())),
            candidate_count=value.get("candidate_count", -1),
            release_policy_sha256=value.get(
                "release_policy_sha256", RELEASE_POLICY_SHA256
            ),
            source_profile_sha256=value.get(
                "source_profile_sha256", PINNED_SOURCE_PROFILE.sha256
            ),
            producer_id=value.get(
                "producer_id", SOLIDITY_CPT_RELEASE_PRODUCER
            ),
            integration_mode=value.get(
                "integration_mode", LOCAL_OBSERVATION_MODE
            ),
            publication_enabled=value.get("publication_enabled", False),
            upload_enabled=value.get("upload_enabled", False),
            proof_authority=value.get("proof_authority", False),
            transaction_authority=value.get("transaction_authority", False),
            schema_version=value.get(
                "schema_version", SOLIDITY_CPT_RELEASE_MANIFEST_VERSION
            ),
            manifest_cid=value.get("manifest_cid", ""),
        )


@dataclass(frozen=True, slots=True)
class SolidityCPTReleaseBuildResult:
    """Local receipt for a deterministic source-free release build."""

    output_dir: str
    manifest_path: str
    manifest: SolidityCPTReleaseManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "manifest_path": self.manifest_path,
            "output_dir": self.output_dir,
        }


def _atomic_write(path: Path, content: bytes) -> None:
    if not path.parent.is_dir():
        raise SolidityCPTReleaseError(
            "release artifact parent must already exist"
        )
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise SolidityCPTReleaseError(
            "release artifact target must be absent or a regular file"
        )
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        raise SolidityCPTReleaseError(
            f"failed to write release artifact {path.name}"
        ) from exc
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _data_card() -> bytes:
    return (
        b"# Solidity CPT source-free release data card\n\n"
        b"This local artifact binds the pinned Solidity CPT source, graph, "
        b"partition, license, configuration, model/checkpoint, and held-out "
        b"evaluation identities. It contains reviewed candidate identifiers "
        b"and prerequisites only; raw Solidity bodies are excluded.\n\n"
        b"The corpus quality label is not a vulnerability label, theorem, "
        b"contract-safety verdict, or transaction authorization.\n"
    )


def _model_card() -> bytes:
    return (
        b"# Solidity CPT candidate model card\n\n"
        b"Learned output authority is candidate-only. GraphRAG rank, model "
        b"confidence, candidate formulas, SAT, simulation, and evaluation "
        b"scores do not count as proof. Independent executed proof receipts "
        b"for the exact deployed code epoch and the existing policy gates are "
        b"required before any transaction can be authorized.\n\n"
        b"Integration is limited to local observation and shadow review. "
        b"Upload and publication are disabled.\n"
    )


class SolidityCPTReleaseBuilder:
    """Build and validate a byte-stable, local-only release directory."""

    def build(
        self,
        output_dir: str | Path,
        *,
        evaluation: SolidityFormalEvaluation | Mapping[str, Any],
        config_cid: str,
        candidates: Sequence[Mapping[str, Any] | Any] = (),
    ) -> SolidityCPTReleaseBuildResult:
        try:
            verified = (
                verify_evaluation_receipt(evaluation)
                if isinstance(evaluation, Mapping)
                else verify_evaluation_receipt(evaluation.to_dict())
            )
            verified.require_promotion_safe()
        except (EvaluationContractError, EvaluationPromotionError) as exc:
            raise SolidityCPTReleaseError(
                f"evaluation failed the deterministic release gate: {exc}"
            ) from exc
        _cid(config_cid, "config_cid")

        publication = evaluate_publication_admission(
            PublicationKind.SOURCE_FREE_DERIVATIVE
        )
        if not publication.admitted:
            raise SolidityCPTReleaseError(
                "source-free derivative failed the reviewed license policy"
            )

        normalized: list[dict[str, Any]] = []
        if len(candidates) > MAX_CANDIDATES:
            raise SolidityCPTReleaseError(
                "candidate metadata exceeds the release count budget"
            )
        for item in candidates:
            normalized.append(
                _normalize_candidate(item)
                if isinstance(item, Mapping)
                else candidate_metadata_from_bridge(item)
            )
        normalized.sort(
            key=lambda item: (item["candidate_id"], item["bridge_id"])
        )
        if len({item["candidate_id"] for item in normalized}) != len(normalized):
            raise SolidityCPTReleaseError(
                "candidate_id values must be unique within a release"
            )

        root = Path(output_dir)
        if root.exists():
            if root.is_symlink() or not root.is_dir():
                raise SolidityCPTReleaseError(
                    "output_dir must be an absent or regular directory"
                )
            if any(root.iterdir()):
                raise SolidityCPTReleaseError(
                    "output_dir must be empty for deterministic staging"
                )
        else:
            try:
                root.mkdir(parents=False)
            except OSError as exc:
                raise SolidityCPTReleaseError(
                    "output_dir parent must already exist"
                ) from exc

        candidate_payload = {
            "candidate_authority": "candidate",
            "candidates": normalized,
            "enforcement_authority": False,
            "license_cid": verified.license_cid,
            "proof_authority": False,
            "schema_version": "solidity-cpt-source-free-candidates/v1",
            "transaction_authority": False,
        }
        _reject_source_or_authority(candidate_payload)
        candidate_bytes = canonical_json_bytes(candidate_payload) + b"\n"
        if len(candidate_bytes) > MAX_CANDIDATE_METADATA_BYTES:
            raise SolidityCPTReleaseError(
                "candidate metadata exceeds the release byte budget"
            )

        contents = {
            "candidates.json": ("application/json", candidate_bytes),
            "DATA_CARD.md": ("text/markdown", _data_card()),
            "MODEL_CARD.md": ("text/markdown", _model_card()),
        }
        descriptors: list[ReleaseArtifactDescriptor] = []
        for relative_path in sorted(contents):
            media_type, content = contents[relative_path]
            _atomic_write(root / relative_path, content)
            descriptors.append(
                ReleaseArtifactDescriptor.from_bytes(
                    relative_path, media_type, content
                )
            )

        gate = verified.promotion_gate()
        manifest = SolidityCPTReleaseManifest(
            source_cid=verified.source_cid,
            graph_cid=verified.graph_cid,
            index_cid=verified.index_cid,
            partition_cid=verified.partition_cid,
            model_cid=verified.model_or_checkpoint_cid,
            evaluation_cid=verified.evaluation_cid,
            license_cid=verified.license_cid,
            config_cid=config_cid,
            promotion_gate_id=gate.gate_id,
            artifacts=tuple(descriptors),
            candidate_count=len(normalized),
        )
        manifest_path = root / "release-manifest.json"
        _atomic_write(
            manifest_path, canonical_json_bytes(manifest.to_dict()) + b"\n"
        )
        validate_solidity_cpt_release(root)
        return SolidityCPTReleaseBuildResult(
            output_dir=str(root),
            manifest_path=str(manifest_path),
            manifest=manifest,
        )


def validate_solidity_cpt_release(
    root: str | Path,
) -> SolidityCPTReleaseManifest:
    """Rehash every staged artifact and return the verified manifest."""

    release_root = Path(root)
    manifest_path = release_root / "release-manifest.json"
    if (
        release_root.is_symlink()
        or not release_root.is_dir()
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
    ):
        raise SolidityCPTReleaseIntegrityError(
            "release root or manifest is missing/unsafe"
        )
    try:
        raw = manifest_path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SolidityCPTReleaseIntegrityError(
            "release manifest is not readable canonical JSON"
        ) from exc
    manifest = SolidityCPTReleaseManifest.from_dict(value)
    expected_wire = canonical_json_bytes(manifest.to_dict()) + b"\n"
    if raw != expected_wire:
        raise SolidityCPTReleaseIntegrityError(
            "release manifest bytes are not canonical"
        )
    expected_paths = {
        "release-manifest.json",
        *(item.relative_path for item in manifest.artifacts),
    }
    observed_paths = {
        str(path.relative_to(release_root))
        for path in release_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed_paths != expected_paths:
        raise SolidityCPTReleaseIntegrityError(
            "release contains an unmanifested, missing, or nested artifact"
        )
    for descriptor in manifest.artifacts:
        path = release_root / descriptor.relative_path
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(release_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise SolidityCPTReleaseIntegrityError(
                "release artifact escapes or is missing from the release root"
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise SolidityCPTReleaseIntegrityError(
                "release artifacts must be regular non-symlink files"
            )
        content = path.read_bytes()
        if (
            len(content) != descriptor.byte_length
            or hashlib.sha256(content).hexdigest() != descriptor.sha256
            or cid_v1(content) != descriptor.cid
        ):
            raise SolidityCPTReleaseIntegrityError(
                f"release artifact mismatch: {descriptor.relative_path}"
            )
        if descriptor.relative_path.endswith(".json"):
            try:
                parsed = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SolidityCPTReleaseIntegrityError(
                    "staged JSON artifact is malformed"
                ) from exc
            _reject_source_or_authority(parsed)
            if descriptor.relative_path == "candidates.json":
                if not isinstance(parsed, Mapping):
                    raise SolidityCPTReleaseIntegrityError(
                        "candidate artifact must be a JSON object"
                    )
                candidates = parsed.get("candidates")
                if not isinstance(candidates, list):
                    raise SolidityCPTReleaseIntegrityError(
                        "candidate artifact must contain a candidate array"
                    )
                if len(candidates) != manifest.candidate_count:
                    raise SolidityCPTReleaseIntegrityError(
                        "candidate_count does not match the staged artifact"
                    )
                if parsed.get("license_cid") != manifest.license_cid:
                    raise SolidityCPTReleaseIntegrityError(
                        "candidate artifact license CID does not match manifest"
                    )
                for candidate in candidates:
                    _normalize_candidate(candidate)
    return manifest


def build_solidity_cpt_release(
    output_dir: str | Path,
    *,
    evaluation: SolidityFormalEvaluation | Mapping[str, Any],
    config_cid: str,
    candidates: Sequence[Mapping[str, Any] | Any] = (),
) -> SolidityCPTReleaseBuildResult:
    """Convenience wrapper for :class:`SolidityCPTReleaseBuilder`."""

    return SolidityCPTReleaseBuilder().build(
        output_dir,
        evaluation=evaluation,
        config_cid=config_cid,
        candidates=candidates,
    )


__all__ = [
    "LOCAL_OBSERVATION_MODE",
    "ReleaseArtifactDescriptor",
    "SOLIDITY_CPT_RELEASE_MANIFEST_VERSION",
    "SOLIDITY_CPT_RELEASE_PRODUCER",
    "SolidityCPTReleaseAuthorityError",
    "SolidityCPTReleaseBuildResult",
    "SolidityCPTReleaseBuilder",
    "SolidityCPTReleaseError",
    "SolidityCPTReleaseIntegrityError",
    "SolidityCPTReleaseManifest",
    "build_solidity_cpt_release",
    "candidate_metadata_from_bridge",
    "validate_solidity_cpt_release",
]
