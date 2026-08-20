"""Focused contract vectors for closed semantic-state payload models."""

from __future__ import annotations

import ast

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
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    ROOT_EXCLUDED_FIELD_NAMES,
    SEMANTIC_STATE_ROOT_SCHEMA,
    AdmissionDecision,
    AnalysisLimitation,
    ArtifactFactNode,
    BindingKind,
    BindingScope,
    CapsuleFreshness,
    EnvironmentBinding,
    EnvironmentBindingSet,
    FreshnessState,
    LinkTargetKind,
    NormalizedTestStatus,
    ObligationOrigin,
    OracleApplicability,
    ReasonPath,
    RelevantBindingProjection,
    SelectionFallback,
    SelectionPolicy,
    SelectionRule,
    SelectionRuleKind,
    SemanticBindingDelta,
    SemanticCapsule,
    SemanticInvalidationObligation,
    SemanticInvalidationPlan,
    SemanticLinkNode,
    SemanticStateBundle,
    SemanticStateModelError,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
    SymbolFactNode,
    SymbolMerkleNode,
    TestOracleComparison,
    TestOutcome,
    TestRunFacts,
    TestSelection,
    VerifiedSourceEvidence,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _symbol(*, span: SourceSpan | None = None) -> SymbolRecord:
    stable = stable_symbol_id(
        "repo:example",
        "python",
        "pkg/mod.py",
        "pkg.mod.answer",
        SymbolKind.FUNCTION,
        "pkg",
    )
    node = ast.parse("def answer(value: int) -> int:\n    return value + 1\n").body[0]
    version = symbol_version_cid(
        stable,
        node,
        {"parameters": ["value"], "return": "int"},
        ["public"],
        {"value": "int", "return": "int"},
    )
    return SymbolRecord(
        stable,
        version,
        "repo:example",
        "python",
        "pkg/mod.py",
        "pkg.mod.answer",
        SymbolKind.FUNCTION,
        "pkg",
        cid_for_bytes(b"source"),
        span,
        AnalysisConfidence.EXACT,
        {"parameters": ["value"], "return": "int"},
        ["public"],
        {"value": "int", "return": "int"},
        normalized_ast=node,
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


def _root(**overrides: object) -> SemanticStateRoot:
    index = SortedPairIndex(pairs=[("k", _cid("block"))]).index_cid
    fields = {
        "repository_id": "repo:example",
        "producer": _producer(),
        "symbol_fact_index_cid": index,
        "artifact_fact_index_cid": index,
        "semantic_link_index_cid": index,
        "symbol_node_index_cid": index,
        "capsule_index_cid": index,
        "environment_binding_set_cid": index,
        "analysis_limitation_index_cid": index,
    }
    fields.update(overrides)
    return SemanticStateRoot(**fields)  # type: ignore[arg-type]


def test_sorted_pair_index_rejects_duplicates_and_verifies_cid() -> None:
    cid = _cid("x")
    index = SortedPairIndex(pairs=[("b", cid), ("a", cid)])
    assert [key for key, _ in index.pairs] == ["a", "b"]
    assert SortedPairIndex.from_dict(index.to_dict()) == index
    with pytest.raises(SemanticStateModelError, match="duplicate key"):
        SortedPairIndex(pairs=[("a", cid), ("a", _cid("y"))])
    forged = index.to_dict()
    forged["index_cid"] = _cid("forged")
    with pytest.raises(SemanticStateModelError, match="does not verify"):
        SortedPairIndex.from_dict(forged)


def test_symbol_and_artifact_facts_preserve_isi_identities_and_round_trip() -> None:
    span = SourceSpan("pkg/mod.py", 1, 0, 2, 18)
    symbol = _symbol(span=span)
    fact = SymbolFactNode(symbol=symbol)
    restored = SymbolFactNode.from_dict(fact.to_dict())
    assert restored == fact
    assert restored.stable_symbol_id == symbol.stable_id
    assert restored.version_cid == symbol.version_cid
    assert restored.span == span

    # Stable/version IDs are preserved verbatim — no translation on the outer record.
    payload = fact.to_dict()
    assert payload["stable_symbol_id"] is not None
    assert payload["stable_symbol_id"] == symbol.stable_id
    assert payload["version_cid"] == symbol.version_cid

    mismatched = fact.to_dict()
    mismatched["stable_symbol_id"] = _cid("other-stable")
    with pytest.raises(SemanticStateModelError, match="verbatim"):
        SymbolFactNode.from_dict(mismatched)

    artifact = ArtifactRecord("artifact:database", "external", "config/db.json")
    artifact_fact = ArtifactFactNode(artifact=artifact)
    assert ArtifactFactNode.from_dict(artifact_fact.to_dict()) == artifact_fact


def test_semantic_link_preserves_edge_id_verbatim() -> None:
    symbol = _symbol()
    edge = DependencyEdge(
        symbol.stable_id,
        "artifact:database",
        RelationType.CALLS,
        "lexical",
        "conservative",
        "1",
    )
    fact = SymbolFactNode(symbol=symbol)
    link = SemanticLinkNode(
        edge_id=edge.edge_id,
        source_stable_id=symbol.stable_id,
        source_version_cid=symbol.version_cid,
        source_fact_cid=fact.fact_cid,
        target_kind=LinkTargetKind.ARTIFACT,
        target_stable_id="artifact:database",
        target_version_cid=None,
        target_fact_cid=None,
        relation=RelationType.CALLS,
        source_span=None,
        extraction_method="lexical",
        confidence=AnalysisConfidence.CONSERVATIVE,
        extractor_version="1",
    )
    assert link.edge_id == edge.edge_id
    restored = SemanticLinkNode.from_dict(link.to_dict())
    assert restored.edge_id == edge.edge_id
    assert restored == link


def test_merkle_capsule_bindings_and_root_round_trip() -> None:
    symbol = _symbol()
    fact = SymbolFactNode(symbol=symbol)
    capsule = SemanticCapsule(
        stable_symbol_id=symbol.stable_id,
        version_cid=symbol.version_cid,
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_version="1",
        source_slice_path="pkg/mod.py",
        source_cid=symbol.source_cid,
        symbol_fact_cid=fact.fact_cid,
        signature={"parameters": ["value"]},
        decorators=["public"],
    )
    node = SymbolMerkleNode(
        stable_symbol_id=symbol.stable_id,
        version_cid=symbol.version_cid,
        symbol_fact_cid=fact.fact_cid,
        capsule_cid=capsule.capsule_cid,
        confidence=AnalysisConfidence.EXACT,
    )
    binding = EnvironmentBinding(
        binding_id="lock:poetry",
        kind=BindingKind.DEPENDENCY_LOCK,
        version_cid=_cid("lock-v1"),
        scope=BindingScope.GLOBAL,
        extraction_authority="isi-artifact",
    )
    binding_set = EnvironmentBindingSet(bindings=[binding])
    projection = RelevantBindingProjection(
        stable_symbol_id=symbol.stable_id,
        binding_ids=[binding.binding_id],
        includes_global=True,
        binding_set_cid=binding_set.binding_set_cid,
    )
    delta = SemanticBindingDelta(
        previous_binding_set_cid=None,
        current_binding_set_cid=binding_set.binding_set_cid,
        added_binding_ids=[binding.binding_id],
        current_version_cids={binding.binding_id: binding.version_cid},
    )
    root = _root(environment_binding_set_cid=binding_set.binding_set_cid)

    for value, loader in (
        (capsule, SemanticCapsule.from_dict),
        (node, SymbolMerkleNode.from_dict),
        (binding, EnvironmentBinding.from_dict),
        (binding_set, EnvironmentBindingSet.from_dict),
        (projection, RelevantBindingProjection.from_dict),
        (delta, SemanticBindingDelta.from_dict),
        (root, SemanticStateRoot.from_dict),
    ):
        assert loader(value.to_dict()) == value

    assert capsule.producer_key() == (
        symbol.stable_id,
        symbol.version_cid,
        "ipfs-datasets.software-contracts.semantic-index@2",
        "1",
    )


def test_root_excludes_operational_and_mcp_fields() -> None:
    root = _root()
    payload = root.to_dict()
    assert payload["schema"] == SEMANTIC_STATE_ROOT_SCHEMA
    assert ROOT_EXCLUDED_FIELD_NAMES.isdisjoint(payload)
    for forbidden in (
        "history",
        "selection",
        "receipt",
        "clock",
        "local_path",
        "lease",
        "generation",
        "model_data",
        "envelope_cid",
        "previous_root",
        "timestamp",
    ):
        polluted = dict(payload)
        polluted[forbidden] = "bad"
        with pytest.raises(SemanticStateModelError, match="excluded"):
            SemanticStateRoot.from_dict(polluted)


def test_unknown_fields_and_schema_versions_fail_closed() -> None:
    root = _root()
    payload = root.to_dict()
    payload["extra"] = True
    with pytest.raises(SemanticStateModelError, match="fields must be exactly"):
        SemanticStateRoot.from_dict(payload)

    bad_schema = root.to_dict()
    bad_schema["schema"] = "ipfs-datasets.software-contracts.semantic-state-root@99"
    with pytest.raises(SemanticStateModelError, match="unsupported"):
        SemanticStateRoot.from_dict(bad_schema)

    with pytest.raises(SemanticStateModelError, match="unsupported"):
        SemanticCapsule(
            stable_symbol_id=_cid("s"),
            version_cid=_cid("v"),
            semantic_index_schema="s",
            extractor_version="1",
            capsule_schema="ipfs-datasets.software-contracts.semantic-capsule@99",
        )

    with pytest.raises(SemanticStateModelError, match="unsupported value"):
        EnvironmentBinding(
            binding_id="x",
            kind="not-a-kind",
            version_cid=_cid("v"),
            scope=BindingScope.GLOBAL,
            extraction_authority="isi",
        )


def test_forged_cids_fail_closed_on_records_and_bundle() -> None:
    root = _root()
    forged_root = root.to_dict()
    forged_root["root_cid"] = _cid("forged-root")
    with pytest.raises(SemanticStateModelError, match="does not verify"):
        SemanticStateRoot.from_dict(forged_root)

    outcome = TestOutcome(
        node_id="tests/test_mod.py::test_answer",
        status=NormalizedTestStatus.FAILED,
        failure_fingerprint="assert-1",
    )
    forged_outcome = outcome.to_dict()
    forged_outcome["outcome_cid"] = _cid("forged-outcome")
    with pytest.raises(SemanticStateModelError, match="does not verify"):
        TestOutcome.from_dict(forged_outcome)

    good_bytes = b"payload-bytes"
    good_cid = cid_for_bytes(good_bytes)
    bundle = SemanticStateBundle(root=root, blocks={good_cid: good_bytes})
    assert bundle.verify() == root
    assert bundle.get_block(good_cid) == good_bytes

    with pytest.raises(SemanticStateModelError, match="forged|mismatched"):
        SemanticStateBundle(
            root=root,
            blocks={good_cid: b"different-bytes"},
        )

    # Structured root block with a forged key must fail.
    root_bytes = canonical_dag_json_bytes(root.identity_payload())
    with pytest.raises(SemanticStateModelError, match="forged|mismatched|valid CID"):
        SemanticStateBundle(
            root=root,
            blocks={_cid("not-the-root"): root_bytes},
        )


def test_selection_oracle_and_freshness_round_trip() -> None:
    root_cid = _root().root_cid
    policy = SelectionPolicy(policy_id="default")
    rule = SelectionRule(
        rule_id="force-db",
        kind=SelectionRuleKind.INCLUDE,
        subjects=["tests/test_db.py::test_connect"],
    )
    path = ReasonPath(
        seed_subject_id="symbol:answer",
        target_node_id="tests/test_mod.py::test_answer",
        edge_ids=["edge:1"],
        link_cids=[_cid("link")],
        relation_steps=["tested_by"],
    )
    selection = TestSelection(
        previous_root_cid=None,
        current_root_cid=root_cid,
        selected_pytest_node_ids=["tests/test_mod.py::test_answer"],
        reason_paths=[path],
        known_test_universe_count=3,
        fallback=SelectionFallback.NONE,
        policy_cid=policy.policy_cid,
    )
    outcome = TestOutcome(
        node_id="tests/test_mod.py::test_answer",
        status=NormalizedTestStatus.PASSED,
    )
    facts = TestRunFacts(run_id="selected-1", outcomes=[outcome])
    oracle = TestOracleComparison(
        selection_cid=selection.selection_cid,
        baseline_facts_cid=facts.facts_cid,
        selected_facts_cid=facts.facts_cid,
        candidate_full_facts_cid=facts.facts_cid,
        applicability=OracleApplicability.NOT_APPLICABLE,
        selected_count=1,
        full_count=3,
        selection_ratio_bp=3333,
    )
    obligation = SemanticInvalidationObligation(
        subject_id="lock:poetry",
        reason_code="dependency_lock_changed",
        remediation_kind="stale_bound_receipts",
        confidence=AnalysisConfidence.EXACT,
        origin=ObligationOrigin.ENVIRONMENT,
    )
    plan = SemanticInvalidationPlan(
        previous_root_cid=None,
        current_root_cid=root_cid,
        obligations=[obligation],
    )
    freshness = CapsuleFreshness(
        capsule_cid=_cid("capsule"),
        root_cid=root_cid,
        capsule_schema="ipfs-datasets.software-contracts.semantic-capsule@1",
        capsule_compiler_version="1",
        producer_repository_state_cid=_cid("state"),
        relevant_binding_projection_cid=None,
        freshness=FreshnessState.STALE,
        admission=AdmissionDecision.RAW_SOURCE_REQUIRED,
        applicable_obligation_ids=[obligation.obligation_id],
        caveats=["lock-changed"],
    )
    evidence = VerifiedSourceEvidence(
        stable_symbol_id=_cid("symbol"),
        producer_state_cid=_cid("state"),
        source_cid=_cid("source"),
        source_slice_path="pkg/mod.py",
        start_offset=0,
        end_offset=32,
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )
    limitation = AnalysisLimitation(
        code="dynamic_import",
        message="importlib usage is opaque",
        confidence=AnalysisConfidence.OPAQUE,
    )

    for value, loader in (
        (policy, SelectionPolicy.from_dict),
        (rule, SelectionRule.from_dict),
        (path, ReasonPath.from_dict),
        (selection, TestSelection.from_dict),
        (outcome, TestOutcome.from_dict),
        (facts, TestRunFacts.from_dict),
        (oracle, TestOracleComparison.from_dict),
        (obligation, SemanticInvalidationObligation.from_dict),
        (plan, SemanticInvalidationPlan.from_dict),
        (freshness, CapsuleFreshness.from_dict),
        (evidence, VerifiedSourceEvidence.from_dict),
        (limitation, AnalysisLimitation.from_dict),
    ):
        assert loader(value.to_dict()) == value


def test_records_are_deeply_immutable() -> None:
    binding = EnvironmentBinding(
        binding_id="policy:sec",
        kind=BindingKind.POLICY,
        version_cid=_cid("policy-v"),
        scope=BindingScope.GLOBAL,
        extraction_authority="injected",
        metadata={"nested": {"items": ["fixed"]}},
    )
    with pytest.raises(TypeError):
        binding.metadata["nested"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        binding.metadata["nested"]["items"] = ()  # type: ignore[index]
    with pytest.raises(AttributeError):
        binding.metadata["nested"]["items"].append("mutate")  # type: ignore[attr-defined]

    bundle = SemanticStateBundle(root=_root(), blocks={})
    with pytest.raises(TypeError):
        bundle.blocks[_cid("x")] = b"no"  # type: ignore[index]
