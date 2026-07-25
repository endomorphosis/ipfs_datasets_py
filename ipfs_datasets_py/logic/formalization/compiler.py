"""Compiler and artifact contracts for deterministic multi-view formalization.

This module defines data and protocol boundaries only.  It invokes no model,
solver, prover, or domain adapter.  Verification attempts are deliberately
absent: a formalization artifact declares formulas and obligations but does not
claim that any obligation has been proved.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    FrozenMap,
    ProofObligation,
)
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticReport,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.provenance import Provenance

from .samples import (
    FormalizationSample,
    FormalizationValidationError,
    _DIGEST_RE,
    _identifier,
    _mapping,
    _reject_unknown,
    _sequence,
    _text,
    _unique_identifiers,
)
from .views import (
    CrossViewLink,
    FormalFormula,
    SymbolTable,
    ViewRegistry,
    validate_view_artifacts,
)


FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION: Final = (
    "formalization-compiler-config/v1"
)
FORMALIZATION_ARTIFACT_SCHEMA_VERSION: Final = "formalization-artifact/v1"
UNSUPPORTED_SEMANTICS_SCHEMA_VERSION: Final = "unsupported-semantics/v1"


class UnsupportedSemanticsPolicy(str, Enum):
    """How a compiler handles semantics it cannot faithfully lower."""

    ERROR = "error"
    PRESERVE_OPAQUE = "preserve_opaque"


@dataclass(frozen=True, slots=True)
class FormalizationCompilerConfig:
    """Immutable configuration whose identity is bound into every artifact."""

    compiler_id: str
    compiler_version: str
    target_view_ids: tuple[str, ...]
    config_id: str = "default"
    producer_id: str = ""
    unsupported_policy: UnsupportedSemanticsPolicy = (
        UnsupportedSemanticsPolicy.PRESERVE_OPAQUE
    )
    options: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "compiler_id", _identifier(self.compiler_id, "compiler_id")
        )
        object.__setattr__(
            self,
            "compiler_version",
            _identifier(self.compiler_version, "compiler_version"),
        )
        object.__setattr__(
            self,
            "target_view_ids",
            _unique_identifiers(self.target_view_ids, "target_view_ids"),
        )
        if not self.target_view_ids:
            raise FormalizationValidationError(
                "target_view_ids must contain at least one view"
            )
        object.__setattr__(self, "config_id", _identifier(self.config_id, "config_id"))
        if self.producer_id:
            object.__setattr__(
                self, "producer_id", _identifier(self.producer_id, "producer_id")
            )
        try:
            policy = (
                self.unsupported_policy
                if isinstance(self.unsupported_policy, UnsupportedSemanticsPolicy)
                else UnsupportedSemanticsPolicy(self.unsupported_policy)
            )
        except (TypeError, ValueError) as exc:
            raise FormalizationValidationError(
                f"unknown unsupported semantics policy: {self.unsupported_policy!r}"
            ) from exc
        object.__setattr__(self, "unsupported_policy", policy)
        object.__setattr__(
            self,
            "options",
            self.options
            if isinstance(self.options, FrozenMap)
            else FrozenMap(_mapping(self.options, "options")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported compiler config schema: {self.schema_version!r}"
            )

    @property
    def strict_unsupported(self) -> bool:
        return self.unsupported_policy is UnsupportedSemanticsPolicy.ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_id": self.compiler_id,
            "compiler_version": self.compiler_version,
            "config_id": self.config_id,
            "options": self.options.to_dict(),
            "producer_id": self.producer_id,
            "schema_version": self.schema_version,
            "target_view_ids": list(self.target_view_ids),
            "unsupported_policy": self.unsupported_policy.value,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-compiler-config",
            schema_version=self.schema_version,
            collection_semantics={"/target_view_ids": "set-like"},
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "FormalizationCompilerConfig":
        value = _mapping(value, "compiler config")
        _reject_unknown(
            value,
            frozenset(
                {
                    "compiler_id",
                    "compiler_version",
                    "config_id",
                    "options",
                    "producer_id",
                    "schema_version",
                    "target_view_ids",
                    "unsupported_policy",
                }
            ),
            "compiler config",
        )
        return cls(
            compiler_id=value.get("compiler_id", ""),
            compiler_version=value.get("compiler_version", ""),
            target_view_ids=tuple(
                _sequence(value.get("target_view_ids", ()), "target_view_ids")
            ),
            config_id=value.get("config_id", "default"),
            producer_id=value.get("producer_id", ""),
            unsupported_policy=value.get(
                "unsupported_policy",
                UnsupportedSemanticsPolicy.PRESERVE_OPAQUE.value,
            ),
            options=FrozenMap(_mapping(value.get("options", {}), "options")),
            schema_version=value.get(
                "schema_version", FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "FormalizationCompilerConfig":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError(
                "compiler config must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "compiler config"))


@dataclass(frozen=True, slots=True)
class UnsupportedSemanticsDiagnostic:
    """Grounded description of semantics that could not be lowered.

    Conversion produces the shared kernel's stable
    ``ir.feature.unsupported`` diagnostic.  Keeping this typed construction
    helper prevents compilers from emitting an ungrounded free-form warning.
    """

    construct_id: str
    reason: str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    view_id: str = ""
    opaque_formula_id: str = ""
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = UNSUPPORTED_SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "construct_id", _identifier(self.construct_id, "construct_id")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(self.source_ref_ids, "source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _unique_identifiers(self.span_ids, "span_ids")
        )
        if not self.source_ref_ids and not self.span_ids:
            raise FormalizationValidationError(
                "unsupported semantics must retain source grounding"
            )
        if self.view_id:
            object.__setattr__(
                self, "view_id", _identifier(self.view_id, "view_id")
            )
        if self.opaque_formula_id:
            object.__setattr__(
                self,
                "opaque_formula_id",
                _identifier(self.opaque_formula_id, "opaque_formula_id"),
            )
        if not isinstance(self.severity, DiagnosticSeverity):
            try:
                object.__setattr__(
                    self, "severity", DiagnosticSeverity(self.severity)
                )
            except (TypeError, ValueError) as exc:
                raise FormalizationValidationError(
                    f"unknown diagnostic severity: {self.severity!r}"
                ) from exc
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != UNSUPPORTED_SEMANTICS_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported unsupported-semantics schema: {self.schema_version!r}"
            )

    def to_diagnostic(self) -> Diagnostic:
        metadata = self.metadata.to_dict()
        metadata.update(
            {
                "construct_id": self.construct_id,
                "opaque_formula_id": self.opaque_formula_id,
                "schema_version": self.schema_version,
                "view_id": self.view_id,
            }
        )
        subject_ids = tuple(
            value
            for value in (self.construct_id, self.opaque_formula_id)
            if value
        )
        result = Diagnostic(
            code=DiagnosticCode.UNSUPPORTED_FEATURE,
            message=self.reason,
            severity=self.severity,
            location=DiagnosticLocation(
                subject_ids=subject_ids,
                source_ref_ids=self.source_ref_ids,
                span_ids=self.span_ids,
            ),
            metadata=metadata,
        )
        result.validate()
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "construct_id": self.construct_id,
            "metadata": self.metadata.to_dict(),
            "opaque_formula_id": self.opaque_formula_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "UnsupportedSemanticsDiagnostic":
        value = _mapping(value, "unsupported semantics")
        _reject_unknown(
            value,
            frozenset(
                {
                    "construct_id",
                    "metadata",
                    "opaque_formula_id",
                    "reason",
                    "schema_version",
                    "severity",
                    "source_ref_ids",
                    "span_ids",
                    "view_id",
                }
            ),
            "unsupported semantics",
        )
        return cls(
            construct_id=value.get("construct_id", ""),
            reason=value.get("reason", ""),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            span_ids=tuple(_sequence(value.get("span_ids", ()), "span_ids")),
            view_id=value.get("view_id", ""),
            opaque_formula_id=value.get("opaque_formula_id", ""),
            severity=value.get("severity", DiagnosticSeverity.ERROR.value),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", UNSUPPORTED_SEMANTICS_SCHEMA_VERSION
            ),
        )


@runtime_checkable
class FormalizationCompiler(Protocol):
    """Structural protocol implemented by deterministic domain compilers."""

    def compile(
        self,
        sample: FormalizationSample,
        config: FormalizationCompilerConfig,
    ) -> "FormalizationArtifact":
        """Compile a grounded sample without invoking proof backends."""


@dataclass(frozen=True, slots=True)
class FormalizationArtifact:
    """Content-addressed output of one deterministic formalization compile."""

    sample_id: str
    domain: str
    declaration_id: str
    declaration_digest: str
    compiler_config: FormalizationCompilerConfig
    view_registry: ViewRegistry
    symbol_table: SymbolTable
    formulas: tuple[FormalFormula, ...]
    cross_view_links: tuple[CrossViewLink, ...]
    assumptions: tuple[Assumption, ...]
    proof_obligations: tuple[ProofObligation, ...]
    source_map: Provenance
    diagnostics: DiagnosticReport
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMALIZATION_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, "sample_id"))
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        if not isinstance(self.declaration_digest, str) or not _DIGEST_RE.fullmatch(
            self.declaration_digest
        ):
            raise FormalizationValidationError(
                "declaration_digest must be a sha256:<hex> digest"
            )
        if not isinstance(self.compiler_config, FormalizationCompilerConfig):
            raise FormalizationValidationError(
                "compiler_config must be a FormalizationCompilerConfig"
            )
        if not isinstance(self.view_registry, ViewRegistry):
            raise FormalizationValidationError(
                "view_registry must be a ViewRegistry"
            )
        if not isinstance(self.symbol_table, SymbolTable):
            raise FormalizationValidationError(
                "symbol_table must be a SymbolTable"
            )
        object.__setattr__(
            self,
            "formulas",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, FormalFormula)
                        else FormalFormula.from_dict(_mapping(item, "formula"))
                        for item in self.formulas
                    ),
                    key=lambda item: item.formula_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "cross_view_links",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, CrossViewLink)
                        else CrossViewLink.from_dict(_mapping(item, "cross-view link"))
                        for item in self.cross_view_links
                    ),
                    key=lambda item: item.link_id,
                )
            ),
        )
        assumptions = tuple(
            item
            if isinstance(item, Assumption)
            else Assumption.from_dict(_mapping(item, "assumption"))
            for item in self.assumptions
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
        )
        obligations = tuple(
            item
            if isinstance(item, ProofObligation)
            else ProofObligation.from_dict(_mapping(item, "proof obligation"))
            for item in self.proof_obligations
        )
        object.__setattr__(
            self,
            "proof_obligations",
            tuple(sorted(obligations, key=lambda item: item.obligation_id)),
        )
        if not isinstance(self.source_map, Provenance):
            raise FormalizationValidationError(
                "source_map must be a shared Provenance instance"
            )
        object.__setattr__(
            self,
            "source_map",
            Provenance.from_dict(self.source_map.to_dict()),
        )
        if not isinstance(self.diagnostics, DiagnosticReport):
            raise FormalizationValidationError(
                "diagnostics must be a shared DiagnosticReport"
            )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        self.validate()

    @classmethod
    def from_sample(
        cls,
        sample: FormalizationSample,
        *,
        compiler_config: FormalizationCompilerConfig,
        view_registry: ViewRegistry,
        symbol_table: SymbolTable,
        formulas: Sequence[FormalFormula],
        cross_view_links: Sequence[CrossViewLink] = (),
        proof_obligations: Sequence[ProofObligation] = (),
        source_map: Provenance | None = None,
        diagnostics: DiagnosticReport,
        assumptions: Sequence[Assumption] | None = None,
        metadata: Mapping[str, Any] | FrozenMap = FrozenMap(),
    ) -> "FormalizationArtifact":
        """Construct an artifact while preserving the sample declaration binding."""

        return cls(
            sample_id=sample.sample_id,
            domain=sample.domain,
            declaration_id=sample.declaration_id,
            declaration_digest=sample.declaration_digest,
            compiler_config=compiler_config,
            view_registry=view_registry,
            symbol_table=symbol_table,
            formulas=tuple(formulas),
            cross_view_links=tuple(cross_view_links),
            assumptions=tuple(
                sample.assumptions if assumptions is None else assumptions
            ),
            proof_obligations=tuple(proof_obligations),
            source_map=source_map or sample.provenance,
            diagnostics=diagnostics,
            metadata=metadata
            if isinstance(metadata, FrozenMap)
            else FrozenMap(metadata),
        )

    def validate(self) -> "FormalizationArtifact":
        if self.schema_version != FORMALIZATION_ARTIFACT_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported formalization artifact schema: {self.schema_version!r}"
            )
        try:
            self.source_map.validate()
        except ValueError as exc:
            raise FormalizationValidationError(str(exc)) from exc
        missing_targets = set(self.compiler_config.target_view_ids) - set(
            self.view_registry.view_ids
        )
        if missing_targets:
            raise FormalizationValidationError(
                "compiler targets unregistered views: "
                + ", ".join(sorted(missing_targets))
            )
        emitted_views = {item.view_id for item in self.formulas}
        unexpected_views = emitted_views - set(self.compiler_config.target_view_ids)
        if unexpected_views:
            raise FormalizationValidationError(
                "formulas emitted for untargeted views: "
                + ", ".join(sorted(unexpected_views))
            )

        assumption_ids = [item.assumption_id for item in self.assumptions]
        if len(assumption_ids) != len(set(assumption_ids)):
            raise FormalizationValidationError("assumption IDs must be unique")
        obligation_ids = [item.obligation_id for item in self.proof_obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise FormalizationValidationError("proof obligation IDs must be unique")
        source_ids = {item.ref_id for item in self.source_map.sources}
        spans = {item.span_id: item for item in self.source_map.spans}
        validate_view_artifacts(
            registry=self.view_registry,
            symbol_table=self.symbol_table,
            formulas=self.formulas,
            links=self.cross_view_links,
            source_ref_ids=tuple(source_ids),
            span_ids=tuple(spans),
            assumption_ids=tuple(assumption_ids),
        )
        for grounded in (
            *self.symbol_table.symbols,
            *self.formulas,
            *self.cross_view_links,
        ):
            _validate_span_sources(grounded, spans)

        bindings_by_subject = {
            item.subject_id: item for item in self.source_map.bindings
        }
        if (
            self.sample_id not in bindings_by_subject
            and self.declaration_id not in bindings_by_subject
        ):
            raise FormalizationValidationError(
                "source_map must bind the sample_id or declaration_id"
            )
        for formula in self.formulas:
            binding = bindings_by_subject.get(formula.formula_id)
            if binding is None:
                raise FormalizationValidationError(
                    f"source_map has no binding for formula {formula.formula_id!r}"
                )
            if not set(formula.source_ref_ids).issubset(binding.source_ref_ids):
                raise FormalizationValidationError(
                    f"formula {formula.formula_id!r} sources disagree with source_map"
                )
            if not set(formula.span_ids).issubset(binding.span_ids):
                raise FormalizationValidationError(
                    f"formula {formula.formula_id!r} spans disagree with source_map"
                )
            unknown_inputs = set(formula.input_node_ids) - set(bindings_by_subject)
            if unknown_inputs:
                raise FormalizationValidationError(
                    f"formula {formula.formula_id!r} has ungrounded input nodes: "
                    + ", ".join(sorted(unknown_inputs))
                )
            if self.compiler_config.producer_id and (
                binding.producer_id != self.compiler_config.producer_id
                or binding.config_id != self.compiler_config.config_id
            ):
                raise FormalizationValidationError(
                    f"formula {formula.formula_id!r} source-map binding does not "
                    "match the compiler producer/config"
                )

        if self.compiler_config.producer_id:
            producer_ids = {
                item.producer_id for item in self.source_map.producers
            }
            configs = {
                item.config_id: item for item in self.source_map.configs
            }
            if self.compiler_config.producer_id not in producer_ids:
                raise FormalizationValidationError(
                    "source_map does not contain the configured compiler producer"
                )
            config_binding = configs.get(self.compiler_config.config_id)
            if config_binding is None:
                raise FormalizationValidationError(
                    "source_map does not contain the compiler configuration"
                )
            if (
                config_binding.content_sha256
                != self.compiler_config.identity.hexdigest
            ):
                raise FormalizationValidationError(
                    "source_map compiler configuration digest does not match "
                    "compiler_config identity"
                )

        known_assumptions = set(assumption_ids)
        for assumption in self.assumptions:
            if not assumption.source_refs:
                raise FormalizationValidationError(
                    f"assumption {assumption.assumption_id!r} must be source-grounded"
                )
            _require_known_sources(
                assumption.source_refs,
                source_ids,
                f"assumption {assumption.assumption_id}",
            )
        for obligation in self.proof_obligations:
            unknown = set(obligation.assumption_ids) - known_assumptions
            if unknown:
                raise FormalizationValidationError(
                    f"obligation {obligation.obligation_id!r} references unknown "
                    f"assumptions: {', '.join(sorted(unknown))}"
                )
            if not obligation.source_refs:
                raise FormalizationValidationError(
                    f"obligation {obligation.obligation_id!r} must be source-grounded"
                )
            _require_known_sources(
                obligation.source_refs,
                source_ids,
                f"obligation {obligation.obligation_id}",
            )

        try:
            self.diagnostics.validate(provenance=self.source_map)
        except ValueError as exc:
            raise FormalizationValidationError(str(exc)) from exc
        unsupported = self.unsupported_diagnostics
        for diagnostic in unsupported:
            if not diagnostic.location.traceable:
                raise FormalizationValidationError(
                    "unsupported diagnostics must retain source grounding"
                )
        for formula in self.formulas:
            if formula.opaque and not any(
                formula.formula_id in item.location.subject_ids
                for item in unsupported
            ):
                raise FormalizationValidationError(
                    f"opaque formula {formula.formula_id!r} requires a matching "
                    "unsupported diagnostic"
                )
        if not self.formulas and not unsupported:
            raise FormalizationValidationError(
                "an artifact with no formulas must explain unsupported semantics"
            )
        missing_view_outputs = set(self.compiler_config.target_view_ids) - emitted_views
        unexplained_views = {
            view_id
            for view_id in missing_view_outputs
            if not any(item.metadata.get("view_id") == view_id for item in unsupported)
        }
        if unexplained_views:
            raise FormalizationValidationError(
                "target views with no formulas require unsupported diagnostics: "
                + ", ".join(sorted(unexplained_views))
            )
        if (
            self.compiler_config.unsupported_policy
            is UnsupportedSemanticsPolicy.ERROR
            and any(
                item.severity.rank < DiagnosticSeverity.ERROR.rank
                for item in unsupported
            )
        ):
            raise FormalizationValidationError(
                "strict unsupported policy requires error/fatal diagnostics"
            )
        return self

    @property
    def unsupported_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(
            item
            for item in self.diagnostics.diagnostics
            if item.code == DiagnosticCode.UNSUPPORTED_FEATURE.value
        )

    def identity_payload(self) -> dict[str, Any]:
        """Return semantic compile output; no runtime results or self-ID."""

        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "compiler_config": self.compiler_config.to_dict(),
            "compiler_config_identity": self.compiler_config.identity.to_dict(),
            "cross_view_links": [
                item.to_dict() for item in self.cross_view_links
            ],
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "diagnostics": self.diagnostics.to_dict(),
            "domain": self.domain,
            "formulas": [item.to_dict() for item in self.formulas],
            "metadata": self.metadata.to_dict(),
            "proof_obligations": [
                item.to_dict() for item in self.proof_obligations
            ],
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_map": self.source_map.to_dict(),
            "symbol_table": self.symbol_table.to_dict(),
            "view_registry": self.view_registry.to_dict(),
            "view_registry_identity": self.view_registry.identity.to_dict(),
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.identity_payload(),
            domain=f"formalization-artifact:{self.domain}",
            schema_version=self.schema_version,
            collection_semantics={
                "/assumptions": "set-like",
                "/compiler_config/target_view_ids": "set-like",
                "/cross_view_links": "set-like",
                "/diagnostics/diagnostics": "set-like",
                "/formulas": "set-like",
                "/proof_obligations": "set-like",
                "/source_map/bindings": "set-like",
                "/source_map/configs": "set-like",
                "/source_map/producers": "set-like",
                "/source_map/sources": "set-like",
                "/source_map/spans": "set-like",
                "/symbol_table/symbols": "set-like",
                "/view_registry/views": "set-like",
            },
        )

    @property
    def artifact_id(self) -> str:
        return self.identity.cid

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def sha256(self) -> str:
        return self.identity.hexdigest

    def canonical_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    def manifest(self) -> dict[str, Any]:
        result = self.to_dict()
        result["artifact_identity"] = self.identity.to_dict()
        result["artifact_id"] = self.artifact_id
        return result

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationArtifact":
        value = _mapping(value, "formalization artifact")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "compiler_config",
                    "compiler_config_identity",
                    "cross_view_links",
                    "declaration_digest",
                    "declaration_id",
                    "diagnostics",
                    "domain",
                    "formulas",
                    "metadata",
                    "proof_obligations",
                    "sample_id",
                    "schema_version",
                    "source_map",
                    "symbol_table",
                    "view_registry",
                    "view_registry_identity",
                }
            ),
            "formalization artifact",
        )
        result = cls(
            sample_id=value.get("sample_id", ""),
            domain=value.get("domain", ""),
            declaration_id=value.get("declaration_id", ""),
            declaration_digest=value.get("declaration_digest", ""),
            compiler_config=FormalizationCompilerConfig.from_dict(
                _mapping(value.get("compiler_config", {}), "compiler_config")
            ),
            view_registry=ViewRegistry.from_dict(
                _mapping(value.get("view_registry", {}), "view_registry")
            ),
            symbol_table=SymbolTable.from_dict(
                _mapping(value.get("symbol_table", {}), "symbol_table")
            ),
            formulas=tuple(
                FormalFormula.from_dict(_mapping(item, "formula"))
                for item in _sequence(value.get("formulas", ()), "formulas")
            ),
            cross_view_links=tuple(
                CrossViewLink.from_dict(_mapping(item, "cross-view link"))
                for item in _sequence(
                    value.get("cross_view_links", ()), "cross_view_links"
                )
            ),
            assumptions=tuple(
                Assumption.from_dict(_mapping(item, "assumption"))
                for item in _sequence(value.get("assumptions", ()), "assumptions")
            ),
            proof_obligations=tuple(
                ProofObligation.from_dict(_mapping(item, "proof obligation"))
                for item in _sequence(
                    value.get("proof_obligations", ()), "proof_obligations"
                )
            ),
            source_map=Provenance.from_dict(
                _mapping(value.get("source_map", {}), "source_map")
            ),
            diagnostics=DiagnosticReport.from_dict(
                _mapping(value.get("diagnostics", {}), "diagnostics")
            ),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", FORMALIZATION_ARTIFACT_SCHEMA_VERSION
            ),
        )
        _verify_embedded_identity(
            value.get("compiler_config_identity"),
            result.compiler_config.identity,
            "compiler_config_identity",
        )
        _verify_embedded_identity(
            value.get("view_registry_identity"),
            result.view_registry.identity,
            "view_registry_identity",
        )
        return result

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "FormalizationArtifact":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError(
                "formalization artifact must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "formalization artifact"))


def _validate_span_sources(item: Any, spans: Mapping[str, Any]) -> None:
    if not item.span_ids or not item.source_ref_ids:
        return
    mismatched = {
        span_id
        for span_id in item.span_ids
        if spans[span_id].source_ref_id not in item.source_ref_ids
    }
    if mismatched:
        identifier = getattr(
            item,
            "formula_id",
            getattr(item, "symbol_id", getattr(item, "link_id", "item")),
        )
        raise FormalizationValidationError(
            f"{identifier!r} spans belong to unlisted sources: "
            + ", ".join(sorted(mismatched))
        )


def _require_known_sources(
    values: Sequence[str], known: set[str], field_name: str
) -> None:
    unknown = set(values) - known
    if unknown:
        raise FormalizationValidationError(
            f"{field_name} references unknown sources: "
            + ", ".join(sorted(unknown))
        )


def _verify_embedded_identity(
    value: Any, expected: CanonicalIdentity, field_name: str
) -> None:
    if value is None:
        return
    supplied = _mapping(value, field_name)
    expected_value = expected.to_dict()
    if dict(supplied) != expected_value:
        raise FormalizationValidationError(f"{field_name} does not match its payload")


__all__ = [
    "FORMALIZATION_ARTIFACT_SCHEMA_VERSION",
    "FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION",
    "UNSUPPORTED_SEMANTICS_SCHEMA_VERSION",
    "FormalizationArtifact",
    "FormalizationCompiler",
    "FormalizationCompilerConfig",
    "UnsupportedSemanticsDiagnostic",
    "UnsupportedSemanticsPolicy",
]
