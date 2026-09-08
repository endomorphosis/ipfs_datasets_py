"""Compositional assume-guarantee discharge over canonical contracts.

The engine compares typed predicates by lowering ``G and not A`` to the
existing SMT term IR and the reusable solver contract.  Prose/opaque clauses
remain uncovered.  Cyclic reasoning requires a typed induction invariant and
an independently solved closure obligation; mutual citation alone is rejected.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtTerm,
    SmtTermKind,
    term_and,
    term_eq,
    term_int,
    term_not,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.incremental import (
    IncrementalSmtResult,
    SmtCheckStatus,
    open_incremental_smt_session,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.software_contracts.compositional import (
    CompositionalContract,
    SemanticContractClause,
    SemanticSupport,
)

ASSUME_GUARANTEE_INTERFACE: Final = "AssumeGuaranteeDischarge@1"
ASSUME_GUARANTEE_GRAPH_SCHEMA: Final = "assume-guarantee-graph/v1"
ASSUME_GUARANTEE_RECEIPT_SCHEMA: Final = "assume-guarantee-discharge-receipt/v1"


class AssumeGuaranteeError(ValueError):
    """Raised for malformed or stale composition requests."""


class DischargeDisposition(StrEnum):
    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    STALE = "stale"
    REJECTED_CYCLE = "rejected_cycle"
    UNAVAILABLE = "unavailable"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise AssumeGuaranteeError(f"{label} must be a trimmed non-empty string")
    return value


def _unique(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise AssumeGuaranteeError(f"{label} must be a sequence")
    result = tuple(sorted(_text(item, f"{label} item") for item in values))
    if len(result) != len(set(result)):
        raise AssumeGuaranteeError(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class CompositionEdge:
    """Exact producer-to-consumer dependency and its semantic interface."""

    edge_id: str
    producer_component_id: str
    consumer_component_id: str
    guarantee_clause_ids: tuple[str, ...]
    assumption_clause_ids: tuple[str, ...]
    exceptional_guarantee_clause_ids: tuple[str, ...] = ()
    exceptional_assumption_clause_ids: tuple[str, ...] = ()
    induction_invariant_clause_ids: tuple[str, ...] = ()
    source_fact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("edge_id", "producer_component_id", "consumer_component_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "guarantee_clause_ids",
            "assumption_clause_ids",
            "exceptional_guarantee_clause_ids",
            "exceptional_assumption_clause_ids",
            "induction_invariant_clause_ids",
            "source_fact_refs",
        ):
            object.__setattr__(self, name, _unique(getattr(self, name), name))
        if not self.guarantee_clause_ids or not self.assumption_clause_ids:
            raise AssumeGuaranteeError("composition edge requires guarantees and assumptions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_clause_ids": list(self.assumption_clause_ids),
            "consumer_component_id": self.consumer_component_id,
            "edge_id": self.edge_id,
            "exceptional_assumption_clause_ids": list(self.exceptional_assumption_clause_ids),
            "exceptional_guarantee_clause_ids": list(self.exceptional_guarantee_clause_ids),
            "guarantee_clause_ids": list(self.guarantee_clause_ids),
            "induction_invariant_clause_ids": list(self.induction_invariant_clause_ids),
            "producer_component_id": self.producer_component_id,
            "source_fact_refs": list(self.source_fact_refs),
        }


@dataclass(frozen=True, slots=True)
class ComponentCompositionGraph:
    """Content-addressed graph built from exact semantic dependency facts."""

    semantic_state_root: str
    contracts: tuple[CompositionalContract, ...]
    edges: tuple[CompositionEdge, ...]
    acceptance_clause_ids: tuple[str, ...] = ()
    system_invariant_clause_ids: tuple[str, ...] = ()
    schema: str = ASSUME_GUARANTEE_GRAPH_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "semantic_state_root", _text(self.semantic_state_root, "semantic_state_root")
        )
        contracts = tuple(sorted(self.contracts, key=lambda item: item.component_id))
        if not contracts or len({item.component_id for item in contracts}) != len(contracts):
            raise AssumeGuaranteeError("graph requires unique component contracts")
        object.__setattr__(self, "contracts", contracts)
        edges = tuple(sorted(self.edges, key=lambda item: item.edge_id))
        if len({item.edge_id for item in edges}) != len(edges):
            raise AssumeGuaranteeError("edge IDs must be unique")
        components = {item.component_id for item in contracts}
        for edge in edges:
            if (
                edge.producer_component_id not in components
                or edge.consumer_component_id not in components
            ):
                raise AssumeGuaranteeError(f"edge {edge.edge_id} references unknown component")
        object.__setattr__(self, "edges", edges)
        object.__setattr__(
            self,
            "acceptance_clause_ids",
            _unique(self.acceptance_clause_ids, "acceptance_clause_ids"),
        )
        object.__setattr__(
            self,
            "system_invariant_clause_ids",
            _unique(self.system_invariant_clause_ids, "system_invariant_clause_ids"),
        )
        if self.schema != ASSUME_GUARANTEE_GRAPH_SCHEMA:
            raise AssumeGuaranteeError("unsupported graph schema")
        # Validate all clause references now, not during solver execution.
        clause_by_component = {
            item.component_id: {clause.clause_id for clause in item.all_semantic_clauses}
            for item in contracts
        }
        for edge in edges:
            producer_refs = set(edge.guarantee_clause_ids) | set(
                edge.exceptional_guarantee_clause_ids
            )
            consumer_refs = (
                set(edge.assumption_clause_ids)
                | set(edge.exceptional_assumption_clause_ids)
                | set(edge.induction_invariant_clause_ids)
            )
            if not producer_refs <= clause_by_component[edge.producer_component_id]:
                raise AssumeGuaranteeError(f"edge {edge.edge_id} has unknown producer clause")
            if not consumer_refs <= clause_by_component[edge.consumer_component_id]:
                raise AssumeGuaranteeError(f"edge {edge.edge_id} has unknown consumer clause")

    @property
    def contract_root(self) -> str:
        payload = {item.component_id: item.cid for item in self.contracts}
        return canonical_identity(
            payload,
            domain="logic.software-verification.contract-root",
            schema_version="compositional-contract-root/v1",
        ).cid

    @property
    def graph_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.software-verification.assume-guarantee-graph",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_clause_ids": list(self.acceptance_clause_ids),
            "contracts": [item.to_dict() for item in self.contracts],
            "edges": [item.to_dict() for item in self.edges],
            "schema": self.schema,
            "semantic_state_root": self.semantic_state_root,
            "system_invariant_clause_ids": list(self.system_invariant_clause_ids),
        }


@dataclass(frozen=True, slots=True)
class DischargeObligationResult:
    obligation_id: str
    edge_id: str
    guarantee_clause_id: str
    assumption_clause_id: str
    status: DischargeDisposition | str
    solver_receipt_id: str = ""
    unsat_core: tuple[str, ...] = ()
    counterexample: FrozenMap = field(default_factory=FrozenMap)
    reason: str = ""
    induction_hypothesis: bool = False
    independent_closure_check: bool = False

    def __post_init__(self) -> None:
        try:
            value = (
                self.status
                if isinstance(self.status, DischargeDisposition)
                else DischargeDisposition(self.status)
            )
        except ValueError as error:
            raise AssumeGuaranteeError(str(error)) from error
        object.__setattr__(self, "status", value)
        object.__setattr__(
            self,
            "counterexample",
            self.counterexample
            if isinstance(self.counterexample, FrozenMap)
            else FrozenMap(self.counterexample),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_clause_id": self.assumption_clause_id,
            "counterexample": self.counterexample.to_dict(),
            "edge_id": self.edge_id,
            "guarantee_clause_id": self.guarantee_clause_id,
            "independent_closure_check": self.independent_closure_check,
            "induction_hypothesis": self.induction_hypothesis,
            "obligation_id": self.obligation_id,
            "reason": self.reason,
            "solver_receipt_id": self.solver_receipt_id,
            "status": (
                self.status.value
                if isinstance(self.status, DischargeDisposition)
                else self.status
            ),
            "unsat_core": list(self.unsat_core),
        }


@dataclass(frozen=True, slots=True)
class AssumeGuaranteeDischargeReceipt:
    graph_cid: str
    semantic_state_root: str
    contract_root: str
    component_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    obligations: tuple[DischargeObligationResult, ...]
    uncovered_assumptions: tuple[str, ...]
    sccs: tuple[tuple[str, ...], ...]
    rejected_cycles: tuple[tuple[str, ...], ...]
    disposition: DischargeDisposition | str
    bounds: FrozenMap
    limitations: tuple[str, ...]
    replay_data: FrozenMap
    schema: str = ASSUME_GUARANTEE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        try:
            disposition = (
                self.disposition
                if isinstance(self.disposition, DischargeDisposition)
                else DischargeDisposition(self.disposition)
            )
        except ValueError as error:
            raise AssumeGuaranteeError(str(error)) from error
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "component_ids", tuple(sorted(self.component_ids)))
        object.__setattr__(self, "edge_ids", tuple(sorted(self.edge_ids)))
        object.__setattr__(self, "uncovered_assumptions", tuple(sorted(self.uncovered_assumptions)))
        object.__setattr__(self, "sccs", tuple(sorted(tuple(sorted(item)) for item in self.sccs)))
        object.__setattr__(
            self,
            "rejected_cycles",
            tuple(sorted(tuple(sorted(item)) for item in self.rejected_cycles)),
        )
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        object.__setattr__(
            self,
            "bounds",
            self.bounds if isinstance(self.bounds, FrozenMap) else FrozenMap(self.bounds),
        )
        object.__setattr__(
            self,
            "replay_data",
            self.replay_data
            if isinstance(self.replay_data, FrozenMap)
            else FrozenMap(self.replay_data),
        )
        if self.schema != ASSUME_GUARANTEE_RECEIPT_SCHEMA:
            raise AssumeGuaranteeError("unsupported receipt schema")

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="logic.software-verification.assume-guarantee-receipt",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": self.bounds.to_dict(),
            "component_ids": list(self.component_ids),
            "contract_root": self.contract_root,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, DischargeDisposition)
                else self.disposition
            ),
            "edge_ids": list(self.edge_ids),
            "graph_cid": self.graph_cid,
            "limitations": list(self.limitations),
            "obligations": [item.to_dict() for item in self.obligations],
            "rejected_cycles": [list(item) for item in self.rejected_cycles],
            "replay_data": self.replay_data.to_dict(),
            "schema": self.schema,
            "sccs": [list(item) for item in self.sccs],
            "semantic_state_root": self.semantic_state_root,
            "uncovered_assumptions": list(self.uncovered_assumptions),
        }


def _clause_map(contract: CompositionalContract) -> dict[str, SemanticContractClause]:
    return {item.clause_id: item for item in contract.all_semantic_clauses}


def _tarjan(graph: ComponentCompositionGraph) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for contract in graph.contracts:
        adjacency[contract.component_id]
    for edge in graph.edges:
        adjacency[edge.producer_component_id].append(edge.consumer_component_id)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    result: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lows[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency[node]):
            if target not in indexes:
                visit(target)
                lows[node] = min(lows[node], lows[target])
            elif target in on_stack:
                lows[node] = min(lows[node], indexes[target])
        if lows[node] == indexes[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            has_self_edge = any(
                edge.producer_component_id == node and edge.consumer_component_id == node
                for edge in graph.edges
            )
            if len(component) > 1 or has_self_edge:
                result.append(tuple(sorted(component)))

    for node in sorted(adjacency):
        if node not in indexes:
            visit(node)
    return tuple(sorted(result))


def _predicate_term(clause: SemanticContractClause, symbol: str) -> SmtTerm | None:
    if clause.support is not SemanticSupport.TYPED_INLINE or clause.predicate is None:
        return None
    predicate = clause.predicate
    subject = term_symbol(symbol)
    if predicate.operator == "range_int":
        lower, upper = predicate.arguments
        return term_and(
            SmtTerm(SmtTermKind.GE, arguments=(subject, term_int(lower))),
            SmtTerm(SmtTermKind.LE, arguments=(subject, term_int(upper))),
        )
    if predicate.operator == "equals" and isinstance(predicate.arguments[0], int):
        return term_eq(subject, term_int(predicate.arguments[0]))
    if predicate.operator == "in_set" and all(
        isinstance(item, int) for item in predicate.arguments
    ):
        terms = tuple(term_eq(subject, term_int(item)) for item in predicate.arguments)
        if len(terms) == 1:
            return terms[0]
        return SmtTerm(SmtTermKind.OR, arguments=terms)
    return None


def _discharge_pair(
    *,
    graph: ComponentCompositionGraph,
    edge: CompositionEdge,
    guarantee: SemanticContractClause,
    assumption: SemanticContractClause,
    obligation_index: int,
    induction: bool,
) -> tuple[DischargeObligationResult, dict[str, Any]]:
    obligation_id = f"{edge.edge_id}:obligation:{obligation_index}"
    symbol = f"value_{obligation_index}"
    guarantee_term = _predicate_term(guarantee, symbol)
    assumption_term = _predicate_term(assumption, symbol)
    if guarantee_term is None or assumption_term is None:
        return (
            DischargeObligationResult(
                obligation_id=obligation_id,
                edge_id=edge.edge_id,
                guarantee_clause_id=guarantee.clause_id,
                assumption_clause_id=assumption.clause_id,
                status=DischargeDisposition.UNKNOWN,
                reason="opaque_or_unsupported_clause_semantics",
                induction_hypothesis=induction,
                independent_closure_check=False,
            ),
            {},
        )
    session = open_incremental_smt_session(
        session_id=f"ag-{obligation_index}",
        translator_identity="software-verification-smt-structured-term@1",
        theory_fingerprint="QF_LIA:range-equality@1",
        policy_root=graph.contract_root,
        configuration_root=graph.graph_cid,
        environment_root=graph.semantic_state_root,
    )
    session.declare_symbol(symbol, INT_SORT)
    session.add_named_assertion(
        f"{obligation_id}:guarantee",
        guarantee_term,
        source_ref=guarantee.cid,
        obligation_id=obligation_id,
    )
    session.add_named_assertion(
        f"{obligation_id}:negated-assumption",
        term_not(assumption_term),
        source_ref=assumption.cid,
        obligation_id=obligation_id,
    )
    solver_result: IncrementalSmtResult = session.check()
    replay = session.snapshot_or_replay_manifest()
    session.close()
    if solver_result.status is SmtCheckStatus.UNSAT and solver_result.core_validated:
        status = DischargeDisposition.PROVED
        reason = "guarantee_implies_assumption"
        counterexample = FrozenMap()
    elif solver_result.status is SmtCheckStatus.SAT and solver_result.model_validated:
        status = DischargeDisposition.DISPROVED
        reason = "concrete_model_violates_assumption"
        counterexample = solver_result.model
    else:
        status = DischargeDisposition.UNKNOWN
        reason = solver_result.unknown_reason or "solver_evidence_not_independently_validated"
        counterexample = FrozenMap()
    return (
        DischargeObligationResult(
            obligation_id=obligation_id,
            edge_id=edge.edge_id,
            guarantee_clause_id=guarantee.clause_id,
            assumption_clause_id=assumption.clause_id,
            status=status,
            solver_receipt_id=solver_result.receipt_id,
            unsat_core=solver_result.unsat_core,
            counterexample=counterexample,
            reason=reason,
            induction_hypothesis=induction,
            independent_closure_check=induction and status is DischargeDisposition.PROVED,
        ),
        {"manifest_cid": replay["manifest_cid"], "obligation_id": obligation_id},
    )


def discharge_assume_guarantee(
    graph: ComponentCompositionGraph,
    *,
    expected_semantic_state_root: str | None = None,
    expected_contract_root: str | None = None,
    maximum_obligations: int = 256,
) -> AssumeGuaranteeDischargeReceipt:
    """Discharge composition on exact roots with bounded solver work."""

    if maximum_obligations <= 0:
        raise AssumeGuaranteeError("maximum_obligations must be positive")
    if (
        expected_semantic_state_root is not None
        and expected_semantic_state_root != graph.semantic_state_root
    ):
        return AssumeGuaranteeDischargeReceipt(
            graph_cid=graph.graph_cid,
            semantic_state_root=graph.semantic_state_root,
            contract_root=graph.contract_root,
            component_ids=tuple(item.component_id for item in graph.contracts),
            edge_ids=tuple(item.edge_id for item in graph.edges),
            obligations=(),
            uncovered_assumptions=(),
            sccs=(),
            rejected_cycles=(),
            disposition=DischargeDisposition.STALE,
            bounds=FrozenMap({"maximum_obligations": maximum_obligations}),
            limitations=("semantic_state_root_mismatch",),
            replay_data=FrozenMap(),
        )
    if expected_contract_root is not None and expected_contract_root != graph.contract_root:
        return AssumeGuaranteeDischargeReceipt(
            graph_cid=graph.graph_cid,
            semantic_state_root=graph.semantic_state_root,
            contract_root=graph.contract_root,
            component_ids=tuple(item.component_id for item in graph.contracts),
            edge_ids=tuple(item.edge_id for item in graph.edges),
            obligations=(),
            uncovered_assumptions=(),
            sccs=(),
            rejected_cycles=(),
            disposition=DischargeDisposition.STALE,
            bounds=FrozenMap({"maximum_obligations": maximum_obligations}),
            limitations=("contract_root_mismatch",),
            replay_data=FrozenMap(),
        )

    contracts = {item.component_id: item for item in graph.contracts}
    clauses = {component: _clause_map(contract) for component, contract in contracts.items()}
    sccs = _tarjan(graph)
    component_to_scc = {component: scc for scc in sccs for component in scc}
    rejected_cycles: set[tuple[str, ...]] = set()
    obligations: list[DischargeObligationResult] = []
    replay_refs: dict[str, str] = {}
    uncovered: set[str] = set()
    index = 0

    for edge in graph.edges:
        scc = component_to_scc.get(edge.producer_component_id)
        in_cycle = scc is not None and edge.consumer_component_id in scc
        if in_cycle and not edge.induction_invariant_clause_ids:
            assert scc is not None
            rejected_cycles.add(scc)
            uncovered.update(edge.assumption_clause_ids)
            continue
        guarantee_ids = edge.guarantee_clause_ids + edge.exceptional_guarantee_clause_ids
        assumption_ids = edge.assumption_clause_ids + edge.exceptional_assumption_clause_ids
        # Each consumer assumption must be established by at least one supplied guarantee.
        for assumption_id in assumption_ids:
            assumption = clauses[edge.consumer_component_id][assumption_id]
            pair_results: list[DischargeObligationResult] = []
            for guarantee_id in guarantee_ids:
                if index >= maximum_obligations:
                    uncovered.add(assumption_id)
                    break
                guarantee = clauses[edge.producer_component_id][guarantee_id]
                result, replay = _discharge_pair(
                    graph=graph,
                    edge=edge,
                    guarantee=guarantee,
                    assumption=assumption,
                    obligation_index=index,
                    induction=in_cycle,
                )
                index += 1
                pair_results.append(result)
                obligations.append(result)
                if replay:
                    replay_refs[result.obligation_id] = replay["manifest_cid"]
                if result.status is DischargeDisposition.PROVED:
                    break
            if not pair_results or all(
                item.status is not DischargeDisposition.PROVED for item in pair_results
            ):
                uncovered.add(assumption_id)

        if in_cycle:
            # Independent closure: each declared induction invariant must also
            # follow from a local guarantee, not merely from a neighboring cite.
            for invariant_id in edge.induction_invariant_clause_ids:
                invariant = clauses[edge.consumer_component_id][invariant_id]
                closed = False
                for guarantee_id in edge.guarantee_clause_ids:
                    if index >= maximum_obligations:
                        break
                    result, replay = _discharge_pair(
                        graph=graph,
                        edge=edge,
                        guarantee=clauses[edge.producer_component_id][guarantee_id],
                        assumption=invariant,
                        obligation_index=index,
                        induction=True,
                    )
                    index += 1
                    obligations.append(result)
                    if replay:
                        replay_refs[result.obligation_id] = replay["manifest_cid"]
                    if result.status is DischargeDisposition.PROVED:
                        closed = True
                        break
                if not closed:
                    assert scc is not None
                    rejected_cycles.add(scc)
                    uncovered.add(invariant_id)

        producer = contracts[edge.producer_component_id]
        consumer = contracts[edge.consumer_component_id]
        if set(producer.forbidden_interference) & set(consumer.allowed_interference):
            uncovered.add(f"{edge.edge_id}:incompatible_interference")
        uncovered_effects = (
            set(producer.write_set) - set(consumer.allowed_interference) - set(consumer.read_set)
        )
        if uncovered_effects and consumer.allowed_interference:
            uncovered.add(f"{edge.edge_id}:uncovered_effects")

    statuses = {item.status for item in obligations}
    if rejected_cycles:
        disposition = DischargeDisposition.REJECTED_CYCLE
    elif DischargeDisposition.DISPROVED in statuses:
        disposition = DischargeDisposition.DISPROVED
    elif uncovered or DischargeDisposition.UNKNOWN in statuses:
        disposition = DischargeDisposition.UNKNOWN
    else:
        disposition = DischargeDisposition.PROVED
    return AssumeGuaranteeDischargeReceipt(
        graph_cid=graph.graph_cid,
        semantic_state_root=graph.semantic_state_root,
        contract_root=graph.contract_root,
        component_ids=tuple(contracts),
        edge_ids=tuple(item.edge_id for item in graph.edges),
        obligations=tuple(obligations),
        uncovered_assumptions=tuple(uncovered),
        sccs=sccs,
        rejected_cycles=tuple(rejected_cycles),
        disposition=disposition,
        bounds=FrozenMap(
            {
                "maximum_obligations": maximum_obligations,
                "obligations_executed": len(obligations),
            }
        ),
        limitations=(
            "initial_lowering_supports_integer_range_equals_and_finite_integer_sets",
            "opaque_or_unavailable_semantics_are_never_discharged",
            "solver_receipts_are_solver_checked_not_kernel_verified",
        ),
        replay_data=FrozenMap(replay_refs),
    )


__all__ = [
    "ASSUME_GUARANTEE_GRAPH_SCHEMA",
    "ASSUME_GUARANTEE_INTERFACE",
    "ASSUME_GUARANTEE_RECEIPT_SCHEMA",
    "AssumeGuaranteeDischargeReceipt",
    "AssumeGuaranteeError",
    "ComponentCompositionGraph",
    "CompositionEdge",
    "DischargeDisposition",
    "DischargeObligationResult",
    "discharge_assume_guarantee",
]
