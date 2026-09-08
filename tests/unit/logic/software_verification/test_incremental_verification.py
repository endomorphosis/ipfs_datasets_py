"""Focused tests for exact semantic/contract verification invalidation."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import replace

import pytest
from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicEvidenceAuthority,
    LogicEvidenceKind,
)
from ipfs_datasets_py.logic.software_contracts.compositional import (
    CompositionalContract,
    SemanticContractClause,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    BoundedPredicate,
    ContractAuthority,
    ContractProvenance,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    normalize_ast,
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge,
    RelationType,
    RepositoryState,
    RepositoryStateDelta,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_verification.assume_guarantee import (
    ComponentCompositionGraph,
    CompositionEdge,
)
from ipfs_datasets_py.logic.software_verification.incremental_verification import (
    EvidenceDecisionDisposition,
    EvidenceReuseRequest,
    IncrementalVerificationStaleError,
    VerificationBindingKind,
    VerificationEvidenceBinding,
    plan_incremental_verification,
)

REPOSITORY_ID = "repo:incremental-verification"


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        "inferred",
        ContractAuthority("authority:test", "inference", "datasets", "test"),
        "fixture.py",
    )


def _symbol(name: str, expression: str) -> SymbolRecord:
    source = f"def {name}():\n    return {expression}\n"
    stable = stable_symbol_id(
        REPOSITORY_ID,
        "python",
        f"pkg/{name}.py",
        f"pkg.{name}.{name}",
        SymbolKind.FUNCTION,
        "pkg",
    )
    normalized = normalize_ast(ast.parse(source).body[0])
    version = symbol_version_cid(stable, normalized, {}, (), {})
    return SymbolRecord(
        stable,
        version,
        REPOSITORY_ID,
        "python",
        f"pkg/{name}.py",
        f"pkg.{name}.{name}",
        SymbolKind.FUNCTION,
        "pkg",
        cid_for_bytes(source.encode()),
        SourceSpan(f"pkg/{name}.py", 1, 0, 2, 20),
        "exact",
        {},
        (),
        {},
        {},
        normalized,
    )


def _clause(component: str, role: str) -> SemanticContractClause:
    kind = "assumption" if role == "assumption" else "guarantee"
    predicate_role = "assumption" if role == "assumption" else "postcondition"
    return SemanticContractClause(
        clause_id=f"{component}:{role}",
        kind=kind,
        support="typed_inline",
        predicate=BoundedPredicate(
            predicate_id=f"{component}:{role}:predicate",
            role=predicate_role,
            operator="range_int",
            subject="return",
            provenance=_provenance(),
            arguments=(0, 10),
        ),
    )


def _contract(
    symbol: SymbolRecord,
    *,
    assumption: bool = False,
    guarantee: bool = False,
    open_world: bool = False,
) -> CompositionalContract:
    component = symbol.stable_id
    return CompositionalContract(
        contract_id=f"contract:{component}",
        component_id=component,
        component_kind="callable",
        provenance=_provenance(),
        source_root=symbol.source_cid,
        ast_root=_sha(f"ast:{symbol.version_cid}"),
        symbol_version_root=symbol.version_cid,
        interface_root=_sha(f"interface:{component}"),
        configuration_root=_sha("config:v1"),
        toolchain_root=_sha("python:3.12"),
        assumptions=((_clause(component, "assumption"),) if assumption else ()),
        guarantees=((_clause(component, "guarantee"),) if guarantee else ()),
        invalidation_selectors=(component,),
        confidence="exact",
        semantic_support_class="supported_subset",
        open_world=open_world,
        attributes={"semantic_index_symbol_id": component},
    )


def _states() -> tuple[RepositoryState, RepositoryState, dict[str, SymbolRecord]]:
    old_a = _symbol("a", "1")
    new_a = _symbol("a", "2")
    b = _symbol("b", "1")
    c = _symbol("c", "1")
    unaffected = _symbol("unaffected", "7")
    old_edges = (
        DependencyEdge(b.stable_id, old_a.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(c.stable_id, b.stable_id, RelationType.CALLS, "static", "exact", "1"),
    )
    new_edges = (
        DependencyEdge(b.stable_id, new_a.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(c.stable_id, b.stable_id, RelationType.CALLS, "static", "exact", "1"),
    )
    previous = RepositoryState(REPOSITORY_ID, (old_a, b, c, unaffected), (), old_edges)
    current = RepositoryState(REPOSITORY_ID, (new_a, b, c, unaffected), (), new_edges)
    return (
        previous,
        current,
        {
            "old_a": old_a,
            "a": new_a,
            "b": b,
            "c": c,
            "unaffected": unaffected,
        },
    )


def _graphs(
    previous: RepositoryState,
    current: RepositoryState,
    symbols: dict[str, SymbolRecord],
    *,
    cycle: bool = False,
    open_world_a: bool = False,
) -> tuple[ComponentCompositionGraph, ComponentCompositionGraph]:
    def build(a: SymbolRecord, root: str) -> ComponentCompositionGraph:
        contracts = (
            _contract(a, assumption=cycle, guarantee=True, open_world=open_world_a),
            _contract(symbols["b"], assumption=True, guarantee=True),
            _contract(symbols["c"], assumption=True),
            _contract(symbols["unaffected"], guarantee=True),
        )
        by_component = {item.component_id: item for item in contracts}
        edges = [
            CompositionEdge(
                "A-to-B",
                a.stable_id,
                symbols["b"].stable_id,
                (f"{a.stable_id}:guarantee",),
                (f"{symbols['b'].stable_id}:assumption",),
            ),
            CompositionEdge(
                "B-to-C",
                symbols["b"].stable_id,
                symbols["c"].stable_id,
                (f"{symbols['b'].stable_id}:guarantee",),
                (f"{symbols['c'].stable_id}:assumption",),
            ),
        ]
        if cycle:
            edges.append(
                CompositionEdge(
                    "B-to-A",
                    symbols["b"].stable_id,
                    a.stable_id,
                    (f"{symbols['b'].stable_id}:guarantee",),
                    (f"{a.stable_id}:assumption",),
                )
            )
        # Access through the exact public graph constructor; no test-only pass
        # flags or prebuilt invalidation receipts are injected.
        return ComponentCompositionGraph(root, tuple(by_component.values()), tuple(edges))

    return build(symbols["old_a"], previous.state_cid), build(symbols["a"], current.state_cid)


def _cache_key(label: str) -> CanonicalProofCacheKey:
    return CanonicalProofCacheKey.build(
        source={"source": label},
        expression={"expression": label},
        formalization={"formalization": "python-range"},
        slice={"symbols": [label]},
        obligation={"obligation": label},
        assumptions=(),
        bounds={"steps": 32},
        translation={"translator": "fixture-v1"},
        provider="provider.z3",
        environment={"python": "3.12", "z3": "4.15"},
        policy={"network": "deny"},
        schema={"semantic-index": "v2"},
        checker="checker.incremental-fixture",
        network_policy={"allow": False},
        evidence_kind=LogicEvidenceKind.SOLVER_RESULT,
        authority_ceiling=LogicEvidenceAuthority.BOUNDED,
    )


def _request(
    binding_id: str,
    kind: VerificationBindingKind,
    subject: SymbolRecord,
    state: RepositoryState,
    contract: CompositionalContract,
    *,
    current_key: CanonicalProofCacheKey | None = None,
    confidence: str = "exact",
) -> EvidenceReuseRequest:
    key = _cache_key(binding_id)
    binding = VerificationEvidenceBinding(
        binding_id=binding_id,
        kind=kind,
        artifact_cid=cid_for_structured({"artifact": binding_id}),
        observed_state_cid=state.state_cid,
        subject_ids=(subject.stable_id,),
        dependency_ids=(subject.version_cid,),
        contract_cids=(contract.cid,),
        cache_key=key,
        confidence=confidence,
    )
    return EvidenceReuseRequest(binding, current_key or key)


def test_change_closes_consumers_invalidates_all_binding_kinds_and_reuses_unaffected() -> None:
    previous, current, symbols = _states()
    old_graph, graph = _graphs(previous, current, symbols)
    old_contracts = {item.component_id: item for item in old_graph.contracts}
    requests = (
        _request(
            "abstract:A",
            VerificationBindingKind.ABSTRACT_STATE,
            symbols["old_a"],
            previous,
            old_contracts[symbols["old_a"].stable_id],
        ),
        _request(
            "contract:B",
            VerificationBindingKind.CONTRACT,
            symbols["b"],
            previous,
            old_contracts[symbols["b"].stable_id],
        ),
        _request(
            "solver:C",
            VerificationBindingKind.SOLVER_SESSION,
            symbols["c"],
            previous,
            old_contracts[symbols["c"].stable_id],
        ),
        _request(
            "capsule:A",
            VerificationBindingKind.CAPSULE,
            symbols["old_a"],
            previous,
            old_contracts[symbols["old_a"].stable_id],
        ),
        _request(
            "proof:C",
            VerificationBindingKind.PROOF,
            symbols["c"],
            previous,
            old_contracts[symbols["c"].stable_id],
        ),
        _request(
            "test:B",
            VerificationBindingKind.TEST,
            symbols["b"],
            previous,
            old_contracts[symbols["b"].stable_id],
        ),
        _request(
            "proof:unaffected",
            VerificationBindingKind.PROOF,
            symbols["unaffected"],
            previous,
            old_contracts[symbols["unaffected"].stable_id],
        ),
    )

    receipt = plan_incremental_verification(
        previous,
        current,
        composition_graph=graph,
        previous_composition_graph=old_graph,
        evidence_requests=requests,
    )

    assert receipt.changed_symbol_ids == (symbols["a"].stable_id,)
    assert receipt.reverse_contract_closure == tuple(
        sorted((symbols["a"].stable_id, symbols["b"].stable_id, symbols["c"].stable_id))
    )
    assert receipt.invalidated_abstract_state_binding_ids == ("abstract:A",)
    assert receipt.invalidated_contract_binding_ids == ("contract:B",)
    assert receipt.invalidated_solver_binding_ids == ("solver:C",)
    assert receipt.invalidated_capsule_binding_ids == ("capsule:A",)
    assert receipt.invalidated_proof_binding_ids == ("proof:C",)
    assert receipt.invalidated_test_binding_ids == ("test:B",)
    assert receipt.reused_evidence_binding_ids == ("proof:unaffected",)
    assert receipt.selected_proof_ids == (symbols["c"].stable_id,)
    assert receipt.selected_test_ids == (symbols["b"].stable_id,)
    assert receipt.dynamic_frontier == ()
    assert receipt.receipt_cid.startswith("b")
    assert receipt.to_dict()["receipt_cid"] == receipt.receipt_cid


def test_scc_membership_is_explicitly_closed_and_open_world_stays_dynamic() -> None:
    previous, current, symbols = _states()
    old_graph, graph = _graphs(previous, current, symbols, cycle=True, open_world_a=True)

    receipt = plan_incremental_verification(
        previous,
        current,
        composition_graph=graph,
        previous_composition_graph=old_graph,
    )

    assert tuple(sorted((symbols["a"].stable_id, symbols["b"].stable_id))) in receipt.affected_sccs
    assert f"contract:{symbols['a'].stable_id}:open_world" in receipt.dynamic_frontier
    assert "dynamic_frontier_requires_raw_source_or_full_verification" in receipt.limitations


def test_cache_mismatch_and_non_exact_evidence_are_not_reused() -> None:
    previous, current, symbols = _states()
    old_graph, graph = _graphs(previous, current, symbols)
    old_unaffected = {item.component_id: item for item in old_graph.contracts}[
        symbols["unaffected"].stable_id
    ]
    mismatched = _request(
        "proof:mismatch",
        VerificationBindingKind.PROOF,
        symbols["unaffected"],
        previous,
        old_unaffected,
        current_key=_cache_key("a-different-current-request"),
    )
    conservative = _request(
        "proof:conservative",
        VerificationBindingKind.PROOF,
        symbols["unaffected"],
        previous,
        old_unaffected,
        confidence="conservative",
    )

    receipt = plan_incremental_verification(
        previous,
        current,
        composition_graph=graph,
        previous_composition_graph=old_graph,
        evidence_requests=(mismatched, conservative),
    )

    decisions = {item.binding_id: item for item in receipt.evidence_decisions}
    assert decisions["proof:mismatch"].disposition is EvidenceDecisionDisposition.INVALIDATED
    assert "cache_key_mismatch" in decisions["proof:mismatch"].reason_codes
    assert decisions["proof:conservative"].disposition is EvidenceDecisionDisposition.INVALIDATED
    assert "non_exact_evidence" in decisions["proof:conservative"].reason_codes
    assert receipt.reused_evidence_binding_ids == ()


def test_stale_graph_delta_and_unrelated_evidence_state_fail_closed() -> None:
    previous, current, symbols = _states()
    old_graph, graph = _graphs(previous, current, symbols)
    stale_graph = replace(graph, semantic_state_root=previous.state_cid)
    with pytest.raises(IncrementalVerificationStaleError, match="semantic_state_root"):
        plan_incremental_verification(previous, current, composition_graph=stale_graph)

    fabricated_delta = RepositoryStateDelta(
        previous.state_cid,
        current.state_cid,
        unchanged_symbol_ids=tuple(item.stable_id for item in current.symbols),
    )
    with pytest.raises(IncrementalVerificationStaleError, match="semantic delta"):
        plan_incremental_verification(
            previous,
            current,
            composition_graph=graph,
            previous_composition_graph=old_graph,
            supplied_delta=fabricated_delta,
        )

    old_unaffected = {item.component_id: item for item in old_graph.contracts}[
        symbols["unaffected"].stable_id
    ]
    request = _request(
        "proof:stale-state",
        VerificationBindingKind.PROOF,
        symbols["unaffected"],
        previous,
        old_unaffected,
    )
    unrelated = replace(
        request.binding,
        observed_state_cid=cid_for_structured({"state": "unrelated"}),
    )
    with pytest.raises(IncrementalVerificationStaleError, match="unrelated state"):
        plan_incremental_verification(
            previous,
            current,
            composition_graph=graph,
            previous_composition_graph=old_graph,
            evidence_requests=(EvidenceReuseRequest(unrelated, request.current_cache_key),),
        )


def test_binding_round_trip_revalidates_closed_schema_and_cache_key() -> None:
    previous, _current, symbols = _states()
    old_graph, _graph = _graphs(previous, _current, symbols)
    old_contract = {item.component_id: item for item in old_graph.contracts}[
        symbols["unaffected"].stable_id
    ]
    request = _request(
        "proof:round-trip",
        VerificationBindingKind.PROOF,
        symbols["unaffected"],
        previous,
        old_contract,
    )

    restored = EvidenceReuseRequest.from_dict(request.to_dict())
    assert restored == request
    forged = request.to_dict()
    forged["extra"] = True
    with pytest.raises(ValueError, match="fields are closed"):
        EvidenceReuseRequest.from_dict(forged)
