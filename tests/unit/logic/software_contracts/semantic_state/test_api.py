"""Acceptance vectors for the storage-neutral semantic-state API (DSS-009)."""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Mapping

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
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state import (
    AnalysisLimitation,
    ArtifactFactNode,
    CorruptBlockError,
    IndexedSemanticStateView,
    MissingBlockError,
    SemanticLinkNode,
    SemanticStateApiError,
    SemanticStateBundle,
    SemanticStateRoot,
    SemanticStateView,
    SymbolFactNode,
    UnknownAnalysisLimitationError,
    UnknownArtifactError,
    UnknownSemanticLinkError,
    UnknownSymbolError,
    VerifiedSemanticStateView,
    assess_capsule_freshness,
    build_semantic_state,
    compare_test_selection_oracle,
    compile_semantic_capsule,
    extend_semantic_invalidation,
    open_semantic_state,
    read_required_source,
    select_tests_and_proofs,
    verify_semantic_state_bundle,
    view_semantic_state_bundle,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.api import (
    INDEXED_SEMANTIC_STATE_VIEW_INTERFACE,
    SEMANTIC_STATE_BLOCK_READER_INTERFACE,
    SEMANTIC_STATE_PRODUCER_INTERFACE,
    SEMANTIC_STATE_VIEW_INTERFACE,
    build_semantic_state as build_from_api,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    BindingKind,
    BindingScope,
    EnvironmentBinding,
    SemanticStateProducer,
    SortedPairIndex,
)


REPO = "repo:semantic-state-api"


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


def _edge(
    source: SymbolRecord,
    target: SymbolRecord | str,
    relation: RelationType | str = RelationType.CALLS,
) -> DependencyEdge:
    target_id = target.stable_id if isinstance(target, SymbolRecord) else target
    return DependencyEdge(
        source.stable_id,
        target_id,
        relation,
        "lexical",
        AnalysisConfidence.EXACT,
        "1",
        None,
        {},
    )


def _state(
    symbols: list[SymbolRecord],
    *,
    artifacts: list[ArtifactRecord] | None = None,
    edges: list[DependencyEdge] | None = None,
) -> RepositoryState:
    return RepositoryState(
        REPO,
        symbols=tuple(symbols),
        artifacts=tuple(artifacts or ()),
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
# Public signature / surface
# ---------------------------------------------------------------------------


def test_interface_constants() -> None:
    assert SEMANTIC_STATE_PRODUCER_INTERFACE == "SemanticStateProducer@1"
    assert SEMANTIC_STATE_VIEW_INTERFACE == "SemanticStateView@1"
    assert INDEXED_SEMANTIC_STATE_VIEW_INTERFACE == "IndexedSemanticStateView@1"
    assert SEMANTIC_STATE_BLOCK_READER_INTERFACE == "SemanticStateBlockReader@1"


def test_public_signatures_match_closed_contract() -> None:
    build_params = list(inspect.signature(build_semantic_state).parameters)
    assert build_params == [
        "semantic_index",
        "environment_bindings",
        "previous_bundle",
    ]
    assert list(inspect.signature(verify_semantic_state_bundle).parameters) == ["bundle"]
    assert list(inspect.signature(open_semantic_state).parameters) == [
        "root_cid",
        "get_block",
    ]
    # Plan-named assurance APIs remain re-exported with previous/current views.
    assert list(inspect.signature(extend_semantic_invalidation).parameters)[:6] == [
        "previous_index",
        "current_index",
        "delta",
        "plan",
        "previous_state",
        "current_state",
    ]
    select_params = list(inspect.signature(select_tests_and_proofs).parameters)
    assert select_params[:3] == ["previous_state", "current_state", "invalidation"]
    assert "policy" in select_params
    assert callable(compile_semantic_capsule)
    assert callable(assess_capsule_freshness)
    assert callable(read_required_source)
    assert callable(compare_test_selection_oracle)


def test_package_exports_closed_facade() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state as pkg

    for name in (
        "build_semantic_state",
        "verify_semantic_state_bundle",
        "open_semantic_state",
        "compile_semantic_capsule",
        "assess_capsule_freshness",
        "read_required_source",
        "extend_semantic_invalidation",
        "select_tests_and_proofs",
        "compare_test_selection_oracle",
        "SemanticStateView",
        "IndexedSemanticStateView",
        "SemanticStateBlockReader",
        "SemanticStateBundle",
        "SymbolFactNode",
        "ArtifactFactNode",
        "SemanticLinkNode",
        "AnalysisLimitation",
        "UnknownArtifactError",
        "UnknownSemanticLinkError",
        "UnknownAnalysisLimitationError",
        "INDEXED_SEMANTIC_STATE_VIEW_INTERFACE",
    ):
        assert name in pkg.__all__
        assert hasattr(pkg, name)


def test_indexed_view_protocol_is_additive_to_legacy_view_contract() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))

    class LegacySemanticStateView:
        def __init__(self) -> None:
            self.root = bundle.root

        def get_block(self, cid: str) -> bytes:
            return bundle.get_block(cid)

        def symbol_node(self, stable_symbol_id: str):
            raise UnknownSymbolError(stable_symbol_id)

        def capsule(self, stable_symbol_id: str):
            raise UnknownSymbolError(stable_symbol_id)

    legacy = LegacySemanticStateView()
    assert isinstance(legacy, SemanticStateView)
    assert not isinstance(legacy, IndexedSemanticStateView)

    indexed = view_semantic_state_bundle(bundle)
    assert isinstance(indexed, SemanticStateView)
    assert isinstance(indexed, IndexedSemanticStateView)


# ---------------------------------------------------------------------------
# Assembly: cold / incremental identity
# ---------------------------------------------------------------------------


def test_cold_build_emits_verified_root_and_reachable_blocks() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    state = _state([alpha, beta], edges=[_edge(alpha, beta)])

    bundle = build_semantic_state(state, environment_bindings=(_binding(),))
    root = verify_semantic_state_bundle(bundle)

    assert isinstance(root, SemanticStateRoot)
    assert root.repository_id == REPO
    assert root.producer.repository_state_cid == state.state_cid
    assert root.root_cid in bundle.blocks
    # Root-referenced indexes and binding set must be present.
    for cid in (
        root.symbol_fact_index_cid,
        root.artifact_fact_index_cid,
        root.semantic_link_index_cid,
        root.symbol_node_index_cid,
        root.capsule_index_cid,
        root.environment_binding_set_cid,
        root.analysis_limitation_index_cid,
    ):
        assert cid in bundle.blocks
        verify_block = bundle.get_block(cid)
        assert type(verify_block) is bytes


def test_cold_and_verified_incremental_are_byte_identical() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    state = _state([alpha, beta], edges=[_edge(alpha, beta)])
    bindings = (_binding(),)

    cold = build_semantic_state(state, environment_bindings=bindings)
    # Incremental with previous_bundle over identical inputs.
    incremental = build_semantic_state(
        state,
        environment_bindings=bindings,
        previous_bundle=cold,
    )

    assert cold.root.root_cid == incremental.root.root_cid
    assert cold.root.to_dict() == incremental.root.to_dict()
    assert dict(cold.blocks) == dict(incremental.blocks)
    # Reachable block CIDs are byte-identical.
    for cid, data in cold.blocks.items():
        assert incremental.blocks[cid] == data


def test_build_is_order_independent() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    edge = _edge(alpha, beta)
    first = build_semantic_state(_state([alpha, beta], edges=[edge]))
    second = build_semantic_state(_state([beta, alpha], edges=[edge]))
    assert first.root.root_cid == second.root.root_cid
    assert dict(first.blocks) == dict(second.blocks)


def test_previous_bundle_has_no_persistence_side_effect(tmp_path) -> None:
    """Assembly never writes to disk even when previous_bundle is supplied."""
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    cold = build_semantic_state(state)
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    # Intentionally pass a path-like object into the ambient workspace; the API
    # must not open or create files under it.
    marker = tmp_path / "must-not-be-created"
    _ = build_semantic_state(state, previous_bundle=cold)
    assert not marker.exists()
    after = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    assert before == after


def test_invalid_previous_bundle_type_fails_typed() -> None:
    state = _state([_make_symbol("pkg.mod.alpha")])
    with pytest.raises(SemanticStateApiError, match="previous_bundle"):
        build_semantic_state(state, previous_bundle=object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Views: in-memory bundle vs injected reader
# ---------------------------------------------------------------------------


def test_bundle_view_and_injected_reader_yield_identical_views() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    state = _state([alpha, beta], edges=[_edge(alpha, beta)])
    bundle = build_semantic_state(state, environment_bindings=(_binding(),))

    mem_view = view_semantic_state_bundle(bundle)
    assert isinstance(mem_view, VerifiedSemanticStateView)
    assert mem_view.root.root_cid == bundle.root.root_cid

    store = dict(bundle.blocks)

    def reader(cid: str) -> bytes:
        try:
            return store[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc

    injected = open_semantic_state(bundle.root.root_cid, reader)
    assert injected.root.to_dict() == mem_view.root.to_dict()
    assert injected.root.root_cid == mem_view.root.root_cid

    # Symbol node and capsule resolve identically.
    node_mem = mem_view.symbol_node(alpha.stable_id)
    node_inj = injected.symbol_node(alpha.stable_id)
    assert node_mem.node_cid == node_inj.node_cid
    assert node_mem.to_dict() == node_inj.to_dict()

    cap_mem = mem_view.capsule(alpha.stable_id)
    cap_inj = injected.capsule(alpha.stable_id)
    assert cap_mem.capsule_cid == cap_inj.capsule_cid
    assert cap_mem.to_dict() == cap_inj.to_dict()

    # Every block read through both views is byte-identical.
    for cid in sorted(bundle.blocks):
        assert mem_view.get_block(cid) == injected.get_block(cid) == bundle.blocks[cid]


def test_verified_view_exposes_all_root_index_records_typed() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    artifact = ArtifactRecord(
        artifact_id="artifact:contract-alpha",
        kind="contract",
        path="contracts/alpha.json",
        source_cid=_cid("contract-alpha"),
    )
    alpha_to_beta = _edge(alpha, beta)
    alpha_to_artifact = _edge(
        alpha,
        artifact.artifact_id,
        RelationType.CONFIGURED_BY,
    )
    beta_to_beta = _edge(beta, beta, RelationType.PROOF_DEPENDS_ON)
    state = _state(
        [alpha, beta],
        artifacts=[artifact],
        edges=[alpha_to_beta, alpha_to_artifact, beta_to_beta],
    )
    limitation = AnalysisLimitation(
        code="dynamic-callback",
        message="callback target remains opaque",
        subject_id=beta.stable_id,
    )
    sealed_index = SimpleNamespace(
        repository_id=state.repository_id,
        symbols=state.symbols,
        artifacts=state.artifacts,
        edges=state.edges,
        extractor_name=state.extractor_name,
        extractor_version=state.extractor_version,
        schema=state.schema,
        state_cid=state.state_cid,
        limitations=(limitation,),
    )
    bundle = build_semantic_state(sealed_index)
    store = dict(bundle.blocks)
    views = (
        view_semantic_state_bundle(bundle),
        open_semantic_state(bundle.root.root_cid, store.__getitem__),
    )

    for view in views:
        symbol_fact = view.symbol_fact(alpha.stable_id)
        assert isinstance(symbol_fact, SymbolFactNode)
        assert symbol_fact.symbol == alpha

        artifact_fact = view.artifact_fact(artifact.artifact_id)
        assert isinstance(artifact_fact, ArtifactFactNode)
        assert artifact_fact.artifact == artifact

        link = view.semantic_link(alpha_to_beta.edge_id)
        assert isinstance(link, SemanticLinkNode)
        assert link.edge_id == alpha_to_beta.edge_id
        assert link.source_stable_id == alpha.stable_id
        assert link.target_stable_id == beta.stable_id

        artifact_link = view.semantic_link(alpha_to_artifact.edge_id)
        assert artifact_link.target_stable_id == artifact.artifact_id
        assert artifact_link.target_fact_cid == artifact_fact.fact_cid
        assert artifact_link.target_version_cid is None

        restored_limitation = view.analysis_limitation(limitation.limitation_cid)
        assert restored_limitation == limitation

        assert tuple(
            item.edge_id
            for item in view.semantic_links_for_symbol(alpha.stable_id, "outgoing")
        ) == tuple(sorted((alpha_to_beta.edge_id, alpha_to_artifact.edge_id)))
        assert view.semantic_links_for_symbol(alpha.stable_id, "incoming") == ()
        assert tuple(
            item.edge_id
            for item in view.semantic_links_for_symbol(beta.stable_id, "incoming")
        ) == tuple(sorted((alpha_to_beta.edge_id, beta_to_beta.edge_id)))
        assert tuple(
            item.edge_id
            for item in view.semantic_links_for_symbol(beta.stable_id, "outgoing")
        ) == (beta_to_beta.edge_id,)
        # The self-loop is present in both node vectors but returned only once.
        assert tuple(
            item.edge_id
            for item in view.semantic_links_for_symbol(beta.stable_id)
        ) == tuple(sorted((alpha_to_beta.edge_id, beta_to_beta.edge_id)))


def test_typed_view_selectors_reject_unknown_keys_and_direction() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    view = view_semantic_state_bundle(build_semantic_state(_state([alpha])))

    with pytest.raises(UnknownSymbolError):
        view.symbol_fact("not-a-real-stable-id")
    with pytest.raises(UnknownArtifactError):
        view.artifact_fact("artifact:not-present")
    with pytest.raises(UnknownSemanticLinkError):
        view.semantic_link(_cid("edge:not-present"))
    with pytest.raises(UnknownAnalysisLimitationError):
        view.analysis_limitation(_cid("limitation:not-present"))
    with pytest.raises(SemanticStateApiError, match="direction"):
        view.semantic_links_for_symbol(alpha.stable_id, "sideways")


def test_typed_view_selectors_fail_closed_on_missing_corrupt_and_mismatched_data() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    artifact = ArtifactRecord(
        artifact_id="artifact:contract-alpha",
        kind="contract",
        path="contracts/alpha.json",
        source_cid=_cid("contract-alpha"),
    )
    edge = _edge(alpha, beta)
    bundle = build_semantic_state(
        _state([alpha, beta], artifacts=[artifact], edges=[edge])
    )
    baseline = view_semantic_state_bundle(bundle)

    missing_store = dict(bundle.blocks)
    del missing_store[bundle.root.artifact_fact_index_cid]
    missing_view = open_semantic_state(bundle.root.root_cid, missing_store.__getitem__)
    with pytest.raises(MissingBlockError):
        missing_view.artifact_fact(artifact.artifact_id)

    alpha_fact = baseline.symbol_fact(alpha.stable_id)
    corrupt_store = dict(bundle.blocks)
    corrupt_store[alpha_fact.fact_cid] = b'{"schema":"forged"}'
    corrupt_view = open_semantic_state(bundle.root.root_cid, corrupt_store.__getitem__)
    with pytest.raises(CorruptBlockError):
        corrupt_view.symbol_fact(alpha.stable_id)

    beta_fact = baseline.symbol_fact(beta.stable_id)
    mismatched_index = SortedPairIndex(
        pairs=((alpha.stable_id, beta_fact.fact_cid),)
    )
    mismatched_blocks = dict(bundle.blocks)
    mismatched_blocks[mismatched_index.index_cid] = canonical_dag_json_bytes(
        mismatched_index.identity_payload()
    )
    mismatched_bundle = SemanticStateBundle(
        root=replace(
            bundle.root,
            symbol_fact_index_cid=mismatched_index.index_cid,
        ),
        blocks=mismatched_blocks,
    )
    with pytest.raises(CorruptBlockError, match="stable_symbol_id mismatch"):
        view_semantic_state_bundle(mismatched_bundle).symbol_fact(alpha.stable_id)


def test_semantic_link_rejects_canonical_fact_and_version_mismatches() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    edge = _edge(alpha, beta)
    bundle = build_semantic_state(_state([alpha, beta], edges=[edge]))
    baseline = view_semantic_state_bundle(bundle)
    link = baseline.semantic_link(edge.edge_id)
    beta_fact = baseline.symbol_fact(beta.stable_id)

    forged_links = (
        (
            replace(link, source_fact_cid=beta_fact.fact_cid),
            "source_fact_cid mismatch",
        ),
        (
            replace(link, target_version_cid=alpha.version_cid),
            "target_version_cid mismatch",
        ),
    )
    for forged_link, expected_error in forged_links:
        forged_index = SortedPairIndex(
            pairs=((edge.edge_id, forged_link.link_cid),)
        )
        forged_blocks = dict(bundle.blocks)
        forged_blocks[forged_link.link_cid] = canonical_dag_json_bytes(
            forged_link.identity_payload()
        )
        forged_blocks[forged_index.index_cid] = canonical_dag_json_bytes(
            forged_index.identity_payload()
        )
        forged_bundle = SemanticStateBundle(
            root=replace(
                bundle.root,
                semantic_link_index_cid=forged_index.index_cid,
            ),
            blocks=forged_blocks,
        )

        # Every changed block and root has a valid canonical CID; only the
        # cross-record semantic binding is false.
        with pytest.raises(CorruptBlockError, match=expected_error):
            view_semantic_state_bundle(forged_bundle).semantic_link(edge.edge_id)


def test_link_traversal_rejects_canonical_node_link_binding_mismatches() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    beta = _make_symbol("pkg.mod.beta")
    edge = _edge(alpha, beta)
    bundle = build_semantic_state(_state([alpha, beta], edges=[edge]))
    baseline = view_semantic_state_bundle(bundle)
    alpha_node = baseline.symbol_node(alpha.stable_id)
    beta_node = baseline.symbol_node(beta.stable_id)
    alpha_fact = baseline.symbol_fact(alpha.stable_id)

    forged_nodes = (
        (
            alpha.stable_id,
            replace(alpha_node, version_cid=beta.version_cid),
            "outgoing",
            "outgoing node version mismatch",
        ),
        (
            beta.stable_id,
            replace(beta_node, symbol_fact_cid=alpha_fact.fact_cid),
            "incoming",
            "incoming node fact mismatch",
        ),
    )
    for stable_symbol_id, forged_node, direction, expected_error in forged_nodes:
        forged_index = SortedPairIndex(
            pairs=((stable_symbol_id, forged_node.node_cid),)
        )
        forged_blocks = dict(bundle.blocks)
        forged_blocks[forged_node.node_cid] = canonical_dag_json_bytes(
            forged_node.identity_payload()
        )
        forged_blocks[forged_index.index_cid] = canonical_dag_json_bytes(
            forged_index.identity_payload()
        )
        forged_bundle = SemanticStateBundle(
            root=replace(
                bundle.root,
                symbol_node_index_cid=forged_index.index_cid,
            ),
            blocks=forged_blocks,
        )

        with pytest.raises(CorruptBlockError, match=expected_error):
            view_semantic_state_bundle(forged_bundle).semantic_links_for_symbol(
                stable_symbol_id,
                direction,
            )


def test_every_read_reverifies_cid_and_schema() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    view = view_semantic_state_bundle(bundle)

    root_bytes = view.get_block(bundle.root.root_cid)
    assert root_bytes == canonical_dag_json_bytes(bundle.root.identity_payload())
    assert cid_for_structured(bundle.root.identity_payload()) == bundle.root.root_cid

    node = view.symbol_node(alpha.stable_id)
    assert node.stable_symbol_id == alpha.stable_id
    capsule = view.capsule(alpha.stable_id)
    assert capsule.stable_symbol_id == alpha.stable_id
    assert node.capsule_cid == capsule.capsule_cid


def test_missing_block_fails_typed() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    store = dict(bundle.blocks)
    # Drop a root-referenced index so open still works (root present) but later
    # symbol_node fails when its index is missing.
    del store[bundle.root.symbol_node_index_cid]

    def reader(cid: str) -> bytes:
        try:
            return store[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc

    view = open_semantic_state(bundle.root.root_cid, reader)
    with pytest.raises(MissingBlockError):
        view.symbol_node(alpha.stable_id)

    with pytest.raises(MissingBlockError):
        view.get_block(bundle.root.symbol_node_index_cid)


def test_corrupt_block_fails_typed() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    store = dict(bundle.blocks)
    # Forge capsule bytes under the real capsule CID.
    view0 = view_semantic_state_bundle(bundle)
    capsule = view0.capsule(alpha.stable_id)
    store[capsule.capsule_cid] = b'{"schema":"forged","not":"canonical"}'

    def reader(cid: str) -> bytes:
        try:
            return store[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc

    view = open_semantic_state(bundle.root.root_cid, reader)
    with pytest.raises(CorruptBlockError):
        view.capsule(alpha.stable_id)

    with pytest.raises(CorruptBlockError):
        view.get_block(capsule.capsule_cid)


def test_unknown_symbol_fails_typed() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    view = view_semantic_state_bundle(bundle)
    with pytest.raises(UnknownSymbolError):
        view.symbol_node("not-a-real-stable-id")
    with pytest.raises(UnknownSymbolError):
        view.capsule("not-a-real-stable-id")


def test_open_missing_root_fails_typed() -> None:
    def reader(_cid: str) -> bytes:
        raise KeyError(_cid)

    with pytest.raises(MissingBlockError):
        open_semantic_state(_cid("absent-root"), reader)


def test_open_corrupt_root_fails_typed() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    bundle = build_semantic_state(_state([alpha]))
    store = {bundle.root.root_cid: b"not-json"}

    def reader(cid: str) -> bytes:
        try:
            return store[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc

    with pytest.raises(CorruptBlockError):
        open_semantic_state(bundle.root.root_cid, reader)


# ---------------------------------------------------------------------------
# Producer binding from sealed ISI view
# ---------------------------------------------------------------------------


def test_producer_fields_copied_from_explicit_producer() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    producer = SemanticStateProducer(
        repository_state_cid=state.state_cid,
        repository_snapshot_cid=_cid("snapshot-explicit"),
        git_commit_oid_or_null="a" * 40,
        git_tree_oid_or_null="b" * 40,
        source_manifest_cid=_cid("manifest-explicit"),
        semantic_index_schema=state.schema,
        extractor_name=state.extractor_name,
        extractor_version=state.extractor_version,
    )

    class _Sealed:
        def __init__(self) -> None:
            self.repository_id = state.repository_id
            self.symbols = state.symbols
            self.artifacts = state.artifacts
            self.edges = state.edges
            self.extractor_name = state.extractor_name
            self.extractor_version = state.extractor_version
            self.schema = state.schema
            self.state_cid = state.state_cid
            self.producer = producer

    bundle = build_semantic_state(_Sealed())
    assert bundle.root.producer == producer
    assert bundle.root.producer.repository_snapshot_cid == _cid("snapshot-explicit")


def test_build_from_api_module_matches_package_export() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    a = build_semantic_state(state)
    b = build_from_api(state)
    assert a.root.root_cid == b.root.root_cid
    assert dict(a.blocks) == dict(b.blocks)


def test_verify_rejects_non_bundle() -> None:
    with pytest.raises(SemanticStateApiError, match="SemanticStateBundle"):
        verify_semantic_state_bundle(object())  # type: ignore[arg-type]


def test_single_symbol_compile_matches_bundle_capsule() -> None:
    alpha = _make_symbol("pkg.mod.alpha")
    state = _state([alpha])
    bundle = build_semantic_state(state)
    view = view_semantic_state_bundle(bundle)
    from_bundle = view.capsule(alpha.stable_id)
    single = compile_semantic_capsule(state, alpha.stable_id)
    assert single.capsule_cid == from_bundle.capsule_cid
    assert single.identity_payload() == from_bundle.identity_payload()
