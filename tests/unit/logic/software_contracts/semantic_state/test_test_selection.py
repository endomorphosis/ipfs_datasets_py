"""Focused contract vectors for pure pytest/proof selection (DSS-007)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Mapping, Sequence

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.invalidation import (
    SemanticRemediation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    ObligationOrigin,
    ReasonPath,
    SelectionFallback,
    SelectionPolicy,
    SelectionRule,
    SelectionRuleKind,
    SemanticInvalidationObligation,
    SemanticInvalidationPlan,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
    TestSelection,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.test_selection import (
    PROOF_SELECTION_INTERFACE,
    TEST_SELECTION_INTERFACE,
    SelectionFallbackReason,
    TestSelectionError,
    select_tests_and_proofs,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _symbol(
    name: str,
    source: str | None = None,
    *,
    module: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind = SymbolKind.FUNCTION,
    confidence: AnalysisConfidence = AnalysisConfidence.EXACT,
    metadata: Mapping[str, object] | None = None,
) -> SymbolRecord:
    source = source or f"def {name}():\n    return 1\n"
    qualified = f"{namespace}.{name}"
    stable = stable_symbol_id(
        "repo:selection", "python", module, qualified, kind, namespace
    )
    node = ast.parse(source).body[0]
    version = symbol_version_cid(stable, node, {}, (), {})
    meta = dict(metadata or {})
    if kind == SymbolKind.TEST and "pytest" not in meta:
        # Bind pytest discovery evidence so node IDs are authoritative.
        meta["pytest"] = {"kind": "test"}
        meta.setdefault(
            "pytest_node_id",
            f"{module}::{name}",
        )
    return SymbolRecord(
        stable,
        version,
        "repo:selection",
        "python",
        module,
        qualified,
        kind,
        namespace,
        cid_for_bytes(source.encode()),
        SourceSpan(module, 1, 0, 2, 20),
        confidence,
        {},
        (),
        {},
        meta,
        node,
    )


def _producer() -> SemanticStateProducer:
    return SemanticStateProducer(
        repository_state_cid=_cid("state"),
        repository_snapshot_cid=_cid("snapshot"),
        git_commit_oid_or_null="a" * 40,
        git_tree_oid_or_null="b" * 40,
        source_manifest_cid=_cid("manifest"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )


def _index_cid() -> str:
    return SortedPairIndex(pairs=[("k", _cid("block"))]).index_cid


@dataclass(frozen=True)
class _View:
    root: SemanticStateRoot
    blocks: Mapping[str, bytes]
    symbols: Sequence[SymbolRecord] = ()
    edges: Sequence[DependencyEdge] = ()
    artifacts: Sequence = ()

    def get_block(self, cid: str) -> bytes:
        try:
            return self.blocks[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc


def _view(
    *,
    symbols: Sequence[SymbolRecord] = (),
    edges: Sequence[DependencyEdge] = (),
    label: str = "current",
) -> _View:
    root = SemanticStateRoot(
        repository_id="repo:selection",
        producer=_producer(),
        symbol_fact_index_cid=_index_cid(),
        artifact_fact_index_cid=_index_cid(),
        semantic_link_index_cid=_index_cid(),
        symbol_node_index_cid=_index_cid(),
        capsule_index_cid=_index_cid(),
        environment_binding_set_cid=_cid(f"bindings:{label}"),
        analysis_limitation_index_cid=_index_cid(),
    )
    blocks = {
        root.environment_binding_set_cid: canonical_dag_json_bytes(
            {"schema": "ipfs-datasets.software-contracts.environment-binding-set@1", "bindings": []}
        )
    }
    return _View(root=root, blocks=blocks, symbols=tuple(symbols), edges=tuple(edges))


def _obligation(
    subject_id: str,
    *,
    reason: str = "stale_test_receipt",
    remediation: str = SemanticRemediation.RERUN_TEST.value,
    confidence: str = AnalysisConfidence.EXACT.value,
    origin: ObligationOrigin = ObligationOrigin.ISI,
    supporting_edge_ids: Sequence[str] = (),
    details: Mapping[str, object] | None = None,
) -> SemanticInvalidationObligation:
    return SemanticInvalidationObligation(
        subject_id=subject_id,
        reason_code=reason,
        remediation_kind=remediation,
        confidence=confidence,
        origin=origin,
        supporting_edge_ids=supporting_edge_ids,
        details=dict(details or {}),
    )


def _plan(
    current: _View,
    obligations: Sequence[SemanticInvalidationObligation],
    *,
    previous: _View | None = None,
) -> SemanticInvalidationPlan:
    return SemanticInvalidationPlan(
        previous_root_cid=None if previous is None else previous.root.root_cid,
        current_root_cid=current.root.root_cid,
        obligations=tuple(obligations),
    )


def _policy(**kwargs: object) -> SelectionPolicy:
    defaults: dict[str, object] = {
        "policy_id": "default",
        "allow_full_fallback": True,
        "include_proofs": True,
        "include_fixtures": True,
    }
    defaults.update(kwargs)
    return SelectionPolicy(**defaults)  # type: ignore[arg-type]


def test_interfaces_are_declared() -> None:
    assert TEST_SELECTION_INTERFACE == "TestSelection@1"
    assert PROOF_SELECTION_INTERFACE == "ProofSelection@1"


def test_direct_tested_by_selects_pytest_node_and_binds_roots() -> None:
    target = _symbol("answer", "def answer():\n    return 42\n")
    test = _symbol(
        "test_answer",
        "def test_answer():\n    assert answer() == 42\n",
        module="tests/test_mod.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_mod.py::test_answer", "pytest": {"kind": "test"}},
    )
    edge = DependencyEdge(
        target.stable_id,
        test.stable_id,
        RelationType.TESTED_BY,
        "static",
        "exact",
        "1",
    )
    current = _view(symbols=(target, test), edges=(edge,))
    previous = _view(symbols=(target, test), edges=(edge,), label="prev")
    plan = _plan(
        current,
        [_obligation(target.stable_id, supporting_edge_ids=[edge.edge_id])],
        previous=previous,
    )
    selection = select_tests_and_proofs(
        previous,
        current,
        plan,
        policy=_policy(),
        previous_index=RepositoryState("repo:selection", symbols=(target, test), edges=(edge,)),
        current_index=RepositoryState("repo:selection", symbols=(target, test), edges=(edge,)),
    )
    assert isinstance(selection, TestSelection)
    assert selection.previous_root_cid == previous.root.root_cid
    assert selection.current_root_cid == current.root.root_cid
    assert selection.selected_pytest_node_ids == ("tests/test_mod.py::test_answer",)
    assert selection.fallback == SelectionFallback.NONE
    assert selection.known_test_universe_count == 1
    assert selection.known_test_universe_cid is not None
    assert selection.policy_cid == _policy().policy_cid
    assert selection.reason_paths
    path = selection.reason_paths[0]
    assert isinstance(path, ReasonPath)
    assert path.seed_subject_id == target.stable_id
    assert path.target_node_id == "tests/test_mod.py::test_answer"
    assert edge.edge_id in path.edge_ids
    assert path.relation_steps == ("tested_by",)
    assert plan.obligations[0].obligation_id in selection.covered_seed_obligation_ids
    # Round-trip identity.
    assert TestSelection.from_dict(selection.to_dict()) == selection


def test_reverse_caller_and_fixture_selection() -> None:
    leaf = _symbol("leaf", "def leaf():\n    return 1\n")
    caller = _symbol("caller", "def caller():\n    return leaf()\n")
    fixture = _symbol(
        "db",
        "def db():\n    yield {}\n",
        module="tests/conftest.py",
        namespace="tests",
        kind=SymbolKind.FIXTURE,
        metadata={"fixture_name": "db", "pytest": {"kind": "fixture", "name": "db"}},
    )
    test = _symbol(
        "test_caller",
        "def test_caller(db):\n    assert caller() == 1\n",
        module="tests/test_caller.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={
            "pytest_node_id": "tests/test_caller.py::test_caller",
            "pytest": {"kind": "test"},
        },
    )
    edges = (
        DependencyEdge(
            caller.stable_id, leaf.stable_id, RelationType.CALLS, "static", "exact", "1"
        ),
        DependencyEdge(
            caller.stable_id,
            test.stable_id,
            RelationType.TESTED_BY,
            "static",
            "exact",
            "1",
        ),
        DependencyEdge(
            test.stable_id,
            fixture.stable_id,
            RelationType.USES_FIXTURE,
            "pytest-static-parameter",
            "exact",
            "1",
            metadata={"fixture_name": "db"},
        ),
    )
    current = _view(symbols=(leaf, caller, fixture, test), edges=edges)
    # Seed is the leaf: reverse CALLS reaches caller, then TESTED_BY reaches test.
    plan = _plan(current, [_obligation(leaf.stable_id)])
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState(
            "repo:selection",
            symbols=(leaf, caller, fixture, test),
            edges=edges,
        ),
    )
    assert "tests/test_caller.py::test_caller" in selection.selected_pytest_node_ids
    assert selection.fallback == SelectionFallback.NONE

    # Fixture seed selects dependents via uses_fixture.
    plan_fx = _plan(current, [_obligation(fixture.stable_id)])
    selection_fx = select_tests_and_proofs(
        None,
        current,
        plan_fx,
        policy=_policy(),
        current_index=RepositoryState(
            "repo:selection",
            symbols=(leaf, caller, fixture, test),
            edges=edges,
        ),
    )
    assert selection_fx.selected_pytest_node_ids == ("tests/test_caller.py::test_caller",)


def test_proof_depends_on_selects_proof_ids() -> None:
    subject = _symbol("verified", "def verified():\n    return True\n")
    proof = _symbol(
        "proof_verified",
        "def proof_verified():\n    return True\n",
        metadata={"proof": True, "is_proof": True},
    )
    # Known non-empty test universe so proof selection is not collapsed by
    # the unknown-universe full-pytest rule.
    sentinel = _symbol(
        "test_sentinel",
        "def test_sentinel():\n    assert True\n",
        module="tests/test_sentinel.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={
            "pytest_node_id": "tests/test_sentinel.py::test_sentinel",
            "pytest": {"kind": "test"},
        },
    )
    edge = DependencyEdge(
        proof.stable_id,
        subject.stable_id,
        RelationType.PROOF_DEPENDS_ON,
        "static",
        "exact",
        "1",
    )
    current = _view(symbols=(subject, proof, sentinel), edges=(edge,))
    plan = _plan(
        current,
        [
            _obligation(
                subject.stable_id,
                reason="proof_rerun",
                remediation=SemanticRemediation.RERUN_PROOF.value,
            )
        ],
    )
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState(
            "repo:selection", symbols=(subject, proof, sentinel), edges=(edge,)
        ),
    )
    assert proof.stable_id in selection.selected_proof_ids
    assert selection.fallback == SelectionFallback.NONE
    assert any(path.target_node_id == proof.stable_id for path in selection.reason_paths)
    assert selection.known_test_universe_count == 1


def test_dynamic_plugin_obligation_forces_full_pytest_fallback() -> None:
    test = _symbol(
        "test_x",
        "def test_x():\n    assert True\n",
        module="tests/test_x.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_x.py::test_x", "pytest": {"kind": "test"}},
    )
    current = _view(symbols=(test,))
    plan = _plan(
        current,
        [
            _obligation(
                "plugin:pytest-xdist",
                reason="pytest_plugin_changed",
                remediation=SemanticRemediation.FULL_PYTEST_FALLBACK.value,
                origin=ObligationOrigin.ENVIRONMENT,
                details={"binding_kind": "pytest_plugin", "rule": "fallback"},
            )
        ],
    )
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState("repo:selection", symbols=(test,)),
    )
    assert selection.fallback == SelectionFallback.FULL_PYTEST
    assert SelectionFallbackReason.DYNAMIC_PYTEST_PLUGIN.value in selection.fallback_reasons or (
        SelectionFallbackReason.FULL_PYTEST_FALLBACK_OBLIGATION.value
        in selection.fallback_reasons
    )
    # Visible fallback clears precise pytest selection.
    assert selection.selected_pytest_node_ids == ()
    assert selection.known_test_universe_count == 1
    assert plan.obligations[0].obligation_id in selection.covered_seed_obligation_ids


def test_opaque_edge_in_cone_forces_both_fallback() -> None:
    target = _symbol("native_wrap", "def native_wrap():\n    return 1\n")
    test = _symbol(
        "test_native",
        "def test_native():\n    assert native_wrap() == 1\n",
        module="tests/test_native.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={
            "pytest_node_id": "tests/test_native.py::test_native",
            "pytest": {"kind": "test"},
        },
    )
    edge = DependencyEdge(
        target.stable_id,
        test.stable_id,
        RelationType.TESTED_BY,
        "static",
        AnalysisConfidence.OPAQUE,
        "1",
        metadata={"native": True, "confidence_reason": "opaque_native"},
    )
    current = _view(symbols=(target, test), edges=(edge,))
    plan = _plan(current, [_obligation(target.stable_id)])
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState(
            "repo:selection", symbols=(target, test), edges=(edge,)
        ),
    )
    assert selection.fallback in {
        SelectionFallback.BOTH,
        SelectionFallback.FULL_PYTEST,
    }
    assert (
        SelectionFallbackReason.NATIVE_OR_OPAQUE_REACHABILITY.value
        in selection.fallback_reasons
    )


def test_unknown_universe_forces_full_pytest_fallback() -> None:
    # Function-only graph: no TEST symbols → unknown pytest universe.
    target = _symbol("solo", "def solo():\n    return 1\n")
    current = _view(symbols=(target,))
    plan = _plan(current, [_obligation(target.stable_id)])
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState("repo:selection", symbols=(target,)),
    )
    assert selection.fallback in {
        SelectionFallback.FULL_PYTEST,
        SelectionFallback.BOTH,
    }
    assert (
        SelectionFallbackReason.UNKNOWN_TEST_UNIVERSE.value
        in selection.fallback_reasons
    )
    assert selection.known_test_universe_count == 0
    assert selection.known_test_universe_cid is None


def test_explicit_include_exclude_and_force_full_rules() -> None:
    test_a = _symbol(
        "test_a",
        "def test_a():\n    assert True\n",
        module="tests/test_a.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_a.py::test_a", "pytest": {"kind": "test"}},
    )
    test_b = _symbol(
        "test_b",
        "def test_b():\n    assert True\n",
        module="tests/test_b.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_b.py::test_b", "pytest": {"kind": "test"}},
    )
    current = _view(symbols=(test_a, test_b))
    index = RepositoryState("repo:selection", symbols=(test_a, test_b))
    # Empty invalidation seeds; include rule supplies subjects.
    plan = _plan(current, [])
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        explicit_rules=(
            SelectionRule(
                rule_id="include-a",
                kind=SelectionRuleKind.INCLUDE,
                subjects=["tests/test_a.py::test_a", "tests/test_b.py::test_b"],
            ),
            SelectionRule(
                rule_id="exclude-b",
                kind=SelectionRuleKind.EXCLUDE,
                subjects=["tests/test_b.py::test_b"],
            ),
        ),
        current_index=index,
    )
    assert selection.selected_pytest_node_ids == ("tests/test_a.py::test_a",)
    assert selection.fallback == SelectionFallback.NONE

    forced = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        explicit_rules=(
            SelectionRule(
                rule_id="force",
                kind=SelectionRuleKind.FORCE_FULL,
                subjects=(),
            ),
        ),
        current_index=index,
    )
    assert forced.fallback == SelectionFallback.BOTH
    assert (
        SelectionFallbackReason.EXPLICIT_RULE_FORCE_FULL.value in forced.fallback_reasons
    )


def test_deletion_evidence_uses_previous_state_graph() -> None:
    deleted = _symbol("gone", "def gone():\n    return 0\n")
    test = _symbol(
        "test_gone",
        "def test_gone():\n    assert gone() == 0\n",
        module="tests/test_gone.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={
            "pytest_node_id": "tests/test_gone.py::test_gone",
            "pytest": {"kind": "test"},
        },
    )
    edge = DependencyEdge(
        deleted.stable_id,
        test.stable_id,
        RelationType.TESTED_BY,
        "static",
        "exact",
        "1",
    )
    previous = _view(symbols=(deleted, test), edges=(edge,), label="prev")
    # Current dropped the deleted symbol but keeps the test for selection identity.
    current = _view(symbols=(test,), edges=(), label="curr")
    plan = _plan(
        current,
        [
            _obligation(
                deleted.stable_id,
                reason="deleted_symbol_dependency",
                remediation=SemanticRemediation.RERUN_TEST.value,
            )
        ],
        previous=previous,
    )
    selection = select_tests_and_proofs(
        previous,
        current,
        plan,
        policy=_policy(),
        previous_index=RepositoryState(
            "repo:selection", symbols=(deleted, test), edges=(edge,)
        ),
        current_index=RepositoryState("repo:selection", symbols=(test,)),
    )
    assert selection.selected_pytest_node_ids == ("tests/test_gone.py::test_gone",)
    assert selection.previous_root_cid == previous.root.root_cid
    assert selection.fallback == SelectionFallback.NONE


def test_policy_disallows_fallback_fails_closed() -> None:
    current = _view()
    plan = _plan(
        current,
        [
            _obligation(
                "plugin:x",
                reason="pytest_plugin_changed",
                remediation=SemanticRemediation.FULL_PYTEST_FALLBACK.value,
                details={"binding_kind": "pytest_plugin"},
            )
        ],
    )
    with pytest.raises(TestSelectionError, match="allow_full_fallback"):
        select_tests_and_proofs(
            None,
            current,
            plan,
            policy=_policy(allow_full_fallback=False),
            current_index=RepositoryState("repo:selection"),
        )


def test_root_cid_mismatch_fails_closed() -> None:
    current = _view()
    other = _view(label="other")
    plan = SemanticInvalidationPlan(
        previous_root_cid=None,
        current_root_cid=other.root.root_cid,
        obligations=(),
    )
    with pytest.raises(TestSelectionError, match="current_root_cid"):
        select_tests_and_proofs(
            None,
            current,
            plan,
            policy=_policy(),
            current_index=RepositoryState("repo:selection"),
        )


def test_configured_by_and_schema_adapter_relations() -> None:
    schema = _symbol(
        "Payload",
        "class Payload:\n    pass\n",
        kind=SymbolKind.CLASS,
    )
    test = _symbol(
        "test_payload",
        "def test_payload():\n    assert True\n",
        module="tests/test_payload.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={
            "pytest_node_id": "tests/test_payload.py::test_payload",
            "pytest": {"kind": "test"},
        },
    )
    edges = (
        DependencyEdge(
            test.stable_id,
            schema.stable_id,
            RelationType.VALIDATES,
            "static",
            "exact",
            "1",
        ),
        DependencyEdge(
            test.stable_id,
            "pytest-config:pytest.ini",
            RelationType.CONFIGURED_BY,
            "pytest-static-config-scope",
            "exact",
            "1",
            metadata={"config_path": "pytest.ini"},
        ),
    )
    current = _view(symbols=(schema, test), edges=edges)
    index = RepositoryState("repo:selection", symbols=(schema, test), edges=edges)

    plan_schema = _plan(current, [_obligation(schema.stable_id)])
    sel_schema = select_tests_and_proofs(
        None, current, plan_schema, policy=_policy(), current_index=index
    )
    assert sel_schema.selected_pytest_node_ids == (
        "tests/test_payload.py::test_payload",
    )

    plan_cfg = _plan(
        current,
        [
            _obligation(
                "pytest-config:pytest.ini",
                reason="pytest_config_changed",
                remediation=SemanticRemediation.RERUN_TEST.value,
                origin=ObligationOrigin.ENVIRONMENT,
            )
        ],
    )
    sel_cfg = select_tests_and_proofs(
        None, current, plan_cfg, policy=_policy(), current_index=index
    )
    assert sel_cfg.selected_pytest_node_ids == ("tests/test_payload.py::test_payload",)


def test_full_proofs_fallback_and_both_combine() -> None:
    current = _view()
    plan = _plan(
        current,
        [
            _obligation(
                "proof-config:lean",
                reason="proof_config_changed",
                remediation=SemanticRemediation.FULL_PROOFS_FALLBACK.value,
                origin=ObligationOrigin.ENVIRONMENT,
            ),
            _obligation(
                "plugin:x",
                reason="pytest_plugin_changed",
                remediation=SemanticRemediation.FULL_PYTEST_FALLBACK.value,
                origin=ObligationOrigin.ENVIRONMENT,
                details={"binding_kind": "pytest_plugin"},
            ),
        ],
    )
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState("repo:selection"),
    )
    assert selection.fallback == SelectionFallback.BOTH
    assert selection.selected_pytest_node_ids == ()
    assert selection.selected_proof_ids == ()


def test_selection_cid_stable_under_reordering() -> None:
    a = _symbol(
        "test_a",
        "def test_a():\n    assert True\n",
        module="tests/test_a.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_a.py::test_a", "pytest": {"kind": "test"}},
    )
    b = _symbol(
        "test_b",
        "def test_b():\n    assert True\n",
        module="tests/test_b.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_b.py::test_b", "pytest": {"kind": "test"}},
    )
    current = _view(symbols=(a, b))
    plan = _plan(current, [])
    rules = (
        SelectionRule(
            rule_id="inc",
            kind=SelectionRuleKind.INCLUDE,
            subjects=["tests/test_b.py::test_b", "tests/test_a.py::test_a"],
        ),
    )
    s1 = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        explicit_rules=rules,
        current_index=RepositoryState("repo:selection", symbols=(a, b)),
    )
    s2 = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        explicit_rules=rules,
        current_index=RepositoryState("repo:selection", symbols=(b, a)),
    )
    assert s1.selection_cid == s2.selection_cid
    assert s1.selected_pytest_node_ids == (
        "tests/test_a.py::test_a",
        "tests/test_b.py::test_b",
    )


def test_empty_plan_yields_none_fallback() -> None:
    test = _symbol(
        "test_ok",
        "def test_ok():\n    assert True\n",
        module="tests/test_ok.py",
        namespace="tests",
        kind=SymbolKind.TEST,
        metadata={"pytest_node_id": "tests/test_ok.py::test_ok", "pytest": {"kind": "test"}},
    )
    current = _view(symbols=(test,))
    plan = _plan(current, [])
    selection = select_tests_and_proofs(
        None,
        current,
        plan,
        policy=_policy(),
        current_index=RepositoryState("repo:selection", symbols=(test,)),
    )
    assert selection.fallback == SelectionFallback.NONE
    assert selection.selected_pytest_node_ids == ()
    assert selection.selected_proof_ids == ()
    assert selection.known_test_universe_count == 1
    assert selection.unresolved_obligation_ids == ()
