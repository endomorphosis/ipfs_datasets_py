"""LGCVF-071: slice and replay unchanged translation and proof obligations.

Acceptance:

* Local mutations invalidate exactly affected translation stages, theorem
  dependencies, and obligations.
* Reusable evidence is independently revalidated (stage replay + cache-key
  admission); it is never trusted by prior disposition.
* Required evidence: theorem-granularity invalidation and unchanged-stage
  replay tests.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.formalization.translation_receipts import (
    STAGE_ORDER,
    CompilationStage,
    EvidenceClass,
    StageArtifactRef,
    StageMapDisposition,
    StageReceiptExpectation,
    StageReplayManifest,
    StageSourceMap,
    StageSourceMapEntry,
    StageTranslationReceipt,
    StageValidationRecord,
    StageValidationStatus,
    SupportedSubset,
    compose_pipeline_receipts,
    emit_stage_receipt,
    stage_successor,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicEvidenceAuthority,
    LogicEvidenceKind,
)
from ipfs_datasets_py.logic.ir_core.claims import Assumption, ProofObligation
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_verification.obligation_slicing import (
    OBLIGATION_SLICING_INTERFACE,
    LocalMutation,
    ObligationEvidenceRequest,
    ObligationSliceBinding,
    ObligationSlicingError,
    ObligationSlicingStaleError,
    SliceDisposition,
    SliceSubjectKind,
    TheoremDependencyGraph,
    TheoremRecord,
    UnchangedStageReplayError,
    classify_translation_stages,
    close_theorem_dependents,
    propagate_changed_source_nodes,
    require_replayed_stages,
    slice_and_replay_obligations,
)
from ipfs_datasets_py.logic.software_verification.translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
)


LOGICAL_NODES: tuple[str, ...] = ("a", "b", "main", "unrelated")


def _identity(tag: str) -> str:
    return f"sha256:{tag.encode('utf-8').hex().ljust(64, '0')[:64]}"


def _artifact(
    stage: CompilationStage,
    *,
    tag: str | None = None,
    family_id: str = "software_verification",
    family_version: str = "1.0.0",
) -> StageArtifactRef:
    token = tag or stage.value
    return StageArtifactRef(
        artifact_id=f"artifact:{token}",
        stage=stage,
        content_identity=_identity(token),
        family_id=family_id,
        family_version=family_version,
    )


def _compiler(stage: CompilationStage, *, version: str = "1.0.0") -> CompilerBinding:
    return CompilerBinding(
        compiler_id=f"compiler:{stage.value}",
        compiler_version=version,
        implementation_identity=_identity(f"impl-{stage.value}-{version}"),
        configuration_identity=_identity(f"cfg-{stage.value}-{version}"),
        stage=stage.value,
    )


def _source_node_id(stage: CompilationStage, logical: str) -> str:
    if stage is CompilationStage.SOURCE:
        return f"node:{logical}"
    return f"{stage.value}:{logical}"


def _source_map(
    input_stage: CompilationStage,
    output_stage: CompilationStage,
    logicals: tuple[str, ...] = LOGICAL_NODES,
) -> StageSourceMap:
    entries = []
    for index, name in enumerate(logicals, start=1):
        entries.append(
            StageSourceMapEntry(
                entry_id=f"entry:{input_stage.value}:{name}",
                source_node_id=_source_node_id(input_stage, name),
                disposition=StageMapDisposition.MAPPED,
                target_node_ids=(_source_node_id(output_stage, name),),
                source_ref_ids=("source:fixture",),
                span_ids=(f"span:{name}",),
            )
        )
    return StageSourceMap(
        map_id=f"map:{input_stage.value}:{output_stage.value}",
        entries=tuple(entries),
        required_source_node_ids=tuple(_source_node_id(input_stage, name) for name in logicals),
    )


def _subset() -> SupportedSubset:
    return SupportedSubset(
        subset_id="subset:reviewed",
        feature_ids=("feature:assignment", "feature:assert"),
        excluded_feature_ids=("feature:eval",),
        description="Reviewed deterministic fragment.",
    )


def _validation(*, identity: str = "validated:ok") -> StageValidationRecord:
    return StageValidationRecord(
        status=StageValidationStatus.VALID,
        checker_id="checker:stage-translation",
        checker_version="1.0.0",
        validated_identity=_identity(identity),
    )


def _replay(
    compiler: CompilerBinding,
    input_artifact: StageArtifactRef,
    output_artifact: StageArtifactRef,
) -> StageReplayManifest:
    return StageReplayManifest(
        replay_id=f"replay:{input_artifact.stage.value}:{output_artifact.stage.value}",
        compiler=compiler,
        input_identity=input_artifact.content_identity,
        output_identity=output_artifact.content_identity,
        configuration_identity=compiler.configuration_identity,
        checker_id="checker:stage-translation",
        checker_version="1.0.0",
        replay_inputs={"seed": "fixture"},
    )


def _assumption() -> Assumption:
    return Assumption(
        assumption_id="assumption:closed-world",
        statement="No additional heap aliases exist.",
        source_refs=("source:fixture",),
    )


def _obligation() -> ProofObligation:
    return ProofObligation(
        obligation_id="obligation:post",
        statement="The postcondition holds on every normal return.",
        assumption_ids=("assumption:closed-world",),
        logic_family="hoare",
        source_refs=("source:fixture",),
    )


def _stage_receipt(
    input_stage: CompilationStage,
    output_stage: CompilationStage,
    *,
    compiler: CompilerBinding | None = None,
    source_map: StageSourceMap | None = None,
    input_artifact: StageArtifactRef | None = None,
    output_artifact: StageArtifactRef | None = None,
) -> StageTranslationReceipt:
    input_ref = input_artifact or _artifact(input_stage)
    output_ref = output_artifact or _artifact(output_stage)
    pinned = compiler or _compiler(output_stage)
    return emit_stage_receipt(
        input=input_ref,
        output=output_ref,
        compiler=pinned,
        source_map=source_map or _source_map(input_stage, output_stage),
        supported_subset=_subset(),
        losses=(),
        assumptions=(_assumption(),),
        obligations=(_obligation(),),
        validation=_validation(identity=f"validated:{output_stage.value}"),
        replay=_replay(pinned, input_ref, output_ref),
        bounds=(),
        evidence_class=EvidenceClass.TRANSLATION_VALIDATED,
        preservation_claim=PreservationClaim(
            kind=PreservationKind.EXACT,
            preserved_property_ids=("property:safety",),
            permitted_result_classes=("proved", "disproved"),
            description="The reviewed fragment is structurally preserved.",
        ),
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    )


def _pipeline_stages(
    *,
    compiler_versions: dict[CompilationStage, str] | None = None,
) -> list[StageTranslationReceipt]:
    versions = compiler_versions or {}
    receipts: list[StageTranslationReceipt] = []
    for input_stage in STAGE_ORDER[:-1]:
        output_stage = stage_successor(input_stage)
        assert output_stage is not None
        version = versions.get(output_stage, "1.0.0")
        receipts.append(
            _stage_receipt(
                input_stage,
                output_stage,
                compiler=_compiler(output_stage, version=version),
            )
        )
    return receipts


def _pipeline(
    *,
    pipeline_id: str = "pipeline:fixture",
    compiler_versions: dict[CompilationStage, str] | None = None,
) -> object:
    return compose_pipeline_receipts(
        _pipeline_stages(compiler_versions=compiler_versions),
        pipeline_id=pipeline_id,
    )


def _theorem(
    theorem_id: str,
    *,
    premises: tuple[str, ...] = (),
    stage: CompilationStage = CompilationStage.AST,
    nodes: tuple[str, ...] = (),
    obligation_ids: tuple[str, ...] = (),
) -> TheoremRecord:
    return TheoremRecord(
        theorem_id=theorem_id,
        statement_identity=f"statement:{theorem_id}",
        premise_ids=premises,
        producing_stage=stage,
        obligation_ids=obligation_ids,
        source_node_ids=nodes,
        content_identity=f"content:{theorem_id}",
    )


def _graph() -> TheoremDependencyGraph:
    return TheoremDependencyGraph(
        graph_id="theorem-graph:fixture",
        theorems=(
            _theorem(
                "lemma_a",
                stage=CompilationStage.AST,
                nodes=("node:a",),
                obligation_ids=("obligation:lemma_a",),
            ),
            _theorem(
                "lemma_b",
                premises=("lemma_a",),
                stage=CompilationStage.CFG,
                nodes=("node:b",),
                obligation_ids=("obligation:lemma_b",),
            ),
            _theorem(
                "theorem_main",
                premises=("lemma_b",),
                stage=CompilationStage.VC,
                nodes=("node:main",),
                obligation_ids=("obligation:main",),
            ),
            _theorem(
                "theorem_unrelated",
                stage=CompilationStage.AST,
                nodes=("node:unrelated",),
                obligation_ids=("obligation:unrelated",),
            ),
        ),
    )


def _bindings() -> tuple[ObligationSliceBinding, ...]:
    return (
        ObligationSliceBinding(
            obligation_id="obligation:lemma_a",
            statement_identity="statement:obligation:lemma_a",
            theorem_ids=("lemma_a",),
            producing_stage=CompilationStage.AST,
            source_node_ids=("node:a",),
        ),
        ObligationSliceBinding(
            obligation_id="obligation:lemma_b",
            statement_identity="statement:obligation:lemma_b",
            theorem_ids=("lemma_b",),
            producing_stage=CompilationStage.CFG,
            source_node_ids=("node:b",),
        ),
        ObligationSliceBinding(
            obligation_id="obligation:main",
            statement_identity="statement:obligation:main",
            theorem_ids=("theorem_main",),
            producing_stage=CompilationStage.VC,
            source_node_ids=("node:main",),
        ),
        ObligationSliceBinding(
            obligation_id="obligation:unrelated",
            statement_identity="statement:obligation:unrelated",
            theorem_ids=("theorem_unrelated",),
            producing_stage=CompilationStage.AST,
            source_node_ids=("node:unrelated",),
        ),
    )


def _cache_key(label: str) -> CanonicalProofCacheKey:
    return CanonicalProofCacheKey.build(
        source={"source": label},
        expression={"expression": label},
        formalization={"formalization": "hoare-vc"},
        slice={"slice": label},
        obligation={"obligation": label},
        assumptions=(),
        bounds={"steps": 8},
        translation={"translator": "fixture-v1"},
        provider="provider.z3",
        environment={"python": "3.12", "z3": "4.15"},
        policy={"network": "deny"},
        schema={"obligation-slice": "v1"},
        checker="checker.obligation-slice-fixture",
        network_policy={"allow": False},
        evidence_kind=LogicEvidenceKind.SOLVER_RESULT,
        authority_ceiling=LogicEvidenceAuthority.BOUNDED,
    )


def _evidence(
    binding_id: str,
    kind: SliceSubjectKind,
    subject_ids: tuple[str, ...],
    *,
    current_key: CanonicalProofCacheKey | None = None,
    dependency_ids: tuple[str, ...] = (),
    producing_stage: CompilationStage | None = None,
    confidence: str = "exact",
    dynamic_frontier: bool = False,
) -> ObligationEvidenceRequest:
    key = _cache_key(binding_id)
    return ObligationEvidenceRequest(
        binding_id=binding_id,
        kind=kind,
        subject_ids=subject_ids,
        artifact_cid=cid_for_structured({"artifact": binding_id}),
        cache_key=key,
        current_cache_key=current_key or key,
        dependency_ids=dependency_ids,
        producing_stage=producing_stage,
        confidence=confidence,
        dynamic_frontier=dynamic_frontier,
    )


def test_theorem_granularity_invalidates_dependents_and_reuses_unrelated() -> None:
    previous = _pipeline()
    mutation = LocalMutation(
        mutation_id="mutation:lemma-a",
        changed_theorem_ids=("lemma_a",),
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=previous,
    )

    assert receipt.invalidated_theorem_ids == ("lemma_a", "lemma_b", "theorem_main")
    assert receipt.reused_theorem_ids == ("theorem_unrelated",)
    assert receipt.invalidated_obligation_ids == (
        "obligation:lemma_a",
        "obligation:lemma_b",
        "obligation:main",
    )
    assert receipt.reused_obligation_ids == ("obligation:unrelated",)
    assert receipt.replayed_stage_ids == tuple(
        stage.value for stage in STAGE_ORDER if stage is not CompilationStage.SOURCE
    )
    assert receipt.invalidated_stage_ids == ()
    decisions = {item.theorem_id: item for item in receipt.theorem_decisions}
    assert "theorem_dependency_invalidated" in decisions["lemma_b"].reason_codes
    assert "mutated_theorem" in decisions["lemma_a"].reason_codes
    assert decisions["theorem_unrelated"].disposition is SliceDisposition.REUSED


def test_source_node_mutation_is_exact_at_theorem_and_obligation_granularity() -> None:
    previous = _pipeline()
    mutation = LocalMutation(
        mutation_id="mutation:node-a",
        changed_source_node_ids=("node:a",),
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
    )

    assert "ast" in receipt.invalidated_stage_ids
    assert "lemma_a" in receipt.invalidated_theorem_ids
    assert "lemma_b" in receipt.invalidated_theorem_ids
    assert "theorem_main" in receipt.invalidated_theorem_ids
    assert "theorem_unrelated" in receipt.reused_theorem_ids
    assert "obligation:unrelated" in receipt.reused_obligation_ids
    assert "obligation:lemma_a" in receipt.invalidated_obligation_ids
    assert "node:a" in receipt.source_node_cone.seeds
    assert "ast" in {stage for stage, _nodes in receipt.source_node_cone.stage_hits}

    reused_unrelated = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
        evidence_requests=(
            _evidence(
                "proof:unrelated",
                SliceSubjectKind.THEOREM,
                ("theorem_unrelated",),
                producing_stage=CompilationStage.AST,
            ),
            _evidence(
                "proof:lemma-a",
                SliceSubjectKind.THEOREM,
                ("lemma_a",),
                producing_stage=CompilationStage.AST,
            ),
        ),
    )
    assert reused_unrelated.reused_evidence_binding_ids == ("proof:unrelated",)
    assert "proof:lemma-a" in reused_unrelated.invalidated_evidence_binding_ids


def test_unchanged_stages_are_independently_replayed() -> None:
    previous = _pipeline()
    current = _pipeline(
        pipeline_id="pipeline:vc-recompiled",
        compiler_versions={
            CompilationStage.VC: "2.0.0",
            CompilationStage.FAMILY_IR: "2.0.0",
            CompilationStage.BACKEND: "2.0.0",
        },
    )
    mutation = LocalMutation(
        mutation_id="mutation:vc-compiler",
        changed_compiler_ids=("compiler:vc",),
        changed_stage_ids=("vc",),
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=current,
    )

    replayed = require_replayed_stages(receipt)
    replayed_ids = tuple(item.stage.value for item in replayed)
    assert "ast" in replayed_ids
    assert "normalized_ast" in replayed_ids
    assert "cfg" in replayed_ids
    assert "ssa_data_flow" in replayed_ids
    assert "contract_effect_ir" in replayed_ids
    assert "vc" in receipt.invalidated_stage_ids
    assert "family_ir" in receipt.invalidated_stage_ids
    assert "backend" in receipt.invalidated_stage_ids
    assert all(item.reproduced for item in replayed)
    assert all("independent_stage_replay" in item.reason_codes for item in replayed)
    assert "theorem_main" in receipt.invalidated_theorem_ids
    assert "theorem_unrelated" in receipt.reused_theorem_ids
    assert "lemma_a" in receipt.reused_theorem_ids


def test_empty_mutation_replays_every_stage_and_reuses_every_subject() -> None:
    previous = _pipeline()
    receipt = slice_and_replay_obligations(
        previous,
        mutation=LocalMutation(mutation_id="mutation:none"),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=previous,
        evidence_requests=(
            _evidence(
                "proof:unrelated",
                SliceSubjectKind.THEOREM,
                ("theorem_unrelated",),
                producing_stage=CompilationStage.AST,
            ),
        ),
    )
    assert receipt.invalidated_stage_ids == ()
    assert receipt.invalidated_theorem_ids == ()
    assert receipt.invalidated_obligation_ids == ()
    assert receipt.reused_evidence_binding_ids == ("proof:unrelated",)
    assert receipt.evidence_decisions[0].reason_codes == ("exact_cache_key_revalidated",)
    assert receipt.receipt_cid.startswith("b")
    assert receipt.to_dict()["interface"] == OBLIGATION_SLICING_INTERFACE


def test_cyclic_scc_is_closed_at_theorem_granularity() -> None:
    graph = TheoremDependencyGraph(
        theorems=(
            _theorem("ind_a", premises=("ind_b",), nodes=("node:a",)),
            _theorem("ind_b", premises=("ind_a",), nodes=("node:b",)),
            _theorem("unrelated", nodes=("node:unrelated",)),
        )
    )
    receipt = slice_and_replay_obligations(
        _pipeline(),
        mutation=LocalMutation(mutation_id="mutation:ind-a", changed_theorem_ids=("ind_a",)),
        theorem_graph=graph,
        current_pipeline=_pipeline(),
    )
    assert receipt.invalidated_theorem_ids == ("ind_a", "ind_b")
    assert receipt.reused_theorem_ids == ("unrelated",)
    assert ("ind_a", "ind_b") in receipt.affected_sccs
    decisions = {item.theorem_id: item for item in receipt.theorem_decisions}
    assert "scc_closure" in decisions["ind_b"].reason_codes
    assert "cyclic_theorem_scc_closed" in receipt.limitations


def test_reusable_evidence_is_independently_revalidated() -> None:
    previous = _pipeline()
    mutation = LocalMutation(
        mutation_id="mutation:lemma-a",
        changed_theorem_ids=("lemma_a",),
    )
    matching = _evidence(
        "proof:unrelated",
        SliceSubjectKind.THEOREM,
        ("theorem_unrelated",),
        producing_stage=CompilationStage.AST,
    )
    mismatched = _evidence(
        "proof:mismatch",
        SliceSubjectKind.THEOREM,
        ("theorem_unrelated",),
        current_key=_cache_key("a-different-current-request"),
        producing_stage=CompilationStage.AST,
    )
    affected = _evidence(
        "proof:lemma-a",
        SliceSubjectKind.THEOREM,
        ("lemma_a",),
        producing_stage=CompilationStage.AST,
    )
    conservative = _evidence(
        "proof:conservative",
        SliceSubjectKind.THEOREM,
        ("theorem_unrelated",),
        producing_stage=CompilationStage.AST,
        confidence="conservative",
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=previous,
        evidence_requests=(matching, mismatched, affected, conservative),
    )
    decisions = {item.binding_id: item for item in receipt.evidence_decisions}
    assert decisions["proof:unrelated"].disposition is SliceDisposition.REUSED
    assert "exact_cache_key_revalidated" in decisions["proof:unrelated"].reason_codes
    assert decisions["proof:mismatch"].disposition is SliceDisposition.INVALIDATED
    assert "cache_key_mismatch" in decisions["proof:mismatch"].reason_codes
    assert decisions["proof:lemma-a"].disposition is SliceDisposition.INVALIDATED
    assert "theorem_dependency_invalidated" in decisions["proof:lemma-a"].reason_codes
    assert decisions["proof:conservative"].disposition is SliceDisposition.INVALIDATED
    assert "non_exact_evidence" in decisions["proof:conservative"].reason_codes
    assert receipt.reused_evidence_binding_ids == ("proof:unrelated",)


def test_replay_failure_invalidates_the_stage() -> None:
    previous = _pipeline()
    first = previous.stages[0]
    stale = replace(
        StageReceiptExpectation.from_receipt(first),
        compiler=_compiler(first.output.stage, version="9.9.9"),
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=LocalMutation(mutation_id="mutation:replay-probe"),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=previous,
        stage_expectations={first.output.stage.value: stale},
    )
    decisions = {item.stage.value: item for item in receipt.stage_decisions}
    assert decisions[first.output.stage.value].disposition is SliceDisposition.INVALIDATED
    assert "replay_failed" in decisions[first.output.stage.value].reason_codes
    assert "unchanged_stage_replay_failed" in receipt.limitations
    with pytest.raises(UnchangedStageReplayError, match="replay failed"):
        require_replayed_stages(receipt)


def test_current_pipeline_receipt_identity_is_authoritative_for_stages() -> None:
    previous = _pipeline()
    current = _pipeline(
        pipeline_id="pipeline:same-receipts",
    )
    mutation = LocalMutation(
        mutation_id="mutation:node-a-with-current",
        changed_source_node_ids=("node:a",),
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=current,
    )
    assert receipt.invalidated_stage_ids == ()
    assert receipt.replayed_stage_ids
    assert "lemma_a" in receipt.invalidated_theorem_ids
    assert "theorem_unrelated" in receipt.reused_theorem_ids


def test_compiler_mutation_without_current_pipeline_invalidates_downstream() -> None:
    previous = _pipeline()
    mutation = LocalMutation(
        mutation_id="mutation:cfg-compiler",
        changed_compiler_ids=("compiler:cfg",),
        changed_stage_ids=("cfg",),
    )
    receipt = slice_and_replay_obligations(
        previous,
        mutation=mutation,
        theorem_graph=_graph(),
        obligations=_bindings(),
    )
    assert "cfg" in receipt.invalidated_stage_ids
    assert "ssa_data_flow" in receipt.invalidated_stage_ids
    assert "vc" in receipt.invalidated_stage_ids
    assert "backend" in receipt.invalidated_stage_ids
    assert "ast" in receipt.replayed_stage_ids
    assert "normalized_ast" in receipt.replayed_stage_ids
    assert "current_pipeline_unavailable" in receipt.limitations
    decisions = {item.stage.value: item for item in receipt.stage_decisions}
    assert "downstream_stage_invalidated" in decisions["vc"].reason_codes
    assert "lemma_a" in receipt.reused_theorem_ids
    assert "lemma_b" in receipt.invalidated_theorem_ids


def test_close_theorem_dependents_is_exact() -> None:
    graph = _graph()
    assert close_theorem_dependents(graph, ("lemma_a",)) == (
        "lemma_a",
        "lemma_b",
        "theorem_main",
    )
    assert close_theorem_dependents(graph, ("theorem_unrelated",)) == ("theorem_unrelated",)
    assert close_theorem_dependents(graph, ()) == ()


def test_source_node_cone_follows_mapped_targets_only() -> None:
    stages = _pipeline_stages()
    cone = propagate_changed_source_nodes(stages, ("node:a",))
    assert cone.seeds == ("node:a",)
    hit_stages = [stage for stage, _nodes in cone.stage_hits]
    assert hit_stages[0] == CompilationStage.AST.value
    assert "node:a" in cone.stage_hits[0][1]
    assert "ast:a" in cone.node_ids
    assert "node:unrelated" not in cone.node_ids
    empty = propagate_changed_source_nodes(stages, ())
    assert empty.stage_hits == ()
    assert empty.node_ids == ()


def test_records_round_trip_and_reject_unknown_fields() -> None:
    theorem = _theorem("lemma_a", nodes=("node:a",))
    assert TheoremRecord.from_dict(theorem.to_dict()) == theorem
    graph = _graph()
    restored = TheoremDependencyGraph.from_dict(graph.to_dict())
    assert restored.graph_cid == graph.graph_cid
    mutation = LocalMutation(mutation_id="mutation:x", changed_theorem_ids=("lemma_a",))
    assert LocalMutation.from_dict(mutation.to_dict()) == mutation
    binding = _bindings()[0]
    assert ObligationSliceBinding.from_dict(binding.to_dict()) == binding
    request = _evidence(
        "proof:round-trip",
        SliceSubjectKind.OBLIGATION,
        ("obligation:unrelated",),
        producing_stage=CompilationStage.AST,
    )
    assert ObligationEvidenceRequest.from_dict(request.to_dict()) == request

    forged = theorem.to_dict()
    forged["extra"] = True
    with pytest.raises(ObligationSlicingError, match="fields are closed"):
        TheoremRecord.from_dict(forged)
    forged_request = request.to_dict()
    forged_request["extra"] = True
    with pytest.raises(ObligationSlicingError, match="fields are closed"):
        ObligationEvidenceRequest.from_dict(forged_request)


def test_receipt_is_content_addressed_and_immutable() -> None:
    receipt = slice_and_replay_obligations(
        _pipeline(),
        mutation=LocalMutation(mutation_id="mutation:lemma-a", changed_theorem_ids=("lemma_a",)),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=_pipeline(),
    )
    payload = receipt.to_dict()
    assert payload["receipt_cid"] == receipt.receipt_cid
    assert payload["interface"] == OBLIGATION_SLICING_INTERFACE
    other = slice_and_replay_obligations(
        _pipeline(),
        mutation=LocalMutation(mutation_id="mutation:other", changed_theorem_ids=("lemma_a",)),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=_pipeline(),
    )
    assert other.receipt_cid != receipt.receipt_cid
    with pytest.raises(FrozenInstanceError):
        receipt.mutation_id = "changed"  # type: ignore[misc]


def test_unknown_premise_and_obligation_citation_fail_closed() -> None:
    with pytest.raises(ObligationSlicingError, match="unknown premises"):
        TheoremDependencyGraph(
            theorems=(_theorem("broken", premises=("missing",)),),
        )
    with pytest.raises(ObligationSlicingError, match="unknown theorems"):
        slice_and_replay_obligations(
            _pipeline(),
            mutation=LocalMutation(mutation_id="mutation:x"),
            theorem_graph=_graph(),
            obligations=(
                ObligationSliceBinding(
                    obligation_id="obligation:orphan",
                    statement_identity="statement:orphan",
                    theorem_ids=("not_a_theorem",),
                ),
            ),
        )


def test_stale_obligation_missing_theorem_citation_fails_closed() -> None:
    with pytest.raises(ObligationSlicingStaleError, match="missing theorem citations"):
        slice_and_replay_obligations(
            _pipeline(),
            mutation=LocalMutation(mutation_id="mutation:x"),
            theorem_graph=_graph(),
            obligations=(
                ObligationSliceBinding(
                    obligation_id="obligation:lemma_a",
                    statement_identity="statement:obligation:lemma_a",
                    theorem_ids=(),
                    producing_stage=CompilationStage.AST,
                ),
            ),
        )


def test_duplicate_ids_and_malformed_inputs_fail_closed() -> None:
    with pytest.raises(ObligationSlicingError, match="unique"):
        TheoremDependencyGraph(
            theorems=(_theorem("dup"), _theorem("dup")),
        )
    with pytest.raises(ObligationSlicingError, match="obligation IDs must be unique"):
        slice_and_replay_obligations(
            _pipeline(),
            mutation=LocalMutation(mutation_id="mutation:x"),
            theorem_graph=_graph(),
            obligations=(_bindings()[0], replace(_bindings()[0])),
        )
    with pytest.raises(ObligationSlicingError, match="CompilationPipelineReceipt"):
        slice_and_replay_obligations(
            {"not": "a pipeline"},  # type: ignore[arg-type]
            mutation=LocalMutation(mutation_id="mutation:x"),
            theorem_graph=_graph(),
        )
    with pytest.raises(ObligationSlicingError, match="LocalMutation"):
        slice_and_replay_obligations(
            _pipeline(),
            mutation="nope",  # type: ignore[arg-type]
            theorem_graph=_graph(),
        )


def test_deleted_theorem_named_in_mutation_is_invalidated() -> None:
    receipt = slice_and_replay_obligations(
        _pipeline(),
        mutation=LocalMutation(
            mutation_id="mutation:deleted",
            changed_theorem_ids=("retired_lemma",),
        ),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=_pipeline(),
    )
    assert "retired_lemma" in receipt.invalidated_theorem_ids
    assert "theorem_unrelated" in receipt.reused_theorem_ids


def test_dynamic_frontier_evidence_is_not_reused() -> None:
    receipt = slice_and_replay_obligations(
        _pipeline(),
        mutation=LocalMutation(mutation_id="mutation:none"),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=_pipeline(),
        evidence_requests=(
            _evidence(
                "proof:dynamic",
                SliceSubjectKind.THEOREM,
                ("theorem_unrelated",),
                producing_stage=CompilationStage.AST,
                dynamic_frontier=True,
            ),
        ),
    )
    assert receipt.reused_evidence_binding_ids == ()
    assert "dynamic_frontier" in receipt.evidence_decisions[0].reason_codes
    assert "dynamic_frontier_requires_full_revalidation" in receipt.limitations


def test_classify_translation_stages_replays_identical_current_pipeline() -> None:
    previous = _pipeline()
    decisions = classify_translation_stages(
        previous,
        LocalMutation(mutation_id="mutation:none"),
        current_pipeline=previous,
    )
    assert {item.disposition for item in decisions} == {SliceDisposition.REPLAYED}
    assert all(item.reproduced for item in decisions)


def test_slice_receipt_uses_existing_cache_key_authority_and_no_second_cache() -> None:
    key = _cache_key("proof:unrelated")
    request = _evidence(
        "proof:unrelated",
        SliceSubjectKind.THEOREM,
        ("theorem_unrelated",),
        producing_stage=CompilationStage.AST,
    )
    assert request.cache_key.key_id == key.key_id
    receipt = slice_and_replay_obligations(
        _pipeline(),
        mutation=LocalMutation(mutation_id="mutation:none"),
        theorem_graph=_graph(),
        obligations=_bindings(),
        current_pipeline=_pipeline(),
        evidence_requests=(request,),
    )
    assert receipt.evidence_decisions[0].admitted_cache_key_id == key.key_id
    assert receipt.authority_ceiling == EvidenceAuthority.INDEPENDENTLY_CHECKABLE.value


def test_full_p7_spine_is_classified() -> None:
    previous = _pipeline()
    receipt = slice_and_replay_obligations(
        previous,
        mutation=LocalMutation(mutation_id="mutation:none"),
        theorem_graph=_graph(),
        current_pipeline=previous,
    )
    classified = tuple(item.stage.value for item in receipt.stage_decisions)
    assert classified == tuple(
        stage.value for stage in STAGE_ORDER if stage is not CompilationStage.SOURCE
    )
    assert receipt.authority_ceiling == previous.authority_ceiling.value
