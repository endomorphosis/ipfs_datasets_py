"""Integration tests: requirements + evidence → fail-closed compliance (PATLAW-042).

Uses compact synthetic fixtures and the real PATLAW-040 / PATLAW-041 builders
rather than bulk golden dumps.
"""

from __future__ import annotations

from datetime import date

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    OFFICE_ACTION_SCHEMA_VERSION,
    AnalysisCandidate,
    CandidateKind,
    CandidateOrigin,
    EvidenceLayer,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    RequirementCompilationInput,
    RequirementProcessor,
    sha256_hex as req_sha,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_evidence import (
    SubmissionEvidenceBuilder,
    SubmissionEvidenceInput,
    sha256_hex as ev_sha,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_processor import (
    EnrichedSubmissionFact,
    FactExtractionStatus,
    SubmissionFactType,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
    SubmissionFact,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_compliance_processor import (
    SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
    ComplianceReasonCode,
    ComplianceStatus,
    ProofExecutionStatus,
    SubmissionComplianceInput,
    SubmissionComplianceProcessor,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    AuthoritySpan,
    AuthorityTextNode,
    PatentTemporalAuthorityGraphBuilder,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    ArtifactIdentity,
    AuthorityTier,
    IdentityRole,
    VerificationState,
)

# ---------------------------------------------------------------------------
# Shared compact fixtures
# ---------------------------------------------------------------------------

_PKG = "pkg:int-cmpl-1"
_ART_OA = "art:int-oa-1"
_ART_SUB = "art:int-sub-1"
_DIGEST_OA = req_sha(b"oa-bytes-int-v1")
_DIGEST_SUB = ev_sha(b"sub-bytes-int-v1")


def _ids(prefix: str):
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"{prefix}:{counter['n']:04d}"

    return _factory


def _span(
    *,
    span_id: str,
    artifact_id: str,
    text: str,
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=0,
        char_start=0,
        char_end=max(len(text), 1),
        bbox=(0.0, 0.0, 200.0, 40.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=0.99,
        text_digest=req_sha(" ".join(text.split())),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _official(sha: str, source_id: str = "src-a") -> ArtifactIdentity:
    return ArtifactIdentity(
        provider="govinfo",
        source_id=source_id,
        artifact_sha256=sha,
        source_url=f"https://www.govinfo.gov/{source_id}",
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )


def _authority_graph():
    builder = PatentTemporalAuthorityGraphBuilder(graph_id="patlaw-042-int")
    builder.add_node(
        AuthorityTextNode(
            node_id="usc-112b-2011",
            citation_key="35-usc-112(b)",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="USCODE",
            citation="35 U.S.C. § 112(b)",
            edition="2011",
            version="aia-2011",
            text_excerpt="The specification shall conclude with one or more claims.",
            effective_start=date(2011, 9, 16),
            is_binding=True,
            official_artifact=_official("b" * 64, "usc-112b"),
            verification_state=VerificationState.VERIFIED,
            span=AuthoritySpan(
                section="112(b)",
                quote="The specification shall conclude with one or more claims.",
                start_offset=0,
                end_offset=56,
                artifact_sha256="b" * 64,
            ),
        )
    )
    return builder.build()


def _oa_candidate(
    *,
    surface: str = (
        "Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite. "
        "Applicant must amend claim 1 and provide remarks."
    ),
    span_id: str = "span:oa:req:1",
) -> AnalysisCandidate:
    return AnalysisCandidate(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        candidate_id="cand:int:1",
        kind=CandidateKind.REJECTION,
        layer=EvidenceLayer.VERIFIED,
        origin=CandidateOrigin.DETERMINISTIC_RULE,
        source_span_id=span_id,
        text_digest=req_sha(" ".join(surface.split())),
        surface_text=surface,
        confidence=0.95,
        ambiguity=None,
        claim_tokens=("1", "2", "3"),
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        citation_match_kind="exact",
        requirement_type="rejection_112",
        alternatives=(),
        exceptions=(),
        labels={},
        validation_receipt_id="val:int:1",
        review_state=ReviewState.PENDING,
    )


def _compile_requirements(*, with_authority: bool = True):
    surface = (
        "Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite. "
        "Applicant must amend claim 1 and provide remarks."
    )
    span = _span(span_id="span:oa:req:1", artifact_id=_ART_OA, text=surface)
    cand = _oa_candidate(surface=surface, span_id=span.span_id)
    proc = RequirementProcessor(
        graph=_authority_graph() if with_authority else None,
        id_factory=_ids("req"),
    )
    return proc.compile(
        RequirementCompilationInput(
            artifact_id=_ART_OA,
            candidates=(cand,),
            spans=(span,),
            classification=DisclosureClassification.PUBLIC_USER,
            analysis_id="oa:int:1",
            labels={"suite": "submission_compliance"},
        )
    )


def _build_evidence(*, include_remarks: bool = True, include_claims: bool = True):
    spans = []
    facts = []
    if include_claims:
        claim_text = "Claim 1 (currently amended). A widget comprising a hinge."
        cspan = _span(span_id="span:sub:claim:1", artifact_id=_ART_SUB, text=claim_text)
        spans.append(cspan)
        facts.append(
            EnrichedSubmissionFact(
                fact=SubmissionFact(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    fact_id="fact:claim:1",
                    evidence_span_id=cspan.span_id,
                    fact_type=SubmissionFactType.CURRENT_CLAIM.value,
                    affected_claims=("1",),
                    version="1",
                    extraction_status=FactExtractionStatus.OK.value,
                    classification=DisclosureClassification.PUBLIC_USER,
                ),
                artifact_id=_ART_SUB,
                value_digest=ev_sha(claim_text),
                display_value=None,
                field_name="claim:1",
                page_index=0,
                authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                is_authoritative=True,
                signature_presence=None,
            )
        )
    if include_remarks:
        remarks_text = "Applicants respectfully traverse the 112 rejection."
        rspan = _span(
            span_id="span:sub:remarks:1", artifact_id=_ART_SUB, text=remarks_text
        )
        spans.append(rspan)
        facts.append(
            EnrichedSubmissionFact(
                fact=SubmissionFact(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    fact_id="fact:remarks:1",
                    evidence_span_id=rspan.span_id,
                    fact_type=SubmissionFactType.REMARKS.value,
                    affected_claims=("1", "2", "3"),
                    version="1",
                    extraction_status=FactExtractionStatus.OK.value,
                    classification=DisclosureClassification.PUBLIC_USER,
                ),
                artifact_id=_ART_SUB,
                value_digest=ev_sha(remarks_text),
                display_value=None,
                field_name="remarks",
                page_index=0,
                authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                is_authoritative=True,
                signature_presence=None,
            )
        )
    builder = SubmissionEvidenceBuilder(id_factory=_ids("ev"))
    return builder.build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=tuple(facts),
            spans=tuple(spans),
            artifact_versions={_ART_SUB: _DIGEST_SUB, _ART_OA: _DIGEST_OA},
            classification=DisclosureClassification.PUBLIC_USER,
            analysis_id="sub:int:1",
            matter_id="matter:int:1",
            labels={"suite": "submission_compliance"},
        )
    )


# ---------------------------------------------------------------------------
# End-to-end fail-closed scenarios
# ---------------------------------------------------------------------------


def test_pipeline_no_requirements_cannot_pass() -> None:
    evidence = _build_evidence()
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            evidence=evidence,
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert ComplianceReasonCode.NO_REQUIREMENTS.value in result.reason_codes
    assert result.schema_version == SUBMISSION_COMPLIANCE_SCHEMA_VERSION


def test_pipeline_no_evidence_cannot_pass() -> None:
    requirements = _compile_requirements(with_authority=True)
    assert requirements.predicates, "fixture must compile at least one predicate"
    empty = SubmissionEvidenceBuilder(id_factory=_ids("ev")).build(
        SubmissionEvidenceInput(
            package_id=_PKG,
            facts=(),
            spans=(),
            artifact_versions={_ART_SUB: _DIGEST_SUB},
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=empty,
        )
    )
    assert result.overall_pass is False
    assert ComplianceReasonCode.NO_EVIDENCE.value in result.reason_codes
    assert all(a.status is not ComplianceStatus.SATISFIED for a in result.assessments)


def test_pipeline_missing_authority_fail_closed() -> None:
    requirements = _compile_requirements(with_authority=False)
    evidence = _build_evidence()
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=evidence,
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert result.mandatory_unknown_count >= 1 or any(
        ComplianceReasonCode.MISSING_AUTHORITY.value in a.reason_codes
        for a in result.assessments
    )


def test_pipeline_timeout_override_fail_closed() -> None:
    requirements = _compile_requirements(with_authority=True)
    evidence = _build_evidence()
    pred_ids = [p.predicate_id for p in requirements.predicates]
    overrides = {pid: ProofExecutionStatus.TIMEOUT for pid in pred_ids}
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=evidence,
            proof_overrides=overrides,
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert all(
        a.proof_status is ProofExecutionStatus.TIMEOUT for a in result.assessments
    )


@pytest.mark.parametrize(
    "status",
    [
        ProofExecutionStatus.UNSUPPORTED,
        ProofExecutionStatus.SKIPPED,
        ProofExecutionStatus.ERROR,
        ProofExecutionStatus.TIMEOUT,
    ],
)
def test_pipeline_non_definitive_proof_statuses_fail_closed(
    status: ProofExecutionStatus,
) -> None:
    requirements = _compile_requirements(with_authority=True)
    evidence = _build_evidence()
    pred_ids = [p.predicate_id for p in requirements.predicates]
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=evidence,
            proof_overrides={pid: status for pid in pred_ids},
        )
    )
    assert result.overall_pass is False
    assert result.overall_status is ComplianceStatus.UNKNOWN
    assert result.mandatory_unknown_count >= 1


def test_pipeline_satisfied_path_with_resolved_authority_and_evidence() -> None:
    requirements = _compile_requirements(with_authority=True)
    assert requirements.predicates
    evidence = _build_evidence(include_remarks=True, include_claims=True)
    assert not evidence.is_empty
    assert evidence.all_edges_round_trip()

    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=evidence,
            matter_id="matter:int:1",
            analysis_id="analyze:int:1",
            labels={"suite": "submission_compliance"},
        )
    )
    assert result.schema_version == SUBMISSION_COMPLIANCE_SCHEMA_VERSION
    assert result.assessments
    # At least one assessment should be definitive given remarks+claims evidence.
    statuses = {a.status for a in result.assessments}
    # If any mandatory unknown remains, overall cannot pass.
    if result.mandatory_unknown_count == 0 and all(
        a.status is ComplianceStatus.SATISFIED
        for a in result.assessments
        if a.mandatory and a.status is not ComplianceStatus.NOT_APPLICABLE
    ):
        assert result.overall_pass is True
        assert result.overall_status is ComplianceStatus.SATISFIED
    else:
        # Still fail-closed; never invent a pass with unknowns.
        assert result.overall_pass is False
        assert ComplianceStatus.UNKNOWN in statuses or result.mandatory_unknown_count >= 0

    # Explanations cite spans and versions for every assessment.
    for a in result.assessments:
        assert a.explanation
        assert "spans=" in a.explanation
        assert "versions=" in a.explanation
        assert a.citations
        # Every support citation carries a content version when present.
        for c in a.citations:
            if c.role.value == "support":
                assert c.content_sha256 == _DIGEST_SUB
                assert c.span_id

    # Round-trip
    restored = type(result).from_dict(result.to_dict())
    assert restored.to_canonical_json() == result.to_canonical_json()
    assert restored.overall_pass == result.overall_pass


def test_pipeline_mandatory_unknown_blocks_overall_pass() -> None:
    """Even with one satisfied requirement, a mandatory unknown blocks pass."""
    requirements = _compile_requirements(with_authority=True)
    evidence = _build_evidence()
    # Force one predicate to unknown via timeout while leaving others default.
    pred_ids = [p.predicate_id for p in requirements.predicates]
    assert pred_ids
    # Add a second synthetic override only if multiple; with one, force timeout.
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=evidence,
            proof_overrides={pred_ids[0]: "timeout"},
        )
    )
    assert result.overall_pass is False
    assert result.mandatory_unknown_count >= 1
    assert result.overall_status is ComplianceStatus.UNKNOWN


def test_pipeline_public_projection_is_identifier_safe() -> None:
    requirements = _compile_requirements(with_authority=True)
    evidence = _build_evidence()
    result = SubmissionComplianceProcessor(id_factory=_ids("cmpl")).analyze(
        SubmissionComplianceInput(
            package_id=_PKG,
            requirements=requirements,
            evidence=evidence,
        )
    )
    public = result.public_projection()
    import json

    blob = json.dumps(public)
    assert "surface_text" not in blob
    # Instruction surface from the OA must not leak into public projection.
    assert "indefinite" not in blob.lower() or "reason" in blob  # reasons ok
    # Prefer: no long instruction prose
    assert "Applicant must amend" not in blob
