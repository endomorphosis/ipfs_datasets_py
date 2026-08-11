"""Bridge runtime MTL onto the shared temporal syntax.

Interface:

* ``RuntimeMTLSyntaxAdapter@1`` — bidirectional mapping between
  ``TemporalSyntax@1`` / ``TraceSemanticsProfile@1`` trees and the portable
  ``RuntimeMTLMonitor@1`` formula/trace/result wire format

Runtime MTL formulas use one shared source/parser identity.  Finite traces,
exact-rational time, monitorability, and three-valued verdicts remain explicit
evidence properties.  Incomplete (finite-prefix) traces and every monitor
outcome stay under **monitor** authority and never produce theorem authority.

Evidence subset: syntax mapping, rational intervals, finite trace,
inconclusive verdict, monitorability, source maps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.parsers.temporal import (
    TEMPORAL_FAMILY_ID,
    TEMPORAL_OPERATOR_PAYLOAD_SCHEMA,
    TEMPORAL_SYNTAX_INTERFACE,
    MetricInterval,
    RationalBound,
    TemporalLogicKind,
    TemporalParseResult,
    TimeDomain,
    TraceModelKind,
    TraceSemanticsProfile,
    parse_temporal,
    print_temporal,
    temporal_semantic_identity,
)
from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
    RUNTIME_MTL_INTERFACE,
    RUNTIME_MTL_INTERVAL_SCHEMA_VERSION,
    Formula,
    Logic,
    MonitorAuthority,
    MonitorEvaluation,
    RuntimeMTLMonitor,
    TimeInterval,
    TimeUnit,
    TimeValue,
    Trace,
    TraceKind,
    Verdict,
    evaluate_case,
    evaluate_portable,
    golden_fixtures,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_and,
    mk_extension,
    mk_false,
    mk_implies,
    mk_not,
    mk_or,
    mk_predicate,
    mk_true,
)
from ipfs_datasets_py.logic.syntax_core.contracts import SourceRange

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE: Final = "RuntimeMTLSyntaxAdapter@1"
RUNTIME_MTL_SYNTAX_ADAPTER_SCHEMA_VERSION: Final = "runtime-mtl-syntax-adapter/v1"
RUNTIME_MTL_SOURCE_MAP_SCHEMA_VERSION: Final = "runtime-mtl-source-map/v1"
RUNTIME_MTL_MAPPING_RECEIPT_SCHEMA_VERSION: Final = "runtime-mtl-mapping-receipt/v1"
RUNTIME_MTL_EVAL_RECEIPT_SCHEMA_VERSION: Final = "runtime-mtl-eval-receipt/v1"
ADAPTER_MODULE_VERSION: Final = "1.0.0"

_TEMPORAL_OPS: Final[frozenset[str]] = frozenset(
    {
        "next",
        "previous",
        "eventually",
        "always",
        "until",
        "release",
        "weak_until",
        "since",
    }
)
_PAST_OPS: Final[frozenset[str]] = frozenset({"previous", "once", "historically", "since"})

_DEFAULT_TIME_UNIT: Final = TimeUnit.LOGICAL_TICK


class RuntimeMTLAdapterError(ValueError):
    """Raised when temporal ↔ runtime MTL mapping fails closed."""


# ---------------------------------------------------------------------------
# Source maps
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLSourceMapEntry:
    """One temporal-node ↔ runtime-formula-node correspondence."""

    temporal_node_id: str
    runtime_node_id: str
    kind: str
    range: SourceRange | None = None
    operator: str = ""
    proposition: str = ""
    schema_version: str = RUNTIME_MTL_SOURCE_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.temporal_node_id, str) or not self.temporal_node_id:
            raise RuntimeMTLAdapterError("temporal_node_id must be a non-empty string")
        if not isinstance(self.runtime_node_id, str) or not self.runtime_node_id:
            raise RuntimeMTLAdapterError("runtime_node_id must be a non-empty string")
        if not isinstance(self.kind, str) or not self.kind:
            raise RuntimeMTLAdapterError("kind must be a non-empty string")
        if self.schema_version != RUNTIME_MTL_SOURCE_MAP_SCHEMA_VERSION:
            raise RuntimeMTLAdapterError(
                f"unsupported source-map schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "operator": self.operator,
            "proposition": self.proposition,
            "range": None
            if self.range is None
            else {"end": self.range.end, "start": self.range.start},
            "runtime_node_id": self.runtime_node_id,
            "schema_version": self.schema_version,
            "temporal_node_id": self.temporal_node_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeMTLSourceMapEntry:
        if not isinstance(value, Mapping):
            raise RuntimeMTLAdapterError("source map entry must be a mapping")
        raw_range = value.get("range")
        span: SourceRange | None = None
        if isinstance(raw_range, Mapping):
            span = SourceRange(start=int(raw_range.get("start", 0)), end=int(raw_range.get("end", 0)))
        return cls(
            temporal_node_id=str(value.get("temporal_node_id") or ""),
            runtime_node_id=str(value.get("runtime_node_id") or ""),
            kind=str(value.get("kind") or ""),
            range=span,
            operator=str(value.get("operator") or ""),
            proposition=str(value.get("proposition") or ""),
            schema_version=str(
                value.get("schema_version") or RUNTIME_MTL_SOURCE_MAP_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Mapping / evaluation receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeMTLMappingReceipt:
    """Deterministic record of a temporal ↔ runtime formula mapping."""

    formula: Formula
    temporal_root: LogicNode | None
    temporal_text: str
    profile: TraceSemanticsProfile
    source_map: tuple[RuntimeMTLSourceMapEntry, ...]
    logic: Logic
    time_unit: TimeUnit
    semantic_identity: dict[str, Any] = field(default_factory=dict)
    schema_version: str = RUNTIME_MTL_MAPPING_RECEIPT_SCHEMA_VERSION
    interface: str = RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.formula, Formula):
            raise RuntimeMTLAdapterError("formula must be a Formula")
        if not isinstance(self.profile, TraceSemanticsProfile):
            raise RuntimeMTLAdapterError("profile must be a TraceSemanticsProfile")
        if not isinstance(self.temporal_text, str):
            raise RuntimeMTLAdapterError("temporal_text must be a string")
        object.__setattr__(self, "source_map", tuple(self.source_map))
        logic = self.logic if isinstance(self.logic, Logic) else Logic(str(self.logic))
        unit = (
            self.time_unit
            if isinstance(self.time_unit, TimeUnit)
            else TimeUnit(str(self.time_unit))
        )
        object.__setattr__(self, "logic", logic)
        object.__setattr__(self, "time_unit", unit)
        if self.schema_version != RUNTIME_MTL_MAPPING_RECEIPT_SCHEMA_VERSION:
            raise RuntimeMTLAdapterError(
                f"unsupported mapping receipt schema {self.schema_version!r}"
            )
        if self.interface != RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE:
            raise RuntimeMTLAdapterError(f"unsupported interface {self.interface!r}")

    @property
    def authorizes_theorem(self) -> bool:
        return False

    @property
    def authorizes_global_proof(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_global_proof": False,
            "authorizes_theorem": False,
            "formula": self.formula.to_dict(),
            "interface": self.interface,
            "logic": self.logic.value,
            "profile": self.profile.to_dict(),
            "schema_version": self.schema_version,
            "semantic_identity": dict(self.semantic_identity),
            "source_map": [entry.to_dict() for entry in self.source_map],
            "temporal_syntax_interface": TEMPORAL_SYNTAX_INTERFACE,
            "temporal_text": self.temporal_text,
            "time_unit": self.time_unit.value,
        }


@dataclass(frozen=True, slots=True)
class RuntimeMTLEvalReceipt:
    """Monitor evaluation under the syntax adapter authority ceiling."""

    evaluation: MonitorEvaluation
    mapping: RuntimeMTLMappingReceipt
    monitorability: str
    finite_trace: bool
    incomplete_trace: bool
    three_valued_verdict: str
    schema_version: str = RUNTIME_MTL_EVAL_RECEIPT_SCHEMA_VERSION
    interface: str = RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation, MonitorEvaluation):
            raise RuntimeMTLAdapterError("evaluation must be a MonitorEvaluation")
        if not isinstance(self.mapping, RuntimeMTLMappingReceipt):
            raise RuntimeMTLAdapterError("mapping must be a RuntimeMTLMappingReceipt")
        if self.evaluation.authority is not MonitorAuthority.MONITOR:
            raise RuntimeMTLAdapterError(
                "adapter evaluation results always have monitor authority"
            )
        if self.evaluation.authorizes_global_proof:
            raise RuntimeMTLAdapterError(
                "incomplete or monitor outcomes never authorize global proof"
            )
        if self.schema_version != RUNTIME_MTL_EVAL_RECEIPT_SCHEMA_VERSION:
            raise RuntimeMTLAdapterError(
                f"unsupported eval receipt schema {self.schema_version!r}"
            )
        if self.interface != RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE:
            raise RuntimeMTLAdapterError(f"unsupported interface {self.interface!r}")

    @property
    def authorizes_theorem(self) -> bool:
        """Hard ceiling: monitor evidence never becomes theorem authority."""

        return False

    @property
    def authorizes_global_proof(self) -> bool:
        return False

    @property
    def authority(self) -> str:
        return MonitorAuthority.MONITOR.value

    def promote_to_theorem(self) -> None:
        """Fail closed: no path upgrades monitor evidence to theorem authority."""

        raise RuntimeMTLAdapterError(
            "runtime MTL monitor results cannot be promoted to theorem authority "
            f"(verdict={self.evaluation.verdict.value}, "
            f"trace_kind={self.evaluation.trace_kind.value}, "
            f"incomplete_trace={self.incomplete_trace})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "authorizes_global_proof": False,
            "authorizes_theorem": False,
            "evaluation": self.evaluation.to_dict(),
            "finite_trace": self.finite_trace,
            "incomplete_trace": self.incomplete_trace,
            "interface": self.interface,
            "mapping": self.mapping.to_dict(),
            "monitorability": self.monitorability,
            "schema_version": self.schema_version,
            "three_valued_verdict": self.three_valued_verdict,
        }


# ---------------------------------------------------------------------------
# Interval codec (exact rationals)
# ---------------------------------------------------------------------------


def metric_interval_to_runtime(
    interval: MetricInterval | Mapping[str, Any],
    *,
    unit: TimeUnit | str = _DEFAULT_TIME_UNIT,
) -> TimeInterval:
    """Map a shared temporal ``MetricInterval`` to a runtime ``TimeInterval``."""

    metric = (
        interval
        if isinstance(interval, MetricInterval)
        else MetricInterval.from_dict(interval)
    )
    clock_unit = unit if isinstance(unit, TimeUnit) else TimeUnit(str(unit))
    return TimeInterval(
        lower=TimeValue(metric.lower.numerator, metric.lower.denominator),
        upper=TimeValue(metric.upper.numerator, metric.upper.denominator),
        unit=clock_unit,
        lower_closed=metric.lower_closed,
        upper_closed=metric.upper_closed,
        schema_version=RUNTIME_MTL_INTERVAL_SCHEMA_VERSION,
    )


def runtime_interval_to_metric(
    interval: TimeInterval | Mapping[str, Any],
) -> MetricInterval:
    """Map a runtime ``TimeInterval`` to a shared temporal ``MetricInterval``.

    Shared temporal syntax rejects unbounded intervals; conversion fails closed
    when the runtime upper bound is absent.
    """

    runtime = (
        interval
        if isinstance(interval, TimeInterval)
        else TimeInterval.from_dict(interval)
    )
    if runtime.upper is None:
        raise RuntimeMTLAdapterError(
            "shared temporal syntax rejects unbounded metric intervals; "
            "runtime interval upper bound is required for syntax mapping"
        )
    return MetricInterval(
        lower=RationalBound(runtime.lower.numerator, runtime.lower.denominator),
        upper=RationalBound(runtime.upper.numerator, runtime.upper.denominator),
        lower_closed=runtime.lower_closed,
        upper_closed=runtime.upper_closed,
    )


# ---------------------------------------------------------------------------
# Profile selection
# ---------------------------------------------------------------------------


def _formula_uses_past(formula: Formula) -> bool:
    if formula.operator in _PAST_OPS:
        return True
    return any(_formula_uses_past(operand) for operand in formula.operands)


def profile_for_runtime_formula(
    formula: Formula,
    *,
    profile_id: str | None = None,
) -> TraceSemanticsProfile:
    """Choose a ``TraceSemanticsProfile`` compatible with *formula*."""

    if not isinstance(formula, Formula):
        raise RuntimeMTLAdapterError("formula must be a Formula")
    uses_past = _formula_uses_past(formula)
    if formula.logic is Logic.MTL:
        return TraceSemanticsProfile(
            profile_id=profile_id or "runtime_mtl_finite",
            logic=TemporalLogicKind.MTL,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.FINITE,
            metric_intervals=True,
            allow_past=uses_past,
        )
    if formula.logic is Logic.LTLF:
        return TraceSemanticsProfile(
            profile_id=profile_id or "runtime_ltlf_finite",
            logic=TemporalLogicKind.LTLF,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.FINITE,
            metric_intervals=False,
            allow_past=uses_past,
        )
    raise RuntimeMTLAdapterError(f"unsupported runtime logic {formula.logic!r}")


def profile_for_logic(
    logic: Logic | str,
    *,
    allow_past: bool = False,
    profile_id: str | None = None,
) -> TraceSemanticsProfile:
    """Build a finite-trace profile for the given runtime logic label."""

    logic_enum = logic if isinstance(logic, Logic) else Logic(str(logic))
    if logic_enum is Logic.MTL:
        return TraceSemanticsProfile(
            profile_id=profile_id or "runtime_mtl_finite",
            logic=TemporalLogicKind.MTL,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.FINITE,
            metric_intervals=True,
            allow_past=allow_past,
        )
    if logic_enum is Logic.LTLF:
        return TraceSemanticsProfile(
            profile_id=profile_id or "runtime_ltlf_finite",
            logic=TemporalLogicKind.LTLF,
            time_domain=TimeDomain.DISCRETE,
            trace_model=TraceModelKind.FINITE,
            metric_intervals=False,
            allow_past=allow_past,
        )
    raise RuntimeMTLAdapterError(f"unsupported runtime logic {logic!r}")


# ---------------------------------------------------------------------------
# Temporal AST → runtime Formula
# ---------------------------------------------------------------------------


def _kind_of(node: LogicNode) -> str:
    kind = node.kind
    return kind.value if isinstance(kind, NodeKind) else str(kind)


def _logic_from_profile(profile: TraceSemanticsProfile) -> Logic:
    logic = profile.logic
    value = logic.value if isinstance(logic, TemporalLogicKind) else str(logic)
    if value == TemporalLogicKind.MTL.value:
        return Logic.MTL
    if value in {
        TemporalLogicKind.LTLF.value,
        TemporalLogicKind.LTL.value,
        TemporalLogicKind.PAST_LTL.value,
    }:
        # Runtime monitor surface is finite-trace only; LTL/past_ltl profiles
        # lower to LTLf wire logic under the adapter contract.
        return Logic.LTLF
    raise RuntimeMTLAdapterError(
        f"profile logic {value!r} is not admitted by RuntimeMTLSyntaxAdapter"
    )


def temporal_node_to_formula(
    node: LogicNode | TypedExpression,
    *,
    logic: Logic | str | None = None,
    time_unit: TimeUnit | str = _DEFAULT_TIME_UNIT,
    profile: TraceSemanticsProfile | None = None,
    source_map: list[RuntimeMTLSourceMapEntry] | None = None,
) -> Formula:
    """Lower a shared temporal ``LogicNode`` to a portable runtime ``Formula``."""

    root = node.root if isinstance(node, TypedExpression) else node
    if not isinstance(root, LogicNode):
        raise RuntimeMTLAdapterError("temporal_node_to_formula requires a LogicNode")
    if logic is None:
        if profile is not None:
            logic_enum = _logic_from_profile(profile)
        else:
            logic_enum = Logic.LTLF
    else:
        logic_enum = logic if isinstance(logic, Logic) else Logic(str(logic))
    unit = time_unit if isinstance(time_unit, TimeUnit) else TimeUnit(str(time_unit))
    entries = source_map if source_map is not None else []

    def walk(n: LogicNode) -> Formula:
        kind = _kind_of(n)
        if kind == NodeKind.TRUE.value:
            formula = Formula.truth(logic=logic_enum)
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="true",
                    range=n.range,
                    operator="true",
                )
            )
            return formula
        if kind == NodeKind.FALSE.value:
            formula = Formula.falsehood(logic=logic_enum)
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="false",
                    range=n.range,
                    operator="false",
                )
            )
            return formula
        if kind == NodeKind.PREDICATE.value:
            if n.arguments:
                raise RuntimeMTLAdapterError(
                    "runtime MTL admits only nullary propositional atoms"
                )
            if not n.symbol:
                raise RuntimeMTLAdapterError("predicate atom requires a symbol")
            formula = Formula.atom(n.symbol, logic=logic_enum)
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="atom",
                    range=n.range,
                    operator="atom",
                    proposition=n.symbol,
                )
            )
            return formula
        if kind == NodeKind.NOT.value:
            child = walk(n.arguments[0])
            formula = Formula("not", logic_enum, (child,))
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="not",
                    range=n.range,
                    operator="not",
                )
            )
            return formula
        if kind == NodeKind.AND.value:
            if len(n.arguments) < 2:
                raise RuntimeMTLAdapterError("and requires at least two arguments")
            # Runtime Formula is binary; fold left-associatively.
            formula = walk(n.arguments[0])
            for arg in n.arguments[1:]:
                formula = Formula("and", logic_enum, (formula, walk(arg)))
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="and",
                    range=n.range,
                    operator="and",
                )
            )
            return formula
        if kind == NodeKind.OR.value:
            if len(n.arguments) < 2:
                raise RuntimeMTLAdapterError("or requires at least two arguments")
            formula = walk(n.arguments[0])
            for arg in n.arguments[1:]:
                formula = Formula("or", logic_enum, (formula, walk(arg)))
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="or",
                    range=n.range,
                    operator="or",
                )
            )
            return formula
        if kind == NodeKind.IMPLIES.value:
            left = walk(n.arguments[0])
            right = walk(n.arguments[1])
            formula = Formula("implies", logic_enum, (left, right))
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="implies",
                    range=n.range,
                    operator="implies",
                )
            )
            return formula
        if kind == NodeKind.IFF.value:
            # Runtime wire has no iff; expand to (a→b) ∧ (b→a).
            left = walk(n.arguments[0])
            right = walk(n.arguments[1])
            forward = Formula("implies", logic_enum, (left, right))
            backward = Formula("implies", logic_enum, (right, left))
            formula = Formula("and", logic_enum, (forward, backward))
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind="iff",
                    range=n.range,
                    operator="iff",
                )
            )
            return formula
        if kind == NodeKind.EXTENSION.value:
            if n.extension is None:
                raise RuntimeMTLAdapterError("extension node missing payload")
            payload = dict(n.extension.payload)
            op = str(payload.get("kind") or "")
            if op == "path":
                raise RuntimeMTLAdapterError(
                    "path quantifiers are not admitted by runtime MTL monitors"
                )
            # Shared temporal admits once/historically; the portable runtime wire
            # does not.  Fail closed rather than miscompile past-eventually /
            # past-always into previous/always.
            if op in {"once", "historically"}:
                raise RuntimeMTLAdapterError(
                    f"shared temporal {op!r} has no portable runtime MTL operator; "
                    "use previous/since on the runtime wire"
                )
            if op not in _TEMPORAL_OPS:
                raise RuntimeMTLAdapterError(
                    f"unsupported temporal extension kind {op!r} for runtime MTL"
                )
            children = n.extension.children
            if op in {"next", "previous", "eventually", "always"}:
                if len(children) != 1:
                    raise RuntimeMTLAdapterError(f"{op} requires one operand")
                child = walk(children[0])
                interval = None
                raw_interval = payload.get("interval")
                if raw_interval is not None:
                    interval = metric_interval_to_runtime(raw_interval, unit=unit)
                elif logic_enum is Logic.MTL:
                    raise RuntimeMTLAdapterError(
                        f"MTL temporal operator {op!r} requires a metric interval"
                    )
                formula = Formula(op, logic_enum, (child,), interval=interval)
            elif op in {"until", "release", "weak_until", "since"}:
                if len(children) != 2:
                    raise RuntimeMTLAdapterError(f"{op} requires two operands")
                left = walk(children[0])
                right = walk(children[1])
                interval = None
                raw_interval = payload.get("interval")
                if raw_interval is not None:
                    interval = metric_interval_to_runtime(raw_interval, unit=unit)
                elif logic_enum is Logic.MTL:
                    raise RuntimeMTLAdapterError(
                        f"MTL temporal operator {op!r} requires a metric interval"
                    )
                formula = Formula(op, logic_enum, (left, right), interval=interval)
            else:
                raise RuntimeMTLAdapterError(f"unsupported temporal operator {op!r}")
            entries.append(
                RuntimeMTLSourceMapEntry(
                    temporal_node_id=n.node_id or formula.node_id,
                    runtime_node_id=formula.node_id,
                    kind=op,
                    range=n.range,
                    operator=op,
                )
            )
            return formula
        raise RuntimeMTLAdapterError(
            f"node kind {kind!r} is not admitted by runtime MTL syntax mapping"
        )

    return walk(root)


# ---------------------------------------------------------------------------
# Runtime Formula → temporal AST / text
# ---------------------------------------------------------------------------


def _mk_temporal_extension(
    operator: str,
    children: Sequence[LogicNode],
    *,
    profile: TraceSemanticsProfile,
    interval: TimeInterval | None,
    node_id: str,
) -> LogicNode:
    payload: dict[str, Any] = {
        "kind": operator,
        "logic": profile.logic.value
        if isinstance(profile.logic, TemporalLogicKind)
        else str(profile.logic),
        "profile_id": profile.profile_id,
        "schema_version": TEMPORAL_OPERATOR_PAYLOAD_SCHEMA,
        "time_domain": profile.time_domain.value
        if isinstance(profile.time_domain, TimeDomain)
        else str(profile.time_domain),
        "trace_model": profile.trace_model.value
        if isinstance(profile.trace_model, TraceModelKind)
        else str(profile.trace_model),
    }
    if interval is not None:
        payload["interval"] = runtime_interval_to_metric(interval).to_dict()
    elif profile.metric_intervals:
        raise RuntimeMTLAdapterError(
            f"MTL temporal operator {operator!r} requires a bounded interval"
        )
    return mk_extension(
        node_id,
        family=TEMPORAL_FAMILY_ID,
        profile=profile.profile_id,
        features=(f"temporal.{operator}",),
        payload_schema=TEMPORAL_OPERATOR_PAYLOAD_SCHEMA,
        payload=payload,
        children=tuple(children),
    )


def formula_to_temporal_node(
    formula: Formula | Mapping[str, Any],
    *,
    profile: TraceSemanticsProfile | None = None,
    source_map: list[RuntimeMTLSourceMapEntry] | None = None,
    node_id_prefix: str = "node:runtime",
) -> LogicNode:
    """Raise a portable runtime ``Formula`` into a shared temporal ``LogicNode``."""

    formula_obj = formula if isinstance(formula, Formula) else Formula.from_dict(formula)
    prof = profile or profile_for_runtime_formula(formula_obj)
    expected = _logic_from_profile(prof)
    if formula_obj.logic is Logic.MTL and expected is not Logic.MTL:
        raise RuntimeMTLAdapterError("MTL formula requires an MTL temporal profile")
    if formula_obj.logic is Logic.LTLF and prof.metric_intervals:
        raise RuntimeMTLAdapterError("LTLf formula rejects MTL metric profiles")
    entries = source_map if source_map is not None else []
    counter = [0]

    def nid(label: str) -> str:
        counter[0] += 1
        return f"{node_id_prefix}:{label}:{counter[0]}"

    def walk(f: Formula) -> LogicNode:
        op = f.operator
        if op == "true":
            node = mk_true(nid("true"))
        elif op == "false":
            node = mk_false(nid("false"))
        elif op == "atom":
            node = mk_predicate(nid("atom"), f.proposition)
        elif op == "not":
            node = mk_not(nid("not"), walk(f.operands[0]))
        elif op == "and":
            node = mk_and(nid("and"), walk(f.operands[0]), walk(f.operands[1]))
        elif op == "or":
            node = mk_or(nid("or"), walk(f.operands[0]), walk(f.operands[1]))
        elif op == "implies":
            node = mk_implies(
                nid("implies"), walk(f.operands[0]), walk(f.operands[1])
            )
        elif op in _TEMPORAL_OPS:
            children = tuple(walk(child) for child in f.operands)
            node = _mk_temporal_extension(
                op,
                children,
                profile=prof,
                interval=f.interval,
                node_id=nid(op),
            )
        else:
            raise RuntimeMTLAdapterError(
                f"runtime operator {op!r} has no shared temporal mapping"
            )
        entries.append(
            RuntimeMTLSourceMapEntry(
                temporal_node_id=node.node_id,
                runtime_node_id=f.node_id,
                kind=op,
                range=node.range,
                operator=op,
                proposition=f.proposition if op == "atom" else "",
            )
        )
        return node

    return walk(formula_obj)


def formula_to_temporal_text(
    formula: Formula | Mapping[str, Any],
    *,
    profile: TraceSemanticsProfile | None = None,
    style: str = "ascii",
) -> str:
    """Print a portable runtime formula in shared temporal surface syntax."""

    formula_obj = formula if isinstance(formula, Formula) else Formula.from_dict(formula)
    prof = profile or profile_for_runtime_formula(formula_obj)
    node = formula_to_temporal_node(formula_obj, profile=prof)
    return print_temporal(node, style=style)


# ---------------------------------------------------------------------------
# Adapter facade
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuntimeMTLSyntaxAdapter:
    """``RuntimeMTLSyntaxAdapter@1`` — shared temporal ↔ runtime MTL bridge.

    Preserves runtime monitor wire compatibility while giving formulas a single
    shared temporal parser identity.  Evaluation evidence always carries
    monitor authority; incomplete traces never produce theorem authority.
    """

    interface: ClassVar[str] = RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE
    schema_version: ClassVar[str] = RUNTIME_MTL_SYNTAX_ADAPTER_SCHEMA_VERSION
    module_version: ClassVar[str] = ADAPTER_MODULE_VERSION

    default_time_unit: TimeUnit | str = _DEFAULT_TIME_UNIT
    print_style: str = "ascii"

    def __post_init__(self) -> None:
        unit = self.default_time_unit
        if not isinstance(unit, TimeUnit):
            unit = TimeUnit(str(unit))
        self.default_time_unit = unit

    # -- mapping ------------------------------------------------------------

    def map_formula(
        self,
        formula: Formula | Mapping[str, Any],
        *,
        profile: TraceSemanticsProfile | None = None,
        time_unit: TimeUnit | str | None = None,
    ) -> RuntimeMTLMappingReceipt:
        """Map a portable formula to shared temporal text with source maps."""

        formula_obj = (
            formula if isinstance(formula, Formula) else Formula.from_dict(formula)
        )
        unit = (
            time_unit
            if time_unit is not None
            else self.default_time_unit
        )
        if not isinstance(unit, TimeUnit):
            unit = TimeUnit(str(unit))
        # Prefer unit from the first interval when present.
        unit = _first_interval_unit(formula_obj) or unit
        prof = profile or profile_for_runtime_formula(formula_obj)
        entries: list[RuntimeMTLSourceMapEntry] = []
        root = formula_to_temporal_node(
            formula_obj, profile=prof, source_map=entries
        )
        text = print_temporal(root, style=self.print_style)
        identity = temporal_semantic_identity(root, prof)
        return RuntimeMTLMappingReceipt(
            formula=formula_obj,
            temporal_root=root,
            temporal_text=text,
            profile=prof,
            source_map=tuple(entries),
            logic=formula_obj.logic,
            time_unit=unit,
            semantic_identity=identity,
        )

    def parse_text(
        self,
        text: str,
        *,
        logic: Logic | str = Logic.LTLF,
        profile: TraceSemanticsProfile | None = None,
        time_unit: TimeUnit | str | None = None,
        allow_past: bool = False,
        document_id: str = "doc:runtime-mtl:1",
    ) -> RuntimeMTLMappingReceipt:
        """Parse shared temporal text into a portable runtime formula."""

        logic_enum = logic if isinstance(logic, Logic) else Logic(str(logic))
        unit = (
            time_unit
            if time_unit is not None
            else self.default_time_unit
        )
        if not isinstance(unit, TimeUnit):
            unit = TimeUnit(str(unit))
        prof = profile or profile_for_logic(
            logic_enum, allow_past=allow_past
        )
        # Enforce profile/logic agreement for MTL.
        if logic_enum is Logic.MTL and not prof.metric_intervals:
            raise RuntimeMTLAdapterError("MTL parse requires a metric temporal profile")
        result = parse_temporal(
            text,
            prof,
            document_id=document_id,
            print_style=self.print_style,
        )
        if not result.ok or result.root is None:
            messages = "; ".join(item.message for item in result.errors) or "parse failed"
            raise RuntimeMTLAdapterError(
                f"shared temporal parse rejected: {messages}"
            )
        entries: list[RuntimeMTLSourceMapEntry] = []
        formula = temporal_node_to_formula(
            result.root,
            logic=logic_enum,
            time_unit=unit,
            profile=prof,
            source_map=entries,
        )
        printed = result.printed or print_temporal(result.root, style=self.print_style)
        identity = temporal_semantic_identity(result.root, prof)
        return RuntimeMTLMappingReceipt(
            formula=formula,
            temporal_root=result.root,
            temporal_text=printed,
            profile=prof,
            source_map=tuple(entries),
            logic=logic_enum,
            time_unit=unit,
            semantic_identity=identity,
        )

    def round_trip_formula(
        self,
        formula: Formula | Mapping[str, Any],
        *,
        profile: TraceSemanticsProfile | None = None,
        time_unit: TimeUnit | str | None = None,
    ) -> RuntimeMTLMappingReceipt:
        """Formula → temporal text → formula; semantic identity must agree."""

        first = self.map_formula(formula, profile=profile, time_unit=time_unit)
        second = self.parse_text(
            first.temporal_text,
            logic=first.logic,
            profile=first.profile,
            time_unit=first.time_unit,
            allow_past=first.profile.allow_past,
        )
        if first.formula.semantic_dict() != second.formula.semantic_dict():
            raise RuntimeMTLAdapterError(
                "runtime formula round-trip lost semantic identity: "
                f"{first.formula.semantic_dict()!r} != {second.formula.semantic_dict()!r}"
            )
        return second

    def temporal_to_formula(
        self,
        node: LogicNode | TypedExpression | TemporalParseResult,
        *,
        logic: Logic | str | None = None,
        time_unit: TimeUnit | str | None = None,
        profile: TraceSemanticsProfile | None = None,
    ) -> Formula:
        """Lower a temporal AST (or parse result) to a portable formula."""

        if isinstance(node, TemporalParseResult):
            if not node.ok or node.root is None:
                raise RuntimeMTLAdapterError("temporal parse result is not successful")
            prof = profile or node.profile
            root = node.root
        elif isinstance(node, TypedExpression):
            root = node.root
            prof = profile
        else:
            root = node
            prof = profile
        unit = time_unit if time_unit is not None else self.default_time_unit
        return temporal_node_to_formula(
            root,
            logic=logic,
            time_unit=unit,
            profile=prof,
        )

    def formula_to_text(
        self,
        formula: Formula | Mapping[str, Any],
        *,
        profile: TraceSemanticsProfile | None = None,
    ) -> str:
        return formula_to_temporal_text(
            formula, profile=profile, style=self.print_style
        )

    # -- evaluation (authority ceiling: monitor) ----------------------------

    def evaluate(
        self,
        formula: Formula | Mapping[str, Any],
        trace: Trace | Mapping[str, Any],
        *,
        position: int = 0,
        profile: TraceSemanticsProfile | None = None,
        time_unit: TimeUnit | str | None = None,
    ) -> RuntimeMTLEvalReceipt:
        """Evaluate *formula* on *trace* under the adapter authority ceiling."""

        mapping = self.map_formula(formula, profile=profile, time_unit=time_unit)
        evaluation = evaluate_portable(mapping.formula, trace, position=position)
        return self._receipt_from_evaluation(evaluation, mapping)

    def evaluate_text(
        self,
        text: str,
        trace: Trace | Mapping[str, Any],
        *,
        logic: Logic | str = Logic.LTLF,
        position: int = 0,
        profile: TraceSemanticsProfile | None = None,
        time_unit: TimeUnit | str | None = None,
        allow_past: bool = False,
    ) -> RuntimeMTLEvalReceipt:
        """Parse shared temporal *text* then evaluate under monitor authority."""

        mapping = self.parse_text(
            text,
            logic=logic,
            profile=profile,
            time_unit=time_unit,
            allow_past=allow_past,
        )
        evaluation = evaluate_portable(mapping.formula, trace, position=position)
        return self._receipt_from_evaluation(evaluation, mapping)

    def evaluate_case(
        self,
        case: Mapping[str, Any],
    ) -> RuntimeMTLEvalReceipt:
        """Evaluate a portable golden/parity case through the syntax adapter."""

        if not isinstance(case, Mapping):
            raise RuntimeMTLAdapterError("case must be a mapping")
        formula = Formula.from_dict(case["formula"])
        mapping = self.map_formula(formula)
        # Preserve wire-compatible evaluation for golden stability.
        evaluation = MonitorEvaluation.from_dict(
            evaluate_case(
                {
                    "formula": case["formula"],
                    "trace": case["trace"],
                    "position": case.get("position", 0),
                }
            )
        )
        # Cross-check adapter-mapped formula semantic identity.
        if formula.semantic_dict() != mapping.formula.semantic_dict():
            raise RuntimeMTLAdapterError(
                "adapter mapping altered golden formula semantic identity"
            )
        return self._receipt_from_evaluation(evaluation, mapping)

    def _receipt_from_evaluation(
        self,
        evaluation: MonitorEvaluation,
        mapping: RuntimeMTLMappingReceipt,
    ) -> RuntimeMTLEvalReceipt:
        if evaluation.authority is not MonitorAuthority.MONITOR:
            raise RuntimeMTLAdapterError("evaluation authority must be monitor")
        if evaluation.authorizes_global_proof:
            raise RuntimeMTLAdapterError(
                "monitor evaluation must not authorize global proof"
            )
        incomplete = evaluation.trace_kind is TraceKind.FINITE_PREFIX
        finite = evaluation.trace_kind in {TraceKind.FINITE, TraceKind.FINITE_PREFIX}
        # Incomplete traces with inconclusive verdicts never become theorems.
        if incomplete and evaluation.verdict is Verdict.INCONCLUSIVE:
            if evaluation.authorizes_global_proof or evaluation.authority is not MonitorAuthority.MONITOR:
                raise RuntimeMTLAdapterError(
                    "incomplete inconclusive traces cannot carry theorem authority"
                )
        return RuntimeMTLEvalReceipt(
            evaluation=evaluation,
            mapping=mapping,
            monitorability=evaluation.monitorability.value
            if hasattr(evaluation.monitorability, "value")
            else str(evaluation.monitorability),
            finite_trace=finite,
            incomplete_trace=incomplete,
            three_valued_verdict=evaluation.verdict.value
            if hasattr(evaluation.verdict, "value")
            else str(evaluation.verdict),
        )

    # -- golden / cross-runtime ---------------------------------------------

    def golden_cases(self) -> list[dict[str, Any]]:
        """Return the portable golden fixtures (Python ↔ TypeScript parity)."""

        return golden_fixtures()

    def assert_golden_stable(self) -> list[RuntimeMTLEvalReceipt]:
        """Evaluate every golden case; fail if verdicts or authority drift."""

        receipts: list[RuntimeMTLEvalReceipt] = []
        for case in self.golden_cases():
            receipt = self.evaluate_case(case)
            expected = case.get("expected") or {}
            result = receipt.evaluation.to_dict()
            for key, value in expected.items():
                if result.get(key) != value:
                    raise RuntimeMTLAdapterError(
                        f"golden case {case.get('case_id')!r} drifted on {key}: "
                        f"expected {value!r}, got {result.get(key)!r}"
                    )
            if result["authority"] != MonitorAuthority.MONITOR.value:
                raise RuntimeMTLAdapterError(
                    f"golden case {case.get('case_id')!r} lost monitor authority"
                )
            if result["authorizes_global_proof"] is not False:
                raise RuntimeMTLAdapterError(
                    f"golden case {case.get('case_id')!r} gained proof authority"
                )
            if receipt.authorizes_theorem:
                raise RuntimeMTLAdapterError(
                    f"golden case {case.get('case_id')!r} produced theorem authority"
                )
            receipts.append(receipt)
        return receipts

    def monitor_from_text(
        self,
        text: str,
        *,
        logic: Logic | str = Logic.LTLF,
        position: int = 0,
        profile: TraceSemanticsProfile | None = None,
        time_unit: TimeUnit | str | None = None,
        allow_past: bool = False,
    ) -> RuntimeMTLMonitor:
        """Build a wire-compatible ``RuntimeMTLMonitor`` from temporal text."""

        mapping = self.parse_text(
            text,
            logic=logic,
            profile=profile,
            time_unit=time_unit,
            allow_past=allow_past,
        )
        return RuntimeMTLMonitor(formula=mapping.formula, position=position)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_time_unit": self.default_time_unit.value
            if isinstance(self.default_time_unit, TimeUnit)
            else str(self.default_time_unit),
            "interface": self.interface,
            "module_version": self.module_version,
            "print_style": self.print_style,
            "runtime_mtl_interface": RUNTIME_MTL_INTERFACE,
            "schema_version": self.schema_version,
            "temporal_syntax_interface": TEMPORAL_SYNTAX_INTERFACE,
        }


def _first_interval_unit(formula: Formula) -> TimeUnit | None:
    if formula.interval is not None:
        return formula.interval.unit
    for operand in formula.operands:
        found = _first_interval_unit(operand)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def adapt_formula(
    formula: Formula | Mapping[str, Any],
    *,
    time_unit: TimeUnit | str = _DEFAULT_TIME_UNIT,
) -> RuntimeMTLMappingReceipt:
    """Map a portable formula through the default adapter."""

    return RuntimeMTLSyntaxAdapter(default_time_unit=time_unit).map_formula(
        formula, time_unit=time_unit
    )


def adapt_text(
    text: str,
    *,
    logic: Logic | str = Logic.LTLF,
    time_unit: TimeUnit | str = _DEFAULT_TIME_UNIT,
    allow_past: bool = False,
) -> RuntimeMTLMappingReceipt:
    """Parse shared temporal text into a portable formula via the adapter."""

    return RuntimeMTLSyntaxAdapter(default_time_unit=time_unit).parse_text(
        text, logic=logic, time_unit=time_unit, allow_past=allow_past
    )


def evaluate_adapted(
    formula: Formula | Mapping[str, Any],
    trace: Trace | Mapping[str, Any],
    *,
    position: int = 0,
) -> RuntimeMTLEvalReceipt:
    """Evaluate a formula under the adapter authority ceiling."""

    return RuntimeMTLSyntaxAdapter().evaluate(formula, trace, position=position)


__all__ = [
    "ADAPTER_MODULE_VERSION",
    "RUNTIME_MTL_EVAL_RECEIPT_SCHEMA_VERSION",
    "RUNTIME_MTL_MAPPING_RECEIPT_SCHEMA_VERSION",
    "RUNTIME_MTL_SOURCE_MAP_SCHEMA_VERSION",
    "RUNTIME_MTL_SYNTAX_ADAPTER_INTERFACE",
    "RUNTIME_MTL_SYNTAX_ADAPTER_SCHEMA_VERSION",
    "RuntimeMTLAdapterError",
    "RuntimeMTLEvalReceipt",
    "RuntimeMTLMappingReceipt",
    "RuntimeMTLSourceMapEntry",
    "RuntimeMTLSyntaxAdapter",
    "adapt_formula",
    "adapt_text",
    "evaluate_adapted",
    "formula_to_temporal_node",
    "formula_to_temporal_text",
    "metric_interval_to_runtime",
    "profile_for_logic",
    "profile_for_runtime_formula",
    "runtime_interval_to_metric",
    "temporal_node_to_formula",
]
