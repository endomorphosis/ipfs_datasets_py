"""Immutable, deterministic artifact and pipeline-run manifests.

The manifest has two deliberately separate representations:

``deterministic_dict``
    Everything that can affect the identity of a run: exact artifact bytes,
    lineage, producers, configurations, versions, diagnostics, and reviewed
    decisions.

``observations``
    Clock readings, durations, resource measurements, and host/environment
    details.  These are preserved in the serialized manifest but are excluded
    from ``manifest_id`` and ``output_identity``.

Artifact paths are portable, root-relative POSIX paths.  Integrity checking is
fail closed and can additionally reject files under the artifact root that are
not bound by the manifest.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final

from .canonical import canonical_json_bytes
from .identity import CanonicalIdentity, canonical_identity, cid_v1_from_digest
from .provenance import (
    ConfigBinding,
    ProducerBinding,
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)


IR_ARTIFACT_MANIFEST_SCHEMA_VERSION: Final = "ir-artifact-manifest/v1"
ARTIFACT_MANIFEST_IDENTITY_DOMAIN: Final = "ir.artifact-manifest"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OBSERVATIONAL_KEYS = frozenset(
    {
        "clock",
        "duration",
        "duration_ms",
        "elapsed",
        "elapsed_ms",
        "ended_at",
        "environment",
        "finished_at",
        "host",
        "hostname",
        "resource_usage",
        "started_at",
        "timing",
        "wall_time",
    }
)


class ArtifactManifestValidationError(ValueError):
    """Raised when an artifact manifest is malformed or has dangling bindings."""


class ArtifactIntegrityError(ArtifactManifestValidationError):
    """Raised when artifact bytes do not agree with a manifest."""

    def __init__(self, report: "IntegrityReport") -> None:
        self.report = report
        summary = "; ".join(
            f"{issue.kind.value}: {issue.message}" for issue in report.issues
        )
        super().__init__(summary or "artifact integrity verification failed")


class ArtifactRole(str, Enum):
    """An artifact's role in one deterministic pipeline run."""

    INPUT = "input"
    PARENT = "parent"
    OUTPUT = "output"
    DIAGNOSTIC = "diagnostic"


class DecisionKind(str, Enum):
    """Reviewed decisions that constrain use or promotion of artifacts."""

    REVIEW = "review"
    LICENSE = "license"
    TRUST = "trust"


class IntegrityIssueKind(str, Enum):
    """Stable categories emitted by artifact integrity verification."""

    MISSING = "missing"
    CHANGED = "changed"
    DUPLICATE = "duplicate"
    UNBOUND = "unbound"
    INVALID = "invalid"


def _require_id(label: str, value: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ArtifactManifestValidationError(
            f"{label} must be a stable non-empty identifier"
        )


def _require_text(label: str, value: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ArtifactManifestValidationError(
            f"{label} must be non-empty and have no surrounding whitespace"
        )


def _require_sha256(label: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ArtifactManifestValidationError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )


def _string_tuple(value: Sequence[str] | None, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ArtifactManifestValidationError(f"{label} must be a sequence of strings")
    result = tuple(value)
    if any(not isinstance(item, str) for item in result):
        raise ArtifactManifestValidationError(f"{label} must contain only strings")
    return result


def _sorted_unique_strings(
    value: Sequence[str] | None,
    *,
    label: str,
    validate_ids: bool = True,
) -> tuple[str, ...]:
    result = _string_tuple(value, label=label)
    if len(set(result)) != len(result):
        duplicate = next(item for item in result if result.count(item) > 1)
        raise ArtifactManifestValidationError(
            f"{label} contains duplicate value {duplicate!r}"
        )
    if validate_ids:
        for item in result:
            _require_id(label, item)
    return tuple(sorted(result))


def _enum_value(enum_type: type[Enum], value: Any, label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactManifestValidationError(
            f"{label} has unsupported value {value!r}"
        ) from exc


def _relative_artifact_path(value: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ArtifactManifestValidationError("Artifact.path must be a string")
    if not value:
        if allow_empty:
            return ""
        raise ArtifactManifestValidationError("Artifact.path must not be empty")
    if "\\" in value or "\x00" in value:
        raise ArtifactManifestValidationError(
            "Artifact.path must be a root-relative POSIX path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactManifestValidationError(
            "Artifact.path must be root-relative and contain no '.'/'..' segments"
        )
    normalized = path.as_posix()
    if normalized != value:
        raise ArtifactManifestValidationError(
            "Artifact.path must be normalized POSIX text"
        )
    return normalized


def _reject_observations(value: Mapping[str, Any], *, label: str) -> None:
    offending: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else key
                if key.casefold().replace("-", "_") in _OBSERVATIONAL_KEYS:
                    offending.append(child_path)
                visit(child, child_path)
        elif isinstance(item, tuple):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    if offending:
        raise ArtifactManifestValidationError(
            f"{label} contains observational keys {sorted(offending)}; put timing, "
            "resource, host, and environment data in observations"
        )


@dataclass(frozen=True, slots=True)
class Artifact:
    """Content binding for one file used or produced by a run.

    ``path`` may be empty only for a parent artifact that is addressed but not
    materialized below the verification root.
    """

    artifact_id: str
    role: ArtifactRole
    content_sha256: str
    size: int
    path: str = ""
    content_cid: str = ""
    media_type: str = "application/octet-stream"
    schema_id: str = ""
    schema_version: str = ""
    producer_id: str = ""
    config_id: str = ""
    parent_artifact_ids: tuple[str, ...] = ()
    license_expression: str = ""
    review_status: str = ""
    trust_decision: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        role = _enum_value(ArtifactRole, self.role, "Artifact.role")
        parents = _sorted_unique_strings(
            self.parent_artifact_ids,
            label="Artifact.parent_artifact_ids",
        )
        try:
            metadata = freeze_json_mapping(self.metadata)
        except ProvenanceValidationError as exc:
            raise ArtifactManifestValidationError(str(exc)) from exc
        _reject_observations(metadata, label="Artifact.metadata")
        path = _relative_artifact_path(
            self.path,
            allow_empty=role is ArtifactRole.PARENT,
        )
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "parent_artifact_ids", parents)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "path", path)
        self.validate()

    @property
    def sha256(self) -> str:
        """Compatibility spelling for the unqualified SHA-256 value."""

        return self.content_sha256

    @property
    def content_digest(self) -> str:
        return f"sha256:{self.content_sha256}"

    @property
    def content_identity(self) -> str:
        """Return the declared CID or the fixed-profile CID for the digest."""

        return self.content_cid or cid_v1_from_digest(
            bytes.fromhex(self.content_sha256)
        )

    def validate(self) -> None:
        _require_id("Artifact.artifact_id", self.artifact_id)
        if not isinstance(self.role, ArtifactRole):
            raise ArtifactManifestValidationError(
                "Artifact.role must be an ArtifactRole member"
            )
        _require_sha256("Artifact.content_sha256", self.content_sha256)
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ArtifactManifestValidationError(
                "Artifact.size must be a non-negative integer"
            )
        if self.path:
            _relative_artifact_path(self.path)
        elif self.role is not ArtifactRole.PARENT:
            raise ArtifactManifestValidationError(
                "Only an external parent artifact may omit path"
            )
        if self.media_type:
            _require_text("Artifact.media_type", self.media_type)
        for label, value in (
            ("Artifact.schema_id", self.schema_id),
            ("Artifact.producer_id", self.producer_id),
            ("Artifact.config_id", self.config_id),
        ):
            if value:
                _require_id(label, value)
        if self.schema_version and not self.schema_id:
            raise ArtifactManifestValidationError(
                "Artifact.schema_version requires schema_id"
            )
        if self.config_id and not self.producer_id:
            raise ArtifactManifestValidationError(
                "Artifact.config_id requires producer_id"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "config_id": self.config_id,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "license_expression": self.license_expression,
            "media_type": self.media_type,
            "metadata": thaw_json(self.metadata),
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "path": self.path,
            "producer_id": self.producer_id,
            "review_status": self.review_status,
            "role": self.role.value,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "size": self.size,
            "trust_decision": self.trust_decision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Artifact":
        return cls(
            artifact_id=str(data.get("artifact_id") or ""),
            role=_enum_value(ArtifactRole, data.get("role"), "Artifact.role"),
            content_sha256=str(data.get("content_sha256") or ""),
            size=_required_int(data, "size"),
            path=str(data.get("path") or ""),
            content_cid=str(data.get("content_cid") or ""),
            media_type=str(data.get("media_type") or ""),
            schema_id=str(data.get("schema_id") or ""),
            schema_version=str(data.get("schema_version") or ""),
            producer_id=str(data.get("producer_id") or ""),
            config_id=str(data.get("config_id") or ""),
            parent_artifact_ids=_string_tuple(
                data.get("parent_artifact_ids"),
                label="Artifact.parent_artifact_ids",
            ),
            license_expression=str(data.get("license_expression") or ""),
            review_status=str(data.get("review_status") or ""),
            trust_decision=str(data.get("trust_decision") or ""),
            metadata=_mapping(data.get("metadata"), "Artifact.metadata"),
        )


@dataclass(frozen=True, slots=True)
class ManifestDecision:
    """A review, license, or trust decision bound to manifest subjects."""

    decision_id: str
    kind: DecisionKind
    decision: str
    subject_ids: tuple[str, ...]
    authority: str = ""
    evidence_ref_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = _enum_value(DecisionKind, self.kind, "ManifestDecision.kind")
        subjects = _sorted_unique_strings(
            self.subject_ids, label="ManifestDecision.subject_ids"
        )
        evidence = _sorted_unique_strings(
            self.evidence_ref_ids,
            label="ManifestDecision.evidence_ref_ids",
        )
        try:
            metadata = freeze_json_mapping(self.metadata)
        except ProvenanceValidationError as exc:
            raise ArtifactManifestValidationError(str(exc)) from exc
        _reject_observations(metadata, label="ManifestDecision.metadata")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "evidence_ref_ids", evidence)
        object.__setattr__(self, "metadata", metadata)
        self.validate()

    def validate(self) -> None:
        _require_id("ManifestDecision.decision_id", self.decision_id)
        _require_text("ManifestDecision.decision", self.decision)
        if not self.subject_ids:
            raise ArtifactManifestValidationError(
                "ManifestDecision.subject_ids must not be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "decision": self.decision,
            "decision_id": self.decision_id,
            "evidence_ref_ids": list(self.evidence_ref_ids),
            "kind": self.kind.value,
            "metadata": thaw_json(self.metadata),
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ManifestDecision":
        return cls(
            decision_id=str(data.get("decision_id") or ""),
            kind=_enum_value(
                DecisionKind, data.get("kind"), "ManifestDecision.kind"
            ),
            decision=str(data.get("decision") or ""),
            subject_ids=_string_tuple(
                data.get("subject_ids"), label="ManifestDecision.subject_ids"
            ),
            authority=str(data.get("authority") or ""),
            evidence_ref_ids=_string_tuple(
                data.get("evidence_ref_ids"),
                label="ManifestDecision.evidence_ref_ids",
            ),
            metadata=_mapping(data.get("metadata"), "ManifestDecision.metadata"),
        )


@dataclass(frozen=True, slots=True)
class RunObservations:
    """Nondeterministic observations intentionally excluded from run identity."""

    started_at: str = ""
    finished_at: str = ""
    duration_ms: int | float | None = None
    environment: Mapping[str, Any] = field(default_factory=dict)
    resource_usage: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            environment = freeze_json_mapping(self.environment)
            resources = freeze_json_mapping(self.resource_usage)
            metadata = freeze_json_mapping(self.metadata)
        except ProvenanceValidationError as exc:
            raise ArtifactManifestValidationError(str(exc)) from exc
        if self.duration_ms is not None and (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, (int, float))
            or not math.isfinite(self.duration_ms)
            or self.duration_ms < 0
        ):
            raise ArtifactManifestValidationError(
                "RunObservations.duration_ms must be a non-negative finite number"
            )
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "resource_usage", resources)
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "environment": thaw_json(self.environment),
            "finished_at": self.finished_at,
            "metadata": thaw_json(self.metadata),
            "resource_usage": thaw_json(self.resource_usage),
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunObservations":
        return cls(
            started_at=str(data.get("started_at") or ""),
            finished_at=str(data.get("finished_at") or ""),
            duration_ms=data.get("duration_ms"),
            environment=_mapping(
                data.get("environment"), "RunObservations.environment"
            ),
            resource_usage=_mapping(
                data.get("resource_usage"), "RunObservations.resource_usage"
            ),
            metadata=_mapping(data.get("metadata"), "RunObservations.metadata"),
        )


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    kind: IntegrityIssueKind
    message: str
    artifact_id: str = ""
    path: str = ""
    expected: str = ""
    actual: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "actual": self.actual,
            "artifact_id": self.artifact_id,
            "expected": self.expected,
            "kind": self.kind.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Deterministically ordered result of an integrity audit."""

    issues: tuple[IntegrityIssue, ...] = ()
    checked_artifact_ids: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def is_valid(self) -> bool:
        return self.valid

    @property
    def issue_kinds(self) -> tuple[IntegrityIssueKind, ...]:
        return tuple(sorted({item.kind for item in self.issues}, key=lambda x: x.value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_artifact_ids": list(self.checked_artifact_ids),
            "issues": [item.to_dict() for item in self.issues],
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Immutable manifest for the deterministic contract of one pipeline run."""

    artifacts: tuple[Artifact, ...]
    repository_commit: str
    producers: tuple[ProducerBinding, ...] = ()
    configs: tuple[ConfigBinding, ...] = ()
    schema_versions: Mapping[str, str] = field(default_factory=dict)
    ontology_versions: Mapping[str, str] = field(default_factory=dict)
    tool_versions: Mapping[str, str] = field(default_factory=dict)
    model_versions: Mapping[str, str] = field(default_factory=dict)
    solver_versions: Mapping[str, str] = field(default_factory=dict)
    prompt_template_digests: Mapping[str, str] = field(default_factory=dict)
    diagnostic_ids: tuple[str, ...] = ()
    decisions: tuple[ManifestDecision, ...] = ()
    deterministic_metadata: Mapping[str, Any] = field(default_factory=dict)
    observations: RunObservations = field(default_factory=RunObservations)
    max_diagnostics: int = 1000
    manifest_id: str = ""
    schema_version: str = IR_ARTIFACT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        artifacts = tuple(
            item
            if isinstance(item, Artifact)
            else Artifact.from_dict(_mapping(item, "artifact"))
            for item in self.artifacts
        )
        producers = tuple(
            item
            if isinstance(item, ProducerBinding)
            else ProducerBinding.from_dict(_mapping(item, "producer"))
            for item in self.producers
        )
        configs = tuple(
            item
            if isinstance(item, ConfigBinding)
            else ConfigBinding.from_dict(_mapping(item, "config"))
            for item in self.configs
        )
        decisions = tuple(
            item
            if isinstance(item, ManifestDecision)
            else ManifestDecision.from_dict(_mapping(item, "decision"))
            for item in self.decisions
        )
        observations = (
            self.observations
            if isinstance(self.observations, RunObservations)
            else RunObservations.from_dict(_mapping(self.observations, "observations"))
        )
        diagnostic_ids = _sorted_unique_strings(
            self.diagnostic_ids,
            label="ArtifactManifest.diagnostic_ids",
        )
        maps: dict[str, Mapping[str, Any]] = {}
        for name in (
            "schema_versions",
            "ontology_versions",
            "tool_versions",
            "model_versions",
            "solver_versions",
            "prompt_template_digests",
            "deterministic_metadata",
        ):
            try:
                maps[name] = freeze_json_mapping(getattr(self, name))
            except ProvenanceValidationError as exc:
                raise ArtifactManifestValidationError(str(exc)) from exc
        _reject_observations(
            maps["deterministic_metadata"],
            label="ArtifactManifest.deterministic_metadata",
        )
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "producers", producers)
        object.__setattr__(self, "configs", configs)
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "diagnostic_ids", diagnostic_ids)
        for name, value in maps.items():
            object.__setattr__(self, name, value)

        self._validate_scalars()
        self._validate_reused_bindings()
        computed = self._compute_identity()
        if self.manifest_id and self.manifest_id != computed.cid:
            raise ArtifactManifestValidationError(
                "ArtifactManifest.manifest_id does not match deterministic content"
            )
        object.__setattr__(self, "manifest_id", computed.cid)

    @property
    def run_id(self) -> str:
        return self.manifest_id

    @property
    def inputs(self) -> tuple[Artifact, ...]:
        return self._by_role(ArtifactRole.INPUT)

    @property
    def parents(self) -> tuple[Artifact, ...]:
        return self._by_role(ArtifactRole.PARENT)

    @property
    def outputs(self) -> tuple[Artifact, ...]:
        return self._by_role(ArtifactRole.OUTPUT)

    @property
    def diagnostics(self) -> tuple[Artifact, ...]:
        return self._by_role(ArtifactRole.DIAGNOSTIC)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def output_identity(self) -> str:
        """Stable run/output identity, excluding all observations."""

        return self.manifest_id

    @property
    def deterministic_output_identity(self) -> str:
        return self.output_identity

    @property
    def sha256(self) -> str:
        """SHA-256 of the deterministic manifest preimage."""

        return self.identity.hexdigest

    def _by_role(self, role: ArtifactRole) -> tuple[Artifact, ...]:
        return tuple(
            sorted(
                (item for item in self.artifacts if item.role is role),
                key=lambda item: item.artifact_id,
            )
        )

    def _validate_scalars(self) -> None:
        if self.schema_version != IR_ARTIFACT_MANIFEST_SCHEMA_VERSION:
            raise ArtifactManifestValidationError(
                f"Unsupported manifest schema_version {self.schema_version!r}"
            )
        _require_text("ArtifactManifest.repository_commit", self.repository_commit)
        if (
            isinstance(self.max_diagnostics, bool)
            or not isinstance(self.max_diagnostics, int)
            or self.max_diagnostics < 0
        ):
            raise ArtifactManifestValidationError(
                "ArtifactManifest.max_diagnostics must be a non-negative integer"
            )
        if len(self.diagnostic_ids) > self.max_diagnostics:
            raise ArtifactManifestValidationError(
                "ArtifactManifest.diagnostic_ids exceeds max_diagnostics"
            )
        for name in (
            "schema_versions",
            "ontology_versions",
            "tool_versions",
            "model_versions",
            "solver_versions",
        ):
            _validate_string_map(name, getattr(self, name))
        _validate_digest_map(
            "prompt_template_digests", self.prompt_template_digests
        )

    def _validate_reused_bindings(self) -> None:
        try:
            for producer in self.producers:
                producer.validate()
                _reject_observations(
                    producer.metadata,
                    label=f"ProducerBinding {producer.producer_id!r}.metadata",
                )
            for config in self.configs:
                config.validate()
                _reject_observations(
                    config.metadata,
                    label=f"ConfigBinding {config.config_id!r}.metadata",
                )
        except ProvenanceValidationError as exc:
            raise ArtifactManifestValidationError(str(exc)) from exc

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain=ARTIFACT_MANIFEST_IDENTITY_DOMAIN,
            schema_version=IR_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        )

    def deterministic_dict(self) -> dict[str, Any]:
        """Return the complete deterministic identity preimage."""

        return {
            "artifacts": [
                item.to_dict()
                for item in sorted(
                    self.artifacts,
                    key=lambda item: (item.role.value, item.artifact_id, item.path),
                )
            ],
            "configs": [
                item.to_dict()
                for item in sorted(self.configs, key=lambda item: item.config_id)
            ],
            "decisions": [
                item.to_dict()
                for item in sorted(
                    self.decisions, key=lambda item: item.decision_id
                )
            ],
            "deterministic_metadata": thaw_json(self.deterministic_metadata),
            "diagnostic_ids": list(self.diagnostic_ids),
            "max_diagnostics": self.max_diagnostics,
            "model_versions": thaw_json(self.model_versions),
            "ontology_versions": thaw_json(self.ontology_versions),
            "producers": [
                item.to_dict()
                for item in sorted(
                    self.producers, key=lambda item: item.producer_id
                )
            ],
            "prompt_template_digests": thaw_json(
                self.prompt_template_digests
            ),
            "repository_commit": self.repository_commit,
            "schema_version": self.schema_version,
            "schema_versions": thaw_json(self.schema_versions),
            "solver_versions": thaw_json(self.solver_versions),
            "tool_versions": thaw_json(self.tool_versions),
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.deterministic_dict()
        result["manifest_id"] = self.manifest_id
        result["observations"] = self.observations.to_dict()
        return result

    def deterministic_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.deterministic_dict())

    def canonical_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    def validate(self) -> None:
        """Validate uniqueness, lineage, and all deterministic bindings."""

        issues = self._binding_issues()
        if issues:
            raise ArtifactManifestValidationError(
                "; ".join(f"{item.kind.value}: {item.message}" for item in issues)
            )
        if self._compute_identity().cid != self.manifest_id:
            raise ArtifactManifestValidationError(
                "ArtifactManifest.manifest_id does not match deterministic content"
            )

    def _binding_issues(self) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        issues.extend(_duplicate_issues(self.artifacts, "artifact_id"))
        issues.extend(_duplicate_issues(self.artifacts, "path", ignore_empty=True))
        issues.extend(_duplicate_issues(self.producers, "producer_id"))
        issues.extend(_duplicate_issues(self.configs, "config_id"))
        issues.extend(_duplicate_issues(self.decisions, "decision_id"))

        artifact_ids = {item.artifact_id for item in self.artifacts}
        producer_ids = {item.producer_id for item in self.producers}
        config_ids = {item.config_id for item in self.configs}
        for artifact in self.artifacts:
            unknown_parents = sorted(
                set(artifact.parent_artifact_ids) - artifact_ids
            )
            if unknown_parents:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.UNBOUND,
                        f"artifact {artifact.artifact_id!r} has unknown parents "
                        f"{unknown_parents}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                    )
                )
            if artifact.producer_id and artifact.producer_id not in producer_ids:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.UNBOUND,
                        f"artifact {artifact.artifact_id!r} references unknown "
                        f"producer {artifact.producer_id!r}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                    )
                )
            if artifact.config_id and artifact.config_id not in config_ids:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.UNBOUND,
                        f"artifact {artifact.artifact_id!r} references unknown "
                        f"config {artifact.config_id!r}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                    )
                )
        for decision in self.decisions:
            unknown_subjects = sorted(set(decision.subject_ids) - artifact_ids)
            if unknown_subjects:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.UNBOUND,
                        f"decision {decision.decision_id!r} has unknown subjects "
                        f"{unknown_subjects}",
                    )
                )
        return issues

    def audit_integrity(
        self,
        root: str | Path,
        *,
        reject_unbound: bool = True,
        ignore_paths: Iterable[str] = (),
    ) -> IntegrityReport:
        """Inspect artifact bytes and return all detected integrity issues."""

        root_path = Path(root)
        issues = self._binding_issues()
        checked: list[str] = []
        try:
            resolved_root = root_path.resolve(strict=True)
        except FileNotFoundError:
            issues.append(
                IntegrityIssue(
                    IntegrityIssueKind.MISSING,
                    f"artifact root does not exist: {root_path}",
                    path=str(root_path),
                )
            )
            return _integrity_report(issues, checked)
        if not resolved_root.is_dir():
            issues.append(
                IntegrityIssue(
                    IntegrityIssueKind.INVALID,
                    f"artifact root is not a directory: {root_path}",
                    path=str(root_path),
                )
            )
            return _integrity_report(issues, checked)

        bound_paths: set[str] = set()
        for artifact in sorted(
            self.artifacts, key=lambda item: (item.path, item.artifact_id)
        ):
            if not artifact.path:
                continue
            bound_paths.add(artifact.path)
            checked.append(artifact.artifact_id)
            candidate = resolved_root.joinpath(*PurePosixPath(artifact.path).parts)
            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.MISSING,
                        f"artifact file is missing: {artifact.path}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                    )
                )
                continue
            if not resolved.is_relative_to(resolved_root):
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.INVALID,
                        f"artifact path escapes verification root: {artifact.path}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                    )
                )
                continue
            if not resolved.is_file():
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.MISSING,
                        f"artifact path is not a regular file: {artifact.path}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                    )
                )
                continue
            actual_size, actual_sha256 = _hash_file(resolved)
            if actual_size != artifact.size:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.CHANGED,
                        f"artifact size changed for {artifact.path}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                        expected=str(artifact.size),
                        actual=str(actual_size),
                    )
                )
            if actual_sha256 != artifact.content_sha256:
                issues.append(
                    IntegrityIssue(
                        IntegrityIssueKind.CHANGED,
                        f"artifact digest changed for {artifact.path}",
                        artifact_id=artifact.artifact_id,
                        path=artifact.path,
                        expected=artifact.content_sha256,
                        actual=actual_sha256,
                    )
                )

        if reject_unbound:
            ignored = {
                _relative_artifact_path(item)
                for item in ignore_paths
            }
            for path in sorted(item for item in resolved_root.rglob("*") if item.is_file()):
                resolved = path.resolve()
                if not resolved.is_relative_to(resolved_root):
                    continue
                relative = path.relative_to(resolved_root).as_posix()
                if relative not in bound_paths and relative not in ignored:
                    issues.append(
                        IntegrityIssue(
                            IntegrityIssueKind.UNBOUND,
                            f"file is not bound by the manifest: {relative}",
                            path=relative,
                        )
                    )
        return _integrity_report(issues, checked)

    def verify_integrity(
        self,
        root: str | Path,
        *,
        reject_unbound: bool = True,
        ignore_paths: Iterable[str] = (),
    ) -> IntegrityReport:
        """Verify bytes and bindings, raising :class:`ArtifactIntegrityError`."""

        report = self.audit_integrity(
            root,
            reject_unbound=reject_unbound,
            ignore_paths=ignore_paths,
        )
        if not report.valid:
            raise ArtifactIntegrityError(report)
        return report

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactManifest":
        return cls(
            artifacts=tuple(
                Artifact.from_dict(_mapping(item, "artifact"))
                for item in _sequence(data.get("artifacts"), "artifacts")
            ),
            repository_commit=str(data.get("repository_commit") or ""),
            producers=tuple(
                ProducerBinding.from_dict(_mapping(item, "producer"))
                for item in _sequence(data.get("producers"), "producers")
            ),
            configs=tuple(
                ConfigBinding.from_dict(_mapping(item, "config"))
                for item in _sequence(data.get("configs"), "configs")
            ),
            schema_versions=_mapping(
                data.get("schema_versions"), "schema_versions"
            ),
            ontology_versions=_mapping(
                data.get("ontology_versions"), "ontology_versions"
            ),
            tool_versions=_mapping(data.get("tool_versions"), "tool_versions"),
            model_versions=_mapping(
                data.get("model_versions"), "model_versions"
            ),
            solver_versions=_mapping(
                data.get("solver_versions"), "solver_versions"
            ),
            prompt_template_digests=_mapping(
                data.get("prompt_template_digests"),
                "prompt_template_digests",
            ),
            diagnostic_ids=_string_tuple(
                data.get("diagnostic_ids"),
                label="ArtifactManifest.diagnostic_ids",
            ),
            decisions=tuple(
                ManifestDecision.from_dict(_mapping(item, "decision"))
                for item in _sequence(data.get("decisions"), "decisions")
            ),
            deterministic_metadata=_mapping(
                data.get("deterministic_metadata"), "deterministic_metadata"
            ),
            observations=RunObservations.from_dict(
                _mapping(data.get("observations"), "observations")
            ),
            max_diagnostics=_required_int(data, "max_diagnostics"),
            manifest_id=str(data.get("manifest_id") or ""),
            schema_version=str(data.get("schema_version") or ""),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "ArtifactManifest":
        if isinstance(value, (bytes, bytearray)):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactManifestValidationError(
                    "manifest JSON must be UTF-8"
                ) from exc
        if not isinstance(value, str):
            raise TypeError("manifest JSON must be str or bytes")
        try:
            data = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ArtifactManifestValidationError(
                f"invalid manifest JSON: {exc}"
            ) from exc
        return cls.from_dict(_mapping(data, "manifest"))


def artifact_from_path(
    path: str | Path,
    *,
    root: str | Path,
    artifact_id: str,
    role: ArtifactRole | str,
    **bindings: Any,
) -> Artifact:
    """Hash a regular file and construct its portable artifact binding."""

    root_path = Path(root).resolve(strict=True)
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = root_path / file_path
    resolved = file_path.resolve(strict=True)
    if not resolved.is_relative_to(root_path):
        raise ArtifactManifestValidationError(
            f"artifact path escapes root: {path}"
        )
    if not resolved.is_file():
        raise ArtifactManifestValidationError(
            f"artifact path is not a regular file: {path}"
        )
    size, digest = _hash_file(resolved)
    return Artifact(
        artifact_id=artifact_id,
        role=_enum_value(ArtifactRole, role, "Artifact.role"),
        content_sha256=digest,
        size=size,
        path=resolved.relative_to(root_path).as_posix(),
        **bindings,
    )


def verify_artifact_integrity(
    manifest: ArtifactManifest,
    root: str | Path,
    *,
    reject_unbound: bool = True,
    ignore_paths: Iterable[str] = (),
) -> IntegrityReport:
    """Functional spelling of :meth:`ArtifactManifest.verify_integrity`."""

    if not isinstance(manifest, ArtifactManifest):
        raise TypeError("manifest must be an ArtifactManifest")
    return manifest.verify_integrity(
        root,
        reject_unbound=reject_unbound,
        ignore_paths=ignore_paths,
    )


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _duplicate_issues(
    records: Sequence[Any],
    attribute: str,
    *,
    ignore_empty: bool = False,
) -> list[IntegrityIssue]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        value = getattr(record, attribute)
        if ignore_empty and not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return [
        IntegrityIssue(
            IntegrityIssueKind.DUPLICATE,
            f"duplicate {attribute} {value!r}",
            artifact_id=value if attribute == "artifact_id" else "",
            path=value if attribute == "path" else "",
        )
        for value in sorted(duplicates)
    ]


def _integrity_report(
    issues: Sequence[IntegrityIssue],
    checked: Sequence[str],
) -> IntegrityReport:
    ordered = tuple(
        sorted(
            issues,
            key=lambda item: (
                item.kind.value,
                item.path,
                item.artifact_id,
                item.message,
                item.expected,
                item.actual,
            ),
        )
    )
    return IntegrityReport(ordered, tuple(sorted(set(checked))))


def _validate_string_map(label: str, value: Mapping[str, Any]) -> None:
    for key, item in value.items():
        _require_text(f"{label} key", key)
        _require_text(f"{label}[{key!r}]", item)


def _validate_digest_map(label: str, value: Mapping[str, Any]) -> None:
    for key, item in value.items():
        _require_id(f"{label} key", key)
        if isinstance(item, str) and item.startswith("sha256:"):
            item = item.removeprefix("sha256:")
        _require_sha256(f"{label}[{key!r}]", item)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ArtifactManifestValidationError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ArtifactManifestValidationError(f"{label} must be a sequence")
    return value


def _required_int(data: Mapping[str, Any], key: str) -> int:
    if key not in data or isinstance(data[key], bool) or not isinstance(data[key], int):
        raise ArtifactManifestValidationError(f"{key} must be an integer")
    return data[key]


# Descriptive compatibility aliases for adapters.
ArtifactBinding = Artifact
ArtifactRecord = Artifact
ArtifactDecision = ManifestDecision
ObservationalMetadata = RunObservations
RunManifest = ArtifactManifest
IntegrityVerificationReport = IntegrityReport
build_artifact = artifact_from_path


__all__ = [
    "ARTIFACT_MANIFEST_IDENTITY_DOMAIN",
    "IR_ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "Artifact",
    "ArtifactBinding",
    "ArtifactDecision",
    "ArtifactIntegrityError",
    "ArtifactManifest",
    "ArtifactManifestValidationError",
    "ArtifactRecord",
    "ArtifactRole",
    "DecisionKind",
    "IntegrityIssue",
    "IntegrityIssueKind",
    "IntegrityReport",
    "IntegrityVerificationReport",
    "ManifestDecision",
    "ObservationalMetadata",
    "RunManifest",
    "RunObservations",
    "artifact_from_path",
    "build_artifact",
    "verify_artifact_integrity",
]
