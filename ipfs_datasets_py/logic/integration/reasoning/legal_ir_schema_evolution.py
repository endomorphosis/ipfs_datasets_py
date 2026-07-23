"""Versioned schema evolution gates for LegalIR artifacts.

LegalIR artifacts are reused across compiler training, Hammer proof feedback,
Leanstral audits, caches, and rollout metrics.  Reuse is intentionally stricter
than parsing: an artifact with no known schema, the wrong family, or incomplete
metric lineage is rejected instead of being silently treated as compatible.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ....optimizers.logic_theorem_optimizer.modal_autoencoder import (
    HAMMER_GUIDANCE_METRIC_SCHEMA_VERSION,
    LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
    LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION,
)
from .hammer_guidance import HAMMER_GUIDANCE_SCHEMA_VERSION
from .legal_ir_contract_telemetry import LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION
from .legal_ir_hammer import LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION
from .legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
)
from .legal_ir_learned_guidance import (
    LEGAL_IR_LEARNED_GUIDANCE_CANARY_SCHEMA_VERSION,
    LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION,
    LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION,
    LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION,
)
from .legal_ir_proof_feedback import (
    LEGAL_IR_PROOF_FEEDBACK_REPLAY_VERSION,
    LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION,
    LEGAL_IR_PROOF_FEEDBACK_STORE_VERSION,
)
from .legal_ir_proof_router import LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION
from .legal_ir_rule_distillation import (
    LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION,
    LEGAL_IR_RULE_DISTILLATION_ROLLBACK_SCHEMA_VERSION,
    LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION,
    LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION,
)
from .legal_ir_semantic_diff import (
    LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION,
    LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION,
)
from .legal_ir_source_maps import LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION
from .legal_ir_verified_gap_repairs import (
    LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION,
    LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION,
)
from .legal_ir_view_contracts import (
    LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
    LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION,
)


LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION: Final = "legal-ir-schema-evolution-v1"
LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION: Final = (
    "legal-ir-schema-evolution-registry-v1"
)

LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION: Final = "legal-ir-leanstral-audit-request-v1"
LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION: Final = "legal-ir-leanstral-audit-response-v2"
LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION: Final = (
    "legal-ir-leanstral-audit-response-v1"
)
LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION: Final = "legal-ir-leanstral-audit-cache-v1"
LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION: Final = (
    "legal-ir-leanstral-artifact-cache-index-v1"
)
LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION: Final = (
    "legal-ir-leanstral-rule-gap-report-v1"
)
LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION: Final = (
    "legal-ir-leanstral-patch-feedback-report-v1"
)
LEANSTRAL_METRIC_ATTRIBUTION_SCHEMA_VERSION: Final = (
    "legal-ir-leanstral-metric-attribution-v1"
)
MODAL_COMPILER_REPAIR_SCHEMA_VERSION: Final = "legal-ir-modal-compiler-repair-v1"
MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION: Final = "legal-ir-modal-decompiler-repair-v1"
LEGAL_IR_TARGET_DISK_CACHE_VERSION: Final = "legal-ir-target-disk-cache-v2"
PROOF_CACHE_SCHEMA_VERSION: Final = "proof-cache-v1"

_VERSION_RE = re.compile(r"^(?P<base>.+)-v(?P<major>[0-9]+)$")


class LegalIRArtifactFamily(str, Enum):
    """Artifact families with independently versioned reuse semantics."""

    VIEW_CONTRACT = "view_contract"
    LEARNED_EXPORT = "learned_export"
    LEARNED_GUIDANCE = "learned_guidance"
    HAMMER_RECEIPT = "hammer_receipt"
    HAMMER_REPORT = "hammer_report"
    LEANSTRAL_AUDIT = "leanstral_audit"
    CACHE = "cache"
    COMPILER_OUTPUT = "compiler_output"
    METRIC = "metric"
    PROOF_FEEDBACK = "proof_feedback"
    SOURCE_MAP = "source_map"


class LegalIRSchemaStatus(str, Enum):
    """Lifecycle status for one schema version."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class LegalIRSchemaCompatibility(str, Enum):
    """Headline compatibility decision."""

    COMPATIBLE = "compatible"
    MIGRATION_REQUIRED = "migration_required"
    DOWNGRADE_REQUIRED = "downgrade_required"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class LegalIRDeprecationPolicy:
    """Machine-readable reuse policy for deprecated schema versions."""

    status: LegalIRSchemaStatus = LegalIRSchemaStatus.ACTIVE
    deprecated_since: str = ""
    replacement_schema_version: str = ""
    reuse_allowed_until: str = ""
    removal_after: str = ""
    downgrade_supported: bool = False
    reason: str = ""

    @property
    def reusable(self) -> bool:
        return self.status is not LegalIRSchemaStatus.RETIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "deprecated_since": self.deprecated_since,
            "downgrade_supported": self.downgrade_supported,
            "reason": self.reason,
            "removal_after": self.removal_after,
            "replacement_schema_version": self.replacement_schema_version,
            "reusable": self.reusable,
            "reuse_allowed_until": self.reuse_allowed_until,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class LegalIRSchemaVersion:
    """One explicit LegalIR schema version."""

    schema_version: str
    artifact_family: LegalIRArtifactFamily
    required_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]
    metric_lineage_fields: tuple[str, ...] = ()
    compatible_reader_versions: tuple[str, ...] = ()
    migration_targets: tuple[str, ...] = ()
    downgrade_targets: tuple[str, ...] = ()
    feature_gates: tuple[str, ...] = ()
    deprecation: LegalIRDeprecationPolicy = field(
        default_factory=LegalIRDeprecationPolicy
    )
    description: str = ""

    @property
    def base_name(self) -> str:
        match = _VERSION_RE.match(self.schema_version)
        return match.group("base") if match else self.schema_version

    @property
    def major(self) -> int:
        match = _VERSION_RE.match(self.schema_version)
        return int(match.group("major")) if match else 0

    @property
    def current_reader_versions(self) -> tuple[str, ...]:
        return (self.schema_version, *self.compatible_reader_versions)

    def can_read_with(self, reader_schema_version: str) -> bool:
        return str(reader_schema_version or "") in self.current_reader_versions

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_family": self.artifact_family.value,
            "base_name": self.base_name,
            "compatible_reader_versions": list(self.compatible_reader_versions),
            "deprecation": self.deprecation.to_dict(),
            "description": self.description,
            "downgrade_targets": list(self.downgrade_targets),
            "feature_gates": list(self.feature_gates),
            "identity_fields": list(self.identity_fields),
            "major": self.major,
            "metric_lineage_fields": list(self.metric_lineage_fields),
            "migration_targets": list(self.migration_targets),
            "required_fields": list(self.required_fields),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LegalIRSchemaCompatibilityIssue:
    """One deterministic schema compatibility violation."""

    code: str
    message: str
    field_path: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class LegalIRSchemaCompatibilityResult:
    """Compatibility decision safe to persist in audit and rollout records."""

    artifact_family: str
    schema_version: str
    reader_schema_version: str
    compatibility: LegalIRSchemaCompatibility
    issues: tuple[LegalIRSchemaCompatibilityIssue, ...] = ()
    migration_path: tuple[str, ...] = ()
    downgrade_path: tuple[str, ...] = ()
    feature_gates: tuple[str, ...] = ()
    artifact_id: str = ""
    schema_version_id: str = LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION

    @property
    def compatible(self) -> bool:
        return self.compatibility is not LegalIRSchemaCompatibility.INCOMPATIBLE

    @property
    def reusable(self) -> bool:
        return (
            self.compatibility is LegalIRSchemaCompatibility.COMPATIBLE
            and not any(issue.severity == "error" for issue in self.issues)
        )

    @property
    def requires_migration(self) -> bool:
        return self.compatibility is LegalIRSchemaCompatibility.MIGRATION_REQUIRED

    @property
    def requires_downgrade(self) -> bool:
        return self.compatibility is LegalIRSchemaCompatibility.DOWNGRADE_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_family": self.artifact_family,
            "artifact_id": self.artifact_id,
            "compatibility": self.compatibility.value,
            "compatible": self.compatible,
            "downgrade_path": list(self.downgrade_path),
            "feature_gates": list(self.feature_gates),
            "issues": [issue.to_dict() for issue in self.issues],
            "migration_path": list(self.migration_path),
            "reader_schema_version": self.reader_schema_version,
            "reusable": self.reusable,
            "schema_version": self.schema_version,
            "schema_version_id": self.schema_version_id,
        }


@dataclass(frozen=True)
class LegalIRSchemaFeatureGate:
    """A feature that may be enabled only for compatible schema versions."""

    gate_id: str
    artifact_family: LegalIRArtifactFamily
    minimum_schema_version: str
    description: str
    enabled_by_default: bool = True

    def enabled_for(self, version: LegalIRSchemaVersion) -> bool:
        if version.artifact_family is not self.artifact_family:
            return False
        if version.schema_version == self.minimum_schema_version:
            return self.enabled_by_default
        if self.gate_id in version.feature_gates and version.major >= (
            _schema_major(self.minimum_schema_version)
        ):
            return self.enabled_by_default
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_family": self.artifact_family.value,
            "description": self.description,
            "enabled_by_default": self.enabled_by_default,
            "gate_id": self.gate_id,
            "minimum_schema_version": self.minimum_schema_version,
        }


@dataclass(frozen=True)
class LegalIRMetricLineageBinding:
    """Result of binding metrics to schema-checked upstream artifacts."""

    binding_id: str
    metric_schema_version: str
    metric_id: str
    compatible: bool
    artifact_bindings: Mapping[str, tuple[str, ...]]
    rejected_artifacts: tuple[Mapping[str, Any], ...] = ()
    missing_lineage: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION

    @property
    def reusable(self) -> bool:
        return self.compatible and not self.rejected_artifacts and not self.missing_lineage

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_bindings": {
                key: list(values) for key, values in sorted(self.artifact_bindings.items())
            },
            "binding_id": self.binding_id,
            "compatible": self.compatible,
            "metric_id": self.metric_id,
            "metric_schema_version": self.metric_schema_version,
            "missing_lineage": list(self.missing_lineage),
            "rejected_artifacts": [dict(item) for item in self.rejected_artifacts],
            "reusable": self.reusable,
            "schema_version": self.schema_version,
        }


MigrationTransform = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class LegalIRSchemaMigration:
    """Explicit, deterministic migration or downgrade edge."""

    source_schema_version: str
    target_schema_version: str
    migration_id: str
    description: str
    downgrade: bool = False
    transform: MigrationTransform | None = field(default=None, repr=False, compare=False)

    def apply(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.transform is None:
            migrated = dict(_canonical_json_value(payload))
            migrated["schema_version"] = self.target_schema_version
            return migrated
        migrated = self.transform(payload)
        migrated["schema_version"] = self.target_schema_version
        return migrated

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "downgrade": self.downgrade,
            "migration_id": self.migration_id,
            "source_schema_version": self.source_schema_version,
            "target_schema_version": self.target_schema_version,
        }


class LegalIRSchemaCompatibilityError(ValueError):
    """Raised when a caller asks to reuse an incompatible LegalIR artifact."""


class LegalIRSchemaRegistry(Mapping[str, LegalIRSchemaVersion]):
    """Read-only registry for schema versions and explicit migrations."""

    def __init__(
        self,
        versions: Sequence[LegalIRSchemaVersion],
        migrations: Sequence[LegalIRSchemaMigration],
        feature_gates: Sequence[LegalIRSchemaFeatureGate],
    ) -> None:
        by_version = {version.schema_version: version for version in versions}
        if len(by_version) != len(versions):
            raise ValueError("LegalIR schema versions must be unique")
        by_family: dict[LegalIRArtifactFamily, list[LegalIRSchemaVersion]] = {}
        for version in versions:
            by_family.setdefault(version.artifact_family, []).append(version)
        by_migration = {
            (migration.source_schema_version, migration.target_schema_version): migration
            for migration in migrations
        }
        if len(by_migration) != len(migrations):
            raise ValueError("LegalIR schema migrations must be unique")
        by_gate = {gate.gate_id: gate for gate in feature_gates}
        if len(by_gate) != len(feature_gates):
            raise ValueError("LegalIR schema feature gates must be unique")
        self._versions = MappingProxyType(by_version)
        self._families = MappingProxyType(
            {family: tuple(items) for family, items in by_family.items()}
        )
        self._migrations = MappingProxyType(by_migration)
        self._gates = MappingProxyType(by_gate)

    def __getitem__(self, key: str) -> LegalIRSchemaVersion:
        return self._versions[key]

    def __iter__(self) -> Iterable[str]:
        return iter(self._versions)

    def __len__(self) -> int:
        return len(self._versions)

    @property
    def migrations(self) -> Mapping[tuple[str, str], LegalIRSchemaMigration]:
        return self._migrations

    @property
    def feature_gates(self) -> Mapping[str, LegalIRSchemaFeatureGate]:
        return self._gates

    def get_version(self, schema_version: str) -> LegalIRSchemaVersion | None:
        return self._versions.get(str(schema_version or ""))

    def current_for_family(
        self, family: LegalIRArtifactFamily | str
    ) -> LegalIRSchemaVersion | None:
        resolved = _artifact_family(family)
        candidates = [
            version
            for version in self._families.get(resolved, ())
            if version.deprecation.status is LegalIRSchemaStatus.ACTIVE
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item.base_name, item.major))[-1]

    def versions_for_family(
        self, family: LegalIRArtifactFamily | str
    ) -> tuple[LegalIRSchemaVersion, ...]:
        return self._families.get(_artifact_family(family), ())

    def migration(
        self, source_schema_version: str, target_schema_version: str
    ) -> LegalIRSchemaMigration | None:
        return self._migrations.get((source_schema_version, target_schema_version))

    def manifest(self) -> dict[str, Any]:
        return {
            "feature_gates": [
                gate.to_dict() for gate in sorted(self._gates.values(), key=lambda item: item.gate_id)
            ],
            "migrations": [
                migration.to_dict()
                for migration in sorted(
                    self._migrations.values(),
                    key=lambda item: (item.source_schema_version, item.target_schema_version),
                )
            ],
            "registry_version": LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION,
            "schema_version": LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION,
            "versions": [
                version.to_dict()
                for version in sorted(
                    self._versions.values(),
                    key=lambda item: (item.artifact_family.value, item.schema_version),
                )
            ],
        }


def validate_legal_ir_schema_compatibility(
    payload_or_schema: Mapping[str, Any] | Any,
    *,
    artifact_family: LegalIRArtifactFamily | str | None = None,
    reader_schema_version: str = "",
    require_lineage: bool = False,
    registry: LegalIRSchemaRegistry | None = None,
) -> LegalIRSchemaCompatibilityResult:
    """Validate whether a LegalIR artifact may be reused by a reader.

    Unknown or inconsistent schemas are hard failures.  ``reader_schema_version``
    defaults to the current active version for the detected family.
    """

    active_registry = registry or LEGAL_IR_SCHEMA_REGISTRY
    payload = _payload_mapping(payload_or_schema)
    schema_version = _schema_version(payload_or_schema, payload)
    artifact_id = _artifact_id(payload)
    issues: list[LegalIRSchemaCompatibilityIssue] = []

    if not schema_version:
        return _compat_result(
            artifact_family=artifact_family,
            schema_version="",
            reader_schema_version=reader_schema_version,
            compatibility=LegalIRSchemaCompatibility.INCOMPATIBLE,
            artifact_id=artifact_id,
            issues=(
                LegalIRSchemaCompatibilityIssue(
                    "schema_version_missing",
                    "LegalIR artifact has no explicit schema_version.",
                    "schema_version",
                ),
            ),
        )

    version = active_registry.get_version(schema_version)
    if version is None:
        return _compat_result(
            artifact_family=artifact_family,
            schema_version=schema_version,
            reader_schema_version=reader_schema_version,
            compatibility=LegalIRSchemaCompatibility.INCOMPATIBLE,
            artifact_id=artifact_id,
            issues=(
                LegalIRSchemaCompatibilityIssue(
                    "unknown_schema_version",
                    f"Schema version {schema_version!r} is not registered.",
                    "schema_version",
                ),
            ),
        )

    if artifact_family is not None:
        expected = _artifact_family(artifact_family)
        if expected is not version.artifact_family:
            issues.append(
                LegalIRSchemaCompatibilityIssue(
                    "schema_family_mismatch",
                    (
                        f"Schema {schema_version!r} belongs to "
                        f"{version.artifact_family.value}, not {expected.value}."
                    ),
                    "schema_version",
                )
            )

    for field_name in version.required_fields:
        value = _field_value(payload, field_name)
        if _empty(value):
            issues.append(
                LegalIRSchemaCompatibilityIssue(
                    "required_schema_field_missing",
                    f"Required field {field_name!r} is missing or empty.",
                    field_name,
                )
            )

    if require_lineage:
        for field_name in version.metric_lineage_fields:
            value = _field_value(payload, field_name)
            if _empty(value):
                issues.append(
                    LegalIRSchemaCompatibilityIssue(
                        "metric_lineage_field_missing",
                        f"Metric lineage field {field_name!r} is missing or empty.",
                        field_name,
                    )
                )

    if not version.deprecation.reusable:
        issues.append(
            LegalIRSchemaCompatibilityIssue(
                "schema_version_retired",
                f"Schema version {schema_version!r} is retired and cannot be reused.",
                "schema_version",
            )
        )

    reader = str(reader_schema_version or "").strip()
    if not reader:
        reader = schema_version
    reader_version = active_registry.get_version(reader)
    if reader_version is None:
        issues.append(
            LegalIRSchemaCompatibilityIssue(
                "unknown_reader_schema_version",
                f"Reader schema version {reader!r} is not registered.",
                "reader_schema_version",
            )
        )
    elif reader_version.artifact_family is not version.artifact_family:
        issues.append(
            LegalIRSchemaCompatibilityIssue(
                "reader_schema_family_mismatch",
                (
                    f"Reader schema {reader!r} belongs to "
                    f"{reader_version.artifact_family.value}, not "
                    f"{version.artifact_family.value}."
                ),
                "reader_schema_version",
            )
        )

    if any(issue.severity == "error" for issue in issues):
        compatibility = LegalIRSchemaCompatibility.INCOMPATIBLE
        migration_path: tuple[str, ...] = ()
        downgrade_path: tuple[str, ...] = ()
    elif version.can_read_with(reader):
        compatibility = LegalIRSchemaCompatibility.COMPATIBLE
        migration_path = ()
        downgrade_path = ()
    else:
        migration = active_registry.migration(schema_version, reader)
        if migration is not None and not migration.downgrade:
            compatibility = LegalIRSchemaCompatibility.MIGRATION_REQUIRED
            migration_path = (schema_version, reader)
            downgrade_path = ()
        elif migration is not None and migration.downgrade:
            compatibility = LegalIRSchemaCompatibility.DOWNGRADE_REQUIRED
            migration_path = ()
            downgrade_path = (schema_version, reader)
        else:
            compatibility = LegalIRSchemaCompatibility.INCOMPATIBLE
            migration_path = ()
            downgrade_path = ()
            issues.append(
                LegalIRSchemaCompatibilityIssue(
                    "no_compatible_migration_path",
                    f"No explicit migration or downgrade path from {schema_version!r} to {reader!r}.",
                    "schema_version",
                )
            )

    return LegalIRSchemaCompatibilityResult(
        artifact_family=version.artifact_family.value,
        artifact_id=artifact_id,
        compatibility=compatibility,
        downgrade_path=downgrade_path,
        feature_gates=version.feature_gates,
        issues=tuple(_dedupe_issues(issues)),
        migration_path=migration_path,
        reader_schema_version=reader,
        schema_version=schema_version,
    )


def assert_legal_ir_schema_compatible(
    payload_or_schema: Mapping[str, Any] | Any,
    *,
    artifact_family: LegalIRArtifactFamily | str | None = None,
    reader_schema_version: str = "",
    require_lineage: bool = False,
) -> LegalIRSchemaCompatibilityResult:
    """Return the compatibility result or raise for non-reusable artifacts."""

    result = validate_legal_ir_schema_compatibility(
        payload_or_schema,
        artifact_family=artifact_family,
        reader_schema_version=reader_schema_version,
        require_lineage=require_lineage,
    )
    if not result.reusable:
        codes = ",".join(issue.code for issue in result.issues) or result.compatibility.value
        raise LegalIRSchemaCompatibilityError(
            f"LegalIR schema compatibility rejected: {codes}"
        )
    return result


def migrate_legal_ir_schema(
    payload: Mapping[str, Any] | Any,
    target_schema_version: str,
    *,
    registry: LegalIRSchemaRegistry | None = None,
) -> dict[str, Any]:
    """Apply an explicitly registered migration or downgrade edge."""

    active_registry = registry or LEGAL_IR_SCHEMA_REGISTRY
    data = _payload_mapping(payload)
    source_schema_version = _schema_version(payload, data)
    migration = active_registry.migration(source_schema_version, target_schema_version)
    if migration is None:
        raise LegalIRSchemaCompatibilityError(
            f"no LegalIR schema migration from {source_schema_version!r} to {target_schema_version!r}"
        )
    source_result = validate_legal_ir_schema_compatibility(
        data,
        reader_schema_version=target_schema_version,
        registry=active_registry,
    )
    if source_result.compatibility not in {
        LegalIRSchemaCompatibility.MIGRATION_REQUIRED,
        LegalIRSchemaCompatibility.DOWNGRADE_REQUIRED,
    }:
        raise LegalIRSchemaCompatibilityError(
            f"migration from {source_schema_version!r} to {target_schema_version!r} is not applicable"
        )
    migrated = migration.apply(data)
    final_result = validate_legal_ir_schema_compatibility(
        migrated,
        reader_schema_version=target_schema_version,
        registry=active_registry,
    )
    if not final_result.reusable:
        codes = ",".join(issue.code for issue in final_result.issues)
        raise LegalIRSchemaCompatibilityError(
            f"migrated LegalIR artifact is not reusable: {codes}"
        )
    return migrated


def downgrade_legal_ir_schema(
    payload: Mapping[str, Any] | Any,
    target_schema_version: str,
    *,
    registry: LegalIRSchemaRegistry | None = None,
) -> dict[str, Any]:
    """Downgrade only when an explicit downgrade edge exists."""

    active_registry = registry or LEGAL_IR_SCHEMA_REGISTRY
    source_schema_version = _schema_version(payload, _payload_mapping(payload))
    migration = active_registry.migration(source_schema_version, target_schema_version)
    if migration is None or not migration.downgrade:
        raise LegalIRSchemaCompatibilityError(
            f"no LegalIR schema downgrade from {source_schema_version!r} to {target_schema_version!r}"
        )
    return migrate_legal_ir_schema(
        payload,
        target_schema_version,
        registry=active_registry,
    )


def legal_ir_feature_gate_enabled(
    gate_id: str,
    payload_or_schema: Mapping[str, Any] | Any,
    *,
    artifact_family: LegalIRArtifactFamily | str | None = None,
    registry: LegalIRSchemaRegistry | None = None,
) -> bool:
    """Return true only when the artifact schema is known and compatible."""

    active_registry = registry or LEGAL_IR_SCHEMA_REGISTRY
    gate = active_registry.feature_gates.get(str(gate_id or ""))
    if gate is None:
        return False
    result = validate_legal_ir_schema_compatibility(
        payload_or_schema,
        artifact_family=artifact_family or gate.artifact_family,
        registry=active_registry,
    )
    if not result.reusable:
        return False
    version = active_registry.get_version(result.schema_version)
    return bool(version is not None and gate.enabled_for(version))


def bind_legal_ir_metric_lineage(
    metric_payload: Mapping[str, Any] | Any,
    artifacts: Sequence[Mapping[str, Any] | Any],
    *,
    required_artifact_families: Sequence[LegalIRArtifactFamily | str] = (),
    registry: LegalIRSchemaRegistry | None = None,
) -> LegalIRMetricLineageBinding:
    """Bind a metric payload to schema-compatible upstream artifact IDs."""

    active_registry = registry or LEGAL_IR_SCHEMA_REGISTRY
    metric = _payload_mapping(metric_payload)
    metric_result = validate_legal_ir_schema_compatibility(
        metric,
        artifact_family=LegalIRArtifactFamily.METRIC,
        require_lineage=True,
        registry=active_registry,
    )
    metric_schema_version = metric_result.schema_version
    metric_id = _artifact_id(metric) or "legal-ir-metric-" + _stable_hash(metric)[:24]
    lineage = _lineage_mapping(metric)
    required = tuple(_artifact_family(item).value for item in required_artifact_families)
    artifact_bindings: dict[str, list[str]] = {}
    rejected: list[Mapping[str, Any]] = []

    for raw_artifact in artifacts:
        artifact = _payload_mapping(raw_artifact)
        result = validate_legal_ir_schema_compatibility(
            artifact,
            registry=active_registry,
        )
        artifact_id = result.artifact_id or _artifact_id(artifact)
        if not result.reusable:
            rejected.append(
                {
                    "artifact_id": artifact_id,
                    "schema_version": result.schema_version,
                    "issues": [issue.to_dict() for issue in result.issues],
                }
            )
            continue
        if not _lineage_contains(lineage, artifact_id):
            rejected.append(
                {
                    "artifact_id": artifact_id,
                    "schema_version": result.schema_version,
                    "issues": [
                        {
                            "code": "artifact_not_bound_by_metric_lineage",
                            "field_path": "metric_lineage",
                            "message": "Artifact ID is absent from metric lineage.",
                            "severity": "error",
                        }
                    ],
                }
            )
            continue
        artifact_bindings.setdefault(result.artifact_family, []).append(artifact_id)

    missing_lineage: list[str] = []
    if not metric_result.reusable:
        missing_lineage.extend(issue.code for issue in metric_result.issues)
    for family in required:
        if not artifact_bindings.get(family):
            missing_lineage.append(f"missing_required_artifact_family:{family}")

    binding_payload = {
        "artifact_bindings": artifact_bindings,
        "metric_id": metric_id,
        "metric_schema_version": metric_schema_version,
        "missing_lineage": sorted(missing_lineage),
        "rejected": rejected,
    }
    return LegalIRMetricLineageBinding(
        binding_id="legal-ir-metric-lineage-" + _stable_hash(binding_payload)[:24],
        metric_schema_version=metric_schema_version,
        metric_id=metric_id,
        compatible=metric_result.reusable and not rejected and not missing_lineage,
        artifact_bindings={
            family: tuple(sorted(set(ids))) for family, ids in artifact_bindings.items()
        },
        rejected_artifacts=tuple(rejected),
        missing_lineage=tuple(sorted(set(missing_lineage))),
    )


def legal_ir_schema_evolution_manifest() -> dict[str, Any]:
    """Return a deterministic manifest of known versions, migrations, and gates."""

    return LEGAL_IR_SCHEMA_REGISTRY.manifest()


def legal_ir_schema_version_registry() -> LegalIRSchemaRegistry:
    """Return the immutable LegalIR schema version registry."""

    return LEGAL_IR_SCHEMA_REGISTRY


def known_legal_ir_schema_versions() -> tuple[str, ...]:
    """Return all schema versions known to the compatibility gate."""

    return tuple(sorted(LEGAL_IR_SCHEMA_REGISTRY))


def _version(
    schema_version: str,
    family: LegalIRArtifactFamily,
    *,
    required: Sequence[str] = ("schema_version",),
    identity: Sequence[str] = (),
    lineage: Sequence[str] = (),
    compatible_readers: Sequence[str] = (),
    migrations: Sequence[str] = (),
    downgrades: Sequence[str] = (),
    gates: Sequence[str] = (),
    deprecation: LegalIRDeprecationPolicy | None = None,
    description: str = "",
) -> LegalIRSchemaVersion:
    return LegalIRSchemaVersion(
        schema_version=schema_version,
        artifact_family=family,
        required_fields=tuple(required),
        identity_fields=tuple(identity),
        metric_lineage_fields=tuple(lineage),
        compatible_reader_versions=tuple(compatible_readers),
        migration_targets=tuple(migrations),
        downgrade_targets=tuple(downgrades),
        feature_gates=tuple(gates),
        deprecation=deprecation or LegalIRDeprecationPolicy(),
        description=description,
    )


def _gate(
    gate_id: str,
    family: LegalIRArtifactFamily,
    minimum: str,
    description: str,
) -> LegalIRSchemaFeatureGate:
    return LegalIRSchemaFeatureGate(
        gate_id=gate_id,
        artifact_family=family,
        minimum_schema_version=minimum,
        description=description,
    )


def _migrate_leanstral_response_v1_to_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(_canonical_json_value(payload))
    data.setdefault("affected_ir_families", [])
    data.setdefault("abstention_reason", "")
    data.setdefault("confidence", 0.0)
    data.setdefault("counterexample", None)
    data.setdefault("drafted_logic_candidates", [])
    data.setdefault("missing_semantic_rule", "")
    data.setdefault("proof_obligation_ids", [])
    data.setdefault("proposed_compiler_surface", [])
    data.setdefault("witness", None)
    return data


def _downgrade_leanstral_response_v2_to_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(_canonical_json_value(payload))
    for key in (
        "abstention_reason",
        "drafted_logic_candidates",
        "proposed_compiler_surface",
    ):
        data.pop(key, None)
    return data


_FEATURE_GATES: tuple[LegalIRSchemaFeatureGate, ...] = (
    _gate(
        "schema.compatibility.reuse",
        LegalIRArtifactFamily.LEARNED_EXPORT,
        LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
        "Allow stable learned feature exports to be reused by promotion code.",
    ),
    _gate(
        "hammer.receipt.trusted-reuse",
        LegalIRArtifactFamily.HAMMER_RECEIPT,
        LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
        "Allow Hammer reconstruction receipts to contribute trusted proof evidence.",
    ),
    _gate(
        "leanstral.audit.cache-reuse",
        LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        "Allow Leanstral audit responses to be reused from content-addressed caches.",
    ),
    _gate(
        "compiler.output.training-reuse",
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        MODAL_COMPILER_REPAIR_SCHEMA_VERSION,
        "Allow deterministic compiler/decompiler outputs to become training targets.",
    ),
    _gate(
        "metric.lineage.binding",
        LegalIRArtifactFamily.METRIC,
        LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION,
        "Require metrics to bind to schema-compatible upstream artifacts.",
    ),
)

_VERSIONS: tuple[LegalIRSchemaVersion, ...] = (
    _version(
        LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION,
        LegalIRArtifactFamily.VIEW_CONTRACT,
        identity=("contract_id", "view"),
        gates=("schema.compatibility.reuse",),
        description="Canonical LegalIR view contract payload.",
    ),
    _version(
        LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
        LegalIRArtifactFamily.VIEW_CONTRACT,
        identity=("registry_version",),
        description="LegalIR view contract registry manifest.",
    ),
    _version(
        LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEARNED_EXPORT,
        required=("schema_version", "export_id", "stable_features"),
        identity=("export_id",),
        gates=("schema.compatibility.reuse",),
        description="Stable source-free learned feature export.",
    ),
    _version(
        LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEARNED_GUIDANCE,
        required=("schema_version", "guidance_id", "source_export_id"),
        identity=("guidance_id",),
        lineage=("source_export_id",),
        description="Promoted learned guidance record.",
    ),
    _version(
        LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEARNED_GUIDANCE,
        required=("schema_version", "promotion_id", "learned_export_id", "compiler_commit"),
        identity=("promotion_id",),
        lineage=("learned_export_id", "proof_receipt_ids", "compiler_commit"),
        description="Promotion report for learned LegalIR guidance.",
    ),
    _version(
        LEGAL_IR_LEARNED_GUIDANCE_CANARY_SCHEMA_VERSION,
        LegalIRArtifactFamily.METRIC,
        required=("schema_version", "canary_id", "evidence_id", "family_metrics"),
        identity=("evidence_id",),
        lineage=("canary_id",),
        gates=("metric.lineage.binding",),
        description="Fixed-canary LegalIR metric evidence.",
    ),
    _version(
        LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEARNED_GUIDANCE,
        required=("schema_version", "rollback_id", "source_export_id"),
        identity=("rollback_id",),
        lineage=("source_export_id",),
        description="Rollback recipe for promoted learned guidance.",
    ),
    _version(
        HAMMER_GUIDANCE_SCHEMA_VERSION,
        LegalIRArtifactFamily.HAMMER_RECEIPT,
        required=("schema_version", "guidance_id", "obligation_id", "trusted"),
        identity=("guidance_id",),
        gates=("hammer.receipt.trusted-reuse",),
        description="Hammer guidance artifact.",
    ),
    _version(
        LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
        LegalIRArtifactFamily.HAMMER_RECEIPT,
        required=("schema_version", "receipt_id", "obligation_id", "trusted"),
        identity=("receipt_id",),
        gates=("hammer.receipt.trusted-reuse",),
        description="Hammer native reconstruction receipt.",
    ),
    _version(
        LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
        LegalIRArtifactFamily.HAMMER_RECEIPT,
        required=("schema_version", "translation_id", "obligation_id", "artifact_sha256"),
        identity=("translation_id",),
        gates=("hammer.receipt.trusted-reuse",),
        description="Hammer translation record.",
    ),
    _version(
        LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
        LegalIRArtifactFamily.HAMMER_REPORT,
        required=("schema_version", "obligation_count", "trusted_count"),
        identity=("schema_version",),
        description="Batch LegalIR Hammer report.",
    ),
    _version(
        LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        required=("schema_version", "request_id", "cache_key"),
        identity=("request_id", "cache_key"),
        description="Leanstral audit request.",
    ),
    _version(
        LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        required=("schema_version", "request_id", "classification"),
        identity=("request_id",),
        migrations=(LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,),
        deprecation=LegalIRDeprecationPolicy(
            status=LegalIRSchemaStatus.DEPRECATED,
            deprecated_since=LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            replacement_schema_version=LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            downgrade_supported=False,
            reason="v1 lacks explicit abstention and compiler-surface fields.",
        ),
        description="Legacy Leanstral audit response; migration required for reuse.",
    ),
    _version(
        LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        required=("schema_version", "request_id", "classification"),
        identity=("request_id",),
        downgrades=(LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,),
        gates=("leanstral.audit.cache-reuse",),
        description="Current Leanstral audit response.",
    ),
    _version(
        LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        required=("schema_version",),
        identity=("report_id", "schema_version"),
        description="Aggregated Leanstral verified rule-gap report.",
    ),
    _version(
        LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION,
        LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        required=("schema_version",),
        identity=("report_id", "schema_version"),
        description="Leanstral patch feedback report.",
    ),
    _version(
        LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION,
        LegalIRArtifactFamily.CACHE,
        required=("schema_version", "key", "response"),
        identity=("key",),
        gates=("leanstral.audit.cache-reuse",),
        description="Local Leanstral audit cache entry.",
    ),
    _version(
        LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION,
        LegalIRArtifactFamily.CACHE,
        required=("schema_version", "entries"),
        identity=("schema_version",),
        gates=("leanstral.audit.cache-reuse",),
        description="Distributed Leanstral audit artifact cache index.",
    ),
    _version(
        LEGAL_IR_TARGET_DISK_CACHE_VERSION,
        LegalIRArtifactFamily.CACHE,
        required=("schema_version", "entries"),
        identity=("schema_version",),
        description="LegalIR target disk cache.",
    ),
    _version(
        PROOF_CACHE_SCHEMA_VERSION,
        LegalIRArtifactFamily.CACHE,
        required=("schema_version", "entries"),
        identity=("schema_version",),
        description="Persisted proof cache.",
    ),
    _version(
        MODAL_COMPILER_REPAIR_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "provenance_ids"),
        identity=("frame_id", "general_rule_id"),
        gates=("compiler.output.training-reuse",),
        description="Deterministic modal compiler repair output.",
    ),
    _version(
        MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "provenance_ids"),
        identity=("decompiler_repair_id", "document_id", "schema_version"),
        gates=("compiler.output.training-reuse",),
        description="Deterministic modal decompiler repair output.",
    ),
    _version(
        LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
        LegalIRArtifactFamily.SOURCE_MAP,
        required=("schema_version", "source_map_id", "sources", "spans", "nodes"),
        identity=("source_map_id",),
        description="Lossless LegalIR source map with provenance spans and transform graph.",
    ),
    _version(
        LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "repair_id", "target_component"),
        identity=("repair_id",),
        gates=("compiler.output.training-reuse",),
        description="Verified compiler/decompiler gap repair.",
    ),
    _version(
        LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "repair_id", "target_component"),
        identity=("repair_id",),
        gates=("compiler.output.training-reuse",),
        description="Clustered verified gap repair.",
    ),
    _version(
        LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "candidate_id", "target_kind"),
        identity=("candidate_id",),
        gates=("compiler.output.training-reuse",),
        description="Distilled deterministic rule candidate.",
    ),
    _version(
        LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "distillation_id"),
        identity=("distillation_id",),
        gates=("compiler.output.training-reuse",),
        description="Rule distillation report.",
    ),
    _version(
        LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "todo_id"),
        identity=("todo_id",),
        description="Codex TODO projection for distilled LegalIR rules.",
    ),
    _version(
        LEGAL_IR_RULE_DISTILLATION_ROLLBACK_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "rollback_id"),
        identity=("rollback_id",),
        description="Rollback recipe for distilled LegalIR rules.",
    ),
    _version(
        LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "diff_id", "before_digest", "after_digest", "changes"),
        identity=("diff_id",),
        gates=("compiler.output.training-reuse",),
        description="Semantic diff and amendment impact report for LegalIR outputs.",
    ),
    _version(
        LEGAL_IR_SEMANTIC_DIFF_TODO_SCHEMA_VERSION,
        LegalIRArtifactFamily.COMPILER_OUTPUT,
        required=("schema_version", "todo_id", "change_id"),
        identity=("todo_id",),
        description="Codex TODO projection for verified LegalIR semantic diff regressions.",
    ),
    _version(
        LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION,
        LegalIRArtifactFamily.METRIC,
        required=("schema_version",),
        identity=("metric_id", "evidence_id", "schema_version"),
        lineage=("metric_lineage",),
        gates=("metric.lineage.binding",),
        description="Per-family LegalIR metric block.",
    ),
    _version(
        HAMMER_GUIDANCE_METRIC_SCHEMA_VERSION,
        LegalIRArtifactFamily.METRIC,
        required=("schema_version",),
        identity=("metric_id", "schema_version"),
        lineage=("guidance_id", "proof_receipt_ids"),
        gates=("metric.lineage.binding",),
        description="Hammer guidance metric block.",
    ),
    _version(
        LEANSTRAL_METRIC_ATTRIBUTION_SCHEMA_VERSION,
        LegalIRArtifactFamily.METRIC,
        required=("schema_version", "audit_request_ids"),
        identity=("metric_id", "schema_version"),
        lineage=("audit_request_ids",),
        gates=("metric.lineage.binding",),
        description="Leanstral metric attribution block.",
    ),
    _version(
        LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION,
        LegalIRArtifactFamily.METRIC,
        required=("schema_version",),
        identity=("telemetry_id", "sample_id", "schema_version"),
        lineage=("sample_id",),
        description="LegalIR contract telemetry metric payload.",
    ),
    _version(
        LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION,
        LegalIRArtifactFamily.PROOF_FEEDBACK,
        required=("schema_version", "record_id"),
        identity=("record_id",),
        lineage=("receipt_ids",),
        description="Trusted LegalIR proof feedback record.",
    ),
    _version(
        LEGAL_IR_PROOF_FEEDBACK_STORE_VERSION,
        LegalIRArtifactFamily.PROOF_FEEDBACK,
        required=("schema_version", "records"),
        identity=("schema_version",),
        description="Trusted proof feedback store.",
    ),
    _version(
        LEGAL_IR_PROOF_FEEDBACK_REPLAY_VERSION,
        LegalIRArtifactFamily.PROOF_FEEDBACK,
        required=("schema_version",),
        identity=("replay_id", "schema_version"),
        description="Proof feedback replay report.",
    ),
    _version(
        LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
        LegalIRArtifactFamily.HAMMER_RECEIPT,
        required=("schema_version",),
        identity=("route_id", "request_id", "schema_version"),
        description="LegalIR proof router result.",
    ),
)

_MIGRATIONS: tuple[LegalIRSchemaMigration, ...] = (
    LegalIRSchemaMigration(
        source_schema_version=LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
        target_schema_version=LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        migration_id="leanstral-audit-response-v1-to-v2",
        description="Add explicit v2 abstention, proof-obligation, and compiler-surface fields.",
        transform=_migrate_leanstral_response_v1_to_v2,
    ),
    LegalIRSchemaMigration(
        source_schema_version=LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        target_schema_version=LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION,
        migration_id="leanstral-audit-response-v2-to-v1",
        description="Drop v2-only guidance fields for legacy readers.",
        downgrade=True,
        transform=_downgrade_leanstral_response_v2_to_v1,
    ),
)

LEGAL_IR_SCHEMA_REGISTRY: Final = LegalIRSchemaRegistry(
    versions=_VERSIONS,
    migrations=_MIGRATIONS,
    feature_gates=_FEATURE_GATES,
)


def _schema_major(schema_version: str) -> int:
    match = _VERSION_RE.match(str(schema_version or ""))
    return int(match.group("major")) if match else 0


def _artifact_family(value: LegalIRArtifactFamily | str) -> LegalIRArtifactFamily:
    if isinstance(value, LegalIRArtifactFamily):
        return value
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "learned_feature_export": LegalIRArtifactFamily.LEARNED_EXPORT,
        "stable_feature_export": LegalIRArtifactFamily.LEARNED_EXPORT,
        "hammer_guidance": LegalIRArtifactFamily.HAMMER_RECEIPT,
        "hammer_reconstruction_receipt": LegalIRArtifactFamily.HAMMER_RECEIPT,
        "hammer_translation": LegalIRArtifactFamily.HAMMER_RECEIPT,
        "leanstral_response": LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        "leanstral_audit_response": LegalIRArtifactFamily.LEANSTRAL_AUDIT,
        "compiler": LegalIRArtifactFamily.COMPILER_OUTPUT,
        "compiler_repair": LegalIRArtifactFamily.COMPILER_OUTPUT,
        "decompiler_repair": LegalIRArtifactFamily.COMPILER_OUTPUT,
        "metrics": LegalIRArtifactFamily.METRIC,
        "source_map": LegalIRArtifactFamily.SOURCE_MAP,
        "source_maps": LegalIRArtifactFamily.SOURCE_MAP,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return LegalIRArtifactFamily(normalized)
    except ValueError:
        raise KeyError(f"unknown LegalIR artifact family: {value!r}") from None


def _payload_mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        return {"schema_version": value}
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _schema_version(raw: Any, payload: Mapping[str, Any]) -> str:
    if isinstance(raw, str):
        return raw.strip()
    return str(
        payload.get("schema_version")
        or payload.get("schemaVersion")
        or payload.get("version")
        or ""
    ).strip()


def _field_value(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for part in str(path or "").split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return len(value) == 0
    return False


def _artifact_id(payload: Mapping[str, Any]) -> str:
    for field_name in (
        "export_id",
        "guidance_id",
        "receipt_id",
        "translation_id",
        "promotion_id",
        "rollback_id",
        "request_id",
        "cache_key",
        "key",
        "repair_id",
        "candidate_id",
        "distillation_id",
        "todo_id",
        "record_id",
        "metric_id",
        "evidence_id",
        "telemetry_id",
        "frame_id",
        "general_rule_id",
        "document_id",
        "schema_version",
    ):
        value = payload.get(field_name)
        if not _empty(value):
            return str(value)
    return ""


def _lineage_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    lineage = payload.get("metric_lineage") or payload.get("lineage")
    result = dict(lineage) if isinstance(lineage, Mapping) else {}
    for key, value in payload.items():
        if key.endswith("_id") or key.endswith("_ids") or key in {
            "compiler_commit",
            "audit_request_ids",
            "learned_export_id",
            "proof_receipt_ids",
            "receipt_ids",
        }:
            result.setdefault(str(key), value)
    return result


def _lineage_contains(lineage: Mapping[str, Any], artifact_id: str) -> bool:
    if not artifact_id:
        return False
    target = str(artifact_id)
    for value in lineage.values():
        if isinstance(value, str) and value == target:
            return True
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
            if target in {str(item) for item in value}:
                return True
        if isinstance(value, Mapping) and _lineage_contains(value, target):
            return True
    return False


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_canonical_json_value(item) for item in value]
    return value


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical_json_value(value),
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dedupe_issues(
    issues: Sequence[LegalIRSchemaCompatibilityIssue],
) -> tuple[LegalIRSchemaCompatibilityIssue, ...]:
    deduped: dict[tuple[str, str, str], LegalIRSchemaCompatibilityIssue] = {}
    for issue in issues:
        deduped.setdefault((issue.code, issue.field_path, issue.message), issue)
    return tuple(deduped.values())


def _compat_result(
    *,
    artifact_family: LegalIRArtifactFamily | str | None,
    schema_version: str,
    reader_schema_version: str,
    compatibility: LegalIRSchemaCompatibility,
    artifact_id: str = "",
    issues: Sequence[LegalIRSchemaCompatibilityIssue] = (),
) -> LegalIRSchemaCompatibilityResult:
    family = ""
    if artifact_family is not None:
        try:
            family = _artifact_family(artifact_family).value
        except KeyError:
            family = str(artifact_family)
    return LegalIRSchemaCompatibilityResult(
        artifact_family=family,
        artifact_id=artifact_id,
        compatibility=compatibility,
        issues=tuple(issues),
        reader_schema_version=str(reader_schema_version or ""),
        schema_version=schema_version,
    )


__all__ = [
    "LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION",
    "LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION",
    "LEGAL_IR_SCHEMA_REGISTRY",
    "LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION",
    "LEGAL_IR_VIEW_FAMILY_METRIC_SCHEMA_VERSION",
    "HAMMER_GUIDANCE_METRIC_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_RESPONSE_LEGACY_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION",
    "LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION",
    "LEANSTRAL_METRIC_ATTRIBUTION_SCHEMA_VERSION",
    "LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION",
    "LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION",
    "LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION",
    "LEGAL_IR_TARGET_DISK_CACHE_VERSION",
    "MODAL_COMPILER_REPAIR_SCHEMA_VERSION",
    "MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION",
    "PROOF_CACHE_SCHEMA_VERSION",
    "LegalIRArtifactFamily",
    "LegalIRDeprecationPolicy",
    "LegalIRMetricLineageBinding",
    "LegalIRSchemaCompatibility",
    "LegalIRSchemaCompatibilityError",
    "LegalIRSchemaCompatibilityIssue",
    "LegalIRSchemaCompatibilityResult",
    "LegalIRSchemaFeatureGate",
    "LegalIRSchemaMigration",
    "LegalIRSchemaRegistry",
    "LegalIRSchemaStatus",
    "LegalIRSchemaVersion",
    "assert_legal_ir_schema_compatible",
    "bind_legal_ir_metric_lineage",
    "downgrade_legal_ir_schema",
    "known_legal_ir_schema_versions",
    "legal_ir_feature_gate_enabled",
    "legal_ir_schema_evolution_manifest",
    "legal_ir_schema_version_registry",
    "migrate_legal_ir_schema",
    "validate_legal_ir_schema_compatibility",
]
