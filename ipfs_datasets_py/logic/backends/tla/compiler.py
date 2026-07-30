"""Reusable TLA+ translation for state, concurrency, and refinement IR.

``TLABackend@1`` owns deterministic module and configuration generation from
canonical software-verification IR.  It never invokes TLC or Apalache; those
runners live in :mod:`.runners`.

Generated artifacts are:

* source-mapped (every emitted operator/predicate records its IR origin);
* deterministic (stable ordering by identifier, fixed rendering vocabulary);
* loss-aware (concurrency, rely/guarantee, and refinement projections always
  disclose what was dropped, over-approximated, or left as commentary); and
* finite (unbounded domains and fairness/liveness limitations are explicit).

The supervisor-local state-model facade remains intact; this module generalizes
the translation surface without requiring supervisor workflow schemas.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ...ir_core.claims import FrozenMap, stable_digest
from ...software_verification.concurrency import (
    ConcurrencyIR,
    RelyGuaranteeContract,
)
from ...software_verification.refinement import RefinementIR
from ...software_verification.state import (
    Boundedness,
    PredicateRole,
    StateSchema,
    StateTypeKind,
    StateVariable,
)
from ...software_verification.transitions import (
    Action,
    FairnessKind,
    StateTransitionIR,
)
from ...software_verification.translations import (
    ApproximationDirection,
    PreservationKind,
    UnsupportedConstruct,
    UnsupportedHandling,
)

TLA_BACKEND_VERSION: Final = "TLABackend@1"
TLA_COMPILER_VERSION: Final = "tla-compiler/v1"
TLA_ARTIFACT_SCHEMA_VERSION: Final = "tla-generated-artifact/v1"
TLA_SOURCE_MAP_SCHEMA_VERSION: Final = "tla-source-map/v1"
TLA_PROJECTION_LOSS_SCHEMA_VERSION: Final = "tla-projection-loss/v1"
TLA_COMPILE_BOUNDS_SCHEMA_VERSION: Final = "tla-compile-bounds/v1"
TLA_TRANSLATOR_ID: Final = "state-transition-ir-to-tla"

_ID_SAFE = re.compile(r"[^A-Za-z0-9_]")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class TLACompilerError(ValueError):
    """Raised when TLA+ compilation cannot proceed without semantic loss of control."""


class ProjectionKind(StrEnum):
    """Source IR family projected into TLA+."""

    STATE = "state"
    CONCURRENCY = "concurrency"
    RELY_GUARANTEE = "rely_guarantee"
    REFINEMENT = "refinement"


class LossSeverity(StrEnum):
    """How severely a projection approximates or drops source meaning."""

    NONE = "none"
    DISCLOSED = "disclosed"
    OVER_APPROXIMATION = "over_approximation"
    UNDER_APPROXIMATION = "under_approximation"
    OMITTED = "omitted"


@dataclass(frozen=True, slots=True)
class TLACompileBounds:
    """Finite compilation bounds bound into every generated artifact."""

    max_steps: int = 64
    max_variables: int = 64
    max_actions: int = 128
    max_predicates: int = 256
    max_enum_members: int = 64
    max_integer_span: int = 256
    max_module_bytes: int = 1_048_576
    default_integer_lower: int = 0
    default_integer_upper: int = 7
    schema_version: str = TLA_COMPILE_BOUNDS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_steps",
            "max_variables",
            "max_actions",
            "max_predicates",
            "max_enum_members",
            "max_integer_span",
            "max_module_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise TLACompilerError(f"{name} must be a positive integer")
        for name in ("default_integer_lower", "default_integer_upper"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TLACompilerError(f"{name} must be an integer")
        if self.default_integer_upper < self.default_integer_lower:
            raise TLACompilerError("default integer upper bound must be >= lower bound")
        if self.schema_version != TLA_COMPILE_BOUNDS_SCHEMA_VERSION:
            raise TLACompilerError(
                f"unsupported compile bounds schema: {self.schema_version!r}"
            )

    @property
    def label(self) -> str:
        return (
            f"steps<={self.max_steps},vars<={self.max_variables},"
            f"actions<={self.max_actions},int=[{self.default_integer_lower},"
            f"{self.default_integer_upper}]"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_integer_lower": self.default_integer_lower,
            "default_integer_upper": self.default_integer_upper,
            "max_actions": self.max_actions,
            "max_enum_members": self.max_enum_members,
            "max_integer_span": self.max_integer_span,
            "max_module_bytes": self.max_module_bytes,
            "max_predicates": self.max_predicates,
            "max_steps": self.max_steps,
            "max_variables": self.max_variables,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TLACompileBounds:
        if not isinstance(value, Mapping):
            raise TLACompilerError("compile bounds must be a mapping")
        return cls(
            max_steps=int(value.get("max_steps", 64)),
            max_variables=int(value.get("max_variables", 64)),
            max_actions=int(value.get("max_actions", 128)),
            max_predicates=int(value.get("max_predicates", 256)),
            max_enum_members=int(value.get("max_enum_members", 64)),
            max_integer_span=int(value.get("max_integer_span", 256)),
            max_module_bytes=int(value.get("max_module_bytes", 1_048_576)),
            default_integer_lower=int(value.get("default_integer_lower", 0)),
            default_integer_upper=int(value.get("default_integer_upper", 7)),
            schema_version=str(
                value.get("schema_version", TLA_COMPILE_BOUNDS_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class TLASourceMapEntry:
    """One source-mapped emission from IR identifier to TLA symbol."""

    source_id: str
    source_kind: str
    tla_symbol: str
    role: str
    line_hint: str = ""
    schema_version: str = TLA_SOURCE_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "source_kind", _text(self.source_kind, "source_kind"))
        object.__setattr__(self, "tla_symbol", _tla_ident(self.tla_symbol, "tla_symbol"))
        object.__setattr__(self, "role", _text(self.role, "role"))
        object.__setattr__(
            self, "line_hint", _text(self.line_hint, "line_hint", optional=True)
        )
        if self.schema_version != TLA_SOURCE_MAP_SCHEMA_VERSION:
            raise TLACompilerError(
                f"unsupported source-map schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "line_hint": self.line_hint,
            "role": self.role,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "tla_symbol": self.tla_symbol,
        }


@dataclass(frozen=True, slots=True)
class ProjectionLoss:
    """Explicit disclosure of what a projection cannot preserve in TLA+."""

    loss_id: str
    projection: ProjectionKind
    severity: LossSeverity
    construct: str
    statement: str
    handling: UnsupportedHandling = UnsupportedHandling.ABSTRACTED
    preservation: PreservationKind = PreservationKind.BOUNDED
    approximation: ApproximationDirection = ApproximationDirection.OVER
    schema_version: str = TLA_PROJECTION_LOSS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "loss_id", _text(self.loss_id, "loss_id"))
        object.__setattr__(
            self, "projection", _enum(self.projection, ProjectionKind, "projection")
        )
        object.__setattr__(
            self, "severity", _enum(self.severity, LossSeverity, "severity")
        )
        object.__setattr__(self, "construct", _text(self.construct, "construct"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self, "handling", _enum(self.handling, UnsupportedHandling, "handling")
        )
        object.__setattr__(
            self,
            "preservation",
            _enum(self.preservation, PreservationKind, "preservation"),
        )
        object.__setattr__(
            self,
            "approximation",
            _enum(self.approximation, ApproximationDirection, "approximation"),
        )
        if self.schema_version != TLA_PROJECTION_LOSS_SCHEMA_VERSION:
            raise TLACompilerError(
                f"unsupported projection loss schema: {self.schema_version!r}"
            )

    def to_unsupported_construct(self) -> UnsupportedConstruct:
        kind = re.sub(r"[^A-Za-z0-9._:-]+", "_", self.construct).strip("._:-") or "construct"
        construct_id = re.sub(r"[^A-Za-z0-9._:-]+", "_", self.loss_id).strip("._:-") or "loss"
        return UnsupportedConstruct(
            construct_id=construct_id,
            construct_kind=kind,
            description=self.statement,
            handling=self.handling,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approximation": self.approximation.value,
            "construct": self.construct,
            "handling": self.handling.value,
            "loss_id": self.loss_id,
            "preservation": self.preservation.value,
            "projection": self.projection.value,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "statement": self.statement,
        }


@dataclass(frozen=True, slots=True)
class GeneratedTLAArtifacts:
    """Deterministic TLA+ module plus distinct TLC and Apalache configurations."""

    module_name: str
    model_text: str
    tlc_config_text: str
    apalache_config_text: str
    source_map: tuple[TLASourceMapEntry, ...]
    losses: tuple[ProjectionLoss, ...]
    bounds: TLACompileBounds
    source_document_id: str
    source_kind: str
    safety_properties: tuple[str, ...]
    liveness_properties: tuple[str, ...]
    fairness_limitations: tuple[str, ...]
    interface_version: str = TLA_BACKEND_VERSION
    schema_version: str = TLA_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "module_name", _tla_ident(self.module_name, "module_name")
        )
        if not self.model_text.endswith("\n"):
            raise TLACompilerError("model_text must end with a newline")
        if not self.tlc_config_text.endswith("\n"):
            raise TLACompilerError("tlc_config_text must end with a newline")
        if not self.apalache_config_text.endswith("\n"):
            raise TLACompilerError("apalache_config_text must end with a newline")
        object.__setattr__(self, "source_map", tuple(self.source_map))
        object.__setattr__(self, "losses", tuple(self.losses))
        if not isinstance(self.bounds, TLACompileBounds):
            raise TLACompilerError("bounds must be TLACompileBounds")
        object.__setattr__(
            self,
            "source_document_id",
            _text(self.source_document_id, "source_document_id"),
        )
        object.__setattr__(self, "source_kind", _text(self.source_kind, "source_kind"))
        object.__setattr__(
            self,
            "safety_properties",
            tuple(_tla_ident(item, "safety property") for item in self.safety_properties),
        )
        object.__setattr__(
            self,
            "liveness_properties",
            tuple(
                _tla_ident(item, "liveness property") for item in self.liveness_properties
            ),
        )
        object.__setattr__(
            self,
            "fairness_limitations",
            tuple(
                _text(item, "fairness limitation") for item in self.fairness_limitations
            ),
        )
        if self.interface_version != TLA_BACKEND_VERSION:
            raise TLACompilerError(
                f"unsupported TLA backend interface: {self.interface_version!r}"
            )
        if self.schema_version != TLA_ARTIFACT_SCHEMA_VERSION:
            raise TLACompilerError(
                f"unsupported artifact schema: {self.schema_version!r}"
            )
        encoded = self.model_text.encode("utf-8")
        if len(encoded) > self.bounds.max_module_bytes:
            raise TLACompilerError("generated TLA module exceeds max_module_bytes")

    @property
    def model_digest(self) -> str:
        return _sha256_text(self.model_text)

    @property
    def tlc_config_digest(self) -> str:
        return _sha256_text(self.tlc_config_text)

    @property
    def apalache_config_digest(self) -> str:
        return _sha256_text(self.apalache_config_text)

    @property
    def artifact_digest(self) -> str:
        return stable_digest(self.to_dict(include_text=False, include_digest=False))

    @property
    def bounded(self) -> bool:
        return True

    @property
    def unbounded_proof(self) -> bool:
        return False

    def configuration_for(self, tool: str) -> str:
        selected = str(tool).strip().lower()
        if selected in {"tlc", "tlc2"}:
            return self.tlc_config_text
        if selected in {"apalache", "apalache-mc"}:
            return self.apalache_config_text
        raise TLACompilerError(f"unknown model-checker tool: {tool!r}")

    def to_dict(
        self, *, include_text: bool = True, include_digest: bool = True
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "apalache_config_digest": self.apalache_config_digest,
            "bounded": True,
            "bounds": self.bounds.to_dict(),
            "fairness_limitations": list(self.fairness_limitations),
            "interface_version": self.interface_version,
            "liveness_properties": list(self.liveness_properties),
            "losses": [item.to_dict() for item in self.losses],
            "model_digest": self.model_digest,
            "module_name": self.module_name,
            "safety_properties": list(self.safety_properties),
            "schema_version": self.schema_version,
            "source_document_id": self.source_document_id,
            "source_kind": self.source_kind,
            "source_map": [item.to_dict() for item in self.source_map],
            "tlc_config_digest": self.tlc_config_digest,
            "translator": {
                "id": TLA_TRANSLATOR_ID,
                "version": TLA_COMPILER_VERSION,
            },
            "unbounded_proof": False,
        }
        if include_digest:
            payload["artifact_digest"] = self.artifact_digest
        if include_text:
            payload.update(
                {
                    "apalache_config_text": self.apalache_config_text,
                    "model_text": self.model_text,
                    "tlc_config_text": self.tlc_config_text,
                }
            )
        return payload


class TLACompiler:
    """Compile state / concurrency / refinement IR into deterministic TLA+."""

    interface_version: Final = TLA_BACKEND_VERSION

    def __init__(self, *, bounds: TLACompileBounds | None = None) -> None:
        self._bounds = bounds or TLACompileBounds()

    @property
    def bounds(self) -> TLACompileBounds:
        return self._bounds

    def supports(self, document: object) -> bool:
        return isinstance(
            document, (StateTransitionIR, ConcurrencyIR, RefinementIR, RelyGuaranteeContract)
        )

    def compile(
        self,
        document: (
            StateTransitionIR
            | ConcurrencyIR
            | RefinementIR
            | RelyGuaranteeContract
            | Mapping[str, Any]
        ),
        *,
        module_name: str = "StateModel",
        bounds: TLACompileBounds | Mapping[str, Any] | None = None,
    ) -> GeneratedTLAArtifacts:
        finite = self._resolve_bounds(bounds)
        if isinstance(document, Mapping):
            document = self._coerce_mapping(document)
        if isinstance(document, StateTransitionIR):
            return self.compile_state(document, module_name=module_name, bounds=finite)
        if isinstance(document, ConcurrencyIR):
            return self.compile_concurrency(
                document, module_name=module_name, bounds=finite
            )
        if isinstance(document, RefinementIR):
            return self.compile_refinement(
                document, module_name=module_name, bounds=finite
            )
        if isinstance(document, RelyGuaranteeContract):
            return self.compile_rely_guarantee(
                document, module_name=module_name, bounds=finite
            )
        raise TLACompilerError(
            "document must be StateTransitionIR, ConcurrencyIR, RefinementIR, "
            "or RelyGuaranteeContract"
        )

    def compile_state(
        self,
        document: StateTransitionIR,
        *,
        module_name: str = "StateModel",
        bounds: TLACompileBounds | None = None,
    ) -> GeneratedTLAArtifacts:
        if not isinstance(document, StateTransitionIR):
            raise TLACompilerError("document must be a StateTransitionIR")
        finite = bounds or self._bounds
        self._validate_state_bounds(document, finite)
        name = _module_name(module_name)
        losses = list(self._state_losses(document, finite))
        source_map: list[TLASourceMapEntry] = []
        lines: list[str] = [
            f"---- MODULE {name} ----",
            "EXTENDS Integers, FiniteSets, Sequences, TLC",
            "",
            f"\\* translator: {TLA_TRANSLATOR_ID} ({TLA_COMPILER_VERSION})",
            f"\\* source_document_id: {document.document_id}",
            f"\\* source_kind: state_transition_ir",
            f"\\* finite bounds: {finite.label}",
            "",
            f"MaxSteps == {finite.max_steps}",
            "",
        ]

        variable_symbols: list[str] = []
        for variable in sorted(document.schema.variables, key=lambda item: item.variable_id):
            symbol = _variable_symbol(variable)
            variable_symbols.append(symbol)
            domain_expr, var_losses = self._domain_expression(variable, finite)
            losses.extend(var_losses)
            lines.append(f"\\* @type: Set;")
            lines.append(f"{symbol}Domain == {domain_expr}")
            source_map.append(
                TLASourceMapEntry(
                    source_id=variable.variable_id,
                    source_kind="state_variable",
                    tla_symbol=f"{symbol}Domain",
                    role="domain",
                    line_hint=f"{symbol}Domain",
                )
            )
            source_map.append(
                TLASourceMapEntry(
                    source_id=variable.variable_id,
                    source_kind="state_variable",
                    tla_symbol=symbol,
                    role="variable",
                    line_hint="VARIABLES",
                )
            )
        lines.append("")

        if not variable_symbols:
            raise TLACompilerError("state schema must declare at least one variable")

        lines.append("VARIABLES")
        for index, symbol in enumerate(variable_symbols):
            suffix = "," if index + 1 < len(variable_symbols) else ""
            lines.append(f"    {symbol}{suffix}")
        # Always include a bounded step counter for finite exploration.
        lines[-1] = lines[-1] + ","
        lines.append("    step")
        lines.append("")
        vars_tuple = ", ".join([*variable_symbols, "step"])
        lines.append(f"vars == <<{vars_tuple}>>")
        lines.append("")

        # Type invariant
        type_conjuncts = [
            f"{symbol} \\in {symbol}Domain" for symbol in variable_symbols
        ]
        type_conjuncts.append("step \\in 0..MaxSteps")
        lines.append("TypeOK ==")
        for index, conjunct in enumerate(type_conjuncts):
            prefix = "    /\\ " if index else "    "
            if index == 0:
                lines.append(f"    /\\ {conjunct}" if type_conjuncts else f"    {conjunct}")
            else:
                lines.append(f"    /\\ {conjunct}")
        # Fix first line properly
        lines = self._rewrite_typeok(lines, type_conjuncts)
        source_map.append(
            TLASourceMapEntry(
                source_id=document.document_id,
                source_kind="state_transition_ir",
                tla_symbol="TypeOK",
                role="type_invariant",
            )
        )
        lines.append("")

        # Init
        initial_preds = document.predicates_by_role(PredicateRole.INITIAL)
        if not initial_preds:
            raise TLACompilerError("StateTransitionIR requires an initial predicate")
        lines.append("Init ==")
        lines.append("    /\\ step = 0")
        init_has_machine_expr = False
        for predicate in sorted(initial_preds, key=lambda item: item.predicate_id):
            expr = self._predicate_expression(
                predicate.statement,
                predicate.expression.to_dict() if predicate.expression else {},
                variables=document.schema,
                primed=False,
            )
            machine = bool(predicate.expression and predicate.expression.to_dict()) or _looks_like_tla(
                predicate.statement
            )
            if machine and expr and expr != "TRUE":
                init_has_machine_expr = True
                lines.append(f"    /\\ {expr}  \\* {predicate.predicate_id}")
            source_map.append(
                TLASourceMapEntry(
                    source_id=predicate.predicate_id,
                    source_kind="predicate",
                    tla_symbol="Init",
                    role="initial",
                    line_hint=predicate.statement,
                )
            )
        if not init_has_machine_expr:
            for symbol in variable_symbols:
                lines.append(f"    /\\ {symbol} \\in {symbol}Domain")
            losses.append(
                ProjectionLoss(
                    loss_id="loss:init-opaque-predicates",
                    projection=ProjectionKind.STATE,
                    severity=LossSeverity.OVER_APPROXIMATION,
                    construct="opaque_initial_predicate",
                    statement=(
                        "Initial predicates lack a reviewed machine-readable "
                        "expression; Init over-approximates as any typed valuation."
                    ),
                    handling=UnsupportedHandling.ABSTRACTED,
                    preservation=PreservationKind.BOUNDED,
                    approximation=ApproximationDirection.OVER,
                )
            )
        lines.append("")

        # Actions / Next
        action_symbols: list[str] = []
        for action in sorted(document.actions, key=lambda item: item.action_id):
            symbol = _action_symbol(action)
            action_symbols.append(symbol)
            action_lines, action_map, action_losses = self._render_action(
                action, document, finite
            )
            lines.extend(action_lines)
            lines.append("")
            source_map.extend(action_map)
            losses.extend(action_losses)

        if action_symbols:
            lines.append("Next ==")
            lines.append("    /\\ step < MaxSteps")
            if len(action_symbols) == 1:
                lines.append(f"    /\\ {action_symbols[0]}")
            else:
                lines.append(
                    "    /\\ \\/ "
                    + "\n       \\/ ".join(action_symbols)
                )
            lines.append("    /\\ step' = step + 1")
        else:
            # Relation-only systems: stuttering next with explicit loss.
            lines.append("Next ==")
            lines.append("    /\\ step < MaxSteps")
            lines.append("    /\\ UNCHANGED <<" + ", ".join(variable_symbols) + ">>")
            lines.append("    /\\ step' = step + 1")
            losses.append(
                ProjectionLoss(
                    loss_id="loss:relation-only-stutter",
                    projection=ProjectionKind.STATE,
                    severity=LossSeverity.UNDER_APPROXIMATION,
                    construct="transition_relation_without_actions",
                    statement=(
                        "No reviewed actions were present; Next is a bounded "
                        "stutter under-approximation of the relation text."
                    ),
                    handling=UnsupportedHandling.APPROXIMATED,
                    preservation=PreservationKind.BOUNDED,
                    approximation=ApproximationDirection.UNDER,
                )
            )
        source_map.append(
            TLASourceMapEntry(
                source_id=document.document_id,
                source_kind="state_transition_ir",
                tla_symbol="Next",
                role="next",
            )
        )
        lines.append("")

        # Safety / invariants
        safety_names: list[str] = ["TypeOK"]
        invariant_preds = document.predicates_by_role(PredicateRole.INVARIANT)
        for predicate in sorted(invariant_preds, key=lambda item: item.predicate_id):
            inv_name = _predicate_symbol(predicate.predicate_id, "Inv")
            safety_names.append(inv_name)
            expr = self._predicate_expression(
                predicate.statement,
                predicate.expression.to_dict() if predicate.expression else {},
                variables=document.schema,
                primed=False,
            )
            if not _looks_like_tla(expr) and not (
                predicate.expression and predicate.expression.to_dict()
            ):
                expr = "TRUE"
                losses.append(
                    ProjectionLoss(
                        loss_id=f"loss:opaque-invariant:{predicate.predicate_id}",
                        projection=ProjectionKind.STATE,
                        severity=LossSeverity.DISCLOSED,
                        construct="opaque_invariant",
                        statement=(
                            f"Invariant {predicate.predicate_id!r} was emitted as TRUE "
                            "because no machine-readable expression was available; "
                            "semantic checking requires a reviewed expression."
                        ),
                        handling=UnsupportedHandling.OMITTED,
                        preservation=PreservationKind.HEURISTIC,
                        approximation=ApproximationDirection.OVER,
                    )
                )
            lines.append(f"{inv_name} == {expr}")
            source_map.append(
                TLASourceMapEntry(
                    source_id=predicate.predicate_id,
                    source_kind="predicate",
                    tla_symbol=inv_name,
                    role="invariant",
                    line_hint=predicate.statement,
                )
            )
        lines.append("")
        lines.append("Safety ==")
        for index, name in enumerate(safety_names):
            lines.append(f"    /\\ {name}")
        lines.append("")

        # Fairness / liveness
        fairness_parts: list[str] = []
        fairness_limitations: list[str] = []
        liveness_names: list[str] = []
        for constraint in sorted(document.fairness, key=lambda item: item.fairness_id):
            fair_name = _predicate_symbol(constraint.fairness_id, "Fair")
            if constraint.kind is FairnessKind.WEAK:
                formula = f"WF_vars(Next)"
                fairness_limitations.append(
                    f"{constraint.fairness_id}: weak fairness projected to WF_vars(Next); "
                    "predicate-specific enabling conditions are not reified."
                )
            elif constraint.kind is FairnessKind.STRONG:
                formula = f"SF_vars(Next)"
                fairness_limitations.append(
                    f"{constraint.fairness_id}: strong fairness projected to SF_vars(Next); "
                    "predicate-specific enabling conditions are not reified."
                )
            else:
                formula = "TRUE"
                fairness_limitations.append(
                    f"{constraint.fairness_id}: unconditional fairness has no reviewed "
                    "TLA+ embedding and is disclosed as a no-op."
                )
                losses.append(
                    ProjectionLoss(
                        loss_id=f"loss:fairness:{constraint.fairness_id}",
                        projection=ProjectionKind.STATE,
                        severity=LossSeverity.OMITTED,
                        construct="unconditional_fairness",
                        statement=(
                            "Unconditional fairness is not emitted as a TLA operator; "
                            "liveness claims remain bounded and tool-specific."
                        ),
                        handling=UnsupportedHandling.OMITTED,
                        preservation=PreservationKind.BOUNDED,
                        approximation=ApproximationDirection.UNDER,
                    )
                )
            lines.append(f"{fair_name} == {formula}")
            fairness_parts.append(fair_name)
            source_map.append(
                TLASourceMapEntry(
                    source_id=constraint.fairness_id,
                    source_kind="fairness",
                    tla_symbol=fair_name,
                    role="fairness",
                )
            )
        if not fairness_parts:
            fairness_limitations.append(
                "No fairness constraints were present; Spec uses only safety stuttering."
            )
        lines.append("")

        # Bounded liveness placeholders (checked by TLC only)
        lines.append("BoundedProgress ==")
        lines.append("    <>(step = MaxSteps)")
        liveness_names.append("BoundedProgress")
        fairness_limitations.append(
            "BoundedProgress only asserts that the finite step budget is reachable; "
            "it is not an unbounded liveness proof."
        )
        source_map.append(
            TLASourceMapEntry(
                source_id=document.document_id,
                source_kind="state_transition_ir",
                tla_symbol="BoundedProgress",
                role="liveness",
            )
        )
        lines.append("")

        fair_suffix = ""
        if fairness_parts:
            fair_suffix = " /\\ " + " /\\ ".join(fairness_parts)
        lines.append(f"Spec == Init /\\ [][Next]_vars{fair_suffix}")
        lines.append("")
        lines.append("====")
        lines.append("")

        model_text = "\n".join(lines)
        tlc_config = self._render_tlc_config(safety_names, liveness_names)
        apalache_config = self._render_apalache_config()
        # Deduplicate losses by loss_id while preserving order.
        seen: set[str] = set()
        unique_losses: list[ProjectionLoss] = []
        for loss in losses:
            if loss.loss_id in seen:
                continue
            seen.add(loss.loss_id)
            unique_losses.append(loss)

        return GeneratedTLAArtifacts(
            module_name=name,
            model_text=model_text,
            tlc_config_text=tlc_config,
            apalache_config_text=apalache_config,
            source_map=tuple(source_map),
            losses=tuple(unique_losses),
            bounds=finite,
            source_document_id=document.document_id,
            source_kind="state_transition_ir",
            safety_properties=tuple(safety_names),
            liveness_properties=tuple(liveness_names),
            fairness_limitations=tuple(fairness_limitations),
        )

    def compile_concurrency(
        self,
        document: ConcurrencyIR,
        *,
        module_name: str = "ConcurrentModel",
        bounds: TLACompileBounds | None = None,
    ) -> GeneratedTLAArtifacts:
        if not isinstance(document, ConcurrencyIR):
            raise TLACompilerError("document must be a ConcurrencyIR")
        finite = bounds or self._bounds
        # Project concurrency into a sequential action system over component PCs.
        components = sorted(document.components, key=lambda item: item.component_id)
        if not components:
            raise TLACompilerError("ConcurrencyIR requires at least one component")
        if len(components) > finite.max_variables:
            raise TLACompilerError("concurrency projection exceeds max_variables")

        schema_variables = []
        for component in components:
            schema_variables.append(
                StateVariable(
                    variable_id=f"var:{component.component_id}:pc",
                    name=_variable_symbol_from_id(component.component_id) + "_pc",
                    type_kind=StateTypeKind.ENUMERATION,
                    boundedness=Boundedness.FINITE,
                    domain_bound=_finite_members_bound(
                        f"bound:{component.component_id}",
                        ("idle", "active", "done"),
                    ),
                )
            )
        from ...software_verification.state import FiniteDomainBound, StatePredicate
        from ...software_verification.transitions import (
            Action as TransitionAction,
            ActionFrame,
            TransitionKind,
            TransitionRelation,
        )

        schema = StateSchema(variables=tuple(schema_variables))
        init = StatePredicate(
            "pred:conc:init",
            PredicateRole.INITIAL,
            "all components start idle",
            expression={
                var.variable_id: "idle" for var in schema_variables
            },
            subject_variable_ids=tuple(var.variable_id for var in schema_variables),
        )
        inv = StatePredicate(
            "pred:conc:inv",
            PredicateRole.INVARIANT,
            "component program counters stay in domain",
            expression={"role": "type"},
            subject_variable_ids=tuple(var.variable_id for var in schema_variables),
        )
        predicates = [init, inv]
        action_records = []
        for component in components:
            var_id = f"var:{component.component_id}:pc"
            guard = StatePredicate(
                f"pred:guard:{component.component_id}",
                PredicateRole.GUARD,
                f"{component.component_id} is idle",
                expression={var_id: "idle"},
                subject_variable_ids=(var_id,),
            )
            nxt = StatePredicate(
                f"pred:next:{component.component_id}",
                PredicateRole.NEXT,
                f"{component.component_id} becomes done",
                expression={var_id: "done"},
                subject_variable_ids=(var_id,),
            )
            predicates.extend([guard, nxt])
            action_records.append(
                TransitionAction(
                    f"action:{component.component_id}:step",
                    _action_name(component.component_id),
                    ActionFrame(reads=(var_id,), writes=(var_id,)),
                    guard_predicate_id=guard.predicate_id,
                    next_predicate_id=nxt.predicate_id,
                )
            )
        relation = TransitionRelation(
            "rel:interleaving",
            TransitionKind.ACTION,
            "Interleaved component steps.",
            action_ids=tuple(item.action_id for item in action_records),
            allows_stutter=True,
        )
        projected = StateTransitionIR(
            schema=schema,
            predicates=tuple(predicates),
            actions=tuple(action_records),
            transitions=(relation,),
            metadata=FrozenMap(
                {
                    "projected_from": "concurrency_ir",
                    "concurrency_document_id": document.document_id,
                }
            ),
        )
        artifacts = self.compile_state(
            projected, module_name=module_name, bounds=finite
        )
        extra_losses = [
            ProjectionLoss(
                loss_id="loss:concurrency:interleaving",
                projection=ProjectionKind.CONCURRENCY,
                severity=LossSeverity.OVER_APPROXIMATION,
                construct="true_concurrency",
                statement=(
                    "Concurrent components are projected to a sequential "
                    "interleaving of program-counter steps; true simultaneous "
                    "execution and fine-grained interference are over-approximated."
                ),
            ),
            ProjectionLoss(
                loss_id="loss:concurrency:channels",
                projection=ProjectionKind.CONCURRENCY,
                severity=LossSeverity.OMITTED,
                construct="channels_and_sessions",
                statement=(
                    "Channels, session types, and message payloads are omitted "
                    "from the TLA projection; only component control locations remain."
                ),
                handling=UnsupportedHandling.OMITTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.UNDER,
            ),
            ProjectionLoss(
                loss_id="loss:concurrency:atomicity",
                projection=ProjectionKind.CONCURRENCY,
                severity=LossSeverity.DISCLOSED,
                construct="atomic_regions",
                statement=(
                    "Atomic regions and lock semantics are not reified; each "
                    "component step is treated as an atomic TLA action."
                ),
                handling=UnsupportedHandling.ABSTRACTED,
            ),
        ]
        if document.rely_guarantee:
            extra_losses.append(
                ProjectionLoss(
                    loss_id="loss:concurrency:rg-embedded",
                    projection=ProjectionKind.RELY_GUARANTEE,
                    severity=LossSeverity.DISCLOSED,
                    construct="rely_guarantee_in_concurrency",
                    statement=(
                        "Rely/guarantee contracts present on the concurrency "
                        "document are not auto-inlined; compile them separately "
                        "via compile_rely_guarantee for explicit loss accounting."
                    ),
                    handling=UnsupportedHandling.OMITTED,
                    preservation=PreservationKind.HEURISTIC,
                    approximation=ApproximationDirection.NONE,
                )
            )
        return GeneratedTLAArtifacts(
            module_name=artifacts.module_name,
            model_text=artifacts.model_text,
            tlc_config_text=artifacts.tlc_config_text,
            apalache_config_text=artifacts.apalache_config_text,
            source_map=artifacts.source_map
            + (
                TLASourceMapEntry(
                    source_id=document.document_id,
                    source_kind="concurrency_ir",
                    tla_symbol=artifacts.module_name,
                    role="projection_root",
                ),
            ),
            losses=artifacts.losses + tuple(extra_losses),
            bounds=artifacts.bounds,
            source_document_id=document.document_id,
            source_kind="concurrency_ir",
            safety_properties=artifacts.safety_properties,
            liveness_properties=artifacts.liveness_properties,
            fairness_limitations=artifacts.fairness_limitations
            + (
                "Concurrency fairness is not reconstructed; only the projected "
                "state fairness operators apply.",
            ),
        )

    def compile_rely_guarantee(
        self,
        document: RelyGuaranteeContract,
        *,
        module_name: str = "RelyGuaranteeModel",
        bounds: TLACompileBounds | None = None,
        shared_state: StateTransitionIR | None = None,
    ) -> GeneratedTLAArtifacts:
        if not isinstance(document, RelyGuaranteeContract):
            raise TLACompilerError("document must be a RelyGuaranteeContract")
        finite = bounds or self._bounds
        # Minimal two-variable system encoding R/G as comment-bound safety.
        from ...software_verification.state import FiniteDomainBound, StatePredicate
        from ...software_verification.transitions import (
            Action as TransitionAction,
            ActionFrame,
            TransitionKind,
            TransitionRelation,
        )

        shared_ids = document.shared_variable_ids or ("var:shared",)
        variables = []
        for index, shared_id in enumerate(shared_ids[: finite.max_variables]):
            variables.append(
                StateVariable(
                    variable_id=shared_id
                    if shared_id.startswith("var:")
                    else f"var:{shared_id}",
                    name=_variable_symbol_from_id(shared_id),
                    type_kind=StateTypeKind.INTEGER,
                    boundedness=Boundedness.FINITE,
                    domain_bound=FiniteDomainBound(
                        f"bound:rg:{index}",
                        lower=finite.default_integer_lower,
                        upper=finite.default_integer_upper,
                    ),
                )
            )
        if not variables:
            raise TLACompilerError("rely/guarantee projection requires a shared variable")
        schema = StateSchema(variables=tuple(variables))
        primary = variables[0].variable_id
        init = StatePredicate(
            "pred:rg:init",
            PredicateRole.INITIAL,
            "shared state at lower bound",
            expression={primary: finite.default_integer_lower},
            subject_variable_ids=(primary,),
        )
        # Encode guarantee as an invariant over shared state domain.
        inv = StatePredicate(
            "pred:rg:guarantee",
            PredicateRole.INVARIANT,
            document.guarantee_statement,
            expression={"role": "guarantee", "text": document.guarantee_statement},
            subject_variable_ids=tuple(item.variable_id for item in variables),
        )
        env_guard = StatePredicate(
            "pred:rg:env-guard",
            PredicateRole.GUARD,
            document.rely_statement,
            expression={"role": "rely", "text": document.rely_statement},
            subject_variable_ids=tuple(item.variable_id for item in variables),
        )
        env_next = StatePredicate(
            "pred:rg:env-next",
            PredicateRole.NEXT,
            "environment may assign any domain value under rely",
            expression={},
            subject_variable_ids=(primary,),
        )
        env_action = TransitionAction(
            "action:environment",
            "Environment",
            ActionFrame(
                reads=tuple(item.variable_id for item in variables),
                writes=(primary,),
            ),
            guard_predicate_id=env_guard.predicate_id,
            next_predicate_id=env_next.predicate_id,
        )
        sys_guard = StatePredicate(
            "pred:rg:sys-guard",
            PredicateRole.GUARD,
            "system may step",
            expression={},
            subject_variable_ids=(primary,),
        )
        sys_next = StatePredicate(
            "pred:rg:sys-next",
            PredicateRole.NEXT,
            "system may assign any domain value under guarantee",
            expression={},
            subject_variable_ids=(primary,),
        )
        sys_action = TransitionAction(
            "action:system",
            "System",
            ActionFrame(
                reads=tuple(item.variable_id for item in variables),
                writes=(primary,),
            ),
            guard_predicate_id=sys_guard.predicate_id,
            next_predicate_id=sys_next.predicate_id,
        )
        relation = TransitionRelation(
            "rel:rg",
            TransitionKind.ACTION,
            "System and environment interleaving under R/G.",
            action_ids=(env_action.action_id, sys_action.action_id),
            allows_stutter=True,
        )
        projected = StateTransitionIR(
            schema=schema,
            predicates=(init, inv, env_guard, env_next, sys_guard, sys_next),
            actions=(env_action, sys_action),
            transitions=(relation,),
            metadata=FrozenMap(
                {
                    "projected_from": "rely_guarantee",
                    "contract_id": document.contract_id,
                    "component_id": document.component_id,
                }
            ),
        )
        if shared_state is not None:
            # Prefer the caller's richer state when supplied.
            projected = shared_state
        artifacts = self.compile_state(
            projected, module_name=module_name, bounds=finite
        )
        extra_losses = (
            ProjectionLoss(
                loss_id=f"loss:rg:{document.contract_id}:rely",
                projection=ProjectionKind.RELY_GUARANTEE,
                severity=LossSeverity.OVER_APPROXIMATION,
                construct="rely_interference",
                statement=(
                    f"Rely text for {document.contract_id!r} is not executed as a "
                    "semantic constraint; the environment action over-approximates "
                    "permitted interference as any typed domain assignment."
                ),
                handling=UnsupportedHandling.ABSTRACTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.OVER,
            ),
            ProjectionLoss(
                loss_id=f"loss:rg:{document.contract_id}:guarantee",
                projection=ProjectionKind.RELY_GUARANTEE,
                severity=LossSeverity.DISCLOSED,
                construct="guarantee_commitment",
                statement=(
                    f"Guarantee text for {document.contract_id!r} is bound as an "
                    "opaque/invariant projection and does not automatically prove "
                    "interference freedom against other components."
                ),
                handling=UnsupportedHandling.ABSTRACTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.UNDER,
            ),
        )
        return GeneratedTLAArtifacts(
            module_name=artifacts.module_name,
            model_text=artifacts.model_text,
            tlc_config_text=artifacts.tlc_config_text,
            apalache_config_text=artifacts.apalache_config_text,
            source_map=artifacts.source_map
            + (
                TLASourceMapEntry(
                    source_id=document.contract_id,
                    source_kind="rely_guarantee_contract",
                    tla_symbol=artifacts.module_name,
                    role="projection_root",
                ),
            ),
            losses=artifacts.losses + extra_losses,
            bounds=artifacts.bounds,
            source_document_id=document.contract_id,
            source_kind="rely_guarantee",
            safety_properties=artifacts.safety_properties,
            liveness_properties=artifacts.liveness_properties,
            fairness_limitations=artifacts.fairness_limitations
            + (
                "Rely/guarantee projections do not claim fairness of environment "
                "or system; interference remains bounded and adversarial.",
            ),
        )

    def compile_refinement(
        self,
        document: RefinementIR,
        *,
        module_name: str = "RefinementModel",
        bounds: TLACompileBounds | None = None,
        prefer: str = "concrete",
    ) -> GeneratedTLAArtifacts:
        if not isinstance(document, RefinementIR):
            raise TLACompilerError("document must be a RefinementIR")
        finite = bounds or self._bounds
        prefer_norm = str(prefer).strip().lower()
        if prefer_norm not in {"concrete", "abstract"}:
            raise TLACompilerError("prefer must be 'concrete' or 'abstract'")

        from ...software_verification.state import FiniteDomainBound, StatePredicate
        from ...software_verification.transitions import (
            Action as TransitionAction,
            ActionFrame,
            TransitionKind,
            TransitionRelation,
        )

        concrete = document.concrete_systems()
        abstract = document.abstract_systems()
        if prefer_norm == "concrete" and concrete:
            system = concrete[0]
        elif prefer_norm == "abstract" and abstract:
            system = abstract[0]
        elif concrete:
            system = concrete[0]
        elif abstract:
            system = abstract[0]
        else:
            system = document.systems[0]

        # Encode refinement system states as a single location variable.
        state_ids = tuple(system.state_ids)[: finite.max_enum_members]
        if not state_ids:
            raise TLACompilerError("refinement system has no states")
        variables = (
            StateVariable(
                "var:loc",
                "loc",
                StateTypeKind.ENUMERATION,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound("bound:loc", members=state_ids),
            ),
        )
        schema = StateSchema(variables=variables)
        initials = tuple(system.initial_state_ids) or (state_ids[0],)
        init = StatePredicate(
            "pred:ref:init",
            PredicateRole.INITIAL,
            "location is an initial refinement state",
            expression={"var:loc": initials[0]},
            subject_variable_ids=("var:loc",),
        )
        inv = StatePredicate(
            "pred:ref:inv",
            PredicateRole.INVARIANT,
            "location stays in refinement state set",
            expression={"role": "type"},
            subject_variable_ids=("var:loc",),
        )
        actions = []
        predicates: list[StatePredicate] = [init, inv]
        for transition in sorted(
            system.transitions, key=lambda item: item.transition_id
        )[: finite.max_actions]:
            guard = StatePredicate(
                f"pred:guard:{transition.transition_id}",
                PredicateRole.GUARD,
                f"loc = {transition.source_state_id}",
                expression={"var:loc": transition.source_state_id},
                subject_variable_ids=("var:loc",),
            )
            nxt = StatePredicate(
                f"pred:next:{transition.transition_id}",
                PredicateRole.NEXT,
                f"loc' = {transition.target_state_id}",
                expression={"var:loc": transition.target_state_id},
                subject_variable_ids=("var:loc",),
            )
            predicates.extend([guard, nxt])
            actions.append(
                TransitionAction(
                    f"action:{transition.transition_id}",
                    _action_name(transition.transition_id),
                    ActionFrame(reads=("var:loc",), writes=("var:loc",)),
                    guard_predicate_id=guard.predicate_id,
                    next_predicate_id=nxt.predicate_id,
                )
            )
        if not actions:
            guard = StatePredicate(
                "pred:ref:stutter-guard",
                PredicateRole.GUARD,
                "stutter",
                expression={},
                subject_variable_ids=("var:loc",),
            )
            nxt = StatePredicate(
                "pred:ref:stutter-next",
                PredicateRole.NEXT,
                "stutter",
                expression={},
                subject_variable_ids=("var:loc",),
            )
            predicates.extend([guard, nxt])
            actions.append(
                TransitionAction(
                    "action:ref:stutter",
                    "Stutter",
                    ActionFrame(reads=("var:loc",), writes=()),
                    guard_predicate_id=guard.predicate_id,
                    next_predicate_id=nxt.predicate_id,
                )
            )
        projected = StateTransitionIR(
            schema=schema,
            predicates=tuple(predicates),
            actions=tuple(actions),
            transitions=(
                TransitionRelation(
                    "rel:ref",
                    TransitionKind.ACTION,
                    "Refinement system steps.",
                    action_ids=tuple(item.action_id for item in actions),
                    allows_stutter=True,
                ),
            ),
            metadata=FrozenMap(
                {
                    "projected_from": "refinement_ir",
                    "refinement_document_id": document.document_id,
                    "prefer": prefer_norm,
                    "system_id": system.system_id,
                }
            ),
        )

        artifacts = self.compile_state(
            projected, module_name=module_name, bounds=finite
        )
        extra_losses = (
            ProjectionLoss(
                loss_id="loss:refinement:single-level",
                projection=ProjectionKind.REFINEMENT,
                severity=LossSeverity.UNDER_APPROXIMATION,
                construct="simulation_relation",
                statement=(
                    f"Only the {prefer_norm} refinement level is compiled; the "
                    "simulation/refinement relation between abstract and concrete "
                    "systems is not reified as a TLA property."
                ),
                handling=UnsupportedHandling.OMITTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.UNDER,
            ),
            ProjectionLoss(
                loss_id="loss:refinement:data-abstraction",
                projection=ProjectionKind.REFINEMENT,
                severity=LossSeverity.DISCLOSED,
                construct="data_refinement",
                statement=(
                    "Data refinement and retrieve relations are collapsed to a "
                    "finite location domain; value-level correspondence is omitted."
                ),
                handling=UnsupportedHandling.ABSTRACTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.UNDER,
            ),
        )
        return GeneratedTLAArtifacts(
            module_name=artifacts.module_name,
            model_text=artifacts.model_text,
            tlc_config_text=artifacts.tlc_config_text,
            apalache_config_text=artifacts.apalache_config_text,
            source_map=artifacts.source_map
            + (
                TLASourceMapEntry(
                    source_id=document.document_id,
                    source_kind="refinement_ir",
                    tla_symbol=artifacts.module_name,
                    role="projection_root",
                ),
            ),
            losses=artifacts.losses + extra_losses,
            bounds=artifacts.bounds,
            source_document_id=document.document_id,
            source_kind="refinement_ir",
            safety_properties=artifacts.safety_properties,
            liveness_properties=artifacts.liveness_properties,
            fairness_limitations=artifacts.fairness_limitations
            + (
                "Refinement projections do not discharge infinite stuttering "
                "or fairness obligations of the omitted system level.",
            ),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_bounds(
        self, bounds: TLACompileBounds | Mapping[str, Any] | None
    ) -> TLACompileBounds:
        if bounds is None:
            return self._bounds
        if isinstance(bounds, TLACompileBounds):
            return bounds
        return TLACompileBounds.from_dict(bounds)

    def _coerce_mapping(
        self, value: Mapping[str, Any]
    ) -> StateTransitionIR | ConcurrencyIR | RefinementIR | RelyGuaranteeContract:
        if not isinstance(value, Mapping):
            raise TLACompilerError("document mapping is required")
        schema = str(value.get("schema_version") or value.get("schema") or "")
        if "state-transition" in schema or value.get("actions") is not None:
            return StateTransitionIR.from_dict(value)
        if "concurrency" in schema or value.get("components") is not None:
            return ConcurrencyIR.from_dict(value)
        if "refinement" in schema or value.get("simulation") is not None:
            return RefinementIR.from_dict(value)
        if value.get("rely_statement") is not None:
            return RelyGuaranteeContract.from_dict(value)
        raise TLACompilerError("unable to coerce mapping to a supported IR document")

    def _validate_state_bounds(
        self, document: StateTransitionIR, bounds: TLACompileBounds
    ) -> None:
        if len(document.schema.variables) > bounds.max_variables:
            raise TLACompilerError("state schema exceeds max_variables")
        if len(document.actions) > bounds.max_actions:
            raise TLACompilerError("action system exceeds max_actions")
        if len(document.predicates) > bounds.max_predicates:
            raise TLACompilerError("predicate set exceeds max_predicates")

    def _state_losses(
        self, document: StateTransitionIR, bounds: TLACompileBounds
    ) -> list[ProjectionLoss]:
        losses: list[ProjectionLoss] = [
            ProjectionLoss(
                loss_id="loss:state:finite-steps",
                projection=ProjectionKind.STATE,
                severity=LossSeverity.DISCLOSED,
                construct="finite_step_bound",
                statement=(
                    f"Exploration is hard-bounded by MaxSteps={bounds.max_steps}; "
                    "a successful check is never an unbounded proof."
                ),
                handling=UnsupportedHandling.ABSTRACTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.UNDER,
            )
        ]
        for variable in document.schema.variables:
            if variable.boundedness is Boundedness.UNBOUNDED:
                losses.append(
                    ProjectionLoss(
                        loss_id=f"loss:state:unbounded:{variable.variable_id}",
                        projection=ProjectionKind.STATE,
                        severity=LossSeverity.OVER_APPROXIMATION,
                        construct="unbounded_domain",
                        statement=(
                            f"Variable {variable.variable_id!r} is unbounded in the IR "
                            "and is compiled under default finite integer bounds."
                        ),
                        handling=UnsupportedHandling.ABSTRACTED,
                        preservation=PreservationKind.BOUNDED,
                        approximation=ApproximationDirection.UNDER,
                    )
                )
        if document.kripke is not None:
            losses.append(
                ProjectionLoss(
                    loss_id="loss:state:kripke-not-expanded",
                    projection=ProjectionKind.STATE,
                    severity=LossSeverity.DISCLOSED,
                    construct="kripke_structure",
                    statement=(
                        "An explicit Kripke structure is present but the compiler "
                        "emits the action-system view; worlds/edges are not expanded "
                        "into the module unless projected separately."
                    ),
                    handling=UnsupportedHandling.OMITTED,
                    preservation=PreservationKind.HEURISTIC,
                    approximation=ApproximationDirection.NONE,
                )
            )
        return losses

    def _domain_expression(
        self, variable: StateVariable, bounds: TLACompileBounds
    ) -> tuple[str, list[ProjectionLoss]]:
        losses: list[ProjectionLoss] = []
        if variable.type_kind is StateTypeKind.BOOLEAN:
            return '{"FALSE", "TRUE"}', losses
        if variable.type_kind is StateTypeKind.ENUMERATION:
            domain = variable.domain_bound
            if domain is None or not domain.members:
                raise TLACompilerError(
                    f"enumeration variable {variable.variable_id!r} requires members"
                )
            if len(domain.members) > bounds.max_enum_members:
                raise TLACompilerError(
                    f"enumeration {variable.variable_id!r} exceeds max_enum_members"
                )
            return _tla_set(domain.members), losses
        if variable.type_kind is StateTypeKind.INTEGER:
            domain = variable.domain_bound
            if domain is not None and domain.lower is not None and domain.upper is not None:
                span = domain.upper - domain.lower
                if span > bounds.max_integer_span:
                    raise TLACompilerError(
                        f"integer domain for {variable.variable_id!r} exceeds max_integer_span"
                    )
                return f"{domain.lower}..{domain.upper}", losses
            losses.append(
                ProjectionLoss(
                    loss_id=f"loss:domain:{variable.variable_id}",
                    projection=ProjectionKind.STATE,
                    severity=LossSeverity.DISCLOSED,
                    construct="default_integer_bounds",
                    statement=(
                        f"Integer variable {variable.variable_id!r} uses default "
                        f"bounds [{bounds.default_integer_lower}, "
                        f"{bounds.default_integer_upper}]."
                    ),
                    handling=UnsupportedHandling.ABSTRACTED,
                    preservation=PreservationKind.BOUNDED,
                    approximation=ApproximationDirection.UNDER,
                )
            )
            return (
                f"{bounds.default_integer_lower}..{bounds.default_integer_upper}",
                losses,
            )
        # set / map / opaque
        losses.append(
            ProjectionLoss(
                loss_id=f"loss:domain-opaque:{variable.variable_id}",
                projection=ProjectionKind.STATE,
                severity=LossSeverity.OVER_APPROXIMATION,
                construct=f"type_{variable.type_kind.value}",
                statement=(
                    f"Variable {variable.variable_id!r} of kind "
                    f"{variable.type_kind.value} is compiled as a finite opaque token set."
                ),
                handling=UnsupportedHandling.ABSTRACTED,
                preservation=PreservationKind.BOUNDED,
                approximation=ApproximationDirection.OVER,
            )
        )
        return '{"opaque"}', losses

    def _render_action(
        self,
        action: Action,
        document: StateTransitionIR,
        bounds: TLACompileBounds,
    ) -> tuple[list[str], list[TLASourceMapEntry], list[ProjectionLoss]]:
        del bounds  # reserved for future action-local bounds
        symbol = _action_symbol(action)
        predicates = {item.predicate_id: item for item in document.predicates}
        losses: list[ProjectionLoss] = []
        source_map = [
            TLASourceMapEntry(
                source_id=action.action_id,
                source_kind="action",
                tla_symbol=symbol,
                role="action",
            )
        ]
        lines = [f"{symbol} =="]
        # Guard
        if action.guard_predicate_id and action.guard_predicate_id in predicates:
            guard = predicates[action.guard_predicate_id]
            guard_expr = self._predicate_expression(
                guard.statement,
                guard.expression.to_dict() if guard.expression else {},
                variables=document.schema,
                primed=False,
            )
            if not _looks_like_tla(guard_expr) and not (
                guard.expression and guard.expression.to_dict()
            ):
                guard_expr = "TRUE"
                losses.append(
                    ProjectionLoss(
                        loss_id=f"loss:guard:{action.action_id}",
                        projection=ProjectionKind.STATE,
                        severity=LossSeverity.OVER_APPROXIMATION,
                        construct="opaque_guard",
                        statement=(
                            f"Guard for action {action.action_id!r} is opaque and "
                            "compiled as TRUE."
                        ),
                        handling=UnsupportedHandling.ABSTRACTED,
                        preservation=PreservationKind.BOUNDED,
                        approximation=ApproximationDirection.OVER,
                    )
                )
            lines.append(f"    /\\ {guard_expr}")
            source_map.append(
                TLASourceMapEntry(
                    source_id=guard.predicate_id,
                    source_kind="predicate",
                    tla_symbol=symbol,
                    role="guard",
                    line_hint=guard.statement,
                )
            )
        else:
            lines.append("    /\\ TRUE")

        # Next-state effects
        written = set(action.frame.writes) if not action.frame.allows_all_writes else set(
            document.schema.variable_ids
        )
        next_updates: dict[str, str] = {}
        if action.next_predicate_id and action.next_predicate_id in predicates:
            nxt = predicates[action.next_predicate_id]
            expr_map = nxt.expression.to_dict() if nxt.expression else {}
            if expr_map:
                for key, value in sorted(expr_map.items()):
                    if key in document.schema.variable_ids or key.startswith("var:"):
                        var_symbol = _variable_symbol_from_id(key)
                        next_updates[var_symbol] = _tla_literal(value)
            elif _looks_like_tla(nxt.statement):
                lines.append(f"    /\\ {nxt.statement}")
            else:
                losses.append(
                    ProjectionLoss(
                        loss_id=f"loss:next:{action.action_id}",
                        projection=ProjectionKind.STATE,
                        severity=LossSeverity.DISCLOSED,
                        construct="opaque_next",
                        statement=(
                            f"Next predicate for action {action.action_id!r} is opaque; "
                            "written variables are left unchanged."
                        ),
                        handling=UnsupportedHandling.OMITTED,
                        preservation=PreservationKind.HEURISTIC,
                        approximation=ApproximationDirection.UNDER,
                    )
                )
            source_map.append(
                TLASourceMapEntry(
                    source_id=nxt.predicate_id,
                    source_kind="predicate",
                    tla_symbol=symbol,
                    role="next",
                    line_hint=nxt.statement,
                )
            )

        for variable in sorted(document.schema.variables, key=lambda item: item.variable_id):
            var_symbol = _variable_symbol(variable)
            if var_symbol in next_updates:
                lines.append(
                    f"    /\\ {var_symbol}' = {next_updates[var_symbol]}"
                )
            elif variable.variable_id in written or action.frame.allows_all_writes:
                # written but no concrete value: stay in domain (non-deterministic)
                lines.append(f"    /\\ {var_symbol}' \\in {var_symbol}Domain")
            else:
                lines.append(f"    /\\ {var_symbol}' = {var_symbol}")

        return lines, source_map, losses

    def _predicate_expression(
        self,
        statement: str,
        expression: Mapping[str, Any],
        *,
        variables: StateSchema,
        primed: bool,
    ) -> str:
        if expression:
            conjuncts: list[str] = []
            for key, value in sorted(expression.items()):
                if key in {"role", "text", "operator", "operands"}:
                    continue
                if key in variables.variable_ids or key.startswith("var:"):
                    symbol = _variable_symbol_from_id(key)
                    target = f"{symbol}'" if primed else symbol
                    conjuncts.append(f"{target} = {_tla_literal(value)}")
            if conjuncts:
                return " /\\ ".join(conjuncts)
        text = str(statement or "").strip()
        if _looks_like_tla(text):
            return text
        return text if text else "TRUE"

    @staticmethod
    def _render_tlc_config(
        safety: Sequence[str], liveness: Sequence[str]
    ) -> str:
        lines = ["SPECIFICATION Spec"]
        for name in safety:
            lines.append(f"INVARIANT {name}")
        for name in liveness:
            lines.append(f"PROPERTY {name}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_apalache_config() -> str:
        # Apalache uses TLC config syntax for INIT/NEXT/INVARIANT but does not
        # check temporal liveness/PROPERTY clauses.
        return "INIT Init\nNEXT Next\nINVARIANT Safety\n"

    @staticmethod
    def _rewrite_typeok(lines: list[str], conjuncts: Sequence[str]) -> list[str]:
        # Remove any partial TypeOK block and rewrite cleanly.
        cleaned = TLACompiler._drop_operator(lines, "TypeOK")
        cleaned.append("TypeOK ==")
        for conjunct in conjuncts:
            cleaned.append(f"    /\\ {conjunct}")
        return cleaned

    @staticmethod
    def _drop_operator(lines: list[str], name: str) -> list[str]:
        result: list[str] = []
        skipping = False
        header = f"{name} =="
        for line in lines:
            if line == header:
                skipping = True
                continue
            if skipping:
                if line == "" or (
                    not line.startswith(" ")
                    and not line.startswith("\\")
                    and "==" in line
                ):
                    skipping = False
                    if line != header:
                        result.append(line)
                continue
            result.append(line)
        return result


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TLACompilerError(f"{field_name} must be a non-empty string")
    return value.strip()


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in enum_type)
        raise TLACompilerError(f"{field_name} must be one of {choices}") from error


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tla_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _tla_set(values: Sequence[str]) -> str:
    items = tuple(sorted({str(item) for item in values}))
    return "{" + ", ".join(_tla_string(item) for item in items) + "}"


def _tla_literal(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if value is None:
        return _tla_string("null")
    return _tla_string(str(value))


def _tla_ident(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if not _IDENTIFIER.fullmatch(text):
        raise TLACompilerError(f"{field_name} must be a TLA+ identifier, got {text!r}")
    return text


def _module_name(value: str) -> str:
    cleaned = _ID_SAFE.sub("_", str(value).strip())
    if not cleaned:
        cleaned = "StateModel"
    if not cleaned[0].isalpha():
        cleaned = "M_" + cleaned
    return cleaned


def _variable_symbol(variable: StateVariable) -> str:
    return _variable_symbol_from_id(variable.name or variable.variable_id)


def _variable_symbol_from_id(value: str) -> str:
    cleaned = _ID_SAFE.sub("_", str(value).split(":")[-1])
    if not cleaned:
        cleaned = "v"
    if not cleaned[0].isalpha():
        cleaned = "v_" + cleaned
    return cleaned


def _predicate_symbol(predicate_id: str, prefix: str) -> str:
    tail = _ID_SAFE.sub("_", predicate_id.split(":")[-1])
    name = f"{prefix}_{tail}" if tail else prefix
    if not name[0].isalpha():
        name = "P_" + name
    return name


def _action_symbol(action: Action) -> str:
    return _action_name(action.name or action.action_id)


def _action_name(value: str) -> str:
    cleaned = _ID_SAFE.sub("_", str(value).split(":")[-1])
    if not cleaned:
        cleaned = "Act"
    if not cleaned[0].isalpha():
        cleaned = "A_" + cleaned
    # Capitalize first letter for TLA action convention
    return cleaned[0].upper() + cleaned[1:]


def _looks_like_tla(text: str) -> bool:
    if not text or len(text) > 512:
        return False
    if any(token in text for token in ("==", "/\\", "\\/", "\\in", "\\A", "\\E", "=>")):
        return True
    if re.fullmatch(r"[A-Za-z0-9_'\s\\/=<>\[\]{}(),.+*-]+", text):
        return "=" in text or "\\in" in text
    return False


def _finite_members_bound(bound_id: str, members: tuple[str, ...]):
    from ...software_verification.state import FiniteDomainBound

    return FiniteDomainBound(bound_id, members=members)


# Public alias matching the interface table.
TLABackend = TLACompiler


__all__ = [
    "TLA_ARTIFACT_SCHEMA_VERSION",
    "TLA_BACKEND_VERSION",
    "TLA_COMPILER_VERSION",
    "TLA_COMPILE_BOUNDS_SCHEMA_VERSION",
    "TLA_PROJECTION_LOSS_SCHEMA_VERSION",
    "TLA_SOURCE_MAP_SCHEMA_VERSION",
    "TLA_TRANSLATOR_ID",
    "GeneratedTLAArtifacts",
    "LossSeverity",
    "ProjectionKind",
    "ProjectionLoss",
    "TLABackend",
    "TLACompileBounds",
    "TLACompiler",
    "TLACompilerError",
    "TLASourceMapEntry",
]
