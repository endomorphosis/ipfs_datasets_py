"""Acceptance vectors for capsule freshness assessment (DSS-006)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Mapping

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
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.capsules import (
    compile_semantic_capsule,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.freshness import (
    CAPSULE_FRESHNESS_INTERFACE,
    FreshnessError,
    FreshnessFailureKind,
    assess_capsule_freshness,
    is_safe_substitute,
    requires_raw_source,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    AdmissionDecision,
    CAPSULE_COMPILER_VERSION,
    EnvironmentBindingSet,
    FreshnessState,
    ObligationOrigin,
    SEMANTIC_CAPSULE_SCHEMA,
    SemanticCapsule,
    SemanticInvalidationObligation,
    SemanticInvalidationPlan,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
)


REPO = "repo:freshness-example"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _make_symbol(
    qualified_name: str,
    *,
    module_path: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind | str = SymbolKind.FUNCTION,
    body: str | None = None,
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
) -> SymbolRecord:
    short = qualified_name.rsplit(".", 1)[-1]
    source = body or f"def {short}(value: int) -> int:\n    return value + 1\n"
    node = ast.parse(source).body[0]
    stable = stable_symbol_id(REPO, "python", module_path, qualified_name, kind, namespace)
    sig = {"parameters": ["value"], "return": "int"}
    decs = ["public"]
    anns = {"value": "int", "return": "int"}
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
        SourceSpan(module_path, 1, 0, 2, 20),
        confidence,
        sig,
        decs,
        anns,
        {},
        normalized_ast=node,
    )


def _producer(state_label: str = "state") -> SemanticStateProducer:
    return SemanticStateProducer(
        repository_state_cid=_cid(state_label),
        repository_snapshot_cid=_cid("snapshot"),
        git_commit_oid_or_null="a" * 40,
        git_tree_oid_or_null="b" * 40,
        source_manifest_cid=_cid("manifest"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )


def _empty_index_cid() -> str:
    return SortedPairIndex(pairs=()).index_cid


@dataclass(frozen=True)
class _View:
    root: SemanticStateRoot
    blocks: Mapping[str, bytes]

    def get_block(self, cid: str) -> bytes:
        try:
            return self.blocks[cid]
        except KeyError as exc:
            raise KeyError(cid) from exc


def _compile_capsule(
    symbol: SymbolRecord,
    *,
    confidence: AnalysisConfidence | str | None = None,
) -> SemanticCapsule:
    state = RepositoryState(repository_id=REPO, symbols=(symbol,), artifacts=(), edges=())
    capsule = compile_semantic_capsule(state, symbol.stable_id)
    if confidence is not None and str(capsule.confidence) != str(confidence):
        # Rebuild with explicit confidence for admission tests when edges don't
        # lower confidence.  Identity fields stay producer-bound.
        return SemanticCapsule(
            stable_symbol_id=capsule.stable_symbol_id,
            version_cid=capsule.version_cid,
            semantic_index_schema=capsule.semantic_index_schema,
            extractor_version=capsule.extractor_version,
            capsule_schema=capsule.capsule_schema,
            capsule_compiler_version=capsule.capsule_compiler_version,
            source_slice_path=capsule.source_slice_path,
            source_cid=capsule.source_cid,
            symbol_fact_cid=capsule.symbol_fact_cid,
            signature=dict(capsule.signature),
            annotations=dict(capsule.annotations),
            defaults=dict(capsule.defaults),
            decorators=list(capsule.decorators),
            contracts=dict(capsule.contracts),
            effects=list(capsule.effects),
            exception_behavior=dict(capsule.exception_behavior),
            schema_relations=list(capsule.schema_relations),
            serialization_relations=list(capsule.serialization_relations),
            test_refs=list(capsule.test_refs),
            fixture_refs=list(capsule.fixture_refs),
            proof_obligation_refs=list(capsule.proof_obligation_refs),
            dependency_stable_ids=list(capsule.dependency_stable_ids),
            dependency_version_cids=list(capsule.dependency_version_cids),
            dependency_fact_cids=list(capsule.dependency_fact_cids),
            dependency_link_ids=list(capsule.dependency_link_ids),
            confidence=confidence,
            relevant_binding_projection_cid=capsule.relevant_binding_projection_cid,
            docstring_hint=capsule.docstring_hint,
            metadata=dict(capsule.metadata),
        )
    return capsule


def _view_for_capsule(
    capsule: SemanticCapsule,
    *,
    include_index: bool = True,
    include_block: bool = True,
    mutate_index_cid: bool = False,
    producer: SemanticStateProducer | None = None,
) -> _View:
    pairs = [(capsule.stable_symbol_id, capsule.capsule_cid)]
    if mutate_index_cid:
        pairs = [(capsule.stable_symbol_id, _cid("other-capsule"))]
    index = SortedPairIndex(pairs=pairs if include_index else ())
    blocks: dict[str, bytes] = {}
    if include_index:
        blocks[index.index_cid] = canonical_dag_json_bytes(index.identity_payload())
    if include_block:
        blocks[capsule.capsule_cid] = canonical_dag_json_bytes(capsule.identity_payload())
    if capsule.relevant_binding_projection_cid is not None:
        # Projection block optional for most tests; skip unless present externally.
        pass
    root = SemanticStateRoot(
        repository_id=REPO,
        producer=producer or _producer(),
        symbol_fact_index_cid=_empty_index_cid(),
        artifact_fact_index_cid=_empty_index_cid(),
        semantic_link_index_cid=_empty_index_cid(),
        symbol_node_index_cid=_empty_index_cid(),
        capsule_index_cid=index.index_cid if include_index else _empty_index_cid(),
        environment_binding_set_cid=EnvironmentBindingSet().binding_set_cid,
        analysis_limitation_index_cid=_empty_index_cid(),
    )
    return _View(root=root, blocks=blocks)


def test_interface_constant() -> None:
    assert CAPSULE_FRESHNESS_INTERFACE == "CapsuleFreshness@1"


def test_fresh_exact_capsule_is_exact_substitute() -> None:
    symbol = _make_symbol("pkg.add")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule)

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.freshness == FreshnessState.FRESH.value
    assert assessment.admission == AdmissionDecision.EXACT_SUBSTITUTE.value
    assert assessment.capsule_cid == capsule.capsule_cid
    assert assessment.root_cid == view.root.root_cid
    assert assessment.producer_repository_state_cid == view.root.producer.repository_state_cid
    assert assessment.capsule_schema == SEMANTIC_CAPSULE_SCHEMA
    assert assessment.capsule_compiler_version == CAPSULE_COMPILER_VERSION
    assert not requires_raw_source(assessment)
    assert is_safe_substitute(assessment)
    # Round-trip durable record.
    assert assessment.from_dict(assessment.to_dict()) == assessment


def test_fresh_conservative_capsule_has_visible_caveats() -> None:
    symbol = _make_symbol("pkg.approx", confidence=AnalysisConfidence.CONSERVATIVE)
    capsule = _compile_capsule(symbol, confidence=AnalysisConfidence.CONSERVATIVE)
    view = _view_for_capsule(capsule)

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.freshness == FreshnessState.FRESH.value
    assert (
        assessment.admission
        == AdmissionDecision.CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS.value
    )
    assert "confidence:conservative" in assessment.caveats
    assert is_safe_substitute(assessment)
    assert not requires_raw_source(assessment)


@pytest.mark.parametrize(
    "confidence",
    [AnalysisConfidence.HEURISTIC, AnalysisConfidence.OPAQUE],
)
def test_heuristic_and_opaque_require_raw_source(
    confidence: AnalysisConfidence,
) -> None:
    symbol = _make_symbol("pkg.dyn", confidence=confidence)
    capsule = _compile_capsule(symbol, confidence=confidence)
    view = _view_for_capsule(capsule)

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert requires_raw_source(assessment)
    assert not is_safe_substitute(assessment)
    assert any(c.startswith("unsafe_confidence:") for c in assessment.caveats)


def test_stale_obligation_forces_raw_source() -> None:
    symbol = _make_symbol("pkg.edited")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule)
    obligation = SemanticInvalidationObligation(
        subject_id=capsule.stable_symbol_id,
        reason_code="new_capsule",
        remediation_kind="retrieve_raw_source",
        confidence=AnalysisConfidence.EXACT,
        origin=ObligationOrigin.ISI,
    )
    plan = SemanticInvalidationPlan(
        previous_root_cid=None,
        current_root_cid=view.root.root_cid,
        obligations=[obligation],
    )

    assessment = assess_capsule_freshness(
        capsule, current_state=view, invalidation=plan
    )

    assert assessment.freshness == FreshnessState.STALE.value
    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert obligation.obligation_id in assessment.applicable_obligation_ids
    assert requires_raw_source(assessment)
    assert not is_safe_substitute(assessment)


def test_environment_lock_obligation_stales_capsule() -> None:
    symbol = _make_symbol("pkg.lock_hit")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule)
    obligation = SemanticInvalidationObligation(
        subject_id=capsule.stable_symbol_id,
        reason_code="dependency_lock_changed",
        remediation_kind="stale_bound_capsules",
        confidence=AnalysisConfidence.EXACT,
        origin=ObligationOrigin.ENVIRONMENT,
    )
    plan = SemanticInvalidationPlan(
        previous_root_cid=_cid("prev-root"),
        current_root_cid=view.root.root_cid,
        obligations=[obligation],
    )

    assessment = assess_capsule_freshness(
        capsule, current_state=view, invalidation=plan
    )

    assert assessment.freshness == FreshnessState.STALE.value
    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert "obligation:dependency_lock_changed" in assessment.caveats


def test_capsule_cid_mismatch_in_index_is_stale() -> None:
    symbol = _make_symbol("pkg.mismatch")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule, mutate_index_cid=True)

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.freshness == FreshnessState.STALE.value
    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert FreshnessFailureKind.CAPSULE_CID_MISMATCH.value in assessment.caveats


def test_missing_index_yields_unknown_and_raw_source() -> None:
    symbol = _make_symbol("pkg.noindex")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule, include_index=False, include_block=False)

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.freshness == FreshnessState.UNKNOWN.value
    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert FreshnessFailureKind.CAPSULE_INDEX_MISSING.value in assessment.caveats
    assert not is_safe_substitute(assessment)


def test_corrupt_capsule_block_is_not_safe_substitute() -> None:
    symbol = _make_symbol("pkg.corrupt")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule, include_block=False)
    # Index points at the capsule CID but block is missing.

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert FreshnessFailureKind.CAPSULE_BLOCK_CORRUPT.value in assessment.caveats
    assert not is_safe_substitute(assessment)


def test_schema_mismatch_rejects_substitution() -> None:
    symbol = _make_symbol("pkg.schema")
    capsule = _compile_capsule(symbol)
    # Root with matching schema is normal; force compiler mismatch via a root
    # that still validates (same constants) by using a mutated capsule record.
    # Capsule model rejects unknown schema, so simulate via assessment caveats
    # by using a producer extractor mismatch instead (closed equivalent).
    producer = _producer()
    mismatched = SemanticStateProducer(
        repository_state_cid=producer.repository_state_cid,
        repository_snapshot_cid=producer.repository_snapshot_cid,
        git_commit_oid_or_null=producer.git_commit_oid_or_null,
        git_tree_oid_or_null=producer.git_tree_oid_or_null,
        source_manifest_cid=producer.source_manifest_cid,
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@1",
        extractor_name=producer.extractor_name,
        extractor_version="9",
    )
    view = _view_for_capsule(capsule, producer=mismatched)

    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert FreshnessFailureKind.PRODUCER_MISMATCH.value in assessment.caveats
    assert not is_safe_substitute(assessment)


def test_invalid_inputs_fail_closed() -> None:
    symbol = _make_symbol("pkg.bad")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule)

    with pytest.raises(FreshnessError):
        assess_capsule_freshness("not-a-capsule", current_state=view)  # type: ignore[arg-type]
    with pytest.raises(FreshnessError):
        assess_capsule_freshness(capsule, current_state=object())  # type: ignore[arg-type]
    with pytest.raises(FreshnessError):
        assess_capsule_freshness(
            capsule, current_state=view, invalidation="nope"  # type: ignore[arg-type]
        )


def test_unsafe_capsule_cannot_substitute_for_raw_source() -> None:
    """No unsafe capsule admission may be treated as a safe exact substitute."""
    symbol = _make_symbol("pkg.unsafe", confidence=AnalysisConfidence.OPAQUE)
    capsule = _compile_capsule(symbol, confidence=AnalysisConfidence.OPAQUE)
    view = _view_for_capsule(capsule)
    assessment = assess_capsule_freshness(capsule, current_state=view)

    assert requires_raw_source(assessment)
    assert not is_safe_substitute(assessment)
    assert assessment.admission != AdmissionDecision.EXACT_SUBSTITUTE.value
    assert (
        assessment.admission
        != AdmissionDecision.CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS.value
    )


def test_full_fallback_obligation_forces_raw_even_for_unrelated_subject() -> None:
    symbol = _make_symbol("pkg.other")
    capsule = _compile_capsule(symbol)
    view = _view_for_capsule(capsule)
    obligation = SemanticInvalidationObligation(
        subject_id="global:pytest",
        reason_code="full_fallback_required",
        remediation_kind="full_fallback",
        confidence=AnalysisConfidence.OPAQUE,
        origin=ObligationOrigin.ENVIRONMENT,
    )
    plan = SemanticInvalidationPlan(
        previous_root_cid=None,
        current_root_cid=view.root.root_cid,
        obligations=[obligation],
    )

    assessment = assess_capsule_freshness(
        capsule, current_state=view, invalidation=plan
    )

    assert assessment.admission == AdmissionDecision.RAW_SOURCE_REQUIRED.value
    assert obligation.obligation_id in assessment.applicable_obligation_ids
