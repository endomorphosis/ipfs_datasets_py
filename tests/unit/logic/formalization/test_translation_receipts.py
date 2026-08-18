"""LGCVF-070: stage-addressed translation-validation receipts.

Acceptance:

* Every compilation stage binds input/output/compiler/source maps/subset/
  losses/assumptions/obligations/validation/replay/bounds/evidence class.
* Unsupported losses cap downstream authority.
* Required evidence: source-map, unsupported/loss, replay, stale-proof, and
  reconstruction tests.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.families.models import BoundednessKind, EvidenceAuthority
from ipfs_datasets_py.logic.formalization.translation_receipts import (
    REQUIRED_STAGE_BINDINGS,
    STAGE_ORDER,
    STAGE_TRANSLATION_RECEIPT_INTERFACE,
    CompilationPipelineReceipt,
    CompilationStage,
    EvidenceClass,
    MissingStageReceiptError,
    StageArtifactRef,
    StageCounterexample,
    StageMapDisposition,
    StageReceiptError,
    StageReceiptExpectation,
    StageReceiptIssueCode,
    StageReplayError,
    StageReplayManifest,
    StageSourceMap,
    StageSourceMapEntry,
    StageTranslationReceipt,
    StageValidationRecord,
    StageValidationStatus,
    StaleProofError,
    StaleStageReceiptError,
    SupportedSubset,
    authority_capped_by_losses,
    compose_pipeline_receipts,
    effective_downstream_authority,
    emit_stage_receipt,
    infer_preservation_claim,
    maximum_authority_for_evidence_class,
    reconstruct_pipeline_receipt,
    reconstruct_stage_receipt,
    replay_stage_receipt,
    require_current_stage_receipt,
    require_reproduced_stage_receipt,
    stage_successor,
    stages_are_adjacent,
    validate_stage_receipt,
)
from ipfs_datasets_py.logic.ir_core.claims import Assumption, ProofObligation
from ipfs_datasets_py.logic.software_verification.translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    SemanticMutation,
    SemanticMutationKind,
    TranslationBound,
    UnsupportedConstruct,
    UnsupportedHandling,
)


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


def _source_map(
    *node_ids: str,
    map_id: str = "map:stage",
    disposition: StageMapDisposition = StageMapDisposition.MAPPED,
) -> StageSourceMap:
    if not node_ids:
        node_ids = ("node:root",)
    entries = []
    for index, node_id in enumerate(node_ids, start=1):
        target_ids = (f"target:{node_id}",) if disposition is not StageMapDisposition.DROPPED else ()
        reason = "explicitly dropped as unsupported" if disposition is StageMapDisposition.DROPPED else ""
        if disposition is StageMapDisposition.UNSUPPORTED:
            target_ids = ()
            reason = "construct is outside the supported subset"
        entries.append(
            StageSourceMapEntry(
                entry_id=f"entry:{index}",
                source_node_id=node_id,
                disposition=disposition,
                target_node_ids=target_ids,
                source_ref_ids=("source:fixture",),
                span_ids=(f"span:{index}",),
                reason=reason,
            )
        )
    return StageSourceMap(
        map_id=map_id,
        entries=tuple(entries),
        required_source_node_ids=tuple(node_ids),
    )


def _subset(*features: str) -> SupportedSubset:
    return SupportedSubset(
        subset_id="subset:reviewed",
        feature_ids=features or ("feature:assignment", "feature:assert"),
        excluded_feature_ids=("feature:eval",),
        description="Reviewed deterministic fragment.",
    )


def _validation(
    *,
    status: StageValidationStatus = StageValidationStatus.VALID,
    identity: str = "validated:ok",
    issues: tuple[str, ...] = (),
    counterexamples: tuple[StageCounterexample, ...] = (),
) -> StageValidationRecord:
    if status is not StageValidationStatus.VALID and not issues:
        issues = (f"status:{status.value}",)
    return StageValidationRecord(
        status=status,
        checker_id="checker:stage-translation",
        checker_version="1.0.0",
        validated_identity=_identity(identity),
        issues=issues,
        counterexamples=counterexamples,
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


def _loss(
    *,
    handling: UnsupportedHandling = UnsupportedHandling.APPROXIMATED,
    construct_id: str = "construct:eval",
) -> UnsupportedConstruct:
    return UnsupportedConstruct(
        construct_id=construct_id,
        construct_kind="dynamic_eval",
        description="eval is outside the reviewed fragment.",
        handling=handling,
        source_ref_ids=("source:fixture",),
    )


def _bound() -> TranslationBound:
    return TranslationBound(
        bound_id="bound:unroll",
        kind=BoundednessKind.STEP_BOUNDED,
        limits={"steps": 8},
        description="Loops are unrolled through eight iterations.",
    )


def _stage_receipt(
    input_stage: CompilationStage = CompilationStage.SOURCE,
    output_stage: CompilationStage | None = None,
    **overrides: object,
) -> StageTranslationReceipt:
    output_stage = output_stage or stage_successor(input_stage)
    assert output_stage is not None
    input_artifact = overrides.pop("input", _artifact(input_stage))
    output_artifact = overrides.pop("output", _artifact(output_stage))
    compiler = overrides.pop("compiler", _compiler(output_stage))
    values: dict[str, object] = {
        "input": input_artifact,
        "output": output_artifact,
        "compiler": compiler,
        "source_map": _source_map("node:root"),
        "supported_subset": _subset(),
        "losses": (),
        "assumptions": (_assumption(),),
        "obligations": (_obligation(),),
        "validation": _validation(),
        "replay": _replay(compiler, input_artifact, output_artifact),
        "bounds": (),
        "evidence_class": EvidenceClass.TRANSLATION_VALIDATED,
        "preservation_claim": PreservationClaim(
            kind=PreservationKind.EXACT,
            preserved_property_ids=("property:safety",),
            permitted_result_classes=("proved", "disproved"),
            description="The reviewed fragment is structurally preserved.",
        ),
        "authority_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    }
    values.update(overrides)
    return emit_stage_receipt(**values)  # type: ignore[arg-type]


def _pipeline_stages() -> list[StageTranslationReceipt]:
    receipts: list[StageTranslationReceipt] = []
    for input_stage in STAGE_ORDER[:-1]:
        output_stage = stage_successor(input_stage)
        assert output_stage is not None
        receipts.append(_stage_receipt(input_stage, output_stage))
    return receipts


def test_stage_order_is_the_p7_compilation_spine() -> None:
    assert STAGE_ORDER == (
        CompilationStage.SOURCE,
        CompilationStage.AST,
        CompilationStage.NORMALIZED_AST,
        CompilationStage.CFG,
        CompilationStage.SSA_DATA_FLOW,
        CompilationStage.CONTRACT_EFFECT_IR,
        CompilationStage.VC,
        CompilationStage.FAMILY_IR,
        CompilationStage.BACKEND,
    )
    assert stage_successor(CompilationStage.BACKEND) is None
    assert stages_are_adjacent(CompilationStage.VC, CompilationStage.FAMILY_IR)
    assert not stages_are_adjacent(CompilationStage.SOURCE, CompilationStage.BACKEND)


def test_every_adjacent_stage_binds_the_required_dimensions() -> None:
    for input_stage in STAGE_ORDER[:-1]:
        output_stage = stage_successor(input_stage)
        assert output_stage is not None
        receipt = _stage_receipt(input_stage, output_stage)
        bindings = receipt.bound_fields()
        assert tuple(bindings) == REQUIRED_STAGE_BINDINGS
        assert bindings["input"]["stage"] == input_stage.value
        assert bindings["output"]["stage"] == output_stage.value
        assert bindings["compiler"]["stage"] == output_stage.value
        assert bindings["source_map"]["entries"]
        assert bindings["supported_subset"]["feature_ids"]
        assert bindings["losses"] == []
        assert bindings["assumptions"][0]["assumption_id"] == "assumption:closed-world"
        assert bindings["obligations"][0]["obligation_id"] == "obligation:post"
        assert bindings["validation"]["status"] == "valid"
        assert bindings["replay"]["input_identity"] == receipt.input.content_identity
        assert bindings["bounds"] == []
        assert bindings["evidence_class"] == EvidenceClass.TRANSLATION_VALIDATED.value
        assert receipt.INTERFACE == STAGE_TRANSLATION_RECEIPT_INTERFACE
        assert receipt.receipt_id.startswith("b")


def test_receipt_round_trips_and_is_content_addressed() -> None:
    receipt = _stage_receipt()
    payload = receipt.to_dict()
    rebuilt = StageTranslationReceipt.from_dict(payload)
    assert rebuilt == receipt
    assert rebuilt.receipt_id == receipt.receipt_id == receipt.content_id
    assert receipt.to_json().encode() == receipt.canonical_bytes()
    rehashed = replace(receipt, metadata={"route": "source-ast"}, receipt_id="")
    assert rehashed.receipt_id != receipt.receipt_id


def test_receipt_is_deeply_immutable() -> None:
    metadata = {"nested": {"values": ["original"]}}
    receipt = _stage_receipt(metadata=metadata)
    metadata["nested"]["values"].append("mutated")
    assert receipt.metadata["nested"]["values"] == ("original",)
    with pytest.raises(TypeError):
        receipt.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        receipt.receipt_id = "changed"  # type: ignore[misc]


def test_non_adjacent_stages_are_rejected() -> None:
    compiler = _compiler(CompilationStage.BACKEND)
    source = _artifact(CompilationStage.SOURCE)
    backend = _artifact(CompilationStage.BACKEND)
    with pytest.raises(StageReceiptError, match="cannot compile directly"):
        emit_stage_receipt(
            input=source,
            output=backend,
            compiler=compiler,
            source_map=_source_map(),
            supported_subset=_subset(),
            validation=_validation(),
            replay=_replay(compiler, source, backend),
            evidence_class=EvidenceClass.CANDIDATE,
        )


def test_source_map_requires_grounding_and_forbids_silent_drops() -> None:
    with pytest.raises(StageReceiptError, match="source grounding"):
        StageSourceMapEntry(
            entry_id="entry:ungrounded",
            source_node_id="node:x",
            disposition=StageMapDisposition.MAPPED,
            target_node_ids=("target:x",),
        )
    with pytest.raises(StageReceiptError, match="explicit reason"):
        StageSourceMapEntry(
            entry_id="entry:drop",
            source_node_id="node:x",
            disposition=StageMapDisposition.DROPPED,
            source_ref_ids=("source:fixture",),
            span_ids=("span:1",),
        )
    with pytest.raises(StageReceiptError, match="silent drops"):
        StageSourceMap(
            map_id="map:partial",
            entries=(
                StageSourceMapEntry(
                    entry_id="entry:1",
                    source_node_id="node:kept",
                    disposition=StageMapDisposition.MAPPED,
                    target_node_ids=("target:kept",),
                    source_ref_ids=("source:fixture",),
                    span_ids=("span:1",),
                ),
            ),
            required_source_node_ids=("node:kept", "node:missing"),
        )


def test_source_map_identity_changes_when_spans_move() -> None:
    original = _source_map("node:root")
    moved = StageSourceMap(
        map_id=original.map_id,
        entries=(
            replace(original.entries[0], span_ids=("span:moved",)),
        ),
        required_source_node_ids=original.required_source_node_ids,
    )
    assert original.identity.cid != moved.identity.cid
    receipt = _stage_receipt(source_map=original)
    expectation = StageReceiptExpectation.from_receipt(receipt)
    stale = replace(expectation, source_map=moved)
    validation = validate_stage_receipt(receipt, stale)
    assert not validation.current
    assert validation.issues[0].code is StageReceiptIssueCode.SOURCE_MAP_MISMATCH
    assert validation.effective_authority_ceiling is EvidenceAuthority.NONE


def test_unsupported_losses_cap_stage_authority_at_advisory() -> None:
    loss = _loss()
    mutation = SemanticMutation(
        mutation_id="mutation:eval-opaque",
        kind=SemanticMutationKind.ABSTRACTION,
        description="eval is replaced by an opaque uninterpreted effect.",
        source_construct_ids=(loss.construct_id,),
        target_construct_ids=("construct:opaque-effect",),
    )
    receipt = _stage_receipt(
        losses=(loss,),
        semantic_mutations=(mutation,),
        preservation_claim=PreservationClaim(PreservationKind.APPROXIMATE),
        authority_ceiling=EvidenceAuthority.ADVISORY,
        evidence_class=EvidenceClass.CANDIDATE,
    )
    assert receipt.authority_ceiling is EvidenceAuthority.ADVISORY
    assert authority_capped_by_losses(
        (loss,),
        preservation=receipt.preservation_claim,
        evidence_class=EvidenceClass.KERNEL_VERIFIED,
        declared=EvidenceAuthority.AUTHORITATIVE,
    ) is EvidenceAuthority.ADVISORY

    with pytest.raises(StageReceiptError, match="cap stage authority at advisory"):
        _stage_receipt(
            losses=(loss,),
            semantic_mutations=(mutation,),
            preservation_claim=PreservationClaim(PreservationKind.APPROXIMATE),
            authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            evidence_class=EvidenceClass.TRANSLATION_VALIDATED,
        )
    with pytest.raises(StageReceiptError, match="exact translations cannot contain"):
        _stage_receipt(losses=(loss,))


def test_rejected_or_omitted_losses_force_authority_none() -> None:
    omitted = _loss(handling=UnsupportedHandling.OMITTED)
    mutation = SemanticMutation(
        mutation_id="mutation:eval-dropped",
        kind=SemanticMutationKind.CONSTRUCT_DROPPED,
        description="eval is omitted from the target.",
        source_construct_ids=(omitted.construct_id,),
        target_construct_ids=("construct:absent",),
    )
    receipt = _stage_receipt(
        losses=(omitted,),
        semantic_mutations=(mutation,),
        preservation_claim=infer_preservation_claim(losses=(omitted,)),
        authority_ceiling=EvidenceAuthority.NONE,
        evidence_class=EvidenceClass.NONE,
        validation=_validation(
            status=StageValidationStatus.UNSUPPORTED,
            identity="validated:unsupported",
        ),
    )
    assert receipt.authority_ceiling is EvidenceAuthority.NONE
    assert receipt.preservation_claim.kind is PreservationKind.HEURISTIC
    with pytest.raises(StageReceiptError, match="authority_ceiling=none"):
        _stage_receipt(
            losses=(omitted,),
            semantic_mutations=(mutation,),
            preservation_claim=PreservationClaim(PreservationKind.HEURISTIC),
            authority_ceiling=EvidenceAuthority.ADVISORY,
            evidence_class=EvidenceClass.CANDIDATE,
        )


@pytest.mark.parametrize(
    ("evidence_class", "too_high"),
    [
        (EvidenceClass.CANDIDATE, EvidenceAuthority.BOUNDED),
        (EvidenceClass.SYNTAX_CHECKED, EvidenceAuthority.INDEPENDENTLY_CHECKABLE),
        (EvidenceClass.TRANSLATION_VALIDATED, EvidenceAuthority.AUTHORITATIVE),
        (EvidenceClass.BOUNDED_MODEL_CHECKED, EvidenceAuthority.INDEPENDENTLY_CHECKABLE),
        (EvidenceClass.SOLVER_CHECKED, EvidenceAuthority.AUTHORITATIVE),
    ],
)
def test_evidence_class_cannot_upgrade_authority(
    evidence_class: EvidenceClass,
    too_high: EvidenceAuthority,
) -> None:
    assert not (
        _authority_rank_allows(
            too_high, maximum_authority_for_evidence_class(evidence_class)
        )
    )
    with pytest.raises(StageReceiptError, match="cannot carry"):
        _stage_receipt(
            evidence_class=evidence_class,
            authority_ceiling=too_high,
        )


def _authority_rank_allows(
    authority: EvidenceAuthority, ceiling: EvidenceAuthority
) -> bool:
    order = [
        EvidenceAuthority.NONE,
        EvidenceAuthority.ADVISORY,
        EvidenceAuthority.BOUNDED,
        EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        EvidenceAuthority.AUTHORITATIVE,
    ]
    return order.index(authority) <= order.index(ceiling)


def test_pipeline_composition_uses_weakest_link_and_caps_downstream() -> None:
    exact = _stage_receipt(CompilationStage.SOURCE, CompilationStage.AST)
    lossy = _stage_receipt(
        CompilationStage.AST,
        CompilationStage.NORMALIZED_AST,
        losses=(_loss(),),
        semantic_mutations=(
            SemanticMutation(
                mutation_id="mutation:eval-opaque",
                kind=SemanticMutationKind.ABSTRACTION,
                description="eval is abstracted.",
                source_construct_ids=("construct:eval",),
                target_construct_ids=("construct:opaque-effect",),
            ),
        ),
        preservation_claim=PreservationClaim(PreservationKind.APPROXIMATE),
        authority_ceiling=EvidenceAuthority.ADVISORY,
        evidence_class=EvidenceClass.CANDIDATE,
    )
    pipeline = compose_pipeline_receipts((exact, lossy), pipeline_id="pipeline:lossy")
    assert pipeline.authority_ceiling is EvidenceAuthority.ADVISORY
    assert pipeline.evidence_class is EvidenceClass.CANDIDATE
    assert effective_downstream_authority((exact, lossy)) is EvidenceAuthority.ADVISORY

    overclaiming = _stage_receipt(
        CompilationStage.NORMALIZED_AST,
        CompilationStage.CFG,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        evidence_class=EvidenceClass.TRANSLATION_VALIDATED,
    )
    with pytest.raises(StageReceiptError, match="cap downstream authority"):
        compose_pipeline_receipts((exact, lossy, overclaiming))


def test_omitted_upstream_loss_caps_every_later_stage_to_none() -> None:
    omitted = _loss(handling=UnsupportedHandling.OMITTED, construct_id="construct:reflect")
    first = _stage_receipt(
        CompilationStage.SOURCE,
        CompilationStage.AST,
        losses=(omitted,),
        semantic_mutations=(
            SemanticMutation(
                mutation_id="mutation:reflect-dropped",
                kind=SemanticMutationKind.CONSTRUCT_DROPPED,
                description="reflection is omitted.",
                source_construct_ids=(omitted.construct_id,),
                target_construct_ids=("construct:absent",),
            ),
        ),
        preservation_claim=PreservationClaim(PreservationKind.HEURISTIC),
        authority_ceiling=EvidenceAuthority.NONE,
        evidence_class=EvidenceClass.NONE,
        validation=_validation(
            status=StageValidationStatus.UNSUPPORTED,
            identity="validated:omitted",
        ),
    )
    later = _stage_receipt(
        CompilationStage.AST,
        CompilationStage.NORMALIZED_AST,
        authority_ceiling=EvidenceAuthority.NONE,
        evidence_class=EvidenceClass.NONE,
        validation=_validation(
            status=StageValidationStatus.UNSUPPORTED,
            identity="validated:downstream-capped",
        ),
        preservation_claim=PreservationClaim(PreservationKind.HEURISTIC),
    )
    pipeline = compose_pipeline_receipts((first, later))
    assert pipeline.authority_ceiling is EvidenceAuthority.NONE
    assert effective_downstream_authority(first) is EvidenceAuthority.NONE


def test_replay_reproduces_unchanged_stage_and_fails_when_inputs_move() -> None:
    receipt = _stage_receipt()
    expectation = StageReceiptExpectation.from_receipt(receipt)
    result = replay_stage_receipt(receipt, expectation)
    assert result.reproduced
    assert result.effective_authority_ceiling is receipt.authority_ceiling
    assert require_reproduced_stage_receipt(receipt, expectation) is receipt

    moved_input = replace(receipt.input, content_identity=_identity("moved-source"))
    stale = replace(expectation, input=moved_input)
    failed = replay_stage_receipt(receipt, stale)
    assert not failed.reproduced
    assert failed.effective_authority_ceiling is EvidenceAuthority.NONE
    assert any(
        issue.code is StageReceiptIssueCode.INPUT_IDENTITY_MISMATCH
        for issue in failed.issues
    )
    with pytest.raises(StageReplayError, match="replay failed"):
        require_reproduced_stage_receipt(receipt, stale)


def test_stale_proof_is_rejected_when_inputs_compiler_or_obligations_change() -> None:
    receipt = _stage_receipt()
    current = StageReceiptExpectation.from_receipt(receipt)
    assert require_current_stage_receipt(receipt, current) is receipt

    moved = replace(
        current,
        input=replace(receipt.input, content_identity=_identity("new-source")),
    )
    with pytest.raises(StaleProofError, match="stale proof"):
        require_current_stage_receipt(receipt, moved)

    newer_compiler = replace(current, compiler=_compiler(CompilationStage.AST, version="1.0.1"))
    with pytest.raises(StaleProofError, match="stale proof"):
        require_current_stage_receipt(receipt, newer_compiler)

    other_obligation = ProofObligation(
        obligation_id="obligation:other",
        statement="A different obligation.",
        logic_family="hoare",
        source_refs=("source:fixture",),
    )
    with pytest.raises(StaleProofError, match="stale proof"):
        require_current_stage_receipt(
            receipt,
            replace(current, obligations=(other_obligation,)),
        )

    missing = validate_stage_receipt(None, current)
    assert missing.issues[0].code is StageReceiptIssueCode.MISSING_RECEIPT
    assert missing.effective_authority_ceiling is EvidenceAuthority.NONE
    with pytest.raises(MissingStageReceiptError):
        require_current_stage_receipt(None, current)
    with pytest.raises(StaleStageReceiptError, match="stale"):
        require_current_stage_receipt(
            receipt, replace(current, supported_subset=_subset("feature:other"))
        )


def test_reconstruction_round_trips_stage_and_pipeline_payloads() -> None:
    stages = _pipeline_stages()
    pipeline = compose_pipeline_receipts(stages, pipeline_id="pipeline:full")
    rebuilt_stage = reconstruct_stage_receipt(stages[0].to_dict())
    assert rebuilt_stage == stages[0]
    rebuilt_pipeline = reconstruct_pipeline_receipt(pipeline.to_dict())
    assert rebuilt_pipeline == pipeline
    assert rebuilt_pipeline.stage_receipt_ids == pipeline.stage_receipt_ids

    tampered = stages[0].to_dict()
    tampered["receipt_id"] = "bafkrei" + "a" * 52
    with pytest.raises(StageReceiptError, match="does not match canonical"):
        reconstruct_stage_receipt(tampered)

    mutated_input = replace(
        stages[0].input, content_identity=_identity("tampered-input")
    )
    mutated_replay = replace(
        stages[0].replay, input_identity=mutated_input.content_identity
    )
    reconstructed = reconstruct_stage_receipt(
        {
            **{key: value for key, value in stages[0].to_dict().items() if key != "receipt_id"},
            "input": mutated_input.to_dict(),
            "replay": mutated_replay.to_dict(),
        }
    )
    assert reconstructed.receipt_id != stages[0].receipt_id


def test_unknown_fields_and_duplicate_identities_fail_closed() -> None:
    receipt = _stage_receipt()
    payload = receipt.to_dict()
    payload["extra"] = True
    with pytest.raises(StageReceiptError, match="unknown"):
        StageTranslationReceipt.from_dict(payload)
    with pytest.raises(StageReceiptError, match="duplicates"):
        _stage_receipt(assumptions=(_assumption(), _assumption()))
    with pytest.raises(StageReceiptError, match="unknown assumptions"):
        _stage_receipt(
            assumptions=(),
            obligations=(_obligation(),),
        )


def test_non_valid_checks_and_failed_validation_carry_no_authority() -> None:
    counterexample = StageCounterexample(
        counterexample_id="cex:1",
        artifact_identity=_identity("cex"),
        description="Postcondition fails on the empty path.",
    )
    receipt = _stage_receipt(
        validation=_validation(
            status=StageValidationStatus.INVALID,
            identity="validated:invalid",
            issues=("postcondition violated",),
            counterexamples=(counterexample,),
        ),
        authority_ceiling=EvidenceAuthority.NONE,
        evidence_class=EvidenceClass.NONE,
        preservation_claim=PreservationClaim(PreservationKind.HEURISTIC),
    )
    assert receipt.validation.counterexamples[0].counterexample_id == "cex:1"
    assert receipt.authority_ceiling is EvidenceAuthority.NONE
    with pytest.raises(StageReceiptError, match="authority_ceiling=none"):
        _stage_receipt(
            validation=_validation(
                status=StageValidationStatus.INVALID,
                identity="validated:invalid2",
                issues=("failed",),
            ),
            authority_ceiling=EvidenceAuthority.ADVISORY,
            evidence_class=EvidenceClass.CANDIDATE,
        )


def test_bounded_stage_binds_limits_and_rejects_exact_bounds() -> None:
    bound = _bound()
    receipt = _stage_receipt(
        CompilationStage.VC,
        CompilationStage.FAMILY_IR,
        bounds=(bound,),
        preservation_claim=PreservationClaim(PreservationKind.BOUNDED),
        authority_ceiling=EvidenceAuthority.BOUNDED,
        evidence_class=EvidenceClass.BOUNDED_MODEL_CHECKED,
    )
    assert receipt.bounds[0].limits["steps"] == 8
    assert receipt.evidence_class is EvidenceClass.BOUNDED_MODEL_CHECKED
    with pytest.raises(StageReceiptError, match="cannot introduce semantic bounds"):
        _stage_receipt(bounds=(bound,))


def test_expectation_round_trip_and_stale_subset() -> None:
    receipt = _stage_receipt()
    expectation = StageReceiptExpectation.from_receipt(receipt)
    assert StageReceiptExpectation.from_dict(expectation.to_dict()) == expectation
    other_subset = _subset("feature:other")
    validation = validate_stage_receipt(
        receipt, replace(expectation, supported_subset=other_subset)
    )
    assert validation.issues[0].code is StageReceiptIssueCode.SUBSET_MISMATCH
    assert not validation.promotion_allowed


def test_pipeline_rejects_broken_identity_chain() -> None:
    first = _stage_receipt(CompilationStage.SOURCE, CompilationStage.AST)
    disconnected = _stage_receipt(
        CompilationStage.AST,
        CompilationStage.NORMALIZED_AST,
        input=replace(_artifact(CompilationStage.AST), content_identity=_identity("other-ast")),
    )
    with pytest.raises(StageReceiptError, match="must feed the next input"):
        compose_pipeline_receipts((first, disconnected))


def test_full_pipeline_reconstructs_every_stage_receipt() -> None:
    stages = _pipeline_stages()
    pipeline = compose_pipeline_receipts(stages)
    assert len(pipeline.stages) == len(STAGE_ORDER) - 1
    assert pipeline.stages[0].input.stage is CompilationStage.SOURCE
    assert pipeline.stages[-1].output.stage is CompilationStage.BACKEND
    rebuilt = CompilationPipelineReceipt.from_dict(pipeline.to_dict())
    assert rebuilt == reconstruct_pipeline_receipt(pipeline)
    for stage in rebuilt.stages:
        assert set(stage.bound_fields()) == set(REQUIRED_STAGE_BINDINGS)
        current = StageReceiptExpectation.from_receipt(stage)
        assert require_current_stage_receipt(stage, current) == stage
        assert replay_stage_receipt(stage, current).reproduced


def test_compiler_stage_must_match_output_stage() -> None:
    source = _artifact(CompilationStage.SOURCE)
    ast = _artifact(CompilationStage.AST)
    compiler = _compiler(CompilationStage.CFG)
    with pytest.raises(StageReceiptError, match="compiler.stage must equal"):
        emit_stage_receipt(
            input=source,
            output=ast,
            compiler=compiler,
            source_map=_source_map(),
            supported_subset=_subset(),
            validation=_validation(),
            replay=_replay(compiler, source, ast),
            evidence_class=EvidenceClass.SYNTAX_CHECKED,
        )
