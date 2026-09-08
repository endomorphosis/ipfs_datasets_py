from __future__ import annotations

from ipfs_datasets_py.logic.software_contracts.compositional import (
    CompositionalContract,
    SemanticContractClause,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    BoundedPredicate,
    ContractAuthority,
    ContractProvenance,
)
from ipfs_datasets_py.logic.software_verification.assume_guarantee import (
    ComponentCompositionGraph,
    CompositionEdge,
    DischargeDisposition,
    discharge_assume_guarantee,
)


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        "inferred",
        ContractAuthority("authority:test", "inference", "datasets", "test"),
        "fixture.py",
    )


def _clause(clause_id: str, kind: str, lower: int, upper: int) -> SemanticContractClause:
    role = (
        "assumption"
        if kind == "assumption"
        else ("invariant" if kind == "invariant" else "postcondition")
    )
    return SemanticContractClause(
        clause_id=clause_id,
        kind=kind,
        support="typed_inline",
        predicate=BoundedPredicate(
            predicate_id=f"{clause_id}:predicate",
            role=role,
            operator="range_int",
            subject="return",
            provenance=_provenance(),
            arguments=(lower, upper),
        ),
    )


def _contract(
    component: str,
    *,
    assumptions: tuple[SemanticContractClause, ...] = (),
    guarantees: tuple[SemanticContractClause, ...] = (),
    invariants: tuple[SemanticContractClause, ...] = (),
    allowed_interference: tuple[str, ...] = (),
    forbidden_interference: tuple[str, ...] = (),
) -> CompositionalContract:
    roots = [f"sha256:{index:064x}" for index in range(1, 7)]
    return CompositionalContract(
        contract_id=f"contract:{component}",
        component_id=component,
        component_kind="callable",
        provenance=_provenance(),
        source_root=roots[0],
        ast_root=roots[1],
        symbol_version_root=roots[2],
        interface_root=roots[3],
        configuration_root=roots[4],
        toolchain_root=roots[5],
        assumptions=assumptions,
        guarantees=guarantees,
        invariants=invariants,
        allowed_interference=allowed_interference,
        forbidden_interference=forbidden_interference,
        confidence="conservative",
        semantic_support_class="supported_subset",
    )


def _graph(guarantee_upper: int = 10) -> ComponentCompositionGraph:
    producer = _contract("A", guarantees=(_clause("A:guarantee", "guarantee", 0, guarantee_upper),))
    consumer = _contract("B", assumptions=(_clause("B:assumption", "assumption", 0, 20),))
    return ComponentCompositionGraph(
        semantic_state_root="sha256:" + "a" * 64,
        contracts=(producer, consumer),
        edges=(
            CompositionEdge(
                edge_id="A-to-B",
                producer_component_id="A",
                consumer_component_id="B",
                guarantee_clause_ids=("A:guarantee",),
                assumption_clause_ids=("B:assumption",),
                source_fact_refs=("call:A:B",),
            ),
        ),
    )


def test_successful_composition_has_validated_unsat_core() -> None:
    receipt = discharge_assume_guarantee(_graph())
    assert receipt.disposition is DischargeDisposition.PROVED
    assert receipt.uncovered_assumptions == ()
    assert receipt.obligations[0].unsat_core
    assert receipt.obligations[0].solver_receipt_id.startswith("b")


def test_weak_guarantee_yields_concrete_counterexample() -> None:
    receipt = discharge_assume_guarantee(_graph(guarantee_upper=30))
    assert receipt.disposition is DischargeDisposition.DISPROVED
    assert receipt.obligations[0].counterexample
    assert receipt.uncovered_assumptions == ("B:assumption",)


def test_stale_contract_root_is_not_a_pass() -> None:
    receipt = discharge_assume_guarantee(_graph(), expected_contract_root="sha256:" + "0" * 64)
    assert receipt.disposition is DischargeDisposition.STALE
    assert receipt.obligations == ()


def test_cycle_without_induction_invariant_is_rejected() -> None:
    a_assume = _clause("A:assume", "assumption", 0, 20)
    a_guarantee = _clause("A:guarantee", "guarantee", 0, 10)
    b_assume = _clause("B:assume", "assumption", 0, 20)
    b_guarantee = _clause("B:guarantee", "guarantee", 0, 10)
    graph = ComponentCompositionGraph(
        semantic_state_root="sha256:" + "b" * 64,
        contracts=(
            _contract("A", assumptions=(a_assume,), guarantees=(a_guarantee,)),
            _contract("B", assumptions=(b_assume,), guarantees=(b_guarantee,)),
        ),
        edges=(
            CompositionEdge("A-B", "A", "B", ("A:guarantee",), ("B:assume",)),
            CompositionEdge("B-A", "B", "A", ("B:guarantee",), ("A:assume",)),
        ),
    )
    receipt = discharge_assume_guarantee(graph)
    assert receipt.disposition is DischargeDisposition.REJECTED_CYCLE
    assert receipt.rejected_cycles == (("A", "B"),)


def test_inductive_cycle_requires_and_records_independent_closure() -> None:
    a_assume = _clause("A:assume", "assumption", 0, 20)
    a_inv = _clause("A:invariant", "invariant", 0, 20)
    a_guarantee = _clause("A:guarantee", "guarantee", 0, 10)
    b_assume = _clause("B:assume", "assumption", 0, 20)
    b_inv = _clause("B:invariant", "invariant", 0, 20)
    b_guarantee = _clause("B:guarantee", "guarantee", 0, 10)
    graph = ComponentCompositionGraph(
        semantic_state_root="sha256:" + "c" * 64,
        contracts=(
            _contract("A", assumptions=(a_assume,), guarantees=(a_guarantee,), invariants=(a_inv,)),
            _contract("B", assumptions=(b_assume,), guarantees=(b_guarantee,), invariants=(b_inv,)),
        ),
        edges=(
            CompositionEdge(
                "A-B",
                "A",
                "B",
                ("A:guarantee",),
                ("B:assume",),
                induction_invariant_clause_ids=("B:invariant",),
            ),
            CompositionEdge(
                "B-A",
                "B",
                "A",
                ("B:guarantee",),
                ("A:assume",),
                induction_invariant_clause_ids=("A:invariant",),
            ),
        ),
    )
    receipt = discharge_assume_guarantee(graph)
    assert receipt.disposition is DischargeDisposition.PROVED
    assert any(item.independent_closure_check for item in receipt.obligations)


def test_incompatible_interference_remains_uncovered() -> None:
    graph = _graph()
    producer = _contract(
        "A",
        guarantees=(_clause("A:guarantee", "guarantee", 0, 10),),
        forbidden_interference=("shared:x",),
    )
    consumer = _contract(
        "B",
        assumptions=(_clause("B:assumption", "assumption", 0, 20),),
        allowed_interference=("shared:x",),
    )
    receipt = discharge_assume_guarantee(
        ComponentCompositionGraph(graph.semantic_state_root, (producer, consumer), graph.edges)
    )
    assert receipt.disposition is DischargeDisposition.UNKNOWN
    assert "A-to-B:incompatible_interference" in receipt.uncovered_assumptions
