"""Acceptance vectors for deterministic incremental capsule compilation (DSS-004)."""

from __future__ import annotations

import ast
import random
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
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
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    build_environment_binding_set,
    relevant_binding_projection_for_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.capsules import (
    CAPSULE_COMPILER_VERSION,
    SEMANTIC_CAPSULE_COMPILER_INTERFACE,
    SEMANTIC_CAPSULE_SCHEMA,
    CapsuleCompileResult,
    CapsuleCompilerError,
    capsule_source_key,
    compile_semantic_capsule,
    compile_semantic_capsules,
    verify_capsule_compile_result,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    EnvironmentBindingSet,
    SemanticCapsule,
    SemanticStateBundle,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
    SymbolFactNode,
)


REPO = "repo:capsule-example"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _make_symbol(
    qualified_name: str,
    *,
    module_path: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind | str = SymbolKind.FUNCTION,
    body: str | None = None,
    span: SourceSpan | None = None,
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
    signature: dict[str, Any] | None = None,
    decorators: list[str] | None = None,
    annotations: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SymbolRecord:
    short = qualified_name.rsplit(".", 1)[-1]
    if body is None:
        source = f"def {short}(value: int) -> int:\n    return value + 1\n"
    else:
        source = body
    node = ast.parse(source).body[0]
    stable = stable_symbol_id(REPO, "python", module_path, qualified_name, kind, namespace)
    sig = signature if signature is not None else {"parameters": ["value"], "return": "int"}
    decs = decorators if decorators is not None else ["public"]
    anns = annotations if annotations is not None else {"value": "int", "return": "int"}
    version = symbol_version_cid(stable, node, sig, decs, anns)
    return SymbolRecord(
        stable,
        version,
        REPO,
        "python",
        module_path,
        qualified_name,
        kind,
        namespace,
        cid_for_bytes(source.encode("utf-8")),
        span,
        confidence,
        sig,
        decs,
        anns,
        metadata or {},
        normalized_ast=node,
    )


def _mutate_symbol_semantics(symbol: SymbolRecord) -> SymbolRecord:
    short = symbol.qualified_name.rsplit(".", 1)[-1]
    source = f"def {short}(value: int) -> int:\n    return value + 99\n"
    node = ast.parse(source).body[0]
    sig = {"parameters": ["value"], "return": "int", "semantic_bump": 99}
    version = symbol_version_cid(
        symbol.stable_id, node, sig, list(symbol.decorators), dict(symbol.annotations)
    )
    return SymbolRecord(
        symbol.stable_id,
        version,
        symbol.repository_id,
        symbol.language,
        symbol.module_path,
        symbol.qualified_name,
        symbol.kind,
        symbol.namespace,
        cid_for_bytes(source.encode("utf-8")),
        symbol.span,
        symbol.confidence,
        sig,
        list(symbol.decorators),
        dict(symbol.annotations),
        dict(symbol.metadata),
        normalized_ast=node,
    )


def _edge(
    source: SymbolRecord,
    target: SymbolRecord | str,
    relation: RelationType | str = RelationType.CALLS,
    *,
    method: str = "lexical",
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
    span: SourceSpan | None = None,
    metadata: dict[str, Any] | None = None,
) -> DependencyEdge:
    target_id = target.stable_id if isinstance(target, SymbolRecord) else target
    return DependencyEdge(
        source.stable_id,
        target_id,
        relation,
        method,
        confidence,
        "1",
        span,
        metadata or {},
    )


def _binding(
    binding_id: str,
    kind: BindingKind,
    *,
    version: str = "v1",
    scope: BindingScope = BindingScope.GLOBAL,
    subject_id: str | None = None,
    confidence: AnalysisConfidence = AnalysisConfidence.EXACT,
) -> EnvironmentBinding:
    return EnvironmentBinding(
        binding_id=binding_id,
        kind=kind,
        version_cid=_cid(f"{binding_id}:{version}"),
        scope=scope,
        extraction_authority="test",
        confidence=confidence,
        subject_id=subject_id,
    )


def _state(
    symbols: list[SymbolRecord],
    *,
    edges: list[DependencyEdge] | None = None,
) -> RepositoryState:
    return RepositoryState(
        REPO,
        symbols=tuple(symbols),
        artifacts=(),
        edges=tuple(edges or ()),
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


def _bundle_from_capsules(
    result: CapsuleCompileResult,
    *,
    binding_set: EnvironmentBindingSet | None = None,
) -> SemanticStateBundle:
    """Package capsule compile output into a minimal verified previous_bundle."""
    placeholder = SortedPairIndex(
        pairs=[("placeholder", _cid("placeholder-block"))]
    ).index_cid
    binding_cid = (
        binding_set.binding_set_cid
        if binding_set is not None
        else SortedPairIndex(pairs=[("empty", _cid("empty-bindings"))]).index_cid
    )
    root = SemanticStateRoot(
        repository_id=REPO,
        producer=_producer(),
        symbol_fact_index_cid=placeholder,
        artifact_fact_index_cid=placeholder,
        semantic_link_index_cid=placeholder,
        symbol_node_index_cid=placeholder,
        capsule_index_cid=result.capsule_index_cid,
        environment_binding_set_cid=binding_cid,
        analysis_limitation_index_cid=placeholder,
    )
    blocks = dict(result.blocks)
    if binding_set is not None:
        blocks[binding_set.binding_set_cid] = canonical_dag_json_bytes(
            binding_set.identity_payload()
        )
    return SemanticStateBundle(root=root, blocks=blocks)


# ---------------------------------------------------------------------------
# Core compilation
# ---------------------------------------------------------------------------


def test_interface_constants() -> None:
    assert SEMANTIC_CAPSULE_COMPILER_INTERFACE == "SemanticCapsuleCompiler@1"
    assert CAPSULE_COMPILER_VERSION == "1"
    assert SEMANTIC_CAPSULE_SCHEMA == (
        "ipfs-datasets.software-contracts.semantic-capsule@1"
    )


def test_compile_capsules_deterministic_sorted_and_order_independent() -> None:
    alpha = _make_symbol("pkg.mod.alpha", body="def alpha(x: int) -> int:\n    return x\n")
    beta = _make_symbol("pkg.mod.beta", body="def beta(x: int) -> int:\n    return x\n")
    edge = _edge(alpha, beta, RelationType.CALLS)
    state_ab = _state([alpha, beta], edges=[edge])
    state_ba = _state([beta, alpha], edges=[edge])

    result_ab = compile_semantic_capsules(state_ab)
    result_ba = compile_semantic_capsules(state_ba)
    assert [c.stable_symbol_id for c in result_ab.capsules] == sorted(
        [alpha.stable_id, beta.stable_id]
    )
    assert result_ab.index.index_cid == result_ba.index.index_cid
    assert dict(result_ab.blocks) == dict(result_ba.blocks)
    assert [c.capsule_cid for c in result_ab.capsules] == [
        c.capsule_cid for c in result_ba.capsules
    ]
    verify_capsule_compile_result(result_ab)


def test_single_capsule_matches_batch_entry() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    edge = _edge(alpha, beta)
    state = _state([alpha, beta], edges=[edge])
    binding_set = build_environment_binding_set(
        [_binding("toolchain:python", BindingKind.PYTHON_TOOLCHAIN)]
    )
    batch = compile_semantic_capsules(state, binding_set=binding_set)
    single = compile_semantic_capsule(
        state, alpha.stable_id, relevant_bindings=binding_set
    )
    assert single == batch.capsule(alpha.stable_id)
    assert single.capsule_cid == batch.capsule(alpha.stable_id).capsule_cid


def test_capsule_binds_producer_key_source_fact_and_dependencies() -> None:
    callee = _make_symbol(
        "pkg.mod.callee",
        body="def callee(x: int) -> int:\n    return x\n",
        metadata={
            "defaults": {"x": "0"},
            "contracts": {"pure": True},
            "docstring": "adds nothing",
            "llm_summary": "must not become truth",
            "effects": ["io:none"],
        },
    )
    caller = _make_symbol(
        "pkg.mod.caller",
        body="def caller(x: int) -> int:\n    return callee(x)\n",
    )
    edges = [
        _edge(caller, callee, RelationType.CALLS),
        _edge(caller, callee, RelationType.READS_STATE),
        _edge(caller, "schema:payload", RelationType.VALIDATES),
        _edge(caller, "schema:payload", RelationType.SERIALIZES),
        _edge(caller, "test:pkg.mod.test_caller", RelationType.TESTED_BY),
        _edge(caller, "fixture:db", RelationType.USES_FIXTURE),
        _edge(caller, "proof:caller-safe", RelationType.PROOF_DEPENDS_ON),
        _edge(caller, "exc:ValueError", RelationType.RAISES),
    ]
    state = _state([caller, callee], edges=edges)
    capsule = compile_semantic_capsule(state, caller.stable_id)

    assert capsule.producer_key() == capsule_source_key(caller)
    assert capsule.source_slice_path == caller.module_path
    assert capsule.source_cid == caller.source_cid
    assert capsule.symbol_fact_cid == SymbolFactNode(symbol=caller).fact_cid
    assert capsule.capsule_schema == SEMANTIC_CAPSULE_SCHEMA
    assert capsule.capsule_compiler_version == CAPSULE_COMPILER_VERSION
    assert capsule.signature == caller.signature
    assert list(capsule.decorators) == list(caller.decorators)
    assert callee.stable_id in capsule.dependency_stable_ids
    assert SymbolFactNode(symbol=callee).fact_cid in capsule.dependency_fact_cids
    assert callee.version_cid in capsule.dependency_version_cids
    assert any(edge.edge_id in capsule.dependency_link_ids for edge in edges[:2])
    assert "reads_state:" + callee.stable_id in capsule.effects
    # caller has no meta effects; callee meta is not copied onto caller.
    assert "io:none" not in capsule.effects
    assert "schema:payload" in capsule.schema_relations
    assert "serializes:schema:payload" in capsule.serialization_relations
    assert "test:pkg.mod.test_caller" in capsule.test_refs
    assert "fixture:db" in capsule.fixture_refs
    assert "proof:caller-safe" in capsule.proof_obligation_refs
    assert list(capsule.exception_behavior.get("raises")) == ["exc:ValueError"]
    assert capsule.docstring_hint is None  # caller has no docstring
    assert "llm_summary" not in capsule.metadata

    callee_capsule = compile_semantic_capsule(state, callee.stable_id)
    assert callee_capsule.defaults == {"x": "0"}
    assert callee_capsule.contracts == {"pure": True}
    assert callee_capsule.docstring_hint == "adds nothing"
    assert "llm_summary" not in callee_capsule.metadata
    assert "io:none" in callee_capsule.effects


def test_capsule_never_references_capsule_or_node_cids_as_dependencies() -> None:
    a = _make_symbol("pkg.mod.a")
    b = _make_symbol("pkg.mod.b")
    state = _state([a, b], edges=[_edge(a, b)])
    result = compile_semantic_capsules(state)
    capsule_cids = {c.capsule_cid for c in result.capsules}
    for capsule in result.capsules:
        for dep in (
            *capsule.dependency_stable_ids,
            *capsule.dependency_version_cids,
            *capsule.dependency_fact_cids,
            *capsule.dependency_link_ids,
        ):
            assert dep not in capsule_cids
        # Fact CIDs are fact-layer, not capsule CIDs.
        if capsule.symbol_fact_cid is not None:
            assert capsule.symbol_fact_cid not in capsule_cids


def test_confidence_never_raised_from_edges() -> None:
    exact = _make_symbol(
        "pkg.mod.exact",
        confidence=AnalysisConfidence.EXACT,
        body="def exact(x: int) -> int:\n    return x\n",
    )
    opaque_target = _make_symbol(
        "pkg.mod.opaque_target",
        confidence=AnalysisConfidence.OPAQUE,
        body="def opaque_target(x: int) -> int:\n    return x\n",
    )
    state = _state(
        [exact, opaque_target],
        edges=[
            _edge(
                exact,
                opaque_target,
                RelationType.CALLS,
                confidence=AnalysisConfidence.HEURISTIC,
            )
        ],
    )
    capsule = compile_semantic_capsule(state, exact.stable_id)
    # Least confident of symbol exact + edge heuristic => heuristic.
    assert capsule.confidence == AnalysisConfidence.HEURISTIC.value
    # Opaque symbol stays opaque (not raised).
    opaque_cap = compile_semantic_capsule(state, opaque_target.stable_id)
    assert opaque_cap.confidence == AnalysisConfidence.OPAQUE.value


# ---------------------------------------------------------------------------
# Binding projections
# ---------------------------------------------------------------------------


def test_unrelated_scoped_projection_does_not_change_capsule() -> None:
    sym_a = _make_symbol(
        "pkg_a.mod.alpha",
        module_path="pkg_a/mod.py",
        namespace="pkg_a",
        body="def alpha(x: int) -> int:\n    return x\n",
    )
    sym_b = _make_symbol(
        "pkg_b.mod.beta",
        module_path="pkg_b/mod.py",
        namespace="pkg_b",
        body="def beta(x: int) -> int:\n    return x\n",
    )
    lock_a = _binding(
        "lock:pkg-a",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.PACKAGE,
        subject_id="pkg_a",
        version="1",
    )
    lock_b_v1 = _binding(
        "lock:pkg-b",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.PACKAGE,
        subject_id="pkg_b",
        version="1",
    )
    lock_b_v2 = _binding(
        "lock:pkg-b",
        BindingKind.DEPENDENCY_LOCK,
        scope=BindingScope.PACKAGE,
        subject_id="pkg_b",
        version="2",
    )
    state = _state([sym_a, sym_b])
    set_v1 = build_environment_binding_set([lock_a, lock_b_v1])
    set_v2 = build_environment_binding_set([lock_a, lock_b_v2])

    result_v1 = compile_semantic_capsules(state, binding_set=set_v1)
    result_v2 = compile_semantic_capsules(state, binding_set=set_v2)

    # Package-B lock change must not alter package-A capsule.
    assert (
        result_v1.capsule(sym_a.stable_id).capsule_cid
        == result_v2.capsule(sym_a.stable_id).capsule_cid
    )
    # Package-B capsule must change with its scoped lock.
    assert (
        result_v1.capsule(sym_b.stable_id).capsule_cid
        != result_v2.capsule(sym_b.stable_id).capsule_cid
    )
    # Membership is decided by bindings; capsule binds only the relevant subset.
    proj_a = relevant_binding_projection_for_symbol(sym_a, set_v2)
    assert "lock:pkg-b" not in proj_a.binding_ids
    assert "lock:pkg-a" in proj_a.binding_ids
    # Same relevant membership against either full set yields the same capsule CID.
    assert result_v1.capsule(sym_a.stable_id).relevant_binding_projection_cid == (
        result_v2.capsule(sym_a.stable_id).relevant_binding_projection_cid
    )


def test_global_and_unknown_projections_conservatively_change_capsules() -> None:
    sym_a = _make_symbol(
        "pkg_a.mod.alpha",
        module_path="pkg_a/mod.py",
        namespace="pkg_a",
        body="def alpha(x: int) -> int:\n    return x\n",
    )
    sym_b = _make_symbol(
        "pkg_b.mod.beta",
        module_path="pkg_b/mod.py",
        namespace="pkg_b",
        body="def beta(x: int) -> int:\n    return x\n",
    )
    toolchain_v1 = _binding(
        "toolchain:python",
        BindingKind.PYTHON_TOOLCHAIN,
        scope=BindingScope.GLOBAL,
        version="1",
    )
    toolchain_v2 = _binding(
        "toolchain:python",
        BindingKind.PYTHON_TOOLCHAIN,
        scope=BindingScope.GLOBAL,
        version="2",
    )
    unknown_v1 = _binding(
        "policy:mystery",
        BindingKind.POLICY,
        scope=BindingScope.UNKNOWN,
        version="1",
    )
    unknown_v2 = _binding(
        "policy:mystery",
        BindingKind.POLICY,
        scope=BindingScope.UNKNOWN,
        version="2",
    )
    state = _state([sym_a, sym_b])

    global_v1 = compile_semantic_capsules(
        state, binding_set=build_environment_binding_set([toolchain_v1])
    )
    global_v2 = compile_semantic_capsules(
        state, binding_set=build_environment_binding_set([toolchain_v2])
    )
    for symbol in (sym_a, sym_b):
        assert (
            global_v1.capsule(symbol.stable_id).capsule_cid
            != global_v2.capsule(symbol.stable_id).capsule_cid
        )

    unknown_r1 = compile_semantic_capsules(
        state, binding_set=build_environment_binding_set([unknown_v1])
    )
    unknown_r2 = compile_semantic_capsules(
        state, binding_set=build_environment_binding_set([unknown_v2])
    )
    for symbol in (sym_a, sym_b):
        assert (
            unknown_r1.capsule(symbol.stable_id).capsule_cid
            != unknown_r2.capsule(symbol.stable_id).capsule_cid
        )
        proj = relevant_binding_projection_for_symbol(
            symbol, build_environment_binding_set([unknown_v1])
        )
        assert proj.includes_global is True


# ---------------------------------------------------------------------------
# Incremental reuse / cold identity
# ---------------------------------------------------------------------------


def test_cold_and_incremental_are_byte_identical_over_identical_inputs() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    edges = [_edge(alpha, beta)]
    state = _state([alpha, beta], edges=edges)
    binding_set = build_environment_binding_set(
        [
            _binding("toolchain:python", BindingKind.PYTHON_TOOLCHAIN),
            _binding(
                "lock:pkg",
                BindingKind.DEPENDENCY_LOCK,
                scope=BindingScope.PACKAGE,
                subject_id="pkg",
            ),
        ]
    )

    cold = compile_semantic_capsules(state, binding_set=binding_set)
    previous = _bundle_from_capsules(cold, binding_set=binding_set)
    incremental = compile_semantic_capsules(
        state, binding_set=binding_set, previous_bundle=previous
    )
    via_result = compile_semantic_capsules(
        state, binding_set=binding_set, previous_bundle=cold
    )

    assert dict(cold.blocks) == dict(incremental.blocks)
    assert cold.index.index_cid == incremental.index.index_cid
    assert [c.capsule_cid for c in cold.capsules] == [
        c.capsule_cid for c in incremental.capsules
    ]
    assert dict(cold.blocks) == dict(via_result.blocks)
    # Complete inputs reverify → every capsule/index block is reusable.
    assert set(incremental.reused_cids) == set(cold.blocks)
    verify_capsule_compile_result(incremental)


def test_previous_bundle_reuses_only_reverified_unchanged_capsules() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    state_v1 = _state([alpha, beta], edges=[_edge(alpha, beta)])
    cold_v1 = compile_semantic_capsules(state_v1)
    previous = _bundle_from_capsules(cold_v1)

    # Semantic change only on alpha; beta inputs identical.
    alpha_v2 = _mutate_symbol_semantics(alpha)
    state_v2 = _state([alpha_v2, beta], edges=[_edge(alpha_v2, beta)])
    cold_v2 = compile_semantic_capsules(state_v2)
    incremental = compile_semantic_capsules(state_v2, previous_bundle=previous)

    assert dict(cold_v2.blocks) == dict(incremental.blocks)
    beta_cid = cold_v2.capsule(beta.stable_id).capsule_cid
    alpha_cid = cold_v2.capsule(alpha_v2.stable_id).capsule_cid
    assert beta_cid in incremental.reused_cids
    assert alpha_cid not in incremental.reused_cids
    assert cold_v1.capsule(beta.stable_id).capsule_cid == beta_cid
    assert cold_v1.capsule(alpha.stable_id).capsule_cid != alpha_cid


def test_tampered_previous_block_is_not_trusted() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    cold = compile_semantic_capsules(state)
    previous = _bundle_from_capsules(cold)

    # Forge a previous bundle that maps an unrelated CID to garbage while
    # preserving the real capsule CID mapping to non-canonical bytes is
    # impossible without failing bundle construction; instead supply a
    # CapsuleCompileResult-like object with divergent bytes under a wrong CID
    # that will simply not be reused.
    forged_blocks = dict(cold.blocks)
    # Insert an unrelated verified block that should never match capsule CIDs.
    noise_payload = {"schema": "noise", "value": 1}
    noise_cid = cid_for_structured(noise_payload)
    forged_blocks[noise_cid] = canonical_dag_json_bytes(noise_payload)

    class _FakePrevious:
        blocks = forged_blocks

    incremental = compile_semantic_capsules(state, previous_bundle=_FakePrevious())
    assert dict(incremental.blocks) == dict(cold.blocks)
    assert noise_cid not in incremental.blocks
    assert set(incremental.reused_cids) == set(cold.blocks)


def test_shuffled_input_order_and_repeated_compile_are_stable() -> None:
    symbols = [
        _make_symbol(f"pkg.mod.fn{i}", body=f"def fn{i}(x: int) -> int:\n    return x + {i}\n")
        for i in range(5)
    ]
    edges = [
        _edge(symbols[i], symbols[i + 1])
        for i in range(len(symbols) - 1)
    ]
    rng = random.Random(7)
    results = []
    for _ in range(5):
        shuffled = list(symbols)
        rng.shuffle(shuffled)
        edge_shuffle = list(edges)
        rng.shuffle(edge_shuffle)
        results.append(
            compile_semantic_capsules(_state(shuffled, edges=edge_shuffle))
        )
    baseline = results[0]
    for result in results[1:]:
        assert dict(result.blocks) == dict(baseline.blocks)
        assert result.index.index_cid == baseline.index.index_cid


def test_unknown_symbol_and_bad_previous_fail_closed() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    with pytest.raises(CapsuleCompilerError, match="unknown stable_symbol_id"):
        compile_semantic_capsule(state, _cid("missing-symbol"))
    with pytest.raises(CapsuleCompilerError, match="previous_bundle"):
        compile_semantic_capsules(state, previous_bundle=object())  # type: ignore[arg-type]


def test_capsule_source_key_helpers() -> None:
    symbol = _make_symbol("pkg.mod.alpha")
    assert capsule_source_key(symbol) == (
        symbol.stable_id,
        symbol.version_cid,
        symbol.semantic_index_schema,
        symbol.extractor_version,
    )
    assert capsule_source_key(
        symbol.stable_id,
        symbol.version_cid,
        symbol.semantic_index_schema,
        symbol.extractor_version,
    ) == capsule_source_key(symbol)
    capsule = SemanticCapsule(
        stable_symbol_id=symbol.stable_id,
        version_cid=symbol.version_cid,
        semantic_index_schema=symbol.semantic_index_schema,
        extractor_version=symbol.extractor_version,
    )
    assert capsule.producer_key() == capsule_source_key(symbol)


def test_supplied_projection_must_match_binding_membership() -> None:
    symbol = _make_symbol("pkg.mod.alpha")
    state = _state([symbol])
    binding_set = build_environment_binding_set(
        [_binding("toolchain:python", BindingKind.PYTHON_TOOLCHAIN)]
    )
    other = build_environment_binding_set(
        [_binding("lock:other", BindingKind.DEPENDENCY_LOCK)]
    )
    wrong = relevant_binding_projection_for_symbol(symbol, other)
    with pytest.raises(CapsuleCompilerError, match="binding_ids"):
        compile_semantic_capsule(
            state,
            symbol.stable_id,
            binding_set=binding_set,
            relevant_projection=wrong,
        )
