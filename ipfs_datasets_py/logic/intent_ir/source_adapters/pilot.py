"""Bounded, reproducible ingestion pilot for two pinned SkillCenter bundles.

The pilot composes the immutable snapshot/cache, read-only SQLite reader,
source policy, structural normalizer, corpus projector, and semantic projector.
It deliberately supports only the Security-lite and GitHub-lite artifacts
declared by a versioned manifest.  GitHub-all is outside this interface and is
rejected even when a caller supplies its hash.

Source bodies remain untrusted data throughout this module.  The pilot never
executes source commands, follows source links, imports source code, or treats
source text as configuration.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import resource
import sys
import time
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ..canonicalize import intent_ir_sha256
from ..graphrag.corpus_projector import (
    ContentAddressedStore,
    CorpusEvidenceRecord,
    CorpusProjector,
)
from ..graphrag.semantic_projector import SemanticIntentGraphProjector
from ..normalize.skill import (
    SkillCenterIntentNormalizer,
    SkillNormalizationPolicyError,
)
from .policy import (
    AllowedUseDecision,
    FindingCategory,
    SkillSourcePolicy,
)
from .skillcenter import SkillCenterBundleReader
from .snapshot import SkillCenterSnapshot, SkillCenterSnapshotCache


SKILLCENTER_PILOT_INTERFACE: Final = "SkillCenterPilot@1"
SKILLCENTER_PILOT_MANIFEST_SCHEMA_VERSION: Final = (
    "skillcenter-pilot-manifest/v1"
)
SKILLCENTER_PILOT_REPORT_SCHEMA_VERSION: Final = "skillcenter-pilot-report/v1"

SECURITY_LITE_PROFILE: Final = "security-lite"
GITHUB_LITE_PROFILE: Final = "github-lite"
REQUIRED_PILOT_PROFILES: Final = frozenset(
    {SECURITY_LITE_PROFILE, GITHUB_LITE_PROFILE}
)
GITHUB_ALL_FILENAME: Final = "github-skillmd-all-v20260608.sqlite"
ROLLOUT_GATE_NAMES: Final = (
    "quality",
    "safety",
    "license",
    "throughput",
    "reproducibility",
)

_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_FAILURE_MESSAGE_CHARS = 500
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_BLOCKED_NORMALIZATION_DECISIONS = frozenset(
    {
        AllowedUseDecision.METADATA_ONLY,
        AllowedUseDecision.QUARANTINED_UNKNOWN,
        AllowedUseDecision.EXCLUDED,
    }
)


class SkillCenterPilotError(ValueError):
    """Base class for an invalid pilot contract or run request."""


class SkillCenterPilotManifestError(SkillCenterPilotError):
    """Raised when the two-bundle manifest is malformed or expands scope."""


class SkillCenterPilotGateError(SkillCenterPilotError):
    """Raised when a full run does not have a qualifying sample receipt."""


class PilotRunMode(str, Enum):
    """Supported pilot phases."""

    SAMPLE = "sample"
    FULL = "full"


def _require_int(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SkillCenterPilotManifestError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise SkillCenterPilotManifestError(
            f"{label} must be non-empty normalized text"
        )
    return value


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise SkillCenterPilotManifestError(
            f"{label} fields do not match the schema ({'; '.join(details)})"
        )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise SkillCenterPilotManifestError(f"{label} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class PilotBundleSpec:
    """Expected identity and bundle metadata for one pilot profile."""

    profile: str
    repository_file: str
    expected_sha256: str
    expected_size_bytes: int
    expected_total_skills: int
    expected_bundle_type: str
    expected_bundle_version: str
    sample_limit: int

    def __post_init__(self) -> None:
        profile = _require_text(self.profile, "bundle.profile")
        if not _PROFILE_RE.fullmatch(profile):
            raise SkillCenterPilotManifestError(
                "bundle.profile must be a lowercase hyphenated identifier"
            )
        repository_file = _require_text(
            self.repository_file, "bundle.repository_file"
        )
        if Path(repository_file).name != repository_file:
            raise SkillCenterPilotManifestError(
                "pilot repository_file must be a root-level filename"
            )
        if "github-skillmd-all" in repository_file.casefold():
            raise SkillCenterPilotManifestError(
                "GitHub-all is prohibited by the bounded pilot contract"
            )
        if not isinstance(self.expected_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.expected_sha256
        ):
            raise SkillCenterPilotManifestError(
                "bundle.expected_sha256 must be lowercase SHA-256"
            )
        size = _require_int(
            self.expected_size_bytes, "bundle.expected_size_bytes"
        )
        total = _require_int(
            self.expected_total_skills, "bundle.expected_total_skills"
        )
        sample_limit = _require_int(self.sample_limit, "bundle.sample_limit")
        if sample_limit > total:
            raise SkillCenterPilotManifestError(
                "bundle.sample_limit cannot exceed expected_total_skills"
            )
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "repository_file", repository_file)
        object.__setattr__(self, "expected_size_bytes", size)
        object.__setattr__(self, "expected_total_skills", total)
        object.__setattr__(self, "sample_limit", sample_limit)
        object.__setattr__(
            self,
            "expected_bundle_type",
            _require_text(
                self.expected_bundle_type, "bundle.expected_bundle_type"
            ),
        )
        object.__setattr__(
            self,
            "expected_bundle_version",
            _require_text(
                self.expected_bundle_version, "bundle.expected_bundle_version"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_bundle_type": self.expected_bundle_type,
            "expected_bundle_version": self.expected_bundle_version,
            "expected_sha256": self.expected_sha256,
            "expected_size_bytes": self.expected_size_bytes,
            "expected_total_skills": self.expected_total_skills,
            "profile": self.profile,
            "repository_file": self.repository_file,
            "sample_limit": self.sample_limit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PilotBundleSpec":
        value = _mapping(value, "bundle")
        fields = {
            "expected_bundle_type",
            "expected_bundle_version",
            "expected_sha256",
            "expected_size_bytes",
            "expected_total_skills",
            "profile",
            "repository_file",
            "sample_limit",
        }
        _require_exact_fields(value, fields, "bundle")
        return cls(**{field: value[field] for field in fields})


@dataclass(frozen=True, slots=True)
class PilotBounds:
    """Hard resource and input bounds shared by both pilot phases."""

    max_bundle_count: int
    max_total_records: int
    max_text_chars: int
    batch_size: int
    max_elapsed_seconds: int
    max_peak_memory_bytes: int

    def __post_init__(self) -> None:
        for field in (
            "max_bundle_count",
            "max_total_records",
            "max_text_chars",
            "batch_size",
            "max_elapsed_seconds",
            "max_peak_memory_bytes",
        ):
            object.__setattr__(
                self, field, _require_int(getattr(self, field), f"bounds.{field}")
            )
        if self.max_bundle_count != 2:
            raise SkillCenterPilotManifestError(
                "bounded pilot must declare exactly two bundles"
            )
        if self.batch_size > 1_000:
            raise SkillCenterPilotManifestError(
                "bounds.batch_size exceeds the reader safety limit"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "batch_size": self.batch_size,
            "max_bundle_count": self.max_bundle_count,
            "max_elapsed_seconds": self.max_elapsed_seconds,
            "max_peak_memory_bytes": self.max_peak_memory_bytes,
            "max_text_chars": self.max_text_chars,
            "max_total_records": self.max_total_records,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PilotBounds":
        value = _mapping(value, "bounds")
        fields = {
            "batch_size",
            "max_bundle_count",
            "max_elapsed_seconds",
            "max_peak_memory_bytes",
            "max_text_chars",
            "max_total_records",
        }
        _require_exact_fields(value, fields, "bounds")
        return cls(**{field: value[field] for field in fields})


@dataclass(frozen=True, slots=True)
class PilotExpansionPolicy:
    """Manifest-level scope barrier for corpus expansion."""

    allowed_repository_files: tuple[str, ...]
    prohibited_repository_files: tuple[str, ...]
    github_all_requires_rollout_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(set(self.allowed_repository_files)) != len(
            self.allowed_repository_files
        ):
            raise SkillCenterPilotManifestError(
                "allowed_repository_files must not contain duplicates"
            )
        if len(set(self.prohibited_repository_files)) != len(
            self.prohibited_repository_files
        ):
            raise SkillCenterPilotManifestError(
                "prohibited_repository_files must not contain duplicates"
            )
        allowed = tuple(
            sorted(
                {
                    _require_text(item, "allowed_repository_files item")
                    for item in self.allowed_repository_files
                }
            )
        )
        prohibited = tuple(
            sorted(
                {
                    _require_text(item, "prohibited_repository_files item")
                    for item in self.prohibited_repository_files
                }
            )
        )
        gates = tuple(self.github_all_requires_rollout_gates)
        if gates != ROLLOUT_GATE_NAMES:
            raise SkillCenterPilotManifestError(
                "GitHub-all must require quality, safety, license, throughput, "
                "and reproducibility gates in that order"
            )
        if GITHUB_ALL_FILENAME not in prohibited:
            raise SkillCenterPilotManifestError(
                f"prohibited_repository_files must include {GITHUB_ALL_FILENAME}"
            )
        if set(allowed) & set(prohibited):
            raise SkillCenterPilotManifestError(
                "allowed and prohibited repository files must be disjoint"
            )
        object.__setattr__(self, "allowed_repository_files", allowed)
        object.__setattr__(self, "prohibited_repository_files", prohibited)
        object.__setattr__(self, "github_all_requires_rollout_gates", gates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_repository_files": list(self.allowed_repository_files),
            "github_all_requires_rollout_gates": list(
                self.github_all_requires_rollout_gates
            ),
            "prohibited_repository_files": list(
                self.prohibited_repository_files
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PilotExpansionPolicy":
        value = _mapping(value, "expansion_policy")
        fields = {
            "allowed_repository_files",
            "github_all_requires_rollout_gates",
            "prohibited_repository_files",
        }
        _require_exact_fields(value, fields, "expansion_policy")
        for field in fields:
            if (
                not isinstance(value[field], list)
                or any(not isinstance(item, str) for item in value[field])
            ):
                raise SkillCenterPilotManifestError(
                    f"expansion_policy.{field} must be a string array"
                )
        return cls(
            allowed_repository_files=tuple(value["allowed_repository_files"]),
            prohibited_repository_files=tuple(
                value["prohibited_repository_files"]
            ),
            github_all_requires_rollout_gates=tuple(
                value["github_all_requires_rollout_gates"]
            ),
        )


@dataclass(frozen=True, slots=True)
class SkillCenterPilotManifest:
    """Strict immutable manifest for the two-bundle pilot."""

    dataset_id: str
    dataset_revision: str
    bundles: tuple[PilotBundleSpec, ...]
    bounds: PilotBounds
    expansion_policy: PilotExpansionPolicy
    interface: str = SKILLCENTER_PILOT_INTERFACE
    schema_version: str = SKILLCENTER_PILOT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        dataset_id = _require_text(self.dataset_id, "dataset_id")
        revision = _require_text(self.dataset_revision, "dataset_revision")
        if self.interface != SKILLCENTER_PILOT_INTERFACE:
            raise SkillCenterPilotManifestError(
                f"interface must be {SKILLCENTER_PILOT_INTERFACE}"
            )
        if self.schema_version != SKILLCENTER_PILOT_MANIFEST_SCHEMA_VERSION:
            raise SkillCenterPilotManifestError(
                "unsupported pilot manifest schema_version"
            )
        if any(not isinstance(item, PilotBundleSpec) for item in self.bundles):
            raise SkillCenterPilotManifestError(
                "bundles must contain PilotBundleSpec values"
            )
        bundles = tuple(sorted(self.bundles, key=lambda item: item.profile))
        if len(bundles) != 2 or {
            item.profile for item in bundles
        } != REQUIRED_PILOT_PROFILES:
            raise SkillCenterPilotManifestError(
                "pilot manifest must contain exactly security-lite and github-lite"
            )
        if len({item.repository_file for item in bundles}) != 2:
            raise SkillCenterPilotManifestError(
                "pilot bundle repository files must be unique"
            )
        allowed_files = set(self.expansion_policy.allowed_repository_files)
        bundle_files = {item.repository_file for item in bundles}
        if allowed_files != bundle_files:
            raise SkillCenterPilotManifestError(
                "expansion_policy allowed files must exactly match pilot bundles"
            )
        total = sum(item.expected_total_skills for item in bundles)
        if total > self.bounds.max_total_records:
            raise SkillCenterPilotManifestError(
                "declared bundle rows exceed bounds.max_total_records"
            )
        # Constructing snapshots centrally validates immutable revision,
        # normalized dataset ID/path, hashes, sizes, and deterministic CIDs.
        for bundle in bundles:
            SkillCenterSnapshot(
                dataset_id=dataset_id,
                dataset_revision=revision,
                repository_file=bundle.repository_file,
                expected_sha256=bundle.expected_sha256,
                expected_size_bytes=bundle.expected_size_bytes,
            )
        object.__setattr__(self, "dataset_id", dataset_id)
        object.__setattr__(self, "dataset_revision", revision)
        object.__setattr__(self, "bundles", bundles)

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    @property
    def total_skills(self) -> int:
        return sum(item.expected_total_skills for item in self.bundles)

    @property
    def sample_records(self) -> int:
        return sum(item.sample_limit for item in self.bundles)

    def snapshot_for(self, bundle: PilotBundleSpec) -> SkillCenterSnapshot:
        if bundle not in self.bundles:
            raise SkillCenterPilotManifestError(
                "bundle does not belong to this pilot manifest"
            )
        return SkillCenterSnapshot(
            dataset_id=self.dataset_id,
            dataset_revision=self.dataset_revision,
            repository_file=bundle.repository_file,
            expected_sha256=bundle.expected_sha256,
            expected_size_bytes=bundle.expected_size_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": self.bounds.to_dict(),
            "bundles": [item.to_dict() for item in self.bundles],
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "expansion_policy": self.expansion_policy.to_dict(),
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillCenterPilotManifest":
        value = _mapping(value, "pilot manifest")
        fields = {
            "bounds",
            "bundles",
            "dataset_id",
            "dataset_revision",
            "expansion_policy",
            "interface",
            "schema_version",
        }
        _require_exact_fields(value, fields, "pilot manifest")
        bundles_value = value["bundles"]
        if not isinstance(bundles_value, list):
            raise SkillCenterPilotManifestError("bundles must be an array")
        return cls(
            dataset_id=value["dataset_id"],
            dataset_revision=value["dataset_revision"],
            bundles=tuple(
                PilotBundleSpec.from_dict(_mapping(item, "bundle"))
                for item in bundles_value
            ),
            bounds=PilotBounds.from_dict(_mapping(value["bounds"], "bounds")),
            expansion_policy=PilotExpansionPolicy.from_dict(
                _mapping(value["expansion_policy"], "expansion_policy")
            ),
            interface=value["interface"],
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_json(
        cls, payload: str | bytes | bytearray
    ) -> "SkillCenterPilotManifest":
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = bytes(payload).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillCenterPilotManifestError(
                    "pilot manifest must be UTF-8"
                ) from exc
        if not isinstance(payload, str):
            raise TypeError("pilot manifest JSON must be str or bytes")
        if len(payload.encode("utf-8")) > _MAX_MANIFEST_BYTES:
            raise SkillCenterPilotManifestError("pilot manifest is oversized")

        def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise SkillCenterPilotManifestError(
                        f"duplicate manifest field: {key}"
                    )
                result[key] = value
            return result

        try:
            decoded = json.loads(payload, object_pairs_hook=no_duplicates)
        except SkillCenterPilotManifestError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SkillCenterPilotManifestError(
                f"invalid pilot manifest JSON: {exc}"
            ) from exc
        return cls.from_dict(_mapping(decoded, "pilot manifest"))

    @classmethod
    def from_path(cls, path: str | Path) -> "SkillCenterPilotManifest":
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise SkillCenterPilotManifestError(
                "pilot manifest path must be a regular file"
            )
        if candidate.stat().st_size > _MAX_MANIFEST_BYTES:
            raise SkillCenterPilotManifestError("pilot manifest is oversized")
        try:
            payload = candidate.read_bytes()
        except OSError as exc:
            raise SkillCenterPilotManifestError(
                f"cannot read pilot manifest: {exc}"
            ) from exc
        return cls.from_json(payload)


@dataclass(frozen=True, slots=True)
class PilotFailure:
    """Bounded non-source failure observation."""

    stage: str
    code: str
    exception_type: str
    message: str
    skill_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "exception_type": self.exception_type,
            "message": self.message,
            "skill_id": self.skill_id,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class PilotGroundingReport:
    """Grounding and normalization diagnostics for one bundle."""

    source_ref_count: int = 0
    source_span_count: int = 0
    grounded_statement_count: int = 0
    grounded_action_count: int = 0
    grounded_control_edge_count: int = 0
    ambiguity_diagnostic_count: int = 0
    unsupported_diagnostic_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "ambiguity_diagnostic_count": self.ambiguity_diagnostic_count,
            "grounded_action_count": self.grounded_action_count,
            "grounded_control_edge_count": self.grounded_control_edge_count,
            "grounded_statement_count": self.grounded_statement_count,
            "source_ref_count": self.source_ref_count,
            "source_span_count": self.source_span_count,
            "unsupported_diagnostic_count": self.unsupported_diagnostic_count,
        }


def _frozen_counts(
    values: Mapping[str, int], keys: tuple[str, ...]
) -> Mapping[str, int]:
    return MappingProxyType({key: int(values.get(key, 0)) for key in keys})


@dataclass(frozen=True, slots=True)
class PilotBundleReport:
    """Complete receipt for one bundle in one pilot phase."""

    profile: str
    repository_file: str
    snapshot_id: str
    snapshot_sha256: str
    snapshot_size_bytes: int
    expected_record_count: int
    selected_record_count: int
    policy_evaluated_count: int
    policy_blocked_count: int
    normalized_record_count: int
    policy_decision_counts: Mapping[str, int]
    finding_counts: Mapping[str, int]
    grounding: PilotGroundingReport
    intent_ir_digests: tuple[str, ...]
    corpus_graph_digest: str
    corpus_graph_cid: str
    corpus_node_count: int
    corpus_edge_count: int
    semantic_graph_digests: tuple[str, ...]
    semantic_graph_cids: tuple[str, ...]
    semantic_node_count: int
    semantic_edge_count: int
    failures: tuple[PilotFailure, ...]
    elapsed_ms: float
    process_peak_memory_bytes: int
    snapshot_verified: bool

    def __post_init__(self) -> None:
        decision_keys = tuple(item.value for item in AllowedUseDecision)
        finding_keys = tuple(item.value for item in FindingCategory)
        object.__setattr__(
            self,
            "policy_decision_counts",
            _frozen_counts(self.policy_decision_counts, decision_keys),
        )
        object.__setattr__(
            self,
            "finding_counts",
            _frozen_counts(self.finding_counts, finding_keys),
        )
        for field in (
            "intent_ir_digests",
            "semantic_graph_digests",
            "semantic_graph_cids",
            "failures",
        ):
            object.__setattr__(self, field, tuple(getattr(self, field)))

    @property
    def passed(self) -> bool:
        return (
            self.snapshot_verified
            and not self.failures
            and self.selected_record_count == self.expected_record_count
            and self.policy_evaluated_count == self.selected_record_count
            and (
                self.normalized_record_count + self.policy_blocked_count
                == self.selected_record_count
            )
        )

    def stable_evidence_dict(self) -> dict[str, Any]:
        """Return deterministic evidence, excluding runtime observations."""

        return {
            "corpus_edge_count": self.corpus_edge_count,
            "corpus_graph_cid": self.corpus_graph_cid,
            "corpus_graph_digest": self.corpus_graph_digest,
            "corpus_node_count": self.corpus_node_count,
            "expected_record_count": self.expected_record_count,
            "failures": [
                {
                    "code": item.code,
                    "exception_type": item.exception_type,
                    "skill_id": item.skill_id,
                    "stage": item.stage,
                }
                for item in self.failures
            ],
            "finding_counts": dict(self.finding_counts),
            "grounding": self.grounding.to_dict(),
            "intent_ir_digests": list(self.intent_ir_digests),
            "normalized_record_count": self.normalized_record_count,
            "policy_blocked_count": self.policy_blocked_count,
            "policy_decision_counts": dict(self.policy_decision_counts),
            "policy_evaluated_count": self.policy_evaluated_count,
            "profile": self.profile,
            "repository_file": self.repository_file,
            "selected_record_count": self.selected_record_count,
            "semantic_edge_count": self.semantic_edge_count,
            "semantic_graph_cids": list(self.semantic_graph_cids),
            "semantic_graph_digests": list(self.semantic_graph_digests),
            "semantic_node_count": self.semantic_node_count,
            "snapshot_id": self.snapshot_id,
            "snapshot_sha256": self.snapshot_sha256,
            "snapshot_size_bytes": self.snapshot_size_bytes,
            "snapshot_verified": self.snapshot_verified,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.stable_evidence_dict()
        value.update(
            {
                "elapsed_ms": self.elapsed_ms,
                "failures": [item.to_dict() for item in self.failures],
                "passed": self.passed,
                "process_peak_memory_bytes": self.process_peak_memory_bytes,
            }
        )
        return value


@dataclass(frozen=True, slots=True)
class SkillCenterPilotReport:
    """Two-bundle pilot result and rollout decision."""

    mode: PilotRunMode
    manifest_sha256: str
    dataset_id: str
    dataset_revision: str
    bundles: tuple[PilotBundleReport, ...]
    rollout_gates: Mapping[str, bool]
    elapsed_ms: float
    process_peak_memory_bytes: int
    github_all_expansion_permitted: bool = False
    github_all_expansion_reason: str = (
        "blocked_by_two_bundle_pilot_scope_pending_external_rollout_approval"
    )
    schema_version: str = SKILLCENTER_PILOT_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SKILLCENTER_PILOT_REPORT_SCHEMA_VERSION:
            raise SkillCenterPilotError(
                "unsupported pilot report schema_version"
            )
        if self.github_all_expansion_permitted:
            raise SkillCenterPilotGateError(
                "SkillCenterPilot@1 cannot permit GitHub-all expansion"
            )
        if tuple(self.rollout_gates) != ROLLOUT_GATE_NAMES:
            raise SkillCenterPilotError(
                "pilot report must contain the five ordered rollout gates"
            )
        object.__setattr__(self, "bundles", tuple(self.bundles))
        object.__setattr__(
            self,
            "rollout_gates",
            MappingProxyType(
                {key: bool(self.rollout_gates[key]) for key in ROLLOUT_GATE_NAMES}
            ),
        )

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.bundles) and all(
            self.rollout_gates.values()
        )

    @property
    def selected_record_count(self) -> int:
        return sum(item.selected_record_count for item in self.bundles)

    @property
    def evidence_sha256(self) -> str:
        payload = {
            "bundles": [
                item.stable_evidence_dict()
                for item in sorted(self.bundles, key=lambda bundle: bundle.profile)
            ],
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "github_all_expansion_permitted": False,
            "github_all_expansion_reason": self.github_all_expansion_reason,
            "manifest_sha256": self.manifest_sha256,
            "mode": self.mode.value,
            "rollout_gates": dict(self.rollout_gates),
            "schema_version": self.schema_version,
        }
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundles": [item.to_dict() for item in self.bundles],
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "elapsed_ms": self.elapsed_ms,
            "evidence_sha256": self.evidence_sha256,
            "github_all_expansion_permitted": False,
            "github_all_expansion_reason": self.github_all_expansion_reason,
            "manifest_sha256": self.manifest_sha256,
            "mode": self.mode.value,
            "passed": self.passed,
            "process_peak_memory_bytes": self.process_peak_memory_bytes,
            "rollout_gates": dict(self.rollout_gates),
            "schema_version": self.schema_version,
            "selected_record_count": self.selected_record_count,
        }


class SkillCenterPilot:
    """Run sample and gated full phases for the pinned two-bundle contract."""

    def __init__(
        self,
        manifest: SkillCenterPilotManifest,
        *,
        cache: SkillCenterSnapshotCache,
        store: ContentAddressedStore,
        policy: SkillSourcePolicy | None = None,
        normalizer: SkillCenterIntentNormalizer | None = None,
    ) -> None:
        if not isinstance(manifest, SkillCenterPilotManifest):
            raise TypeError("manifest must be a SkillCenterPilotManifest")
        if not isinstance(cache, SkillCenterSnapshotCache):
            raise TypeError("cache must be a SkillCenterSnapshotCache")
        if not isinstance(store, ContentAddressedStore):
            raise TypeError(
                "store must implement put_bytes(payload, media_type=...)"
            )
        if policy is not None and not isinstance(policy, SkillSourcePolicy):
            raise TypeError("policy must be a SkillSourcePolicy")
        if normalizer is not None and not isinstance(
            normalizer, SkillCenterIntentNormalizer
        ):
            raise TypeError(
                "normalizer must be a SkillCenterIntentNormalizer"
            )
        self.manifest = manifest
        self.cache = cache
        self.store = store
        self.policy = policy or SkillSourcePolicy()
        self.normalizer = normalizer or SkillCenterIntentNormalizer(
            policy=self.policy
        )

    def run_sample(self) -> SkillCenterPilotReport:
        """Run the deterministic per-bundle sample limits."""

        return self.run(PilotRunMode.SAMPLE)

    def run_full(
        self, sample_report: SkillCenterPilotReport
    ) -> SkillCenterPilotReport:
        """Run both complete small bundles after a matching sample passes."""

        return self.run(PilotRunMode.FULL, sample_report=sample_report)

    def run(
        self,
        mode: PilotRunMode | str = PilotRunMode.SAMPLE,
        *,
        sample_report: SkillCenterPilotReport | None = None,
    ) -> SkillCenterPilotReport:
        try:
            selected_mode = (
                mode if isinstance(mode, PilotRunMode) else PilotRunMode(mode)
            )
        except (TypeError, ValueError) as exc:
            raise SkillCenterPilotError(f"unsupported pilot mode: {mode!r}") from exc
        if selected_mode is PilotRunMode.FULL:
            self._validate_sample_gate(sample_report)
        elif sample_report is not None:
            raise SkillCenterPilotGateError(
                "sample_report is accepted only for a full pilot run"
            )

        started = time.monotonic_ns()
        reports = tuple(
            self._run_bundle(bundle, selected_mode)
            for bundle in self.manifest.bundles
        )
        elapsed_ms = _elapsed_ms(started)
        peak_memory = _process_peak_memory_bytes()
        failures = sum(len(item.failures) for item in reports)
        selected = sum(item.selected_record_count for item in reports)
        policy_evaluated = sum(
            item.policy_evaluated_count for item in reports
        )
        normalized = sum(item.normalized_record_count for item in reports)
        blocked = sum(item.policy_blocked_count for item in reports)
        expected = (
            self.manifest.sample_records
            if selected_mode is PilotRunMode.SAMPLE
            else self.manifest.total_skills
        )
        gates = MappingProxyType(
            {
                "quality": failures == 0 and selected == expected,
                "safety": (
                    policy_evaluated == selected
                    and normalized + blocked == selected
                ),
                "license": (
                    policy_evaluated == selected
                    and all(
                        sum(item.policy_decision_counts.values())
                        == item.policy_evaluated_count
                        for item in reports
                    )
                ),
                "throughput": (
                    elapsed_ms
                    <= self.manifest.bounds.max_elapsed_seconds * 1000
                    and peak_memory
                    <= self.manifest.bounds.max_peak_memory_bytes
                ),
                "reproducibility": all(
                    item.snapshot_verified
                    and bool(item.corpus_graph_digest)
                    and bool(item.corpus_graph_cid)
                    for item in reports
                ),
            }
        )
        return SkillCenterPilotReport(
            mode=selected_mode,
            manifest_sha256=self.manifest.manifest_sha256,
            dataset_id=self.manifest.dataset_id,
            dataset_revision=self.manifest.dataset_revision,
            bundles=reports,
            rollout_gates=gates,
            elapsed_ms=elapsed_ms,
            process_peak_memory_bytes=peak_memory,
        )

    def _validate_sample_gate(
        self, sample_report: SkillCenterPilotReport | None
    ) -> None:
        if not isinstance(sample_report, SkillCenterPilotReport):
            raise SkillCenterPilotGateError(
                "full pilot requires a SkillCenterPilotReport sample receipt"
            )
        if sample_report.mode is not PilotRunMode.SAMPLE:
            raise SkillCenterPilotGateError(
                "full pilot requires a sample-mode receipt"
            )
        if sample_report.manifest_sha256 != self.manifest.manifest_sha256:
            raise SkillCenterPilotGateError(
                "sample receipt belongs to a different pilot manifest"
            )
        if (
            sample_report.dataset_id != self.manifest.dataset_id
            or sample_report.dataset_revision != self.manifest.dataset_revision
        ):
            raise SkillCenterPilotGateError(
                "sample receipt snapshot identity does not match the manifest"
            )
        if sample_report.selected_record_count != self.manifest.sample_records:
            raise SkillCenterPilotGateError(
                "sample receipt does not cover every declared sample"
            )
        if not sample_report.passed:
            raise SkillCenterPilotGateError(
                "sample receipt did not pass all pilot gates"
            )
        if sample_report.github_all_expansion_permitted:
            raise SkillCenterPilotGateError(
                "sample receipt illegally permits GitHub-all expansion"
            )

    def _run_bundle(
        self, bundle: PilotBundleSpec, mode: PilotRunMode
    ) -> PilotBundleReport:
        started = time.monotonic_ns()
        snapshot = self.manifest.snapshot_for(bundle)
        expected_count = (
            bundle.sample_limit
            if mode is PilotRunMode.SAMPLE
            else bundle.expected_total_skills
        )
        failures: list[PilotFailure] = []
        records = []
        decisions = []
        evaluated = []
        snapshot_verified = False
        actual_manifest = None
        corpus_graph = None
        intent_digests: list[str] = []
        semantic_digests: list[str] = []
        semantic_cids: list[str] = []
        semantic_nodes = 0
        semantic_edges = 0
        policy_counts: Counter[str] = Counter()
        finding_counts: Counter[str] = Counter()
        grounding_counts: Counter[str] = Counter()

        try:
            path = self.cache.materialize(snapshot)
            snapshot_verified = True
            reader = SkillCenterBundleReader(
                path,
                dataset_id=self.manifest.dataset_id,
                dataset_revision=self.manifest.dataset_revision,
                repository_file=bundle.repository_file,
                max_text_chars=self.manifest.bounds.max_text_chars,
            )
            actual_manifest = reader.inspect()
            self._validate_bundle_metadata(bundle, actual_manifest)
            limit = (
                bundle.sample_limit if mode is PilotRunMode.SAMPLE else None
            )
            records = list(
                reader.iter_records(
                    limit=limit,
                    batch_size=self.manifest.bounds.batch_size,
                )
            )
            if len(records) != expected_count:
                raise SkillCenterPilotError(
                    f"selected {len(records)} records; expected {expected_count}"
                )
        except Exception as exc:
            failures.append(_failure("snapshot_and_read", "bundle_read_failed", exc))

        if records:
            for record in records:
                try:
                    decision = self.policy.evaluate(record)
                    decisions.append(decision)
                    evaluated.append((record, decision))
                    policy_counts[decision.allowed_use.value] += 1
                    finding_counts.update(
                        finding.category.value for finding in decision.findings
                    )
                except Exception as exc:
                    failures.append(
                        _failure(
                            "policy",
                            "policy_evaluation_failed",
                            exc,
                            skill_id=record.skill_id,
                        )
                    )

        if len(decisions) == len(records) and records:
            try:
                corpus_graph = CorpusProjector(
                    store=self.store,
                    policy=self.policy,
                    max_records=self.manifest.bounds.max_total_records,
                ).project(
                    tuple(
                        CorpusEvidenceRecord(
                            record=record, policy_decision=decision
                        )
                        for record, decision in zip(records, decisions)
                    )
                )
            except Exception as exc:
                failures.append(
                    _failure(
                        "corpus_projection",
                        "corpus_projection_failed",
                        exc,
                    )
                )

        for record, decision in evaluated:
            if decision.allowed_use in _BLOCKED_NORMALIZATION_DECISIONS:
                continue
            try:
                result = self.normalizer.normalize_with_diagnostics(record)
                if result.policy_decision.to_dict() != decision.to_dict():
                    raise SkillCenterPilotError(
                        "normalizer policy decision differs from pilot policy"
                    )
                document = result.document
                grounding_counts["source_refs"] += len(document.sources)
                grounding_counts["source_spans"] += sum(
                    source.span is not None for source in document.sources
                )
                grounding_counts["statements"] += len(document.statements)
                grounding_counts["actions"] += len(document.actions)
                grounding_counts["control_edges"] += len(
                    document.control_edges
                )
                grounding_counts["ambiguity"] += len(
                    result.ambiguity_diagnostics
                )
                grounding_counts["unsupported"] += len(
                    result.unsupported_diagnostics
                )
                intent_digests.append(intent_ir_sha256(document))
                semantic = SemanticIntentGraphProjector(self.store).project(
                    document, corpus_graph=corpus_graph
                )
                semantic_digests.append(semantic.graph_digest)
                semantic_cids.append(semantic.graph_cid)
                semantic_nodes += len(semantic.nodes)
                semantic_edges += len(semantic.edges)
            except SkillNormalizationPolicyError as exc:
                failures.append(
                    _failure(
                        "normalization",
                        "policy_changed_during_normalization",
                        exc,
                        skill_id=record.skill_id,
                    )
                )
            except Exception as exc:
                failures.append(
                    _failure(
                        "normalization_and_semantic_projection",
                        "record_projection_failed",
                        exc,
                        skill_id=record.skill_id,
                    )
                )

        peak_memory = _process_peak_memory_bytes()
        elapsed_ms = _elapsed_ms(started)
        if elapsed_ms > self.manifest.bounds.max_elapsed_seconds * 1000:
            failures.append(
                PilotFailure(
                    stage="resource_bounds",
                    code="elapsed_time_bound_exceeded",
                    exception_type="SkillCenterPilotError",
                    message="bundle elapsed time exceeded manifest bound",
                )
            )
        if peak_memory > self.manifest.bounds.max_peak_memory_bytes:
            failures.append(
                PilotFailure(
                    stage="resource_bounds",
                    code="peak_memory_bound_exceeded",
                    exception_type="SkillCenterPilotError",
                    message="process peak memory exceeded manifest bound",
                )
            )

        decision_keys = tuple(item.value for item in AllowedUseDecision)
        finding_keys = tuple(item.value for item in FindingCategory)
        grounding = PilotGroundingReport(
            source_ref_count=grounding_counts["source_refs"],
            source_span_count=grounding_counts["source_spans"],
            grounded_statement_count=grounding_counts["statements"],
            grounded_action_count=grounding_counts["actions"],
            grounded_control_edge_count=grounding_counts["control_edges"],
            ambiguity_diagnostic_count=grounding_counts["ambiguity"],
            unsupported_diagnostic_count=grounding_counts["unsupported"],
        )
        blocked_count = sum(
            policy_counts[item.value]
            for item in _BLOCKED_NORMALIZATION_DECISIONS
        )
        return PilotBundleReport(
            profile=bundle.profile,
            repository_file=bundle.repository_file,
            snapshot_id=snapshot.snapshot_id,
            snapshot_sha256=(
                actual_manifest.local_sha256
                if actual_manifest is not None
                else bundle.expected_sha256
            ),
            snapshot_size_bytes=(
                actual_manifest.size_bytes
                if actual_manifest is not None
                else bundle.expected_size_bytes
            ),
            expected_record_count=expected_count,
            selected_record_count=len(records),
            policy_evaluated_count=len(decisions),
            policy_blocked_count=blocked_count,
            normalized_record_count=len(intent_digests),
            policy_decision_counts=_frozen_counts(policy_counts, decision_keys),
            finding_counts=_frozen_counts(finding_counts, finding_keys),
            grounding=grounding,
            intent_ir_digests=tuple(intent_digests),
            corpus_graph_digest=(
                corpus_graph.graph_digest if corpus_graph is not None else ""
            ),
            corpus_graph_cid=(
                corpus_graph.graph_cid if corpus_graph is not None else ""
            ),
            corpus_node_count=(
                len(corpus_graph.nodes) if corpus_graph is not None else 0
            ),
            corpus_edge_count=(
                len(corpus_graph.edges) if corpus_graph is not None else 0
            ),
            semantic_graph_digests=tuple(semantic_digests),
            semantic_graph_cids=tuple(semantic_cids),
            semantic_node_count=semantic_nodes,
            semantic_edge_count=semantic_edges,
            failures=tuple(failures),
            elapsed_ms=elapsed_ms,
            process_peak_memory_bytes=peak_memory,
            snapshot_verified=snapshot_verified,
        )

    @staticmethod
    def _validate_bundle_metadata(
        expected: PilotBundleSpec, actual: Any
    ) -> None:
        mismatches = []
        if actual.total_skills != expected.expected_total_skills:
            mismatches.append(
                "total_skills "
                f"{actual.total_skills} != {expected.expected_total_skills}"
            )
        if actual.bundle_type != expected.expected_bundle_type:
            mismatches.append(
                f"bundle_type {actual.bundle_type!r} != "
                f"{expected.expected_bundle_type!r}"
            )
        if actual.bundle_version != expected.expected_bundle_version:
            mismatches.append(
                f"bundle_version {actual.bundle_version!r} != "
                f"{expected.expected_bundle_version!r}"
            )
        if actual.local_sha256 != expected.expected_sha256:
            mismatches.append("local SHA-256 differs from manifest")
        if actual.size_bytes != expected.expected_size_bytes:
            mismatches.append("local byte size differs from manifest")
        if mismatches:
            raise SkillCenterPilotError(
                "bundle metadata mismatch: " + "; ".join(mismatches)
            )


def _failure(
    stage: str,
    code: str,
    exc: Exception,
    *,
    skill_id: str = "",
) -> PilotFailure:
    message = " ".join(str(exc).split())
    if len(message) > _MAX_FAILURE_MESSAGE_CHARS:
        message = message[: _MAX_FAILURE_MESSAGE_CHARS - 1] + "…"
    return PilotFailure(
        stage=stage,
        code=code,
        exception_type=type(exc).__name__,
        message=message,
        skill_id=skill_id,
    )


def _elapsed_ms(started_ns: int) -> float:
    return round(max(0, time.monotonic_ns() - started_ns) / 1_000_000, 3)


def _process_peak_memory_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS and the BSDs report bytes.
    return peak if sys.platform == "darwin" else peak * 1024


__all__ = [
    "GITHUB_ALL_FILENAME",
    "GITHUB_LITE_PROFILE",
    "PilotBounds",
    "PilotBundleReport",
    "PilotBundleSpec",
    "PilotExpansionPolicy",
    "PilotFailure",
    "PilotGroundingReport",
    "PilotRunMode",
    "ROLLOUT_GATE_NAMES",
    "SECURITY_LITE_PROFILE",
    "SKILLCENTER_PILOT_INTERFACE",
    "SKILLCENTER_PILOT_MANIFEST_SCHEMA_VERSION",
    "SKILLCENTER_PILOT_REPORT_SCHEMA_VERSION",
    "SkillCenterPilot",
    "SkillCenterPilotError",
    "SkillCenterPilotGateError",
    "SkillCenterPilotManifest",
    "SkillCenterPilotManifestError",
    "SkillCenterPilotReport",
]
