"""Unit tests for USPTO span/authority/fact → Legal IR boundary contracts (PATLAW-122)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    canonical_json as uspto_canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_contracts import (
    LEGAL_IR_CONTRACTS_INTERFACE,
    LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
    ActorRole,
    AssertionKind,
    AssumptionRef,
    AuthorityBinding,
    AuthorityRank,
    AuthorityResolutionState,
    CitationRef,
    ConditionRef,
    CounterEvidenceRef,
    DeadlineRef,
    DisclosureMetadata,
    ExceptionRef,
    LegalIRContractBundle,
    LegalIRContractError,
    LegalIRMapping,
    LegalModality,
    MappingReasonCode,
    MappingStatus,
    NormalizedProposition,
    ProofObligation,
    SourceIdentity,
    SubmissionFactRef,
    TemporalMetadata,
    TriStateOutcome,
    UsptoSpanRef,
    assertion_kind_may_be_proven,
    assertion_kinds,
    build_legal_ir_mapping,
    canonical_json,
    is_binding_authority_rank,
    round_trip_mapping,
    validate_mapping_candidate,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
PRIVATE_CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


def _source_identity(**overrides: object) -> SourceIdentity:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "artifact_id": "artifact:oa:1",
        "content_digest": DIGEST_A,
        "media_type": "application/pdf",
        "private_cid": PRIVATE_CID,
        "public_cid": None,
        "parser_version": "patlaw-122.v1",
        "source_receipt_id": "receipt:odp:1",
        "labels": {"doc_code": "CTFR"},
    }
    payload.update(overrides)
    return SourceIdentity(**payload)  # type: ignore[arg-type]


def _temporal(**overrides: object) -> TemporalMetadata:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "as_of": "2026-08-01",
        "effective_start": "2024-01-01",
        "effective_end": None,
        "retrieval_utc": "2026-08-03T12:00:00Z",
        "edition_or_version": "2024-11",
        "release_point": "rp-2024-11",
        "jurisdiction": "US",
        "labels": {},
    }
    payload.update(overrides)
    return TemporalMetadata(**payload)  # type: ignore[arg-type]


def _disclosure(
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_OFFICIAL,
    **overrides: object,
) -> DisclosureMetadata:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "classification": classification,
        "quarantine_required": False,
        "redaction_policy_id": None,
        "labels": {},
    }
    payload.update(overrides)
    return DisclosureMetadata(**payload)  # type: ignore[arg-type]


def _span(**overrides: object) -> UsptoSpanRef:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "span_id": "span:1",
        "artifact_id": "artifact:oa:1",
        "page_index": 0,
        "char_start": 10,
        "char_end": 40,
        "text_digest": DIGEST_B,
        "image_digest": None,
        "reading_order": 1,
        "classification": DisclosureClassification.PUBLIC_OFFICIAL,
    }
    payload.update(overrides)
    return UsptoSpanRef(**payload)  # type: ignore[arg-type]


def _authority(
    *,
    rank: AuthorityRank = AuthorityRank.OFFICIAL_BASE,
    state: AuthorityResolutionState = AuthorityResolutionState.RESOLVED,
    **overrides: object,
) -> AuthorityBinding:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "binding_id": "auth:1",
        "state": state,
        "authority_rank": rank,
        "temporal": _temporal(),
        "citation_ids": ("cite:112b",),
        "selected_node_ids": ("node:35usc112b",),
        "selected_versions": ("2024-11",),
        "reasons": (),
    }
    payload.update(overrides)
    return AuthorityBinding(**payload)  # type: ignore[arg-type]


def _proposition(
    *,
    kind: AssertionKind = AssertionKind.DETERMINISTIC_NORMALIZATION,
    **overrides: object,
) -> NormalizedProposition:
    payload: dict[str, object] = {
        "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        "proposition_id": "prop:1",
        "assertion_kind": kind,
        "modality": LegalModality.OBLIGATION,
        "actor_role": ActorRole.APPLICANT,
        "predicate": "amend_claim",
        "subject": "claim:1",
        "object_ref": None,
        "condition_ids": (),
        "exception_ids": (),
        "deadline_ids": (),
        "citation_ids": ("cite:112b",),
        "source_span_ids": ("span:1",),
        "normalizer_id": "norm:uspto-req",
        "normalizer_version": "1.0.0",
        "proposition_digest": DIGEST_C,
        "labels": {},
    }
    payload.update(overrides)
    return NormalizedProposition(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema / enumeration contracts
# ---------------------------------------------------------------------------


def test_schema_version_and_interface_pinned() -> None:
    assert LEGAL_IR_CONTRACTS_SCHEMA_VERSION == "uspto.legal-ir-contracts.v1"
    assert LEGAL_IR_CONTRACTS_INTERFACE == "UsptoLegalIRContracts@1"


def test_assertion_kinds_are_closed_and_distinct() -> None:
    kinds = assertion_kinds()
    assert kinds == (
        "quoted_text",
        "deterministic_normalization",
        "model_candidate",
        "human_finding",
        "proven_conclusion",
    )
    assert set(kinds) == {k.value for k in AssertionKind}
    assert not assertion_kind_may_be_proven(AssertionKind.QUOTED_TEXT)
    assert not assertion_kind_may_be_proven(AssertionKind.MODEL_CANDIDATE)
    assert not assertion_kind_may_be_proven(AssertionKind.HUMAN_FINDING)
    assert not assertion_kind_may_be_proven(AssertionKind.DETERMINISTIC_NORMALIZATION)
    assert assertion_kind_may_be_proven(AssertionKind.PROVEN_CONCLUSION)


def test_authority_rank_binding_policy() -> None:
    assert is_binding_authority_rank(AuthorityRank.OFFICIAL_BASE)
    assert is_binding_authority_rank(AuthorityRank.OFFICIAL_CHANGE)
    assert not is_binding_authority_rank(AuthorityRank.GUIDANCE)
    assert not is_binding_authority_rank(AuthorityRank.CANDIDATE)
    assert not is_binding_authority_rank(AuthorityRank.UNOFFICIAL_CURRENT)
    assert not is_binding_authority_rank(AuthorityRank.UNKNOWN)


def test_tri_state_and_mapping_status_enumerations() -> None:
    assert {s.value for s in MappingStatus} == {
        "accepted",
        "rejected",
        "unknown",
        "ambiguous",
    }
    assert {s.value for s in TriStateOutcome} == {
        "satisfied",
        "unsatisfied",
        "unknown",
    }


# ---------------------------------------------------------------------------
# Round trips preserve source identity and temporal/disclosure metadata
# ---------------------------------------------------------------------------


def test_source_identity_round_trip_preserves_fields() -> None:
    record = _source_identity()
    _assert_round_trip(record)
    restored = SourceIdentity.from_dict(record.to_dict())
    assert restored.artifact_id == "artifact:oa:1"
    assert restored.content_digest == DIGEST_A
    assert restored.private_cid == PRIVATE_CID
    assert restored.source_receipt_id == "receipt:odp:1"
    assert restored.labels["doc_code"] == "CTFR"


def test_temporal_and_disclosure_round_trip() -> None:
    temporal = _temporal(
        as_of="2026-07-15T00:00:00Z",
        effective_start="2023-06-01",
        effective_end="2027-06-01",
        edition_or_version="37-cfr-2024",
    )
    disclosure = _disclosure(
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        quarantine_required=True,
        redaction_policy_id="policy:redact:1",
    )
    _assert_round_trip(temporal)
    _assert_round_trip(disclosure)
    assert temporal.edition_or_version == "37-cfr-2024"
    assert disclosure.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
    assert disclosure.quarantine_required is True


def test_unknown_disclosure_forces_quarantine() -> None:
    disclosure = _disclosure(
        DisclosureClassification.UNKNOWN,
        quarantine_required=False,
    )
    assert disclosure.quarantine_required is True


def test_span_citation_authority_proposition_round_trips() -> None:
    _assert_round_trip(_span())
    _assert_round_trip(
        CitationRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            citation_id="cite:112b",
            surface="35 U.S.C. 112(b)",
            citation_key="35usc112b",
            authority_rank=AuthorityRank.OFFICIAL_BASE,
            family="usc",
            edition_or_version="2024",
            node_id="node:35usc112b",
            quote_text_digest=DIGEST_B,
            labels={},
        )
    )
    _assert_round_trip(_authority())
    _assert_round_trip(_proposition())


def test_fact_condition_exception_deadline_assumption_counter_round_trips() -> None:
    _assert_round_trip(
        SubmissionFactRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            fact_id="fact:1",
            fact_type="claim_limitation_present",
            evidence_span_id="span:2",
            affected_claims=("1",),
            version="1",
            extraction_status="ok",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
            labels={},
        )
    )
    _assert_round_trip(
        ConditionRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            condition_id="cond:1",
            description_digest=DIGEST_A,
            source_span_ids=("span:1",),
            resolved=True,
            labels={},
        )
    )
    _assert_round_trip(
        ExceptionRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            exception_id="exc:1",
            description_digest=DIGEST_B,
            source_span_ids=("span:3",),
            labels={},
        )
    )
    _assert_round_trip(
        DeadlineRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            deadline_id="dl:1",
            candidate_utc="2026-11-03T04:59:59Z",
            rule_chain=("37 CFR 1.134",),
            uncertainty=None,
            source_span_ids=("span:1",),
            labels={},
        )
    )
    _assert_round_trip(
        AssumptionRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            assumption_id="asm:1",
            description_digest=DIGEST_C,
            asserted_by=ActorRole.SYSTEM,
            labels={},
        )
    )
    _assert_round_trip(
        CounterEvidenceRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            counter_id="ctr:1",
            span_ids=("span:9",),
            fact_ids=(),
            reason_codes=("contradiction",),
            labels={},
        )
    )
    _assert_round_trip(
        ProofObligation(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            obligation_id="obl:1",
            proposition_id="prop:1",
            required_outcome=TriStateOutcome.SATISFIED,
            premise_proposition_ids=("prop:pre:1",),
            premise_fact_ids=("fact:1",),
            assumption_ids=("asm:1",),
            proof_receipt_id="proof:1",
            labels={},
        )
    )


def test_full_mapping_round_trip_preserves_identity_and_metadata() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:quoted:1",
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        citations=(
            CitationRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                citation_id="cite:112b",
                surface="35 U.S.C. 112(b)",
                citation_key="35usc112b",
                authority_rank=AuthorityRank.OFFICIAL_BASE,
                family="usc",
                edition_or_version="2024",
                node_id="node:35usc112b",
                quote_text_digest=DIGEST_B,
                labels={},
            ),
        ),
        authority=_authority(),
        desired_outcome=TriStateOutcome.UNKNOWN,
        confidence=0.95,
        labels={"stage": "extraction"},
    )
    assert mapping.status is MappingStatus.ACCEPTED
    restored = round_trip_mapping(mapping)
    assert restored.source_identity == mapping.source_identity
    assert restored.temporal == mapping.temporal
    assert restored.disclosure == mapping.disclosure
    assert restored.source_spans == mapping.source_spans
    assert restored.citations[0].surface == "35 U.S.C. 112(b)"
    assert restored.labels["stage"] == "extraction"
    # Shared USPTO canonical_json is byte-compatible for nested dicts.
    assert uspto_canonical_json(mapping.to_dict()) == canonical_json(mapping.to_dict())


def test_bundle_round_trip_and_duplicate_mapping_id_rejected() -> None:
    m1 = build_legal_ir_mapping(
        mapping_id="map:1",
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
    )
    m2 = build_legal_ir_mapping(
        mapping_id="map:2",
        assertion_kind=AssertionKind.MODEL_CANDIDATE,
        source_identity=_source_identity(artifact_id="artifact:oa:2"),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(span_id="span:2"),),
        desired_outcome=TriStateOutcome.UNKNOWN,
    )
    bundle = LegalIRContractBundle(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        bundle_id="bundle:1",
        mappings=(m1, m2),
        parser_version="patlaw-122.v1",
        ruleset_version="rules:1",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        labels={},
    )
    _assert_round_trip(bundle)

    with pytest.raises(LegalIRContractError) as exc:
        LegalIRContractBundle(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            bundle_id="bundle:dup",
            mappings=(m1, m1),
            parser_version="patlaw-122.v1",
            ruleset_version="rules:1",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            labels={},
        )
    assert exc.value.code == MappingReasonCode.DUPLICATE_MAPPING_ID.value


# ---------------------------------------------------------------------------
# Invalid / ambiguous mappings rejected or marked unknown
# ---------------------------------------------------------------------------


def test_missing_source_span_for_quoted_text_is_rejected() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(),
    )
    assert status is MappingStatus.REJECTED or status is MappingStatus.UNKNOWN
    codes = {i.code for i in issues}
    assert MappingReasonCode.MISSING_SOURCE_SPAN in codes or (
        MappingReasonCode.QUOTE_DIGEST_REQUIRED in codes
    )
    assert outcome is TriStateOutcome.UNKNOWN


def test_quoted_text_without_digest_rejected() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(text_digest=None),),
    )
    assert status is MappingStatus.REJECTED
    assert any(i.code is MappingReasonCode.QUOTE_DIGEST_REQUIRED for i in issues)
    assert outcome is TriStateOutcome.UNKNOWN


def test_missing_source_identity_rejected() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=None,
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
    )
    assert status is MappingStatus.REJECTED
    assert any(i.code is MappingReasonCode.MISSING_SOURCE_IDENTITY for i in issues)
    assert outcome is TriStateOutcome.UNKNOWN


def test_ambiguous_authority_marked_ambiguous() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        authority=_authority(state=AuthorityResolutionState.AMBIGUOUS),
        proposition=_proposition(),
    )
    assert status is MappingStatus.AMBIGUOUS
    assert outcome is TriStateOutcome.UNKNOWN
    assert any(i.code is MappingReasonCode.AMBIGUOUS_AUTHORITY for i in issues)


def test_unresolved_authority_marked_unknown() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        authority=_authority(state=AuthorityResolutionState.UNRESOLVED),
        proposition=_proposition(),
    )
    assert status is MappingStatus.UNKNOWN
    assert outcome is TriStateOutcome.UNKNOWN
    assert any(i.code is MappingReasonCode.UNRESOLVED_AUTHORITY for i in issues)


def test_empty_temporal_metadata_marked_unknown() -> None:
    empty_temporal = TemporalMetadata(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        as_of=None,
        effective_start=None,
        effective_end=None,
        retrieval_utc=None,
        edition_or_version=None,
        release_point=None,
        jurisdiction=None,
        labels={},
    )
    assert empty_temporal.is_empty
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=empty_temporal,
        disclosure=_disclosure(),
        source_spans=(_span(),),
    )
    assert status is MappingStatus.UNKNOWN
    assert any(i.code is MappingReasonCode.MISSING_TEMPORAL_METADATA for i in issues)
    assert outcome is TriStateOutcome.UNKNOWN


def test_hard_coded_latest_edition_rejected() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        _temporal(edition_or_version="latest")
    assert exc.value.code == MappingReasonCode.MISSING_TEMPORAL_METADATA.value


def test_guidance_not_binding_for_proven_conclusion() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.PROVEN_CONCLUSION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        authority=_authority(rank=AuthorityRank.GUIDANCE),
        proof_receipt_id="proof:1",
        desired_outcome=TriStateOutcome.SATISFIED,
    )
    assert status is MappingStatus.REJECTED
    assert any(i.code is MappingReasonCode.GUIDANCE_NOT_BINDING for i in issues)
    assert outcome is TriStateOutcome.UNKNOWN


def test_model_candidate_cannot_be_satisfied() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.MODEL_CANDIDATE,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        desired_outcome=TriStateOutcome.SATISFIED,
    )
    assert status is MappingStatus.REJECTED
    assert any(i.code is MappingReasonCode.MODEL_CANDIDATE_NOT_PROVEN for i in issues)
    assert outcome is TriStateOutcome.UNKNOWN


def test_proven_conclusion_without_proof_receipt_rejected() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.PROVEN_CONCLUSION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        authority=_authority(),
        proof_receipt_id=None,
        desired_outcome=TriStateOutcome.SATISFIED,
    )
    assert status is MappingStatus.REJECTED
    assert any(i.code is MappingReasonCode.PROOF_RECEIPT_MISSING for i in issues)


def test_human_finding_requires_reviewer() -> None:
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=AssertionKind.HUMAN_FINDING,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        reviewer_id=None,
    )
    assert status is MappingStatus.REJECTED
    assert any(i.code is MappingReasonCode.REVIEWER_IDENTITY_REQUIRED for i in issues)


def test_build_mapping_promotes_deadline_ambiguity() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:dl:amb",
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        deadlines=(
            DeadlineRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                deadline_id="dl:amb",
                candidate_utc=None,
                rule_chain=("37 CFR 1.134",),
                uncertainty="conflicting_mail_dates",
                source_span_ids=("span:1",),
                labels={},
            ),
        ),
    )
    assert mapping.status is MappingStatus.AMBIGUOUS
    assert mapping.outcome is TriStateOutcome.UNKNOWN
    assert MappingReasonCode.DEADLINE_AMBIGUOUS.value in mapping.reason_codes


def test_unresolved_condition_blocks_satisfied() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:cond:unres",
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        authority=_authority(),
        conditions=(
            ConditionRef(
                schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                condition_id="cond:unres",
                description_digest=DIGEST_A,
                source_span_ids=("span:1",),
                resolved=False,
                labels={},
            ),
        ),
        desired_outcome=TriStateOutcome.SATISFIED,
    )
    # Quoted text can be accepted, but satisfied is forced to unknown when
    # conditions remain unresolved.
    assert mapping.outcome is TriStateOutcome.UNKNOWN
    assert MappingReasonCode.CONDITION_UNRESOLVED.value in mapping.reason_codes


def test_accepted_proven_conclusion_requires_receipt_invariant() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        LegalIRMapping(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            mapping_id="map:bad-proof",
            assertion_kind=AssertionKind.PROVEN_CONCLUSION,
            status=MappingStatus.ACCEPTED,
            outcome=TriStateOutcome.SATISFIED,
            source_identity=_source_identity(),
            temporal=_temporal(),
            disclosure=_disclosure(),
            source_spans=(_span(),),
            citations=(),
            authority=_authority(),
            proposition=_proposition(kind=AssertionKind.PROVEN_CONCLUSION),
            facts=(),
            conditions=(),
            exceptions=(),
            deadlines=(),
            proof_obligation=None,
            assumptions=(),
            counter_evidence=(),
            reason_codes=(),
            reviewer_id=None,
            proof_receipt_id=None,
            confidence=1.0,
            labels={},
        )
    assert exc.value.code == MappingReasonCode.PROOF_RECEIPT_REQUIRED.value


def test_satisfied_cannot_rest_on_guidance_authority() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        LegalIRMapping(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            mapping_id="map:bad-guidance",
            assertion_kind=AssertionKind.QUOTED_TEXT,
            status=MappingStatus.ACCEPTED,
            outcome=TriStateOutcome.SATISFIED,
            source_identity=_source_identity(),
            temporal=_temporal(),
            disclosure=_disclosure(),
            source_spans=(_span(),),
            citations=(),
            authority=_authority(rank=AuthorityRank.GUIDANCE),
            proposition=None,
            facts=(),
            conditions=(),
            exceptions=(),
            deadlines=(),
            proof_obligation=None,
            assumptions=(),
            counter_evidence=(),
            reason_codes=(),
            reviewer_id=None,
            proof_receipt_id=None,
            confidence=None,
            labels={},
        )
    assert exc.value.code == MappingReasonCode.GUIDANCE_NOT_BINDING.value


def test_submission_fact_cannot_be_proven_conclusion() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        SubmissionFactRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            fact_id="fact:bad",
            fact_type="claim_present",
            evidence_span_id="span:1",
            affected_claims=("1",),
            version="1",
            extraction_status="ok",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            assertion_kind=AssertionKind.PROVEN_CONCLUSION,
            labels={},
        )
    assert exc.value.code == MappingReasonCode.ASSERTION_KIND_MISMATCH.value


def test_deterministic_normalization_requires_normalizer_identity() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        NormalizedProposition(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            proposition_id="prop:bad",
            assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
            modality=LegalModality.OBLIGATION,
            actor_role=ActorRole.APPLICANT,
            predicate="file_response",
            subject=None,
            object_ref=None,
            condition_ids=(),
            exception_ids=(),
            deadline_ids=(),
            citation_ids=(),
            source_span_ids=("span:1",),
            normalizer_id=None,
            normalizer_version=None,
            proposition_digest=DIGEST_C,
            labels={},
        )
    assert exc.value.code == MappingReasonCode.NORMALIZER_IDENTITY_REQUIRED.value


def test_unknown_fields_rejected_on_from_dict() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        SourceIdentity.from_dict(
            {
                "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                "artifact_id": "artifact:1",
                "content_digest": DIGEST_A,
                "media_type": None,
                "private_cid": None,
                "public_cid": None,
                "parser_version": None,
                "source_receipt_id": None,
                "labels": {},
                "extra_field": "nope",
            }
        )
    assert exc.value.code == MappingReasonCode.UNKNOWN_FIELDS.value


def test_schema_version_mismatch_rejected() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        SourceIdentity(
            schema_version="uspto.legal-ir-contracts.v0",
            artifact_id="artifact:1",
            content_digest=DIGEST_A,
            media_type=None,
            private_cid=None,
            public_cid=None,
            parser_version=None,
            source_receipt_id=None,
            labels={},
        )
    assert exc.value.code == MappingReasonCode.SCHEMA_VERSION_MISMATCH.value


def test_char_end_before_start_rejected() -> None:
    with pytest.raises(ValueError):
        _span(char_start=50, char_end=10)


def test_counter_evidence_requires_span_or_fact() -> None:
    with pytest.raises(ValueError):
        CounterEvidenceRef(
            schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
            counter_id="ctr:empty",
            span_ids=(),
            fact_ids=(),
            reason_codes=(),
            labels={},
        )


# ---------------------------------------------------------------------------
# Assertion-kind discrimination end-to-end via build_legal_ir_mapping
# ---------------------------------------------------------------------------


def test_build_quoted_text_accepted() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:qt",
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
    )
    assert mapping.status is MappingStatus.ACCEPTED
    assert mapping.assertion_kind is AssertionKind.QUOTED_TEXT
    assert MappingReasonCode.VALID_MAPPING.value in mapping.reason_codes


def test_build_deterministic_normalization_accepted() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:norm",
        assertion_kind=AssertionKind.DETERMINISTIC_NORMALIZATION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        proposition=_proposition(),
        authority=_authority(),
    )
    assert mapping.status is MappingStatus.ACCEPTED
    assert mapping.proposition is not None
    assert mapping.proposition.normalizer_id == "norm:uspto-req"


def test_build_model_candidate_accepted_as_unknown_outcome() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:model",
        assertion_kind=AssertionKind.MODEL_CANDIDATE,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        desired_outcome=TriStateOutcome.UNKNOWN,
    )
    assert mapping.status is MappingStatus.ACCEPTED
    assert mapping.assertion_kind is AssertionKind.MODEL_CANDIDATE
    assert mapping.outcome is TriStateOutcome.UNKNOWN


def test_build_human_finding_accepted_with_reviewer() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:human",
        assertion_kind=AssertionKind.HUMAN_FINDING,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        reviewer_id="reviewer:alice",
        desired_outcome=TriStateOutcome.UNSATISFIED,
    )
    assert mapping.status is MappingStatus.ACCEPTED
    assert mapping.reviewer_id == "reviewer:alice"
    assert mapping.outcome is TriStateOutcome.UNSATISFIED


def test_build_proven_conclusion_accepted_with_receipt_and_binding_authority() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:proven",
        assertion_kind=AssertionKind.PROVEN_CONCLUSION,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(),
        source_spans=(_span(),),
        authority=_authority(rank=AuthorityRank.OFFICIAL_BASE),
        proposition=_proposition(kind=AssertionKind.PROVEN_CONCLUSION),
        proof_receipt_id="proof:receipt:1",
        desired_outcome=TriStateOutcome.SATISFIED,
        confidence=1.0,
    )
    assert mapping.status is MappingStatus.ACCEPTED
    assert mapping.assertion_kind is AssertionKind.PROVEN_CONCLUSION
    assert mapping.outcome is TriStateOutcome.SATISFIED
    assert mapping.proof_receipt_id == "proof:receipt:1"
    assert mapping.authority is not None
    assert mapping.authority.is_binding


def test_quarantine_disclosure_forces_unknown_outcome() -> None:
    mapping = build_legal_ir_mapping(
        mapping_id="map:quar",
        assertion_kind=AssertionKind.QUOTED_TEXT,
        source_identity=_source_identity(),
        temporal=_temporal(),
        disclosure=_disclosure(DisclosureClassification.UNKNOWN),
        source_spans=(_span(classification=DisclosureClassification.UNKNOWN),),
        desired_outcome=TriStateOutcome.SATISFIED,
    )
    assert mapping.status is MappingStatus.UNKNOWN
    assert mapping.outcome is TriStateOutcome.UNKNOWN
    assert MappingReasonCode.DISCLOSURE_QUARANTINE.value in mapping.reason_codes


def test_legal_modality_and_actor_enumerations() -> None:
    assert LegalModality.OBLIGATION.value == "obligation"
    assert LegalModality.PROHIBITION.value == "prohibition"
    assert ActorRole.EXAMINER.value == "examiner"
    assert ActorRole.APPLICANT.value == "applicant"


def test_invalid_enum_raises_contract_error() -> None:
    with pytest.raises(LegalIRContractError) as exc:
        _coerce = AuthorityRank  # silence linter about unused
        AuthorityBinding.from_dict(
            {
                "schema_version": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                "binding_id": "auth:x",
                "state": "not-a-real-state",
                "authority_rank": "official-base",
                "temporal": _temporal().to_dict(),
                "citation_ids": [],
                "selected_node_ids": [],
                "selected_versions": [],
                "reasons": [],
            }
        )
    assert exc.value.code == MappingReasonCode.INVALID_ENUM.value
    del _coerce


def test_audit_dict_never_includes_body_text() -> None:
    err = LegalIRContractError("fail closed", code=MappingReasonCode.MISSING_SOURCE_SPAN)
    audit = err.audit_dict()
    assert set(audit.keys()) == {"code", "message"}
    assert "body" not in audit["message"].lower()
