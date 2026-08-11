"""Deterministic round-trip and classification tests for USPTO contracts."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
    build_artifact_manifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AnalysisBundle,
    ApplicationIdentity,
    AssessmentStatus,
    AuthorityRelation,
    CandidateDeadline,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    GovernmentRequirement,
    MatterEvent,
    MatterEventKind,
    RequirementAssessment,
    ReviewState,
    SourceReceipt,
    SubmissionFact,
    canonical_json,
    is_private_classification,
    is_public_classification,
    most_restrictive_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    PRIVACY_POLICY_SCHEMA_VERSION,
    ContentKind,
    PublicSink,
    QuarantineRecord,
    UsptoPrivacyPolicy,
    VaultKind,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
PRIVATE_CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
PUBLIC_CID = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    # Encoding itself is byte-stable across dumps.
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


def test_schema_versions_are_pinned() -> None:
    assert CONTRACTS_SCHEMA_VERSION == "uspto.contracts.v1"
    assert ARTIFACT_MANIFEST_SCHEMA_VERSION == "uspto.artifact-manifest.v1"
    assert PRIVACY_POLICY_SCHEMA_VERSION == "uspto.privacy.v1"


def test_disclosure_classification_enumeration() -> None:
    values = {c.value for c in DisclosureClassification}
    assert values == {
        "public_official",
        "public_user",
        "confidential_application",
        "privileged_work_product",
        "restricted_export_review",
        "credential_or_payment",
        "unknown",
    }
    assert is_public_classification(DisclosureClassification.PUBLIC_OFFICIAL)
    assert is_public_classification(DisclosureClassification.PUBLIC_USER)
    assert is_private_classification(DisclosureClassification.CONFIDENTIAL_APPLICATION)
    assert is_private_classification(DisclosureClassification.PRIVILEGED_WORK_PRODUCT)
    assert is_private_classification(DisclosureClassification.RESTRICTED_EXPORT_REVIEW)
    assert is_private_classification(DisclosureClassification.CREDENTIAL_OR_PAYMENT)
    assert requires_quarantine(DisclosureClassification.UNKNOWN)
    assert not requires_quarantine(DisclosureClassification.PUBLIC_OFFICIAL)


def test_most_restrictive_classification() -> None:
    assert (
        most_restrictive_classification(
            [
                DisclosureClassification.PUBLIC_OFFICIAL,
                DisclosureClassification.CONFIDENTIAL_APPLICATION,
            ]
        )
        is DisclosureClassification.CONFIDENTIAL_APPLICATION
    )
    assert (
        most_restrictive_classification([]) is DisclosureClassification.UNKNOWN
    )
    assert (
        most_restrictive_classification(
            [
                DisclosureClassification.PUBLIC_USER,
                DisclosureClassification.UNKNOWN,
            ]
        )
        is DisclosureClassification.UNKNOWN
    )
    assert (
        most_restrictive_classification(
            [
                DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
                DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            ]
        )
        is DisclosureClassification.CREDENTIAL_OR_PAYMENT
    )


def test_application_identity_round_trip() -> None:
    record = ApplicationIdentity(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        application_number="16/123,456",
        publication_number=None,
        patent_number=None,
        source="odp_patent_file_wrapper",
        confidence=0.91,
        unresolved_ambiguity=False,
        notes=("normalized",),
    )
    _assert_round_trip(record)


def test_source_receipt_round_trip() -> None:
    record = SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id="receipt:odp:1",
        endpoint="https://data.uspto.gov/apis/patent-file-wrapper/application-data",
        retrieval_utc="2026-08-03T12:00:00Z",
        response_status=200,
        upstream_id="app-16123456",
        last_modified="2026-08-01T00:00:00Z",
        request_digest=DIGEST_A,
        response_digest=DIGEST_B,
        cache_hit=False,
        retry_count=0,
        metadata={"api_version": "v1"},
    )
    _assert_round_trip(record)


def test_extracted_span_round_trip() -> None:
    record = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:1",
        artifact_id="artifact:oa:1",
        page_index=0,
        char_start=10,
        char_end=40,
        bbox=(1.0, 2.0, 3.0, 4.0),
        origin=ExtractionOrigin.MERGED,
        reading_order=1,
        confidence=0.88,
        text_digest=DIGEST_A,
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    _assert_round_trip(record)


def test_government_requirement_round_trip() -> None:
    record = GovernmentRequirement(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        requirement_id="req:112b:1",
        instruction_text_digest=DIGEST_A,
        source_span_id="span:1",
        requirement_type="enablement",
        affected_claims=("1", "2"),
        legal_citations=("35 U.S.C. 112(b)",),
        applicability_conditions=("independent_claim",),
        proposed_date_rule="mail_date_plus_3_months",
        exceptions=(),
        parser_confidence=0.7,
        review_state=ReviewState.PENDING,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    _assert_round_trip(record)


def test_submission_fact_round_trip() -> None:
    record = SubmissionFact(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        fact_id="fact:1",
        evidence_span_id="span:2",
        fact_type="claim_limitation_present",
        affected_claims=("1",),
        version="1",
        extraction_status="ok",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    _assert_round_trip(record)


def test_requirement_assessment_round_trip_and_unknown_human_action() -> None:
    record = RequirementAssessment(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        assessment_id="assess:1",
        requirement_id="req:112b:1",
        status=AssessmentStatus.UNKNOWN,
        evidence_span_ids=(),
        counter_evidence_span_ids=(),
        authority_snapshot_id=None,
        proof_result=None,
        confidence=None,
        reasons=("missing_evidence",),
        required_human_action=None,
        classification=DisclosureClassification.UNKNOWN,
    )
    assert record.required_human_action == "review_unknown_assessment"
    _assert_round_trip(record)


def test_candidate_deadline_round_trip() -> None:
    record = CandidateDeadline(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        deadline_id="deadline:1",
        event_basis="office_action_mailing",
        rule_chain=("37 CFR 1.134", "MPEP 710"),
        calendar="US-federal",
        time_zone="America/New_York",
        entity_status_assumption="small",
        extension_assumption="none",
        candidate_utc="2026-11-03T04:59:59Z",
        uncertainty="rule_chain_requires_review",
        reviewer_confirmation=ReviewState.REQUIRED,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    _assert_round_trip(record)


def test_matter_event_round_trip() -> None:
    record = MatterEvent(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        event_id="event:1",
        matter_id="matter:16-123456",
        kind=MatterEventKind.DOCUMENT,
        event_utc="2026-08-01T15:00:00Z",
        source_receipt_id="receipt:odp:1",
        description_digest=DIGEST_A,
        related_artifact_ids=("artifact:oa:1",),
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        metadata={"doc_code": "CTFR"},
    )
    _assert_round_trip(record)


def test_analysis_bundle_round_trip_and_unknown_forces_review() -> None:
    record = AnalysisBundle(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        bundle_id="bundle:1",
        input_artifact_ids=("artifact:oa:1",),
        output_artifact_ids=("artifact:assessment:1",),
        warning_codes=("low_ocr_confidence",),
        unsupported_checks=("foreign_priority_chain",),
        model_versions={"extractor": "v1"},
        ruleset_versions={"mpep": "2024-11"},
        validation_receipt_ids=("receipt:val:1",),
        classification=DisclosureClassification.UNKNOWN,
        review_state=ReviewState.NOT_REQUIRED,
    )
    assert record.review_state is ReviewState.REQUIRED
    _assert_round_trip(record)


def test_artifact_manifest_public_round_trip() -> None:
    manifest = ArtifactManifest(
        schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
        artifact_id="artifact:public:1",
        sha256=DIGEST_A,
        size_bytes=1024,
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
        media_type="application/pdf",
        media_signature="pdf-1.7",
        private_cid=None,
        public_cid=PUBLIC_CID,
        encryption_namespace=None,
        matter_id="matter:16-123456",
        source_receipt_id="receipt:odp:1",
        authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
        parent_artifact_ids=(),
        parser_versions={"pdf": "1.0"},
        labels={"kind": "office_action"},
    )
    _assert_round_trip(manifest)
    assert "public_cid" in manifest.public_projection()


def test_artifact_manifest_private_requires_encryption_namespace() -> None:
    with pytest.raises(ValueError, match="encryption_namespace"):
        ArtifactManifest(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            artifact_id="artifact:private:1",
            sha256=DIGEST_A,
            size_bytes=2048,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            media_type="application/pdf",
            media_signature=None,
            private_cid=PRIVATE_CID,
            public_cid=None,
            encryption_namespace=None,
            matter_id="matter:16-123456",
            source_receipt_id=None,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            parent_artifact_ids=(),
            parser_versions={},
            labels={},
        )


def test_artifact_manifest_private_forbids_public_cid() -> None:
    with pytest.raises(ValueError, match="public_cid"):
        ArtifactManifest(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            artifact_id="artifact:private:2",
            sha256=DIGEST_A,
            size_bytes=2048,
            classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
            media_type="application/pdf",
            media_signature=None,
            private_cid=PRIVATE_CID,
            public_cid=PUBLIC_CID,
            encryption_namespace="private://tenant/demo",
            matter_id=None,
            source_receipt_id=None,
            authority_relation=AuthorityRelation.DERIVATIVE,
            parent_artifact_ids=("artifact:private:1",),
            parser_versions={},
            labels={},
        )


def test_build_artifact_manifest_unknown_quarantines_with_namespace() -> None:
    manifest = build_artifact_manifest(
        artifact_id="artifact:unknown:1",
        sha256=DIGEST_B,
        size_bytes=10,
        classification="not-a-real-class",
        private_cid=PRIVATE_CID,
    )
    assert manifest.classification is DisclosureClassification.UNKNOWN
    assert manifest.is_quarantined
    assert manifest.encryption_namespace is not None
    assert manifest.public_cid is None
    _assert_round_trip(manifest)


def test_build_artifact_manifest_rejects_credentials() -> None:
    from ipfs_datasets_py.processors.domains.uspto.privacy import PrivacyBoundaryError

    with pytest.raises(PrivacyBoundaryError):
        build_artifact_manifest(
            artifact_id="artifact:cred:1",
            sha256=DIGEST_A,
            size_bytes=1,
            classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
        )


def test_privacy_policy_round_trip() -> None:
    policy = UsptoPrivacyPolicy(
        allow_external_models_for_private=False,
        allow_public_cid_for_private=False,
    )
    restored = UsptoPrivacyPolicy.from_dict(policy.to_dict())
    assert restored.to_dict() == policy.to_dict()
    assert canonical_json(restored.to_dict()) == canonical_json(policy.to_dict())


def test_quarantine_record_round_trip() -> None:
    policy = UsptoPrivacyPolicy()
    record = policy.quarantine(
        quarantine_id="q:1",
        classification=DisclosureClassification.UNKNOWN,
        reason_codes=("unknown_classification",),
        related_artifact_ids=("artifact:unknown:1",),
        content_kinds=(ContentKind.DOCUMENT_BYTES,),
    )
    assert isinstance(record, QuarantineRecord)
    restored = QuarantineRecord.from_dict(record.to_dict())
    assert restored.to_dict() == record.to_dict()


def test_reject_unknown_fields_on_contracts() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        ApplicationIdentity.from_dict(
            {
                "schema_version": CONTRACTS_SCHEMA_VERSION,
                "application_number": "16/1",
                "publication_number": None,
                "patent_number": None,
                "source": "test",
                "confidence": None,
                "unresolved_ambiguity": False,
                "notes": [],
                "extra_field": "nope",
            }
        )


def test_classify_before_dispatch_inherits_most_restrictive() -> None:
    policy = UsptoPrivacyPolicy()
    assert (
        policy.classify_before_dispatch(
            DisclosureClassification.PUBLIC_OFFICIAL,
            source_classifications=(
                DisclosureClassification.CONFIDENTIAL_APPLICATION,
            ),
        )
        is DisclosureClassification.CONFIDENTIAL_APPLICATION
    )
    assert (
        policy.classify_before_dispatch(None) is DisclosureClassification.UNKNOWN
    )


@pytest.mark.parametrize(
    "sink",
    list(PublicSink),
)
def test_unknown_classification_denies_every_public_sink(sink: PublicSink) -> None:
    policy = UsptoPrivacyPolicy()
    for kind in (
        ContentKind.DOCUMENT_BYTES,
        ContentKind.EXTRACTED_TEXT,
        ContentKind.EMBEDDING,
        ContentKind.CONTENT_IDENTIFIER,
    ):
        decision = policy.evaluate_sink(
            DisclosureClassification.UNKNOWN, sink, kind
        )
        assert decision.allowed is False
        assert decision.quarantined is True


def test_vault_kinds_are_separated() -> None:
    assert VaultKind.CREDENTIALS.value == "credentials_vault"
    assert VaultKind.DOCUMENT.value == "document_vault"
