"""Integration: government instruction logic assurance (PATLAW-134).

Wires office-action semantics (PATLAW-129), temporal authority support
(PATLAW-135-style snapshots as support records), and privacy-safe proof
execution (PATLAW-126) into semantic instruction consistency.

Compact recipe generators — not bulk golden dumps.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_contracts import (
    LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
    ActorRole,
    AssertionKind,
    AuthorityBinding,
    AuthorityRank,
    AuthorityResolutionState,
    CitationRef,
    DisclosureMetadata,
    LegalModality,
    MappingStatus,
    NormalizedProposition,
    SourceIdentity,
    TemporalMetadata,
    UsptoSpanRef,
    build_legal_ir_mapping,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
    ProofOutcome,
    execute_legal_ir_proof,
    run_local_bounded_kernel,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_semantics_v2 import (
    CommunicationFamily,
    OfficeActionSemanticsInput,
    OfficeActionSemanticsV2,
    SemanticFieldKind,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.semantic_instruction_consistency_processor import (
    DOCUMENTED_DETERMINISTIC_RULES,
    FindingKind,
    InstructionCheckUnit,
    PropositionAtom,
    SemanticConsistencyInput,
    SemanticDisposition,
    SemanticInstructionConsistencyProcessor,
    SemanticReasonCode,
    SemanticVerdict,
    SupportKind,
    build_binding_authority_support,
    build_conflicting_authority_fixture,
    build_missing_authority_fixture,
    build_superseded_authority_fixture,
    build_verified_consistent_fixture,
    build_wrong_proposition_fixture,
    verify_semantic_instruction_consistency,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_materializer import (
    MaterializedAuthorityRecord,
    filter_records_as_of,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AuthorityKind,
    RenditionLegalStatus,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    VerificationState,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
STATUTE_112B = (
    "The specification shall conclude with one or more claims particularly "
    "pointing out and distinctly claiming the subject matter."
)
MISQUOTE = "The specification may omit claims when the drawings are sufficient."


# ---------------------------------------------------------------------------
# Compact recipes
# ---------------------------------------------------------------------------


def _oa_non_final_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/123,456
Mailing Date: 2024-06-01
Office Action Summary

This is a non-final office action.

Claim Rejections - 35 U.S.C. § 112(b)

Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite because the
statute provides "{STATUTE_112B}".

Response Period
A shortened statutory period for reply is set to expire in 3 months from the
mailing date under 37 C.F.R. § 1.134.
Applicant is required to traverse the rejection or amend the claims.
"""


def _materialized_112b(
    *,
    superseded: bool = False,
    version: str = "aia-2011",
    text: str = STATUTE_112B,
    record_id: str = "rec:112b",
) -> MaterializedAuthorityRecord:
    return MaterializedAuthorityRecord(
        record_id=record_id,
        citation_key="35-usc-112(b)",
        authority_kind=AuthorityKind.CODIFIED_STATUTE,
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        rendition_legal_status=RenditionLegalStatus.OFFICIAL_ELECTRONIC,
        collection="USCODE",
        source_key="govinfo:usc-112b",
        jurisdiction="US",
        citation="35 U.S.C. § 112(b)",
        title="Definiteness",
        edition=version,
        version=version,
        text_excerpt=text,
        effective_start=date(2000, 1, 1) if superseded else date(2011, 9, 16),
        effective_end=date(2011, 9, 15) if superseded else None,
        is_binding=not superseded,
        is_withdrawn=superseded,
        is_mandatory=True,
        verification_state=VerificationState.VERIFIED,
        content_sha256=DIGEST_A if not superseded else DIGEST_B,
    )


def _support_from_materialized(
    rec: MaterializedAuthorityRecord,
    *,
    predicates: tuple[str, ...] = ("claims_must_particularly_point_out",),
) -> Any:
    return build_binding_authority_support(
        support_id=rec.record_id,
        citation_surface=rec.citation or rec.citation_key,
        citation_key=rec.citation_key,
        text_excerpt=rec.text_excerpt or "",
        version=rec.version or rec.edition or "unknown",
        proposition_predicates=predicates,
        node_id=rec.record_id,
        authority_rank=(
            AuthorityRank.OFFICIAL_BASE.value
            if rec.authority_tier is AuthorityTier.OFFICIAL_BASE
            else AuthorityRank.GUIDANCE.value
        ),
        is_binding=bool(rec.is_binding) and not bool(rec.is_withdrawn),
        is_superseded=bool(rec.is_withdrawn)
        or (
            rec.effective_end is not None
            and rec.effective_end < date(2024, 6, 1)
        ),
        is_withdrawn=bool(rec.is_withdrawn),
        effective_start=(
            rec.effective_start.isoformat() if rec.effective_start else None
        ),
        effective_end=(
            rec.effective_end.isoformat() if rec.effective_end else None
        ),
        content_sha256=rec.content_sha256,
    )


def _processor() -> SemanticInstructionConsistencyProcessor:
    n = {"i": 0}

    def ids() -> str:
        n["i"] += 1
        return f"sic:int:{n['i']:04d}"

    return SemanticInstructionConsistencyProcessor(id_factory=ids)


# ---------------------------------------------------------------------------
# Pipeline: OA semantics → instruction units → semantic assurance
# ---------------------------------------------------------------------------


def test_pipeline_office_action_to_semantic_assurance() -> None:
    """End-to-end: parse OA semantics, bind authority, verify instructions."""
    text = _oa_non_final_text()
    semantics = OfficeActionSemanticsV2().analyze(
        OfficeActionSemanticsInput(
            artifact_id="art:oa:int:1",
            text=text,
            document_code="CTNF",
            classification=DisclosureClassification.PUBLIC_USER,
            mailing_date="2024-06-01",
        )
    )
    # OA semantics v2 is a dependency; require a parsed analysis payload so
    # downstream instruction units remain grounded in a real OA parse.
    assert semantics is not None
    assert semantics.artifact_id == "art:oa:int:1"
    assert semantics.family is not None or semantics.fields is not None

    # Materialize temporal authority and filter as-of mailing date.
    records = (_materialized_112b(),)
    as_of_records = filter_records_as_of(records, as_of=date(2024, 6, 1))
    assert as_of_records
    support = _support_from_materialized(as_of_records[0])

    # Build instruction units from semantic fields + authority support.
    units: list[InstructionCheckUnit] = []
    rejection_surface = (
        f'Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite '
        f'because the statute provides "{STATUTE_112B}".'
    )
    units.append(
        InstructionCheckUnit(
            unit_id="unit:rej-112b",
            finding_kind=FindingKind.INSTRUCTION,
            instruction_span_id="span:rej-112b",
            instruction_surface_text=rejection_surface,
            instruction_text_digest=None,
            legal_citations=("35 U.S.C. § 112(b)",),
            citation_keys=("35-usc-112(b)",),
            claimed_atoms=(
                PropositionAtom(
                    atom_id="prop:point-out",
                    predicate="claims_must_particularly_point_out",
                    polarity=True,
                    modality=LegalModality.OBLIGATION.value,
                ),
            ),
            quoted_authority_text=STATUTE_112B,
            deadline_basis=None,
            required_act="amend_or_traverse",
            exceptions=(),
            applicability_conditions=("non_final_office_action",),
            assumptions=("mailing_date:2024-06-01",),
            authority_supports=(support,),
            legal_ir_mapping=None,
            confidence=0.91,
            classification=DisclosureClassification.PUBLIC_USER,
            labels={"source": "oa_semantics_v2"},
            force_skip_proof=False,
        )
    )
    # Deadline basis unit from response period.
    cfr_support = build_binding_authority_support(
        support_id="auth:cfr-1.134",
        citation_surface="37 C.F.R. § 1.134",
        citation_key="37-cfr-1.134",
        text_excerpt="Time period for reply to Office action.",
        version="2020-base",
        proposition_predicates=("reply_period_set_by_office",),
        effective_start="2020-01-01",
    )
    units.append(
        InstructionCheckUnit(
            unit_id="unit:deadline-reply",
            finding_kind=FindingKind.DEADLINE_BASIS,
            instruction_span_id="span:deadline",
            instruction_surface_text=(
                "A shortened statutory period for reply is set to expire in "
                "3 months from the mailing date under 37 C.F.R. § 1.134."
            ),
            instruction_text_digest=None,
            legal_citations=("37 C.F.R. § 1.134",),
            citation_keys=("37-cfr-1.134",),
            claimed_atoms=(
                PropositionAtom(
                    atom_id="prop:reply",
                    predicate="reply_period_set_by_office",
                    polarity=True,
                ),
            ),
            quoted_authority_text="Time period for reply to Office action.",
            deadline_basis="reply_period_set_by_office",
            required_act=None,
            exceptions=(),
            applicability_conditions=(),
            assumptions=("mailing_date:2024-06-01",),
            authority_supports=(cfr_support,),
            legal_ir_mapping=None,
            confidence=0.9,
            classification=DisclosureClassification.PUBLIC_USER,
            labels={"source": "oa_semantics_v2"},
            force_skip_proof=True,  # exercise deterministic rule path
        )
    )

    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:oa:int:1",
            units=tuple(units),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:int:pipeline",
            matter_id="matter:int:1",
            snapshot_id="snap:asof:2024-06-01",
            run_proofs=True,
            labels={"pipeline": "oa_semantics_to_semantic_assurance"},
        )
    )

    assert result.disposition is SemanticDisposition.ASSURED
    assert result.is_pass is True
    assert result.pass_count == 2
    assert result.fail_count == 0
    assert result.is_final_legal_determination is False
    assert result.human_review.is_final_legal_determination is False
    assert result.snapshot_id == "snap:asof:2024-06-01"

    # Each finding exposes sources, assumptions, confidence, review boundary.
    for finding in result.findings:
        assert finding.is_pass is True
        assert finding.verdict is SemanticVerdict.VERIFIED_CONSISTENT
        assert finding.sources
        assert finding.assumptions
        assert finding.confidence is not None
        assert finding.human_review is not None
        assert finding.human_review.is_final_legal_determination is False
        assert finding.support_kind in (
            SupportKind.PROOF_RECEIPT,
            SupportKind.DETERMINISTIC_RULE,
        )
        if finding.support_kind is SupportKind.PROOF_RECEIPT:
            assert finding.proof_receipt is not None
            assert finding.proof_receipt.is_proved
        if finding.support_kind is SupportKind.DETERMINISTIC_RULE:
            assert any(r.applied for r in finding.deterministic_rule_receipts)

    # Round-trip stability.
    restored = result.from_dict(result.to_dict())
    assert restored.to_dict() == result.to_dict()
    public = result.public_projection()
    assert public["is_pass"] is True
    assert "findings" not in public
    assert STATUTE_112B not in canonical_json(public)


def test_pipeline_wrong_proposition_blocks_assurance() -> None:
    """Exact citation + wrong proposition from OA-style surface fails closed."""
    rec = _materialized_112b()
    support = _support_from_materialized(rec)
    unit = InstructionCheckUnit(
        unit_id="unit:wrong",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:wrong",
        instruction_surface_text=(
            f'Claims rejected under 35 U.S.C. § 112(b) because "{MISQUOTE}".'
        ),
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="prop:omit",
                predicate="specification_may_omit_claims",
                polarity=True,
            ),
        ),
        quoted_authority_text=MISQUOTE,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.8,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "integration_wrong_prop"},
    )
    result = verify_semantic_instruction_consistency(
        SemanticConsistencyInput(
            artifact_id="art:wrong",
            units=(unit,),
            classification=DisclosureClassification.PUBLIC_USER,
            as_of="2024-06-01",
            analysis_id="analysis:int:wrong",
            run_proofs=True,
        )
    )
    assert result.is_pass is False
    assert result.disposition is SemanticDisposition.FAILED
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.WRONG_PROPOSITION
    assert finding.human_review.requires_human_review is True
    assert finding.counterexamples or finding.unsupported_atoms
    assert (
        SemanticReasonCode.CITATION_EXACT_BUT_WRONG_PROPOSITION.value
        in finding.reason_codes
        or SemanticReasonCode.VERDICT_WRONG_PROPOSITION.value in finding.reason_codes
    )


def test_superseded_materialized_record_cannot_pass() -> None:
    rec = _materialized_112b(superseded=True, version="pre-aia")
    # filter_records_as_of may still return the record; support marks superseded.
    support = _support_from_materialized(rec)
    assert support.is_superseded or not support.is_controlling
    unit = InstructionCheckUnit(
        unit_id="unit:sup",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:sup",
        instruction_surface_text="Rejected under 35 U.S.C. § 112(b).",
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="prop:point",
                predicate="claims_must_particularly_point_out",
                polarity=True,
            ),
        ),
        quoted_authority_text=None,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.7,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:sup",
            units=(unit,),
            as_of="2024-06-01",
            analysis_id="analysis:int:sup",
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.is_pass is False
    assert result.findings[0].verdict is SemanticVerdict.SUPERSEDED_AUTHORITY


def test_recipe_matrix_fail_closed() -> None:
    """Compact matrix: wrong/superseded/conflict/missing never pass; ok does."""
    cases = [
        ("wrong", build_wrong_proposition_fixture, False, SemanticVerdict.WRONG_PROPOSITION),
        ("superseded", build_superseded_authority_fixture, False, SemanticVerdict.SUPERSEDED_AUTHORITY),
        ("conflict", build_conflicting_authority_fixture, False, SemanticVerdict.CONFLICTING_AUTHORITY),
        ("missing", build_missing_authority_fixture, False, SemanticVerdict.MISSING_AUTHORITY),
        ("ok_proof", lambda: build_verified_consistent_fixture(use_proof=True), True, SemanticVerdict.VERIFIED_CONSISTENT),
        ("ok_rule", lambda: build_verified_consistent_fixture(use_proof=False), True, SemanticVerdict.VERIFIED_CONSISTENT),
    ]
    proc = _processor()
    for name, builder, expect_pass, expect_verdict in cases:
        result = proc.verify(builder())
        assert result.is_pass is expect_pass, name
        assert result.findings[0].verdict is expect_verdict, name
        assert result.is_final_legal_determination is False, name
        assert result.findings[0].sources, name
        assert result.findings[0].confidence is not None, name
        assert result.findings[0].human_review is not None, name
        if expect_pass:
            assert result.findings[0].support_kind in (
                SupportKind.PROOF_RECEIPT,
                SupportKind.DETERMINISTIC_RULE,
            ), name
            assert result.documented_rules
            for key in result.documented_rules:
                assert key in DOCUMENTED_DETERMINISTIC_RULES


def test_proof_disproved_blocks_pass() -> None:
    """When claimed atoms conflict with authority support, cannot verify consistent via proof alone with wrong props."""
    # Use wrong-prop fixture — proof of unsupported atoms is incomplete/unknown,
    # and verdict is wrong_proposition before proof elevation.
    result = _processor().verify(build_wrong_proposition_fixture())
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict is SemanticVerdict.WRONG_PROPOSITION
    # Proof either skipped or not proved.
    if finding.proof_receipt is not None:
        assert finding.proof_receipt.outcome != ProofOutcome.PROVED.value


def test_as_of_excludes_later_authority() -> None:
    """Later-effective authority must not support an earlier as-of analysis."""
    future = build_binding_authority_support(
        support_id="auth:future",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt=STATUTE_112B,
        version="future-2030",
        proposition_predicates=("claims_must_particularly_point_out",),
        effective_start="2030-01-01",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:future",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:future",
        instruction_surface_text=(
            f'Rejected under 35 U.S.C. § 112(b): "{STATUTE_112B}".'
        ),
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="prop:point",
                predicate="claims_must_particularly_point_out",
                polarity=True,
            ),
        ),
        quoted_authority_text=STATUTE_112B,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(future,),
        legal_ir_mapping=None,
        confidence=0.8,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:future",
            units=(unit,),
            as_of="2024-06-01",
            analysis_id="analysis:future",
            classification=DisclosureClassification.PUBLIC_USER,
            run_proofs=True,
        )
    )
    # effective_start after as_of → treated as superseded / non-controlling.
    assert result.is_pass is False
    finding = result.findings[0]
    assert finding.verdict in (
        SemanticVerdict.SUPERSEDED_AUTHORITY,
        SemanticVerdict.UNSUPPORTED_INSTRUCTION,
        SemanticVerdict.REQUIRES_REVIEW,
        SemanticVerdict.MISSING_AUTHORITY,
    )


def test_required_act_and_exception_recorded() -> None:
    support = build_binding_authority_support(
        support_id="auth:act",
        citation_surface="37 C.F.R. § 1.111",
        citation_key="37-cfr-1.111",
        text_excerpt="Reply by applicant must fully respond.",
        version="2020",
        proposition_predicates=("fully_respond_to_office_action",),
        effective_start="2020-01-01",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:act",
        finding_kind=FindingKind.REQUIRED_ACT,
        instruction_span_id="span:act",
        instruction_surface_text=(
            'Applicant is required to fully respond under 37 C.F.R. § 1.111: '
            '"Reply by applicant must fully respond."'
        ),
        instruction_text_digest=None,
        legal_citations=("37 C.F.R. § 1.111",),
        citation_keys=("37-cfr-1.111",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="prop:respond",
                predicate="fully_respond_to_office_action",
                polarity=True,
            ),
        ),
        quoted_authority_text="Reply by applicant must fully respond.",
        deadline_basis=None,
        required_act="fully_respond_to_office_action",
        exceptions=("after_final_special_rules",),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.87,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={},
        force_skip_proof=True,
    )
    result = _processor().verify(
        SemanticConsistencyInput(
            artifact_id="art:act",
            units=(unit,),
            as_of="2024-06-01",
            analysis_id="analysis:act",
            classification=DisclosureClassification.PUBLIC_USER,
            run_proofs=False,
        )
    )
    finding = result.findings[0]
    assert finding.is_pass is True
    assert finding.finding_kind is FindingKind.REQUIRED_ACT
    assert any("exception:" in a for a in finding.assumptions)
    assert any(
        r.rule_key == "sic.required_act_support@1" and r.applied
        for r in finding.deterministic_rule_receipts
    )


def test_local_proof_kernel_available_for_assurance() -> None:
    """Dependency check: local bounded kernel is always available (PATLAW-126)."""
    from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
        AtomicLiteral,
        LogicFamily,
        PremiseCitation,
        ProofProblem,
        build_fixture_problem,
        expected_fixture_outcome,
        FixtureKind,
    )

    problem = build_fixture_problem(FixtureKind.SATISFIABLE)
    kernel = run_local_bounded_kernel(
        problem, timeout_ms=5_000, max_steps=10_000
    )
    assert kernel.outcome is expected_fixture_outcome(FixtureKind.SATISFIABLE)

    # Direct entailment used by semantic processor path.
    atom = AtomicLiteral(atom_id="atom:goal", polarity=True)
    p = ProofProblem(
        problem_id="sic:int:kernel",
        logic_family=LogicFamily.ENTAILMENT_CHECK,
        goal=atom,
        premises=(atom,),
        required_premise_ids=("atom:goal",),
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=(
            PremiseCitation(premise_id="atom:goal", kind="atom", digest=DIGEST_A),
        ),
        classification=DisclosureClassification.PUBLIC_USER,
    )
    k2 = run_local_bounded_kernel(p, timeout_ms=5_000, max_steps=10_000)
    assert k2.outcome is ProofOutcome.PROVED
