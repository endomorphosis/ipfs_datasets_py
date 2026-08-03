"""Unit tests for fail-closed submission compliance analysis (PATLAW-042)."""

from __future__ import annotations

import itertools
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    GovernmentRequirement,
    ReviewState,
    SubmissionFact,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
    ApplicabilityBinding,
    ApplicabilityState,
    AuthorityBinding,
    AuthorityResolutionState,
    CompiledPredicate,
    PredicateAdmissionState,
    RequirementCompilationResult,
    RequirementComposition,
    RequirementScope,
    UncompiledClause,
    CompilationDisposition,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_evidence import (
    SUBMISSION_EVIDENCE_SCHEMA_VERSION,
    AdmittedSubmissionFact,
    ArtifactVersionBinding,
    EvidenceDisposition,
    EvidenceEdge,
    EvidenceEdgeRole,
    SubmissionEvidenceMap,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_processor import (
    FactExtractionStatus,
    SubmissionFactType,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_compliance_processor import (
    COMPLIANCE_RULESET_VERSION,
    PARSER_VERSION,
    SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
    AuthoritySnapshot,
    ComplianceDisposition,
    ComplianceReasonCode,
    ComplianceStatus,
    ProofExecutionReceipt,
    ProofExecutionStatus,
    RequirementAssessment,
    ReviewerActionKind,
    SubmissionComplianceInput,
    SubmissionComplianceProcessor,
    SubmissionComplianceResult,
    analyze_submission_compliance,
    default_evidence_prover,
    proof_status_blocks_pass,
    sha256_hex,
)

# ---------------------------------------------------------------------------
# Compact fixtures
# ---------------------------------------------------------------------------

_DIGEST_A = sha256_hex(b"artifact-bytes-version-a")
_DIGEST_OA = sha256_hex(b"office-action-bytes-v1")
_ART_SUB = "art:sub:1"
_ART_OA = "art:oa:1"
_PKG = "pkg:cmpl:unit-1"
_INSTR_DIGEST = sha256_hex("Claims 1-3 are rejected under 35 U.S.C. 112(b).")

_seq: Iterator[int] = itertools.count(1)


def _reset_seq() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _processor(**kwargs: Any) -> SubmissionComplianceProcessor:
    _reset_seq()
    return SubmissionComplianceProcessor(id_factory=_id_factory, **kwargs)


def _span(
    *,
    span_id: str = "span:sub:1",
    artifact_id: str = _ART_SUB,
    text: str = "Claim 1. A widget comprising a hinge.",
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=0,
        char_start=0,
        char_end=max(len(text), 1),
        bbox=(0.0, 0.0, 100.0, 40.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=1.0,
        text_digest=sha256_hex(text),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _authority(
    *,
    state: AuthorityResolutionState = AuthorityResolutionState.RESOLVED,
    node_id: str = "usc-112b-2011",
    version: str = "aia-2011",
) -> AuthorityBinding:
    if state is AuthorityResolutionState.RESOLVED:
        return AuthorityBinding(
            state=state,
            citation_surfaces=("35 U.S.C. § 112(b)",),
            citation_keys=("35-usc-112(b)",),
            selected_node_ids=(node_id,),
            selected_versions=(version,),
            match_kinds=("exact",),
            authority_tiers=("official-base",),
            reasons=(),
        )
    if state is AuthorityResolutionState.NOT_APPLICABLE:
        return AuthorityBinding(
            state=state,
            citation_surfaces=(),
            citation_keys=(),
            selected_node_ids=(),
            selected_versions=(),
            match_kinds=(),
            authority_tiers=(),
            reasons=("no_citations",),
        )
    return AuthorityBinding(
        state=state,
        citation_surfaces=("35 U.S.C. § 112(b)",) if state is AuthorityResolutionState.AMBIGUOUS else (),
        citation_keys=("35-usc-112(b)",) if state is AuthorityResolutionState.AMBIGUOUS else (),
        selected_node_ids=(),
        selected_versions=(),
        match_kinds=("ambiguous",) if state is AuthorityResolutionState.AMBIGUOUS else (),
        authority_tiers=(),
        reasons=("missing_authority",),
    )


def _applicability(
    state: ApplicabilityState = ApplicabilityState.APPLICABLE,
) -> ApplicabilityBinding:
    return ApplicabilityBinding(
        state=state,
        conditions=(),
        exceptions=(),
        lifecycle_status="active" if state is ApplicabilityState.APPLICABLE else None,
        reasons=(),
    )


def _predicate(
    *,
    predicate_id: str = "pred:unit:1",
    source_span_id: str = "span:oa:1",
    requirement_type: str = "rejection_112",
    scope: RequirementScope = RequirementScope.CLAIM_SPECIFIC,
    composition: RequirementComposition = RequirementComposition.ATOMIC,
    affected_claims: tuple[str, ...] = ("1", "2", "3"),
    authority: AuthorityBinding | None = None,
    applicability: ApplicabilityBinding | None = None,
    child_predicate_ids: tuple[str, ...] = (),
) -> CompiledPredicate:
    return CompiledPredicate(
        schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        predicate_id=predicate_id,
        source_candidate_id="cand:1",
        source_span_id=source_span_id,
        instruction_text_digest=_INSTR_DIGEST,
        surface_text="Claims 1-3 are rejected under 35 U.S.C. § 112(b).",
        composition=composition,
        scope=scope,
        requirement_type=requirement_type,
        affected_claims=affected_claims,
        legal_citations=("35 U.S.C. § 112(b)",),
        child_predicate_ids=child_predicate_ids,
        authority=authority or _authority(),
        applicability=applicability or _applicability(),
        proposed_date_rule=None,
        parser_confidence=0.9,
        review_state=ReviewState.PENDING,
        classification=DisclosureClassification.PUBLIC_USER,
        admission=PredicateAdmissionState.ADMITTED,
        labels={},
    )


def _compilation(
    *predicates: CompiledPredicate,
    uncompiled: tuple[UncompiledClause, ...] = (),
    disposition: CompilationDisposition = CompilationDisposition.COMPILED,
) -> RequirementCompilationResult:
    return RequirementCompilationResult(
        schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        compilation_id="comp:unit:1",
        source_analysis_id="oa:unit:1",
        source_artifact_id=_ART_OA,
        disposition=disposition,
        review_state=ReviewState.PENDING if uncompiled else ReviewState.NOT_REQUIRED,
        classification=DisclosureClassification.PUBLIC_USER,
        reason_codes=("predicates_admitted",),
        warnings=(),
        predicates=predicates,
        uncompiled=uncompiled,
        government_requirements=tuple(p.to_government_requirement() for p in predicates),
        ruleset_versions={
            "requirement_compiler": "requirement-compiler-rules@1",
            "requirement_processor": REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        },
        authority_graph_id="graph:unit",
        as_of=None,
        labels={},
        text_digest=sha256_hex("compilation"),
        retained=True,
    )


def _fact(
    *,
    fact_id: str = "fact:unit:1",
    span_id: str = "span:sub:1",
    fact_type: str = SubmissionFactType.REMARKS.value,
    affected_claims: tuple[str, ...] = ("1", "2", "3"),
) -> SubmissionFact:
    return SubmissionFact(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        fact_id=fact_id,
        evidence_span_id=span_id,
        fact_type=fact_type,
        affected_claims=affected_claims,
        version="1",
        extraction_status=FactExtractionStatus.OK.value,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _edge(
    *,
    edge_id: str = "edge:s:1",
    fact_id: str = "fact:unit:1",
    span_id: str = "span:sub:1",
    artifact_id: str = _ART_SUB,
    content_sha256: str = _DIGEST_A,
    role: EvidenceEdgeRole = EvidenceEdgeRole.SUPPORT,
    fact_type: str = SubmissionFactType.REMARKS.value,
) -> EvidenceEdge:
    return EvidenceEdge(
        edge_id=edge_id,
        fact_id=fact_id,
        span_id=span_id,
        artifact_id=artifact_id,
        content_sha256=content_sha256,
        role=role,
        fact_type=fact_type,
        fact_version="1",
        char_start=0,
        char_end=20,
        page_index=0,
    )


def _evidence_map(
    *,
    facts: tuple[AdmittedSubmissionFact, ...] | None = None,
    support_edges: tuple[EvidenceEdge, ...] | None = None,
    counter_edges: tuple[EvidenceEdge, ...] = (),
    spans: tuple[ExtractedSpan, ...] | None = None,
    empty: bool = False,
) -> SubmissionEvidenceMap:
    if empty:
        return SubmissionEvidenceMap(
            schema_version=SUBMISSION_EVIDENCE_SCHEMA_VERSION,
            map_id="emap:empty",
            package_id=_PKG,
            disposition=EvidenceDisposition.EMPTY,
            review_state=ReviewState.NOT_REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            reason_codes=("empty_no_implicit_support",),
            warnings=(),
            admitted_facts=(),
            support_edges=(),
            counter_edges=(),
            excluded=(),
            document_versions=(),
            claim_versions=(),
            spans=(),
            artifact_bindings=(
                ArtifactVersionBinding(
                    artifact_id=_ART_SUB, content_sha256=_DIGEST_A
                ),
            ),
            parser_versions={"submission_evidence": "patlaw-041.submission-evidence.v1"},
            labels={},
        )

    span = _span()
    spans = spans or (span,)
    edge = _edge()
    support_edges = support_edges if support_edges is not None else (edge,)
    fact = _fact()
    if facts is None:
        facts = (
            AdmittedSubmissionFact(
                fact=fact,
                artifact_id=_ART_SUB,
                content_sha256=_DIGEST_A,
                value_digest=sha256_hex("remarks"),
                field_name="remarks",
                is_authoritative=True,
                support_edge_ids=tuple(e.edge_id for e in support_edges),
                counter_edge_ids=tuple(e.edge_id for e in counter_edges),
            ),
        )
    return SubmissionEvidenceMap(
        schema_version=SUBMISSION_EVIDENCE_SCHEMA_VERSION,
        map_id="emap:unit:1",
        package_id=_PKG,
        disposition=EvidenceDisposition.MAPPED,
        review_state=ReviewState.NOT_REQUIRED,
        classification=DisclosureClassification.PUBLIC_USER,
        reason_codes=("facts_admitted", "support_edges_mapped"),
        warnings=(),
        admitted_facts=facts,
        support_edges=support_edges,
        counter_edges=counter_edges,
        excluded=(),
        document_versions=(),
        claim_versions=(),
        spans=spans,
        artifact_bindings=(
            ArtifactVersionBinding(artifact_id=_ART_SUB, content_sha256=_DIGEST_A),
            ArtifactVersionBinding(artifact_id=_ART_OA, content_sha256=_DIGEST_OA),
        ),
        parser_versions={"submission_evidence": "patlaw-041.submission-evidence.v1"},
        labels={},
        analysis_id="sub:unit:1",
        matter_id="matter:unit:1",
    )


def _assert_round_trip(result: SubmissionComplianceResult) -> None:
    payload = result.to_dict()
    restored = SubmissionComplianceResult.from_dict(payload)
    assert restored.to_canonical_json() == result.to_canonical_json()
    assert restored.schema_version == SUBMISSION_COMPLIANCE_SCHEMA_VERSION
    assert restored.overall_pass == result.overall_pass


# ---------------------------------------------------------------------------
# Fail-closed fixtures (acceptance)
# ---------------------------------------------------------------------------


def test_no_requirements_fail_closed() -> None:
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            evidence=_evidence_map(),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert ComplianceReasonCode.NO_REQUIREMENTS.value in result.reason_codes
    assert result.disposition is ComplianceDisposition.EMPTY
    assert result.mandatory_satisfied_count == 0
    assert result.reviewer_actions
    _assert_round_trip(result)


def test_no_evidence_fail_closed() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(empty=True),
        )
    )
    assert result.overall_pass is False
    assert ComplianceReasonCode.NO_EVIDENCE.value in result.reason_codes
    assert len(result.assessments) == 1
    a = result.assessments[0]
    # Absent evidence with resolved authority → unsatisfied or unknown; never pass.
    assert a.status in (ComplianceStatus.UNSATISFIED, ComplianceStatus.UNKNOWN)
    assert a.status is not ComplianceStatus.SATISFIED
    _assert_round_trip(result)


def test_unsupported_proof_fail_closed() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
            proof_overrides={pred.predicate_id: ProofExecutionStatus.UNSUPPORTED},
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    a = result.assessments[0]
    assert a.status is ComplianceStatus.UNKNOWN
    assert a.proof_status is ProofExecutionStatus.UNSUPPORTED
    assert ComplianceReasonCode.PROOF_UNSUPPORTED.value in a.reason_codes
    assert ComplianceReasonCode.MANDATORY_UNKNOWN.value in result.reason_codes
    _assert_round_trip(result)


def test_skipped_proof_fail_closed() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
            proof_overrides={pred.predicate_id: "skipped"},
        )
    )
    assert result.overall_pass is False
    assert result.assessments[0].status is ComplianceStatus.UNKNOWN
    assert result.assessments[0].proof_status is ProofExecutionStatus.SKIPPED
    assert ComplianceReasonCode.PROOF_SKIPPED.value in result.assessments[0].reason_codes


def test_timeout_proof_fail_closed() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
            proof_overrides={pred.predicate_id: ProofExecutionStatus.TIMEOUT},
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert result.assessments[0].proof_status is ProofExecutionStatus.TIMEOUT
    assert result.assessments[0].reviewer_action is not None
    assert (
        result.assessments[0].reviewer_action.kind is ReviewerActionKind.RESOLVE_PROOF
    )


def test_error_proof_fail_closed() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
            proof_overrides={pred.predicate_id: ProofExecutionStatus.ERROR},
        )
    )
    assert result.overall_pass is False
    assert result.assessments[0].status is ComplianceStatus.UNKNOWN
    assert ComplianceReasonCode.PROOF_ERROR.value in result.assessments[0].reason_codes


def test_contradiction_fail_closed() -> None:
    support = _edge(edge_id="edge:s:1", role=EvidenceEdgeRole.SUPPORT)
    counter = _edge(
        edge_id="edge:c:1",
        fact_id="fact:unit:1",
        span_id="span:sub:1",
        role=EvidenceEdgeRole.COUNTER,
    )
    fact = _fact()
    admitted = AdmittedSubmissionFact(
        fact=fact,
        artifact_id=_ART_SUB,
        content_sha256=_DIGEST_A,
        value_digest=sha256_hex("remarks"),
        field_name="remarks",
        is_authoritative=True,
        support_edge_ids=(support.edge_id,),
        counter_edge_ids=(counter.edge_id,),
    )
    evidence = _evidence_map(
        facts=(admitted,),
        support_edges=(support,),
        counter_edges=(counter,),
    )
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=evidence,
        )
    )
    assert result.overall_pass is False
    a = result.assessments[0]
    assert a.status is not ComplianceStatus.SATISFIED
    assert ComplianceReasonCode.CONTRADICTION.value in a.reason_codes
    assert a.counter_span_ids
    assert a.support_span_ids
    assert a.reviewer_action is not None
    assert a.reviewer_action.kind is ReviewerActionKind.RESOLVE_CONTRADICTION


def test_missing_authority_fail_closed() -> None:
    pred = _predicate(authority=_authority(state=AuthorityResolutionState.UNKNOWN))
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    a = result.assessments[0]
    assert a.status is ComplianceStatus.UNKNOWN
    assert ComplianceReasonCode.MISSING_AUTHORITY.value in a.reason_codes
    assert a.reviewer_action is not None
    assert a.reviewer_action.kind is ReviewerActionKind.RESOLVE_AUTHORITY


def test_ambiguous_authority_fail_closed() -> None:
    pred = _predicate(authority=_authority(state=AuthorityResolutionState.AMBIGUOUS))
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert result.overall_pass is False
    assert result.assessments[0].status is ComplianceStatus.UNKNOWN
    assert ComplianceReasonCode.AUTHORITY_AMBIGUOUS.value in result.assessments[0].reason_codes


def test_top_level_cannot_pass_with_mandatory_unknown() -> None:
    good = _predicate(predicate_id="pred:good")
    bad = _predicate(
        predicate_id="pred:bad",
        authority=_authority(state=AuthorityResolutionState.UNKNOWN),
    )
    # Evidence supports claim-specific remarks for both.
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(good, bad),
            evidence=_evidence_map(),
            proof_overrides={
                good.predicate_id: ProofExecutionStatus.SUCCESS,
                # leave bad to default (unsupported due to missing authority)
            },
        )
    )
    assert result.overall_pass is False
    assert result.mandatory_unknown_count >= 1
    assert result.overall_status is ComplianceStatus.UNKNOWN
    # Structural invariant also enforced on the result dataclass.
    with pytest.raises(ValueError, match="mandatory unknowns"):
        SubmissionComplianceResult(
            schema_version=SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
            result_id="cmpl:bad",
            package_id=_PKG,
            disposition=ComplianceDisposition.ASSESSED,
            overall_status=ComplianceStatus.SATISFIED,
            overall_pass=True,
            review_state=ReviewState.NOT_REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            reason_codes=(),
            warnings=(),
            assessments=(),
            proof_receipts=(),
            reviewer_actions=(),
            ruleset_versions={},
            parser_versions={},
            labels={},
            mandatory_unknown_count=1,
            mandatory_satisfied_count=1,
        )


# ---------------------------------------------------------------------------
# Happy path + explanations cite spans/versions
# ---------------------------------------------------------------------------


def test_satisfied_with_support_and_resolved_authority() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert len(result.assessments) == 1
    a = result.assessments[0]
    assert a.status is ComplianceStatus.SATISFIED
    assert a.proof_status is ProofExecutionStatus.SUCCESS
    assert result.overall_pass is True
    assert result.overall_status is ComplianceStatus.SATISFIED
    assert result.mandatory_satisfied_count == 1
    assert result.mandatory_unknown_count == 0
    assert ComplianceReasonCode.OVERALL_PASS.value in result.reason_codes
    _assert_round_trip(result)


def test_explanations_cite_all_source_spans_and_versions() -> None:
    pred = _predicate()
    evidence = _evidence_map()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=evidence,
        )
    )
    a = result.assessments[0]
    assert a.citations, "assessment must cite sources"
    # Instruction span cited.
    roles = {c.role.value for c in a.citations}
    assert "requirement" in roles or a.instruction_span_id
    # Support span + content version cited.
    support_cites = [c for c in a.citations if c.role.value == "support"]
    assert support_cites
    for c in support_cites:
        assert c.span_id
        assert c.content_sha256 == _DIGEST_A
        assert c.artifact_id == _ART_SUB
    # Authority version cited.
    auth_cites = [c for c in a.citations if c.role.value == "authority"]
    assert auth_cites
    assert any(c.authority_version == "aia-2011" for c in auth_cites)
    # Explanation string enumerates spans and versions.
    assert "spans=" in a.explanation
    assert "versions=" in a.explanation
    assert a.instruction_span_id in a.explanation or "span:" in a.explanation
    assert _DIGEST_A[:12] in a.explanation or "aia-2011" in a.explanation


def test_not_applicable_does_not_alone_enable_pass() -> None:
    pred = _predicate(
        applicability=_applicability(ApplicabilityState.NOT_APPLICABLE),
    )
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert result.assessments[0].status is ComplianceStatus.NOT_APPLICABLE
    assert result.assessments[0].mandatory is False
    assert result.overall_pass is False  # no mandatory satisfied
    assert result.not_applicable_count == 1


def test_unsatisfied_when_counter_only() -> None:
    counter = _edge(edge_id="edge:c:1", role=EvidenceEdgeRole.COUNTER)
    fact = _fact()
    admitted = AdmittedSubmissionFact(
        fact=fact,
        artifact_id=_ART_SUB,
        content_sha256=_DIGEST_A,
        value_digest=sha256_hex("counter"),
        field_name="remarks",
        is_authoritative=True,
        support_edge_ids=(),
        counter_edge_ids=(counter.edge_id,),
    )
    evidence = _evidence_map(
        facts=(admitted,),
        support_edges=(),
        counter_edges=(counter,),
    )
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=evidence,
        )
    )
    assert result.overall_pass is False
    assert result.assessments[0].status is ComplianceStatus.UNSATISFIED
    assert result.overall_status is ComplianceStatus.UNSATISFIED


def test_uncompiled_clause_forces_review() -> None:
    pred = _predicate()
    unc = UncompiledClause(
        schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        clause_id="unc:1",
        source_candidate_id="cand:u",
        source_span_id="span:oa:1",
        instruction_text_digest=sha256_hex("uncompiled residual language"),
        surface_text="[uncompiled residual]",
        reason="uncompiled_retained",
        classification=DisclosureClassification.PUBLIC_USER,
        review_state=ReviewState.REQUIRED,
        labels={},
    )
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred, uncompiled=(unc,)),
            evidence=_evidence_map(),
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert ComplianceReasonCode.UNCOMPILED_RETAINED.value in result.reason_codes
    assert any(
        a.kind is ReviewerActionKind.COMPILE_REQUIREMENT for a in result.reviewer_actions
    )


def test_unsupported_composition_without_children() -> None:
    pred = _predicate(
        composition=RequirementComposition.ALTERNATIVE,
        child_predicate_ids=(),
    )
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert result.overall_pass is False
    assert result.assessments[0].status is ComplianceStatus.UNKNOWN
    assert (
        ComplianceReasonCode.UNSUPPORTED_SEMANTICS.value
        in result.assessments[0].reason_codes
    )


def test_injected_proof_executor_error() -> None:
    def boom(req_id: str, ctx: Any) -> Any:
        raise RuntimeError("prover crashed")

    pred = _predicate()
    result = _processor(proof_executor=boom).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert result.overall_pass is False
    assert result.assessments[0].proof_status is ProofExecutionStatus.ERROR


def test_public_projection_omits_surface_explanation_body_safe() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    public = result.public_projection()
    blob = canonical_json(public)
    assert "surface_text" not in blob
    assert "Claims 1-3" not in blob
    # Assessment public projection omits instruction surface prose.
    assert "rejected under" not in canonical_json(
        result.assessments[0].public_projection()
    )


def test_module_wrapper_and_mapping_input() -> None:
    pred = _predicate()
    compilation = _compilation(pred)
    evidence = _evidence_map()
    result = analyze_submission_compliance(
        {
            "package_id": _PKG,
            "requirements": compilation.to_dict(),
            "evidence": evidence.to_dict(),
        },
        id_factory=_id_factory,
    )
    _reset_seq()
    assert result.schema_version == SUBMISSION_COMPLIANCE_SCHEMA_VERSION
    assert COMPLIANCE_RULESET_VERSION in result.ruleset_versions.values() or (
        result.ruleset_versions.get("submission_compliance") == COMPLIANCE_RULESET_VERSION
    )


def test_form_verifier_empty_inputs_fail_closed() -> None:
    pred = _predicate(
        scope=RequirementScope.FORM,
        requirement_type="form_sb08",
        affected_claims=(),
        authority=_authority(state=AuthorityResolutionState.NOT_APPLICABLE),
    )
    # Form-scoped with matching form fact.
    form_fact = _fact(
        fact_id="fact:form:1",
        fact_type=SubmissionFactType.FORM.value,
        affected_claims=(),
    )
    edge = _edge(edge_id="edge:form:1", fact_id="fact:form:1")
    admitted = AdmittedSubmissionFact(
        fact=form_fact,
        artifact_id=_ART_SUB,
        content_sha256=_DIGEST_A,
        value_digest=sha256_hex("form"),
        field_name="form:sb08",
        is_authoritative=True,
        support_edge_ids=(edge.edge_id,),
        counter_edge_ids=(),
    )
    evidence = _evidence_map(facts=(admitted,), support_edges=(edge,))
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=evidence,
            form_values={"full_name": "Ada"},  # incomplete: no rule_set
        )
    )
    assert result.overall_pass is False
    assert ComplianceReasonCode.FORM_VERIFIER_EMPTY.value in result.reason_codes


def test_proof_status_blocks_pass_helper() -> None:
    assert proof_status_blocks_pass(ProofExecutionStatus.SUCCESS) is False
    for s in (
        ProofExecutionStatus.FAILURE,
        ProofExecutionStatus.TIMEOUT,
        ProofExecutionStatus.ERROR,
        ProofExecutionStatus.UNSUPPORTED,
        ProofExecutionStatus.SKIPPED,
    ):
        assert proof_status_blocks_pass(s) is True


def test_default_evidence_prover_forced_status() -> None:
    receipt = default_evidence_prover(
        "pred:x",
        {"forced_status": "timeout", "prover": "test"},
        id_factory=lambda: "1",
    )
    assert isinstance(receipt, ProofExecutionReceipt)
    assert receipt.status is ProofExecutionStatus.TIMEOUT


def test_fee_scope_matches_fee_facts() -> None:
    pred = _predicate(
        scope=RequirementScope.FEE,
        requirement_type="fee_payment",
        affected_claims=(),
        authority=_authority(state=AuthorityResolutionState.NOT_APPLICABLE),
    )
    fact = _fact(
        fact_id="fact:fee:1",
        fact_type=SubmissionFactType.FEE_PRESENCE.value,
        affected_claims=(),
    )
    edge = _edge(edge_id="edge:fee:1", fact_id="fact:fee:1")
    admitted = AdmittedSubmissionFact(
        fact=fact,
        artifact_id=_ART_SUB,
        content_sha256=_DIGEST_A,
        value_digest=sha256_hex("fee"),
        field_name="fee:1011",
        is_authoritative=True,
        support_edge_ids=(edge.edge_id,),
        counter_edge_ids=(),
    )
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(facts=(admitted,), support_edges=(edge,)),
        )
    )
    assert result.assessments[0].status is ComplianceStatus.SATISFIED
    assert result.overall_pass is True


def test_versioned_schema_on_result() -> None:
    pred = _predicate()
    result = _processor().analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        )
    )
    assert result.schema_version == SUBMISSION_COMPLIANCE_SCHEMA_VERSION
    assert PARSER_VERSION in result.parser_versions.values()
    for a in result.assessments:
        assert a.schema_version == SUBMISSION_COMPLIANCE_SCHEMA_VERSION
        assert isinstance(a, RequirementAssessment)
        assert a.authority is not None
        assert isinstance(a.authority, AuthoritySnapshot)


def test_analyze_many() -> None:
    pred = _predicate()
    inputs = [
        SubmissionComplianceInput(package_id="pkg:a", evidence=_evidence_map(empty=True)),
        SubmissionComplianceInput(
            package_id="pkg:b",
            requirements=_compilation(pred),
            evidence=_evidence_map(),
        ),
    ]
    results = _processor().analyze_many(inputs)
    assert len(results) == 2
    assert results[0].overall_pass is False
    assert results[1].overall_pass is True
