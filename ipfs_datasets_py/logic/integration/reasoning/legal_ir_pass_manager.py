"""Verified pass scheduling and replay for LegalIR compiler pipelines.

The pass manager is intentionally a metadata and verification layer.  Concrete
compiler and decompiler passes remain ordinary callables, but every callable is
run behind a deterministic contract: declared inputs and outputs, invalidation
rules, source-map preservation, schema migration declarations, Hammer proof
obligations, and protected-field mutation checks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Final

from .legal_ir_obligations import (
    LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
    LegalIRProofObligation,
)
from .legal_ir_schema_evolution import (
    LegalIRArtifactFamily,
    LegalIRSchemaCompatibility,
    LegalIRSchemaMigration,
    legal_ir_schema_version_registry,
    migrate_legal_ir_schema,
    validate_legal_ir_schema_compatibility,
)
from .legal_ir_source_maps import (
    LegalIRSourceMap,
    LegalIRSourceMapIssue,
    trace_legal_ir_fact,
    validate_legal_ir_source_map,
)


LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION: Final = "legal-ir-pass-manager-v1"
LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION: Final = "legal-ir-pass-replay-v1"

DEFAULT_LEGAL_IR_PROTECTED_FIELD_PATHS: Final[tuple[str, ...]] = (
    "citation",
    "normalized_text",
    "normalized_text_sha256",
    "proof_obligation_ids",
    "provenance",
    "provenance_ids",
    "receipt_ids",
    "schema_version",
    "source_document_id",
    "source_map",
    "source_map_id",
    "source_node_ids",
    "sources",
    "span_ids",
    "spans",
    "trusted",
)


class LegalIRPassKind(str, Enum):
    """Stable pass categories used by compiler/decompiler orchestration."""

    COMPILER = "compiler"
    DECOMPILER = "decompiler"
    VALIDATION = "validation"
    SCHEMA_MIGRATION = "schema_migration"
    HAMMER = "hammer"
    SOURCE_MAP = "source_map"
    DIAGNOSTIC = "diagnostic"
    ANALYSIS = "analysis"


class LegalIRPassDiagnosticSeverity(str, Enum):
    """Severity for pass-manager diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LegalIRPassError(ValueError):
    """Base class for pass-manager contract failures."""


class LegalIRPassValidationError(LegalIRPassError):
    """Raised when pass specifications or pass execution violate contracts."""


@dataclass(frozen=True)
class LegalIRPassDiagnostic:
    """One deterministic pass-manager diagnostic."""

    code: str
    message: str
    severity: str = LegalIRPassDiagnosticSeverity.ERROR.value
    pass_id: str = ""
    field_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def error(self) -> bool:
        return str(self.severity or "").lower() == LegalIRPassDiagnosticSeverity.ERROR.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "metadata": _json_ready(self.metadata),
            "pass_id": self.pass_id,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRPassDiagnostic":
        return cls(
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            severity=str(data.get("severity") or LegalIRPassDiagnosticSeverity.ERROR.value),
            pass_id=str(data.get("pass_id") or ""),
            field_path=str(data.get("field_path") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRProtectedMutationJustification:
    """Proof or diagnostic authorizing a protected-field mutation."""

    field_path: str
    reason: str = ""
    proof_obligation_ids: tuple[str, ...] = ()
    proof_receipt_ids: tuple[str, ...] = ()
    diagnostic_id: str = ""
    diagnostic_code: str = ""
    approved_by: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "proof_obligation_ids", _unique_text(self.proof_obligation_ids))
        object.__setattr__(self, "proof_receipt_ids", _unique_text(self.proof_receipt_ids))

    @property
    def has_proof(self) -> bool:
        return bool(self.proof_obligation_ids or self.proof_receipt_ids)

    @property
    def has_explicit_diagnostic(self) -> bool:
        return bool(self.diagnostic_id or self.diagnostic_code)

    @property
    def authorized(self) -> bool:
        return bool(self.field_path and (self.has_proof or self.has_explicit_diagnostic))

    def covers(self, field_path: str) -> bool:
        return _path_matches(str(field_path or ""), self.field_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_by": self.approved_by,
            "diagnostic_code": self.diagnostic_code,
            "diagnostic_id": self.diagnostic_id,
            "field_path": self.field_path,
            "metadata": _json_ready(self.metadata),
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proof_receipt_ids": list(self.proof_receipt_ids),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "LegalIRProtectedMutationJustification":
        return cls(
            field_path=str(data.get("field_path") or ""),
            reason=str(data.get("reason") or ""),
            proof_obligation_ids=tuple(_strings(data.get("proof_obligation_ids", ()))),
            proof_receipt_ids=tuple(_strings(data.get("proof_receipt_ids", ()))),
            diagnostic_id=str(data.get("diagnostic_id") or ""),
            diagnostic_code=str(data.get("diagnostic_code") or ""),
            approved_by=str(data.get("approved_by") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRInvalidationRule:
    """Cache or downstream-output invalidation caused by a pass output."""

    invalidates: tuple[str, ...]
    when_outputs_change: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "invalidates", _unique_text(self.invalidates))
        object.__setattr__(
            self,
            "when_outputs_change",
            _unique_text(self.when_outputs_change),
        )

    def applies(self, changed_fields: Sequence[str]) -> bool:
        if not self.when_outputs_change:
            return True
        return any(
            _path_matches(changed, watched)
            for changed in changed_fields
            for watched in self.when_outputs_change
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "invalidates": list(self.invalidates),
            "reason": self.reason,
            "when_outputs_change": list(self.when_outputs_change),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRInvalidationRule":
        return cls(
            invalidates=tuple(_strings(data.get("invalidates", ()))),
            when_outputs_change=tuple(_strings(data.get("when_outputs_change", ()))),
            reason=str(data.get("reason") or ""),
        )


@dataclass(frozen=True)
class LegalIRSchemaMigrationSpec:
    """Declared schema migration edge owned by one pass."""

    source_schema_version: str
    target_schema_version: str
    migration_id: str = ""
    artifact_family: str = ""
    required: bool = True

    @property
    def registered(self) -> bool:
        registry = legal_ir_schema_version_registry()
        return registry.migration(self.source_schema_version, self.target_schema_version) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_family": self.artifact_family,
            "migration_id": self.migration_id
            or f"{self.source_schema_version}-to-{self.target_schema_version}",
            "registered": self.registered,
            "required": bool(self.required),
            "source_schema_version": self.source_schema_version,
            "target_schema_version": self.target_schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSchemaMigrationSpec":
        return cls(
            source_schema_version=str(data.get("source_schema_version") or ""),
            target_schema_version=str(data.get("target_schema_version") or ""),
            migration_id=str(data.get("migration_id") or ""),
            artifact_family=str(data.get("artifact_family") or ""),
            required=bool(data.get("required", True)),
        )


@dataclass(frozen=True)
class LegalIRHammerObligationSpec:
    """Pass-owned Hammer obligation declaration."""

    obligation_id: str
    statement: str
    kind: str
    legal_ir_view: str
    logic_family: str
    pass_id: str = ""
    formula_id: str = ""
    sample_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_OBLIGATION_SCHEMA_VERSION

    def to_obligation(self) -> LegalIRProofObligation:
        return LegalIRProofObligation(
            obligation_id=self.obligation_id,
            statement=self.statement,
            kind=self.kind,
            legal_ir_view=self.legal_ir_view,
            logic_family=self.logic_family,
            sample_id=self.sample_id,
            formula_id=self.formula_id,
            metadata={"pass_id": self.pass_id, **dict(self.metadata)},
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_obligation().to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRHammerObligationSpec":
        return cls(
            obligation_id=str(data.get("obligation_id") or ""),
            statement=str(data.get("statement") or ""),
            kind=str(data.get("kind") or ""),
            legal_ir_view=str(data.get("legal_ir_view") or ""),
            logic_family=str(data.get("logic_family") or ""),
            pass_id=str(data.get("pass_id") or _mapping(data.get("metadata")).get("pass_id") or ""),
            formula_id=str(data.get("formula_id") or ""),
            sample_id=str(data.get("sample_id") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_OBLIGATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRPassSpec:
    """Static contract for one LegalIR pass."""

    pass_id: str
    title: str
    kind: LegalIRPassKind | str
    order: int
    declared_inputs: tuple[str, ...] = ()
    declared_outputs: tuple[str, ...] = ()
    invalidation_rules: tuple[LegalIRInvalidationRule, ...] = ()
    preserves_source_map: bool = True
    source_map_inputs: tuple[str, ...] = ()
    source_map_outputs: tuple[str, ...] = ()
    schema_migrations: tuple[LegalIRSchemaMigrationSpec, ...] = ()
    hammer_obligations: tuple[LegalIRHammerObligationSpec, ...] = ()
    protected_fields: tuple[str, ...] = DEFAULT_LEGAL_IR_PROTECTED_FIELD_PATHS
    protected_mutation_justifications: tuple[
        LegalIRProtectedMutationJustification, ...
    ] = ()
    deterministic: bool = True
    depends_on: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _pass_kind(self.kind))
        object.__setattr__(self, "declared_inputs", _unique_text(self.declared_inputs))
        object.__setattr__(self, "declared_outputs", _unique_text(self.declared_outputs))
        object.__setattr__(self, "source_map_inputs", _unique_text(self.source_map_inputs))
        object.__setattr__(self, "source_map_outputs", _unique_text(self.source_map_outputs))
        object.__setattr__(self, "protected_fields", _unique_text(self.protected_fields))
        object.__setattr__(self, "depends_on", _unique_text(self.depends_on))
        object.__setattr__(
            self,
            "invalidation_rules",
            tuple(
                item
                if isinstance(item, LegalIRInvalidationRule)
                else LegalIRInvalidationRule.from_dict(_mapping(item))
                for item in self.invalidation_rules
            ),
        )
        object.__setattr__(
            self,
            "schema_migrations",
            tuple(
                item
                if isinstance(item, LegalIRSchemaMigrationSpec)
                else LegalIRSchemaMigrationSpec.from_dict(_mapping(item))
                for item in self.schema_migrations
            ),
        )
        object.__setattr__(
            self,
            "hammer_obligations",
            tuple(_hammer_obligation_spec(item, pass_id=self.pass_id) for item in self.hammer_obligations),
        )
        object.__setattr__(
            self,
            "protected_mutation_justifications",
            tuple(
                item
                if isinstance(item, LegalIRProtectedMutationJustification)
                else LegalIRProtectedMutationJustification.from_dict(_mapping(item))
                for item in self.protected_mutation_justifications
            ),
        )

    @property
    def protected_declared_outputs(self) -> tuple[str, ...]:
        return tuple(
            output
            for output in self.declared_outputs
            if _is_protected_path(output, self.protected_fields)
        )

    def authorizes_protected_path(self, field_path: str) -> bool:
        return any(
            justification.authorized and justification.covers(field_path)
            for justification in self.protected_mutation_justifications
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_inputs": list(self.declared_inputs),
            "declared_outputs": list(self.declared_outputs),
            "depends_on": list(self.depends_on),
            "deterministic": bool(self.deterministic),
            "hammer_obligations": [
                obligation.to_dict() for obligation in self.hammer_obligations
            ],
            "invalidation_rules": [rule.to_dict() for rule in self.invalidation_rules],
            "kind": self.kind.value,
            "metadata": _json_ready(self.metadata),
            "order": int(self.order),
            "pass_id": self.pass_id,
            "preserves_source_map": bool(self.preserves_source_map),
            "protected_fields": list(self.protected_fields),
            "protected_mutation_justifications": [
                item.to_dict() for item in self.protected_mutation_justifications
            ],
            "schema_migrations": [
                migration.to_dict() for migration in self.schema_migrations
            ],
            "source_map_inputs": list(self.source_map_inputs),
            "source_map_outputs": list(self.source_map_outputs),
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRPassSpec":
        return cls(
            pass_id=str(data.get("pass_id") or ""),
            title=str(data.get("title") or data.get("name") or ""),
            kind=_pass_kind(data.get("kind")),
            order=int(data.get("order", 0) or 0),
            declared_inputs=tuple(_strings(data.get("declared_inputs", ()))),
            declared_outputs=tuple(_strings(data.get("declared_outputs", ()))),
            invalidation_rules=tuple(
                LegalIRInvalidationRule.from_dict(_mapping(item))
                for item in _sequence(data.get("invalidation_rules"))
            ),
            preserves_source_map=bool(data.get("preserves_source_map", True)),
            source_map_inputs=tuple(_strings(data.get("source_map_inputs", ()))),
            source_map_outputs=tuple(_strings(data.get("source_map_outputs", ()))),
            schema_migrations=tuple(
                LegalIRSchemaMigrationSpec.from_dict(_mapping(item))
                for item in _sequence(data.get("schema_migrations"))
            ),
            hammer_obligations=tuple(
                LegalIRHammerObligationSpec.from_dict(_mapping(item))
                for item in _sequence(data.get("hammer_obligations"))
            ),
            protected_fields=tuple(
                _strings(
                    data.get(
                        "protected_fields",
                        DEFAULT_LEGAL_IR_PROTECTED_FIELD_PATHS,
                    )
                )
            ),
            protected_mutation_justifications=tuple(
                LegalIRProtectedMutationJustification.from_dict(_mapping(item))
                for item in _sequence(data.get("protected_mutation_justifications"))
            ),
            deterministic=bool(data.get("deterministic", True)),
            depends_on=tuple(_strings(data.get("depends_on", ()))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRPassValidationResult:
    """Validation report for a pass registry."""

    pass_count: int
    diagnostics: tuple[LegalIRPassDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(diagnostic.error for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "pass_count": int(self.pass_count),
            "schema_version": self.schema_version,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRPassExecutionRecord:
    """Deterministic execution record for one pass."""

    pass_id: str
    order: int
    input_digest: str
    output_digest: str
    changed_fields: tuple[str, ...] = ()
    declared_inputs: tuple[str, ...] = ()
    declared_outputs: tuple[str, ...] = ()
    invalidated_paths: tuple[str, ...] = ()
    protected_mutations: tuple[str, ...] = ()
    source_map_preserved: bool = True
    hammer_obligation_ids: tuple[str, ...] = ()
    schema_migration_path: tuple[str, ...] = ()
    diagnostics: tuple[LegalIRPassDiagnostic, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION

    @property
    def successful(self) -> bool:
        return not any(diagnostic.error for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_fields": list(self.changed_fields),
            "declared_inputs": list(self.declared_inputs),
            "declared_outputs": list(self.declared_outputs),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "hammer_obligation_ids": list(self.hammer_obligation_ids),
            "input_digest": self.input_digest,
            "invalidated_paths": list(self.invalidated_paths),
            "metadata": _json_ready(self.metadata),
            "order": int(self.order),
            "output_digest": self.output_digest,
            "pass_id": self.pass_id,
            "protected_mutations": list(self.protected_mutations),
            "schema_migration_path": list(self.schema_migration_path),
            "schema_version": self.schema_version,
            "source_map_preserved": bool(self.source_map_preserved),
            "successful": self.successful,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRPassExecutionRecord":
        return cls(
            pass_id=str(data.get("pass_id") or ""),
            order=int(data.get("order", 0) or 0),
            input_digest=str(data.get("input_digest") or ""),
            output_digest=str(data.get("output_digest") or ""),
            changed_fields=tuple(_strings(data.get("changed_fields", ()))),
            declared_inputs=tuple(_strings(data.get("declared_inputs", ()))),
            declared_outputs=tuple(_strings(data.get("declared_outputs", ()))),
            invalidated_paths=tuple(_strings(data.get("invalidated_paths", ()))),
            protected_mutations=tuple(_strings(data.get("protected_mutations", ()))),
            source_map_preserved=bool(data.get("source_map_preserved", True)),
            hammer_obligation_ids=tuple(_strings(data.get("hammer_obligation_ids", ()))),
            schema_migration_path=tuple(_strings(data.get("schema_migration_path", ()))),
            diagnostics=tuple(
                LegalIRPassDiagnostic.from_dict(_mapping(item))
                for item in _sequence(data.get("diagnostics"))
            ),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRPassRun:
    """Complete deterministic replay record for a pass-manager run."""

    records: tuple[LegalIRPassExecutionRecord, ...]
    initial_digest: str
    final_digest: str
    replay_digest: str
    output_state: Mapping[str, Any]
    diagnostics: tuple[LegalIRPassDiagnostic, ...] = ()
    deterministic_replay: bool = True
    schema_version: str = LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION

    @property
    def successful(self) -> bool:
        return not any(diagnostic.error for diagnostic in self.diagnostics) and all(
            record.successful for record in self.records
        )

    @property
    def pass_ids(self) -> tuple[str, ...]:
        return tuple(record.pass_id for record in self.records)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic_replay": bool(self.deterministic_replay),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "final_digest": self.final_digest,
            "initial_digest": self.initial_digest,
            "output_state": _json_ready(self.output_state),
            "pass_ids": list(self.pass_ids),
            "records": [record.to_dict() for record in self.records],
            "replay_digest": self.replay_digest,
            "schema_version": self.schema_version,
            "successful": self.successful,
        }


PassCallable = Callable[[Mapping[str, Any]], Mapping[str, Any] | Any]


class LegalIRPassManager:
    """Validate, order, run, and replay LegalIR compiler/decompiler passes."""

    def __init__(
        self,
        passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
        *,
        protected_fields: Sequence[str] = DEFAULT_LEGAL_IR_PROTECTED_FIELD_PATHS,
    ) -> None:
        self.protected_fields = _unique_text(protected_fields)
        self._passes = tuple(
            _pass_spec(item, protected_fields=self.protected_fields)
            for item in (passes if passes is not None else default_legal_ir_passes())
        )

    @property
    def passes(self) -> tuple[LegalIRPassSpec, ...]:
        return self._passes

    @property
    def pass_by_id(self) -> Mapping[str, LegalIRPassSpec]:
        return {item.pass_id: item for item in self._passes}

    def ordered_passes(self) -> tuple[LegalIRPassSpec, ...]:
        return tuple(
            sorted(self._passes, key=lambda item: (int(item.order), item.pass_id))
        )

    def manifest(self) -> dict[str, Any]:
        validation = self.validate().to_dict()
        ordered = self.ordered_passes()
        return {
            "deterministic": all(item.deterministic for item in ordered),
            "diagnostics": validation["diagnostics"],
            "ordered_pass_ids": [item.pass_id for item in ordered],
            "passes": [item.to_dict() for item in ordered],
            "protected_fields": list(self.protected_fields),
            "schema_version": LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION,
            "valid": validation["valid"],
        }

    def validate(self) -> LegalIRPassValidationResult:
        diagnostics: list[LegalIRPassDiagnostic] = []
        pass_ids = [item.pass_id for item in self._passes]
        for duplicate in _duplicates(pass_ids):
            diagnostics.append(
                _diagnostic(
                    "duplicate_pass_id",
                    f"Pass id {duplicate!r} is declared more than once.",
                    pass_id=duplicate,
                )
            )
        for item in self._passes:
            diagnostics.extend(self._validate_pass(item))
        by_id = self.pass_by_id
        for item in self._passes:
            for dependency in item.depends_on:
                dep = by_id.get(dependency)
                if dep is None:
                    diagnostics.append(
                        _diagnostic(
                            "pass_dependency_missing",
                            f"Pass {item.pass_id!r} depends on missing pass {dependency!r}.",
                            pass_id=item.pass_id,
                            field_path="depends_on",
                        )
                    )
                elif dep.order >= item.order:
                    diagnostics.append(
                        _diagnostic(
                            "pass_dependency_order_invalid",
                            (
                                f"Dependency {dependency!r} must run before "
                                f"{item.pass_id!r}."
                            ),
                            pass_id=item.pass_id,
                            field_path="depends_on",
                        )
                    )
        return LegalIRPassValidationResult(
            pass_count=len(self._passes),
            diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
        )

    def run(
        self,
        initial_state: Mapping[str, Any],
        pass_functions: Mapping[str, PassCallable] | None = None,
        *,
        fail_fast: bool = True,
    ) -> LegalIRPassRun:
        """Run all ordered passes and return a deterministic replay record."""

        validation = self.validate()
        if not validation.valid:
            raise LegalIRPassValidationError(_format_diagnostics(validation.diagnostics))

        functions = dict(pass_functions or {})
        state: dict[str, Any] = _deepcopy_mapping(initial_state)
        initial_digest = _stable_hash(state)
        records: list[LegalIRPassExecutionRecord] = []
        run_diagnostics: list[LegalIRPassDiagnostic] = []
        for spec in self.ordered_passes():
            before = _deepcopy_mapping(state)
            input_digest = _stable_hash(before)
            function = functions.get(spec.pass_id)
            if function is None:
                after = before
            else:
                produced = function(_deepcopy_mapping(before))
                after = _deepcopy_mapping(_payload_mapping(produced))
            record = self._execution_record(spec, before, after, input_digest)
            records.append(record)
            run_diagnostics.extend(record.diagnostics)
            if fail_fast and any(diagnostic.error for diagnostic in record.diagnostics):
                raise LegalIRPassValidationError(_format_diagnostics(record.diagnostics))
            state = after
        final_digest = _stable_hash(state)
        replay_payload = {
            "final_digest": final_digest,
            "initial_digest": initial_digest,
            "records": [record.to_dict() for record in records],
        }
        return LegalIRPassRun(
            records=tuple(records),
            initial_digest=initial_digest,
            final_digest=final_digest,
            replay_digest=_stable_hash(replay_payload),
            output_state=_json_ready(state),
            diagnostics=tuple(_dedupe_diagnostics(run_diagnostics)),
            deterministic_replay=all(spec.deterministic for spec in self._passes),
        )

    def replay(
        self,
        initial_state: Mapping[str, Any],
        expected: LegalIRPassRun | Mapping[str, Any],
        pass_functions: Mapping[str, PassCallable] | None = None,
    ) -> LegalIRPassRun:
        """Re-run a pass pipeline and reject nondeterministic replay."""

        expected_payload = expected.to_dict() if isinstance(expected, LegalIRPassRun) else dict(expected)
        actual = self.run(initial_state, pass_functions, fail_fast=True)
        expected_digest = str(expected_payload.get("replay_digest") or "")
        if expected_digest and actual.replay_digest != expected_digest:
            raise LegalIRPassValidationError(
                (
                    "LegalIR pass replay digest mismatch: "
                    f"expected {expected_digest}, got {actual.replay_digest}"
                )
            )
        return actual

    def _validate_pass(self, spec: LegalIRPassSpec) -> tuple[LegalIRPassDiagnostic, ...]:
        diagnostics: list[LegalIRPassDiagnostic] = []
        if not spec.pass_id:
            diagnostics.append(_diagnostic("pass_id_missing", "Pass has no id."))
        if not spec.title:
            diagnostics.append(
                _diagnostic(
                    "pass_title_missing",
                    "Pass has no title.",
                    pass_id=spec.pass_id,
                    field_path="title",
                )
            )
        if not spec.declared_outputs:
            diagnostics.append(
                _diagnostic(
                    "pass_outputs_missing",
                    "Pass declares no outputs.",
                    pass_id=spec.pass_id,
                    field_path="declared_outputs",
                )
            )
        for output in spec.protected_declared_outputs:
            if not spec.authorizes_protected_path(output):
                diagnostics.append(
                    _diagnostic(
                        "protected_output_requires_proof_or_diagnostic",
                        (
                            f"Pass {spec.pass_id!r} declares protected output "
                            f"{output!r} without proof or explicit diagnostic."
                        ),
                        pass_id=spec.pass_id,
                        field_path=output,
                    )
                )
        for migration in spec.schema_migrations:
            if not migration.source_schema_version or not migration.target_schema_version:
                diagnostics.append(
                    _diagnostic(
                        "schema_migration_endpoint_missing",
                        "Schema migration must declare source and target versions.",
                        pass_id=spec.pass_id,
                        field_path="schema_migrations",
                    )
                )
            elif migration.required and not migration.registered:
                diagnostics.append(
                    _diagnostic(
                        "schema_migration_not_registered",
                        (
                            f"Schema migration {migration.source_schema_version!r} "
                            f"to {migration.target_schema_version!r} is not registered."
                        ),
                        pass_id=spec.pass_id,
                        field_path="schema_migrations",
                    )
                )
        for obligation in spec.hammer_obligations:
            if not obligation.obligation_id or not obligation.statement:
                diagnostics.append(
                    _diagnostic(
                        "hammer_obligation_incomplete",
                        "Hammer obligation declarations require id and statement.",
                        pass_id=spec.pass_id,
                        field_path="hammer_obligations",
                    )
                )
        for justification in spec.protected_mutation_justifications:
            if not justification.authorized:
                diagnostics.append(
                    _diagnostic(
                        "protected_mutation_justification_incomplete",
                        "Protected mutation justification must carry proof evidence or a diagnostic id/code.",
                        pass_id=spec.pass_id,
                        field_path=justification.field_path,
                    )
                )
        return tuple(diagnostics)

    def _execution_record(
        self,
        spec: LegalIRPassSpec,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        input_digest: str,
    ) -> LegalIRPassExecutionRecord:
        changed = _changed_fields(before, after)
        invalidated = tuple(
            _unique(
                path
                for rule in spec.invalidation_rules
                if rule.applies(changed)
                for path in rule.invalidates
            )
        )
        protected = tuple(
            path for path in changed if _is_protected_path(path, spec.protected_fields)
        )
        diagnostics: list[LegalIRPassDiagnostic] = []
        for path in protected:
            if not spec.authorizes_protected_path(path) and not _state_has_explicit_diagnostic(after, spec.pass_id, path):
                diagnostics.append(
                    _diagnostic(
                        "protected_field_mutation_rejected",
                        (
                            f"Pass {spec.pass_id!r} mutated protected field "
                            f"{path!r} without proof or explicit diagnostic."
                        ),
                        pass_id=spec.pass_id,
                        field_path=path,
                    )
                )
        undeclared = tuple(
            path
            for path in changed
            if not any(_path_matches(path, output) for output in spec.declared_outputs)
        )
        for path in undeclared:
            diagnostics.append(
                _diagnostic(
                    "undeclared_output_mutation",
                    (
                        f"Pass {spec.pass_id!r} changed {path!r}, which is not "
                        "covered by declared_outputs."
                    ),
                    pass_id=spec.pass_id,
                    field_path=path,
                    severity=LegalIRPassDiagnosticSeverity.WARNING.value,
                )
            )
        source_map_preserved, source_map_diagnostics = _check_source_map_preservation(
            spec,
            before,
            after,
        )
        diagnostics.extend(source_map_diagnostics)
        diagnostics.extend(_check_schema_migrations(spec, before, after))
        output_digest = _stable_hash(after)
        return LegalIRPassExecutionRecord(
            pass_id=spec.pass_id,
            order=spec.order,
            input_digest=input_digest,
            output_digest=output_digest,
            changed_fields=tuple(changed),
            declared_inputs=spec.declared_inputs,
            declared_outputs=spec.declared_outputs,
            invalidated_paths=invalidated,
            protected_mutations=protected,
            source_map_preserved=source_map_preserved,
            hammer_obligation_ids=tuple(
                obligation.obligation_id for obligation in spec.hammer_obligations
            ),
            schema_migration_path=tuple(
                item
                for migration in spec.schema_migrations
                for item in (
                    migration.source_schema_version,
                    migration.target_schema_version,
                )
            ),
            diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
        )


def default_legal_ir_passes() -> tuple[LegalIRPassSpec, ...]:
    """Return the canonical ordered LegalIR compiler/decompiler pass list."""

    schema_migration_justification = LegalIRProtectedMutationJustification(
        field_path="schema_version",
        diagnostic_code="schema_migration_declared",
        reason="Schema migrations are explicit pass-manager transitions.",
    )
    source_map_justification = LegalIRProtectedMutationJustification(
        field_path="source_map",
        proof_obligation_ids=("lir-pass-source-map-preservation",),
        reason="Source-map construction and preservation are Hammer-checked.",
    )
    obligations_justification = LegalIRProtectedMutationJustification(
        field_path="proof_obligation_ids",
        proof_obligation_ids=("lir-pass-hammer-obligation-coverage",),
        reason="Obligation extraction is checked by Hammer coverage gates.",
    )
    return (
        LegalIRPassSpec(
            pass_id="legal_ir.source_ingest",
            title="Normalize sources and seed provenance",
            kind=LegalIRPassKind.COMPILER,
            order=10,
            declared_inputs=("raw_document",),
            declared_outputs=("normalized_document", "source_map"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("parsed_formulas", "proof_obligations", "decompiled_text"),
                    when_outputs_change=("normalized_document", "source_map"),
                    reason="Changing normalized input invalidates all derived compiler views.",
                ),
            ),
            source_map_outputs=("source_map",),
            protected_mutation_justifications=(source_map_justification,),
            metadata={"phase": "compiler_frontend"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.schema_migration",
            title="Apply explicit schema migrations",
            kind=LegalIRPassKind.SCHEMA_MIGRATION,
            order=20,
            declared_inputs=("normalized_document", "schema_version"),
            declared_outputs=("schema_version", "schema_migration_log"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("compatibility_cache", "training_exports"),
                    when_outputs_change=("schema_version",),
                    reason="Schema changes invalidate compatibility and training reuse decisions.",
                ),
            ),
            schema_migrations=(
                LegalIRSchemaMigrationSpec(
                    source_schema_version="legal-ir-leanstral-audit-response-v1",
                    target_schema_version="legal-ir-leanstral-audit-response-v2",
                    migration_id="leanstral-audit-response-v1-to-v2",
                    artifact_family=LegalIRArtifactFamily.LEANSTRAL_AUDIT.value,
                    required=True,
                ),
            ),
            protected_mutation_justifications=(schema_migration_justification,),
            metadata={"phase": "schema_evolution"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.citation_linking",
            title="Resolve citation references",
            kind=LegalIRPassKind.COMPILER,
            order=30,
            declared_inputs=("normalized_document", "source_map"),
            declared_outputs=("citation_graph", "citation_ids", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("authority_graph", "proof_obligations"),
                    when_outputs_change=("citation_graph", "citation_ids"),
                    reason="Citation changes affect authority and proof scopes.",
                ),
            ),
            metadata={"phase": "legal_reference_resolution"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.symbol_resolution",
            title="Resolve LegalIR symbols and scopes",
            kind=LegalIRPassKind.COMPILER,
            order=40,
            declared_inputs=("normalized_document", "citation_graph", "source_map"),
            declared_outputs=("symbol_table", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("lowered_views", "proof_obligations"),
                    when_outputs_change=("symbol_table",),
                    reason="Symbol changes affect all lowered logic views.",
                ),
            ),
            metadata={"phase": "semantic_binding"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.temporal_authority",
            title="Bind authority and temporal applicability",
            kind=LegalIRPassKind.COMPILER,
            order=50,
            declared_inputs=("citation_graph", "symbol_table", "source_map"),
            declared_outputs=("authority_graph", "temporal_context", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("proof_obligations", "hammer_routes"),
                    when_outputs_change=("authority_graph", "temporal_context"),
                    reason="Authority and time windows scope deontic conclusions.",
                ),
            ),
            hammer_obligations=(
                LegalIRHammerObligationSpec(
                    obligation_id="lir-pass-temporal-authority-scoped",
                    statement="legal_ir_conclusions_are_time_and_authority_scoped",
                    kind="temporal_authority_pass_invariant",
                    legal_ir_view="TDFOL.prover",
                    logic_family="temporal",
                    pass_id="legal_ir.temporal_authority",
                    metadata={"coverage_scope": "temporal"},
                ),
            ),
            metadata={"phase": "temporal_authority"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.ambiguity",
            title="Represent unresolved ambiguity as first-class IR",
            kind=LegalIRPassKind.COMPILER,
            order=60,
            declared_inputs=("normalized_document", "symbol_table", "source_map"),
            declared_outputs=("ambiguities", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("proof_obligations", "learned_targets"),
                    when_outputs_change=("ambiguities",),
                    reason="Ambiguity cannot be collapsed into proof or learned targets.",
                ),
            ),
            protected_mutation_justifications=(
                LegalIRProtectedMutationJustification(
                    field_path="ambiguities",
                    diagnostic_code="ambiguity_ir_declared",
                    reason="Ambiguity records are explicit diagnostics or typed IR values.",
                ),
            ),
            metadata={"phase": "ambiguity"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.lower_views",
            title="Lower canonical IR into logic views",
            kind=LegalIRPassKind.COMPILER,
            order=70,
            declared_inputs=(
                "normalized_document",
                "symbol_table",
                "authority_graph",
                "ambiguities",
                "source_map",
            ),
            declared_outputs=("lowered_views", "view_contracts", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("proof_obligations", "decompiled_text"),
                    when_outputs_change=("lowered_views",),
                    reason="Lowered views drive Hammer targets and decompiler output.",
                ),
            ),
            hammer_obligations=(
                LegalIRHammerObligationSpec(
                    obligation_id="lir-pass-cross-view-preservation",
                    statement="legal_ir_lowered_views_preserve_canonical_semantics",
                    kind="cross_view_pass_invariant",
                    legal_ir_view="modal.frame_logic",
                    logic_family="modal",
                    pass_id="legal_ir.lower_views",
                    metadata={"coverage_scope": "cross_view_consistency"},
                ),
            ),
            metadata={"phase": "view_lowering"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.hammer_obligations",
            title="Extract Hammer obligations",
            kind=LegalIRPassKind.HAMMER,
            order=80,
            declared_inputs=("lowered_views", "view_contracts", "source_map"),
            declared_outputs=("proof_obligations", "proof_obligation_ids", "hammer_obligation_manifest"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("hammer_receipts", "coverage_report"),
                    when_outputs_change=("proof_obligations",),
                    reason="Proof target changes invalidate existing Hammer results.",
                ),
            ),
            hammer_obligations=(
                LegalIRHammerObligationSpec(
                    obligation_id="lir-pass-hammer-obligation-coverage",
                    statement="legal_ir_passes_emit_all_required_hammer_obligations",
                    kind="hammer_obligation_coverage",
                    legal_ir_view="external_provers.router",
                    logic_family="meta",
                    pass_id="legal_ir.hammer_obligations",
                    metadata={"coverage_scope": "round_trip"},
                ),
            ),
            protected_mutation_justifications=(obligations_justification,),
            metadata={"phase": "hammer"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.hammer_verify",
            title="Verify pass and view obligations",
            kind=LegalIRPassKind.HAMMER,
            order=90,
            declared_inputs=("proof_obligations", "lowered_views"),
            declared_outputs=("hammer_receipts", "coverage_report", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("learned_targets", "promotion_evidence"),
                    when_outputs_change=("hammer_receipts", "coverage_report"),
                    reason="Trusted proof evidence gates learned reuse and promotion.",
                ),
            ),
            metadata={"phase": "hammer"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.decompile",
            title="Decompile checked views to surface forms",
            kind=LegalIRPassKind.DECOMPILER,
            order=100,
            declared_inputs=("lowered_views", "source_map", "hammer_receipts"),
            declared_outputs=("decompiled_text", "decompiler_map", "diagnostics"),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("round_trip_report",),
                    when_outputs_change=("decompiled_text", "decompiler_map"),
                    reason="Decompiler output changes require round-trip checks.",
                ),
            ),
            hammer_obligations=(
                LegalIRHammerObligationSpec(
                    obligation_id="lir-pass-decompiler-source-map-preservation",
                    statement="legal_ir_decompiler_preserves_source_map_attribution",
                    kind="decompiler_source_map_preservation",
                    legal_ir_view="modal.decompiler",
                    logic_family="modal",
                    pass_id="legal_ir.decompile",
                    metadata={"coverage_scope": "round_trip"},
                ),
            ),
            metadata={"phase": "decompiler"},
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.source_map_validate",
            title="Validate source-map preservation",
            kind=LegalIRPassKind.VALIDATION,
            order=110,
            declared_inputs=("source_map", "decompiler_map", "hammer_receipts"),
            declared_outputs=("source_map_validation", "diagnostics"),
            hammer_obligations=(
                LegalIRHammerObligationSpec(
                    obligation_id="lir-pass-source-map-preservation",
                    statement="legal_ir_pass_pipeline_preserves_source_map_traceability",
                    kind="source_map_preservation",
                    legal_ir_view="source_map",
                    logic_family="meta",
                    pass_id="legal_ir.source_map_validate",
                    metadata={"coverage_scope": "provenance"},
                ),
            ),
            metadata={"phase": "validation"},
        ),
    )


def validate_legal_ir_passes(
    passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
) -> LegalIRPassValidationResult:
    """Validate pass specifications without running pass code."""

    return LegalIRPassManager(passes).validate()


def assert_legal_ir_passes_valid(
    passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
) -> LegalIRPassValidationResult:
    """Validate pass specifications and raise on any error diagnostic."""

    result = validate_legal_ir_passes(passes)
    if not result.valid:
        raise LegalIRPassValidationError(_format_diagnostics(result.diagnostics))
    return result


def legal_ir_pass_manager_manifest(
    passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a serializable manifest for a LegalIR pass pipeline."""

    return LegalIRPassManager(passes).manifest()


def run_legal_ir_passes(
    initial_state: Mapping[str, Any],
    pass_functions: Mapping[str, PassCallable] | None = None,
    *,
    passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
    fail_fast: bool = True,
) -> LegalIRPassRun:
    """Run a LegalIR pass pipeline with deterministic replay recording."""

    return LegalIRPassManager(passes).run(
        initial_state,
        pass_functions,
        fail_fast=fail_fast,
    )


def replay_legal_ir_passes(
    initial_state: Mapping[str, Any],
    expected: LegalIRPassRun | Mapping[str, Any],
    pass_functions: Mapping[str, PassCallable] | None = None,
    *,
    passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
) -> LegalIRPassRun:
    """Replay a LegalIR pass pipeline and reject digest drift."""

    return LegalIRPassManager(passes).replay(initial_state, expected, pass_functions)


def apply_declared_schema_migration(
    payload: Mapping[str, Any],
    migration: LegalIRSchemaMigrationSpec | Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a declared schema migration through the shared schema registry."""

    spec = (
        migration
        if isinstance(migration, LegalIRSchemaMigrationSpec)
        else LegalIRSchemaMigrationSpec.from_dict(_mapping(migration))
    )
    return migrate_legal_ir_schema(payload, spec.target_schema_version)


def _check_source_map_preservation(
    spec: LegalIRPassSpec,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[bool, tuple[LegalIRPassDiagnostic, ...]]:
    before_map = before.get("source_map")
    after_map = after.get("source_map")
    diagnostics: list[LegalIRPassDiagnostic] = []
    if before_map is None:
        return True, ()
    if after_map is None:
        diagnostics.append(
            _diagnostic(
                "source_map_dropped",
                f"Pass {spec.pass_id!r} dropped the source_map.",
                pass_id=spec.pass_id,
                field_path="source_map",
            )
        )
        return False, tuple(diagnostics)
    validation = validate_legal_ir_source_map(after_map)
    if not validation.valid:
        diagnostics.extend(
            _diagnostic(
                "source_map_invalid_after_pass",
                issue.message,
                pass_id=spec.pass_id,
                field_path=issue.field_path,
            )
            for issue in validation.issues
            if issue.severity == "error"
        )
    if spec.preserves_source_map:
        before_node_ids = _source_map_node_ids(before_map)
        for node_id in before_node_ids:
            trace = trace_legal_ir_fact(after_map, node_id)
            if not trace.traceable:
                diagnostics.append(
                    _diagnostic(
                        "source_map_traceability_lost",
                        f"Pass {spec.pass_id!r} lost traceability for {node_id!r}.",
                        pass_id=spec.pass_id,
                        field_path=f"source_map.nodes.{node_id}",
                    )
                )
    return not any(diagnostic.error for diagnostic in diagnostics), tuple(diagnostics)


def _check_schema_migrations(
    spec: LegalIRPassSpec,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[LegalIRPassDiagnostic, ...]:
    if not spec.schema_migrations:
        return ()
    diagnostics: list[LegalIRPassDiagnostic] = []
    before_schema = str(before.get("schema_version") or "")
    after_schema = str(after.get("schema_version") or "")
    for migration in spec.schema_migrations:
        if before_schema == migration.source_schema_version and after_schema == migration.target_schema_version:
            compatibility = validate_legal_ir_schema_compatibility(
                after,
                artifact_family=migration.artifact_family or None,
                reader_schema_version=migration.target_schema_version,
            )
            if compatibility.compatibility is LegalIRSchemaCompatibility.INCOMPATIBLE:
                diagnostics.append(
                    _diagnostic(
                        "schema_migration_output_incompatible",
                        (
                            f"Output for migration {migration.source_schema_version!r} "
                            f"to {migration.target_schema_version!r} is incompatible."
                        ),
                        pass_id=spec.pass_id,
                        field_path="schema_version",
                        metadata={"issues": [issue.to_dict() for issue in compatibility.issues]},
                    )
                )
            return tuple(diagnostics)
    if before_schema and after_schema and before_schema != after_schema:
        diagnostics.append(
            _diagnostic(
                "undeclared_schema_migration",
                (
                    f"Pass {spec.pass_id!r} changed schema_version from "
                    f"{before_schema!r} to {after_schema!r} without a declared migration."
                ),
                pass_id=spec.pass_id,
                field_path="schema_version",
            )
        )
    return tuple(diagnostics)


def _source_map_node_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, LegalIRSourceMap):
        return tuple(node.node_id for node in value.nodes)
    payload = _mapping(value)
    return tuple(str(_mapping(node).get("node_id") or "") for node in _sequence(payload.get("nodes")) if str(_mapping(node).get("node_id") or ""))


def _state_has_explicit_diagnostic(
    state: Mapping[str, Any],
    pass_id: str,
    field_path: str,
) -> bool:
    for item in _sequence(state.get("diagnostics")):
        diagnostic = _mapping(item)
        if not diagnostic:
            continue
        if str(diagnostic.get("severity") or "error").lower() not in {"error", "warning", "info"}:
            continue
        diag_pass = str(diagnostic.get("pass_id") or diagnostic.get("source_pass_id") or "")
        diag_field = str(diagnostic.get("field_path") or diagnostic.get("target_field") or "")
        code = str(diagnostic.get("code") or diagnostic.get("diagnostic_type") or "")
        if code and (not diag_pass or diag_pass == pass_id) and (
            not diag_field or _path_matches(field_path, diag_field)
        ):
            return True
    return False


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[str, ...]:
    left = _flatten(_json_ready(before))
    right = _flatten(_json_ready(after))
    changed = [
        path
        for path in sorted(set(left) | set(right))
        if left.get(path) != right.get(path)
    ]
    return tuple(_collapse_changed_paths(changed))


def _collapse_changed_paths(paths: Sequence[str]) -> tuple[str, ...]:
    collapsed: list[str] = []
    for path in sorted(paths):
        root = _protected_root(path)
        candidate = root or path
        if candidate not in collapsed:
            collapsed.append(candidate)
    return tuple(collapsed)


def _protected_root(path: str) -> str:
    for protected in DEFAULT_LEGAL_IR_PROTECTED_FIELD_PATHS:
        if _path_matches(path, protected):
            return protected
    return ""


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        if not value:
            return {prefix: {}} if prefix else {}
        items: dict[str, Any] = {}
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            items.update(_flatten(child, child_prefix))
        return items
    if isinstance(value, list):
        if not value:
            return {prefix: []}
        items = {}
        for index, child in enumerate(value):
            items.update(_flatten(child, f"{prefix}.{index}" if prefix else str(index)))
        return items
    return {prefix: value}


def _is_protected_path(path: str, protected_fields: Sequence[str]) -> bool:
    return any(_path_matches(path, protected) for protected in protected_fields)


def _path_matches(path: str, pattern: str) -> bool:
    path = str(path or "")
    pattern = str(pattern or "")
    if not path or not pattern:
        return False
    if pattern == "*":
        return True
    if path == pattern or path.startswith(pattern + "."):
        return True
    path_parts = path.split(".")
    pattern_parts = pattern.split(".")
    if len(pattern_parts) > len(path_parts):
        return False
    for actual, expected in zip(path_parts, pattern_parts):
        if expected == "*":
            continue
        if actual != expected:
            return False
    return True


def _pass_spec(
    value: LegalIRPassSpec | Mapping[str, Any],
    *,
    protected_fields: Sequence[str],
) -> LegalIRPassSpec:
    if isinstance(value, LegalIRPassSpec):
        if value.protected_fields == tuple(protected_fields):
            return value
        return replace(value, protected_fields=tuple(protected_fields))
    data = dict(value)
    data.setdefault("protected_fields", tuple(protected_fields))
    return LegalIRPassSpec.from_dict(data)


def _hammer_obligation_spec(
    value: LegalIRHammerObligationSpec | LegalIRProofObligation | Mapping[str, Any],
    *,
    pass_id: str,
) -> LegalIRHammerObligationSpec:
    if isinstance(value, LegalIRHammerObligationSpec):
        if value.pass_id:
            return value
        return replace(value, pass_id=pass_id)
    if isinstance(value, LegalIRProofObligation):
        data = value.to_dict()
    else:
        data = _mapping(value)
    data.setdefault("pass_id", pass_id)
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault("pass_id", pass_id)
    data["metadata"] = metadata
    return LegalIRHammerObligationSpec.from_dict(data)


def _pass_kind(value: LegalIRPassKind | str | Any) -> LegalIRPassKind:
    if isinstance(value, LegalIRPassKind):
        return value
    try:
        return LegalIRPassKind(str(value or LegalIRPassKind.COMPILER.value))
    except ValueError:
        return LegalIRPassKind.COMPILER


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: str = LegalIRPassDiagnosticSeverity.ERROR.value,
    pass_id: str = "",
    field_path: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRPassDiagnostic:
    return LegalIRPassDiagnostic(
        code=code,
        message=message,
        severity=severity,
        pass_id=pass_id,
        field_path=field_path,
        metadata=dict(metadata or {}),
    )


def _format_diagnostics(diagnostics: Sequence[LegalIRPassDiagnostic]) -> str:
    if not diagnostics:
        return "LegalIR pass validation failed"
    return "; ".join(
        f"{diagnostic.code}:{diagnostic.pass_id or '-'}:{diagnostic.field_path or '-'}"
        for diagnostic in diagnostics
        if diagnostic.error
    ) or "; ".join(diagnostic.code for diagnostic in diagnostics)


def _dedupe_diagnostics(
    diagnostics: Sequence[LegalIRPassDiagnostic],
) -> tuple[LegalIRPassDiagnostic, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[LegalIRPassDiagnostic] = []
    for diagnostic in diagnostics:
        key = (
            diagnostic.code,
            diagnostic.pass_id,
            diagnostic.field_path,
            diagnostic.message,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(diagnostic)
    return tuple(deduped)


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicated: list[str] = []
    for value in values:
        if value in seen and value not in duplicated:
            duplicated.append(value)
        seen.add(value)
    return tuple(duplicated)


def _unique(values: Sequence[Any]) -> tuple[Any, ...]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = _stable_json(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _unique_text(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value) if str(item))


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _payload_mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _deepcopy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(value))


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


__all__ = [
    "DEFAULT_LEGAL_IR_PROTECTED_FIELD_PATHS",
    "LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION",
    "LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION",
    "LegalIRHammerObligationSpec",
    "LegalIRInvalidationRule",
    "LegalIRPassDiagnostic",
    "LegalIRPassDiagnosticSeverity",
    "LegalIRPassError",
    "LegalIRPassExecutionRecord",
    "LegalIRPassKind",
    "LegalIRPassManager",
    "LegalIRPassRun",
    "LegalIRPassSpec",
    "LegalIRPassValidationError",
    "LegalIRPassValidationResult",
    "LegalIRProtectedMutationJustification",
    "LegalIRSchemaMigrationSpec",
    "apply_declared_schema_migration",
    "assert_legal_ir_passes_valid",
    "default_legal_ir_passes",
    "legal_ir_pass_manager_manifest",
    "replay_legal_ir_passes",
    "run_legal_ir_passes",
    "validate_legal_ir_passes",
]
