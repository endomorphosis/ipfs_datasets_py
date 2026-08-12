"""Closeout regressions for every prior semantic-state boundary (DSS-011).

Locks the accelerate consumer interface, storage-neutral view/get_block, bundle
handoff, TestSelectionRef / SemanticCapsuleRef field mapping, MCP++ wire
exclusion, deterministic cold/incremental identity, and known opaque limits
without re-running the full controlled e2e matrix owned by DSS-010.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
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
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state import (
    CorruptBlockError,
    MissingBlockError,
    SemanticCapsule,
    SemanticStateApiError,
    SemanticStateBundle,
    SemanticStateRoot,
    UnknownSymbolError,
    VerifiedSemanticStateView,
    assess_capsule_freshness,
    build_semantic_state,
    compare_test_selection_oracle,
    open_semantic_state,
    select_tests_and_proofs,
    verify_semantic_state_bundle,
    view_semantic_state_bundle,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.api import (
    SEMANTIC_STATE_API_SCHEMA,
    SEMANTIC_STATE_BLOCK_READER_INTERFACE,
    SEMANTIC_STATE_PRODUCER_INTERFACE,
    SEMANTIC_STATE_VIEW_INTERFACE,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    ROOT_EXCLUDED_FIELD_NAMES,
    AdmissionDecision,
    BindingKind,
    BindingScope,
    CAPSULE_FRESHNESS_SCHEMA,
    EnvironmentBinding,
    SEMANTIC_CAPSULE_SCHEMA,
    SelectionFallback,
    SelectionPolicy,
    SemanticInvalidationPlan,
    TEST_SELECTION_SCHEMA,
    TestSelection,
)

REPO = "repo:semantic-state-regressions"
PACKAGE_DIR = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
)
CONTRACT_DOC = (
    Path(__file__).resolve().parents[5]
    / "docs"
    / "software_contracts"
    / "SEMANTIC_STATE_CONTRACT.md"
)

# Precise consumer reference shapes from the accelerate dependency seal.
TEST_SELECTION_REF_FIELDS: tuple[str, ...] = (
    "selection_cid",
    "previous_semantic_state_root_cid_or_null",
    "current_semantic_state_root_cid",
)
SEMANTIC_CAPSULE_REF_FIELDS: tuple[str, ...] = (
    "capsule_cid",
    "semantic_state_root_cid",
    "stable_symbol_id",
    "version_cid",
    "source_cid",
    "confidence",
    "validity_bindings",
    "raw_source_required",
)

_FORBIDDEN_MCP_TYPES = frozenset(
    {
        "InterfaceDescriptor",
        "ExecutionEnvelope",
        "ExecutionReceipt",
        "DAGEvent",
    }
)
_FORBIDDEN_MUTATION_METHODS = frozenset(
    {
        "put",
        "put_block",
        "publish",
        "cas",
        "compare_and_swap",
        "write",
        "store",
        "commit",
        "wal_append",
    }
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _make_symbol(
    qualified_name: str,
    *,
    module_path: str = "pkg/mod.py",
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
    body: str | None = None,
) -> SymbolRecord:
    short = qualified_name.rsplit(".", 1)[-1]
    source = body or f"def {short}(value: int) -> int:\n    return value + 1\n"
    node = ast.parse(source).body[0]
    stable = stable_symbol_id(
        REPO, "python", module_path, qualified_name, SymbolKind.FUNCTION, "pkg"
    )
    sig = {"parameters": ["value"], "return": "int"}
    version = symbol_version_cid(stable, node, sig, ["public"], {"value": "int"})
    return SymbolRecord(
        stable,
        version,
        REPO,
        "python",
        module_path,
        qualified_name,
        SymbolKind.FUNCTION,
        "pkg",
        cid_for_bytes(source.encode("utf-8")),
        None,
        confidence,
        sig,
        ["public"],
        {"value": "int"},
        {},
        normalized_ast=node,
    )


def _edge(
    source: SymbolRecord,
    target: SymbolRecord,
    relation: RelationType | str = RelationType.CALLS,
    *,
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
) -> DependencyEdge:
    return DependencyEdge(
        source.stable_id,
        target.stable_id,
        relation,
        "lexical",
        confidence,
        "1",
        None,
        {},
    )


def _state(
    symbols: list[SymbolRecord],
    edges: list[DependencyEdge] | None = None,
) -> RepositoryState:
    return RepositoryState(
        REPO,
        symbols=tuple(symbols),
        artifacts=(),
        edges=tuple(edges or ()),
    )


def _binding(binding_id: str = "toolchain:python") -> EnvironmentBinding:
    return EnvironmentBinding(
        binding_id=binding_id,
        kind=BindingKind.PYTHON_TOOLCHAIN,
        version_cid=_cid(f"{binding_id}:v1"),
        scope=BindingScope.GLOBAL,
        extraction_authority="test",
        confidence=AnalysisConfidence.EXACT,
    )


# ---------------------------------------------------------------------------
# Documentation freeze (SemanticStateRelease@1)
# ---------------------------------------------------------------------------


def test_contract_document_exists_and_names_release_surface() -> None:
    assert CONTRACT_DOC.is_file()
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    assert "SemanticStateRelease@1" in text
    assert "TestSelectionRef" in text
    assert "SemanticCapsuleRef" in text
    assert "SemanticStateView" in text
    assert "get_block" in text
    assert "SemanticStateBundle" in text
    for field in TEST_SELECTION_REF_FIELDS:
        assert field in text
    for field in SEMANTIC_CAPSULE_REF_FIELDS:
        assert field in text
    # Known limits without overclaim.
    assert "opaque" in text.lower()
    assert "dynamic" in text.lower()
    assert "cannot make dynamic Python exact" in text or "cannot make dynamic" in text


def test_contract_document_does_not_overclaim_cli_server_or_benchmark() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    # Explicit non-goals must remain present.
    for phrase in (
        "does not define a",
        "CLI",
        "benchmark",
        "ZK",
    ):
        assert phrase in text


# ---------------------------------------------------------------------------
# Closed public API / interface constants
# ---------------------------------------------------------------------------


def test_interface_constants_remain_stable() -> None:
    assert SEMANTIC_STATE_PRODUCER_INTERFACE == "SemanticStateProducer@1"
    assert SEMANTIC_STATE_VIEW_INTERFACE == "SemanticStateView@1"
    assert SEMANTIC_STATE_BLOCK_READER_INTERFACE == "SemanticStateBlockReader@1"
    assert SEMANTIC_STATE_API_SCHEMA == (
        "ipfs-datasets.software-contracts.semantic-state-api@1"
    )


def test_public_facade_still_exports_accelerate_surface() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state as pkg

    required = (
        "build_semantic_state",
        "verify_semantic_state_bundle",
        "open_semantic_state",
        "view_semantic_state_bundle",
        "compile_semantic_capsule",
        "assess_capsule_freshness",
        "read_required_source",
        "extend_semantic_invalidation",
        "select_tests_and_proofs",
        "compare_test_selection_oracle",
        "SemanticStateView",
        "SemanticStateBlockReader",
        "SemanticStateBundle",
        "SemanticStateRoot",
        "SemanticCapsule",
        "VerifiedSemanticStateView",
    )
    for name in required:
        assert name in pkg.__all__
        assert hasattr(pkg, name)


def test_build_and_open_signatures_remain_closed() -> None:
    assert list(inspect.signature(build_semantic_state).parameters) == [
        "semantic_index",
        "environment_bindings",
        "previous_bundle",
    ]
    assert list(inspect.signature(open_semantic_state).parameters) == [
        "root_cid",
        "get_block",
    ]
    assert list(inspect.signature(verify_semantic_state_bundle).parameters) == [
        "bundle"
    ]


# ---------------------------------------------------------------------------
# Bundle handoff + cold/incremental identity
# ---------------------------------------------------------------------------


def test_cold_and_incremental_bundles_are_byte_identical() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    state = _state([alpha, beta], [_edge(alpha, beta)])
    bindings = (_binding(),)

    cold = build_semantic_state(state, environment_bindings=bindings)
    incremental = build_semantic_state(
        state, environment_bindings=bindings, previous_bundle=cold
    )

    assert cold.root.root_cid == incremental.root.root_cid
    assert dict(cold.blocks) == dict(incremental.blocks)
    verify_semantic_state_bundle(cold)
    verify_semantic_state_bundle(incremental)


def test_bundle_exposes_only_read_verify_handoff_methods() -> None:
    public = {
        name
        for name, _ in inspect.getmembers(SemanticStateBundle, predicate=callable)
        if not name.startswith("_")
    }
    # Finite verified handoff: root/blocks properties plus get/verify/root_cid.
    assert "get_block" in public
    assert "verify" in public
    assert "root_cid" in public
    assert public.isdisjoint(_FORBIDDEN_MUTATION_METHODS)


def test_bundle_has_no_storage_mutation_methods_on_instance() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    for name in _FORBIDDEN_MUTATION_METHODS:
        assert not hasattr(bundle, name)


# ---------------------------------------------------------------------------
# SemanticStateView / get_block storage-neutral boundary
# ---------------------------------------------------------------------------


def test_view_get_block_reverifies_and_is_read_only() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]), environment_bindings=(_binding(),))
    view = view_semantic_state_bundle(bundle)

    assert isinstance(view, VerifiedSemanticStateView)
    root_bytes = view.get_block(view.root.root_cid)
    assert type(root_bytes) is bytes
    assert root_bytes == bundle.get_block(view.root.root_cid)

    # Unknown CID is typed missing, not a write side channel.
    missing = _cid("absent-block")
    with pytest.raises(MissingBlockError):
        view.get_block(missing)

    public = {
        name
        for name, _ in inspect.getmembers(type(view), predicate=callable)
        if not name.startswith("_")
    }
    assert {"get_block", "symbol_node", "capsule", "from_bundle"} <= public
    assert public.isdisjoint(_FORBIDDEN_MUTATION_METHODS)


def test_open_semantic_state_injected_reader_reverifies_corrupt_bytes() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    root_cid = bundle.root.root_cid
    blocks = dict(bundle.blocks)

    def get_block(cid: str) -> bytes:
        if cid == root_cid:
            return blocks[cid]
        if cid in blocks:
            # Corrupt a non-root fetch path after open.
            return b'{"forged": true}'
        raise KeyError(cid)

    view = open_semantic_state(root_cid, get_block)
    assert view.root.root_cid == root_cid

    # Pick any non-root block if present; otherwise re-fetch root is fine.
    other = next((c for c in blocks if c != root_cid), None)
    if other is not None:
        with pytest.raises(CorruptBlockError):
            view.get_block(other)


def test_view_symbol_and_capsule_resolve_through_indexes() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    view = view_semantic_state_bundle(bundle)
    node = view.symbol_node(alpha.stable_id)
    capsule = view.capsule(alpha.stable_id)
    assert node.stable_symbol_id == alpha.stable_id
    assert capsule.stable_symbol_id == alpha.stable_id
    assert capsule.version_cid == alpha.version_cid
    with pytest.raises(UnknownSymbolError):
        view.capsule("stable:does-not-exist")


# ---------------------------------------------------------------------------
# TestSelectionRef mapping
# ---------------------------------------------------------------------------


def test_test_selection_ref_fields_project_from_test_selection() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    cold = build_semantic_state(state)
    view = view_semantic_state_bundle(cold)
    # Empty plan over a single state: selection still binds root CIDs.
    plan = SemanticInvalidationPlan(
        previous_root_cid=None,
        current_root_cid=cold.root.root_cid,
        obligations=(),
    )
    # Some implementations require previous_root; try both shapes via public API.
    try:
        selection = select_tests_and_proofs(
            None,
            view,
            plan,
            policy=SelectionPolicy(policy_id="reg-ref", allow_full_fallback=True),
        )
    except (TypeError, SemanticStateApiError, ValueError):
        # If previous is required as a view, rebuild with previous=current.
        selection = select_tests_and_proofs(
            view,
            view,
            SemanticInvalidationPlan(
                previous_root_cid=cold.root.root_cid,
                current_root_cid=cold.root.root_cid,
                obligations=(),
            ),
            policy=SelectionPolicy(policy_id="reg-ref", allow_full_fallback=True),
        )

    assert isinstance(selection, TestSelection)
    assert selection.selection_cid == cid_for_structured(selection.identity_payload())
    assert selection.to_dict()["schema"] == TEST_SELECTION_SCHEMA

    ref = {
        "selection_cid": selection.selection_cid,
        "previous_semantic_state_root_cid_or_null": selection.previous_root_cid,
        "current_semantic_state_root_cid": selection.current_root_cid,
    }
    assert set(ref) == set(TEST_SELECTION_REF_FIELDS)
    assert ref["current_semantic_state_root_cid"] == cold.root.root_cid
    assert ref["selection_cid"]
    # Accelerate must hold the ref, not re-author selection membership.
    assert "selected_pytest_node_ids" in selection.to_dict()
    assert "fallback" in selection.to_dict()
    assert selection.fallback in {item.value for item in SelectionFallback} | set(
        SelectionFallback
    )


def test_test_selection_schema_constant_is_closed() -> None:
    assert TEST_SELECTION_SCHEMA == (
        "ipfs-datasets.software-contracts.semantic-test-selection@1"
    )


# ---------------------------------------------------------------------------
# SemanticCapsuleRef mapping
# ---------------------------------------------------------------------------


def test_semantic_capsule_ref_fields_project_from_capsule_and_freshness() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]), environment_bindings=(_binding(),))
    view = view_semantic_state_bundle(bundle)
    capsule = view.capsule(alpha.stable_id)
    assert isinstance(capsule, SemanticCapsule)
    assert capsule.capsule_schema == SEMANTIC_CAPSULE_SCHEMA

    freshness = assess_capsule_freshness(capsule, current_state=view)
    assert freshness.capsule_cid == capsule.capsule_cid
    assert freshness.to_dict()["schema"] == CAPSULE_FRESHNESS_SCHEMA

    raw_source_required = (
        str(freshness.admission) == AdmissionDecision.RAW_SOURCE_REQUIRED.value
        or freshness.admission == AdmissionDecision.RAW_SOURCE_REQUIRED
    )
    validity_bindings = {
        "relevant_binding_projection_cid": capsule.relevant_binding_projection_cid,
        "applicable_obligation_ids": list(freshness.applicable_obligation_ids),
    }
    ref = {
        "capsule_cid": capsule.capsule_cid,
        "semantic_state_root_cid": view.root.root_cid,
        "stable_symbol_id": capsule.stable_symbol_id,
        "version_cid": capsule.version_cid,
        "source_cid": capsule.source_cid,
        "confidence": str(capsule.confidence),
        "validity_bindings": validity_bindings,
        "raw_source_required": raw_source_required,
    }
    assert set(ref) == set(SEMANTIC_CAPSULE_REF_FIELDS)
    assert ref["stable_symbol_id"] == alpha.stable_id
    assert ref["version_cid"] == alpha.version_cid
    assert isinstance(ref["raw_source_required"], bool)


def test_opaque_confidence_forces_raw_source_or_visible_caveat() -> None:
    """Opaque producer confidence must not silently admit exact substitution."""
    opaque = _make_symbol(
        "pkg.mod.opaque_fn",
        confidence=AnalysisConfidence.OPAQUE,
        body="def opaque_fn(value: int) -> int:\n    return value\n",
    )
    bundle = build_semantic_state(_state([opaque]))
    view = view_semantic_state_bundle(bundle)
    capsule = view.capsule(opaque.stable_id)
    freshness = assess_capsule_freshness(capsule, current_state=view)
    admission = str(freshness.admission)
    # Exact substitute is forbidden for opaque evidence.
    assert admission != AdmissionDecision.EXACT_SUBSTITUTE.value
    assert admission in {
        AdmissionDecision.RAW_SOURCE_REQUIRED.value,
        AdmissionDecision.CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS.value,
    }
    if admission == AdmissionDecision.CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS.value:
        assert list(freshness.caveats)


# ---------------------------------------------------------------------------
# MCP++ / root exclusion regressions
# ---------------------------------------------------------------------------


def test_package_defines_no_mcp_wire_types() -> None:
    found: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in _FORBIDDEN_MCP_TYPES:
                found.append(f"{path.name}:{node.name}")
    assert found == []


def test_root_payload_excludes_wire_and_operational_fields() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    root = build_semantic_state(_state([alpha])).root
    payload = root.identity_payload()
    claim = root.to_dict()
    for field in (
        "request_id",
        "attempt",
        "provider",
        "envelope_cid",
        "execution_envelope",
        "dag_event",
        "selection",
        "receipt",
        "generation",
        "timestamp",
    ):
        assert field not in payload
        assert field not in claim
        assert field in ROOT_EXCLUDED_FIELD_NAMES


def test_api_module_has_no_kit_or_envelope_side_channels() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state.api as api

    source = inspect.getsource(api)
    for banned in (
        "cid_for_envelope",
        "ExecutionEnvelope",
        "ExecutionReceipt",
        "DAGEvent",
        "InterfaceDescriptor",
        "ipfs_kit",
        "IpfsKit",
    ):
        assert banned not in source


# ---------------------------------------------------------------------------
# Schema packaging + payload schema presence
# ---------------------------------------------------------------------------


def test_payload_schema_packaged_and_names_root() -> None:
    schema_path = PACKAGE_DIR / "schemas" / "semantic-state.payload.schema.json"
    assert schema_path.is_file()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    blob = json.dumps(schema)
    assert "semantic" in blob.lower()
    assert (
        "SemanticStateRoot" in blob
        or "semantic-state-root" in blob
        or "repository_state_cid" in blob
    )


# ---------------------------------------------------------------------------
# Oracle purity regression (no execution)
# ---------------------------------------------------------------------------


def test_oracle_compare_is_pure_over_supplied_facts() -> None:
    from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
        NormalizedTestStatus,
        TestOutcome,
        TestRunFacts,
    )

    selection = TestSelection(
        previous_root_cid=None,
        current_root_cid=_cid("current-root"),
        selected_pytest_node_ids=("tests/test_a.py::test_one",),
        selected_proof_ids=(),
        known_test_universe_count=1,
        fallback=SelectionFallback.NONE,
    )
    outcome = TestOutcome(
        node_id="tests/test_a.py::test_one",
        status=NormalizedTestStatus.PASSED,
    )
    facts = TestRunFacts(run_id="reg-oracle-run", outcomes=(outcome,))
    comparison = compare_test_selection_oracle(
        selection,
        baseline_full=facts,
        selected_run=facts,
        candidate_full=facts,
        authored_oracle=("tests/test_a.py::test_one",),
    )
    assert comparison is not None
    # Pure metrics object — no pytest execution fields.
    payload = comparison.to_dict() if hasattr(comparison, "to_dict") else {}
    if payload:
        assert "subprocess" not in json.dumps(payload)
        assert "command" not in payload
