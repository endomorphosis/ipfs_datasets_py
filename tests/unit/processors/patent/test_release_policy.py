"""Unit tests for JusticeDAO patent/legal release policy gates."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib

import pytest

from ipfs_datasets_py.processors.domains.patent.release_policy import (
    ARTIFACT_KINDS,
    RELEASE_POLICY_SHA256,
    RELEASE_POLICY_VERSION,
    ArtifactKind,
    ClassificationStatus,
    PatentReleasePolicy,
    PrivacyRejectedError,
    PublicationRejectedError,
    ReleaseCandidate,
    ReleasePolicyError,
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
    assert_public_batch,
    evaluate_batch_admission,
    evaluate_record_admission,
    is_private_classification,
    is_public_classification,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lineage(**changes: object) -> SourceLineage:
    base = {
        "source_id": "govinfo/uscode",
        "source_revision": "2024-title-35",
        "source_uri": "https://www.govinfo.gov/app/details/USCODE-2024-title35",
        "source_sha256": _sha("uscode-2024-title35"),
        "authority": "official",
    }
    base.update(changes)
    return SourceLineage(**base)  # type: ignore[arg-type]


def _rights(
    *,
    status: RightsReviewStatus = RightsReviewStatus.REVIEWED,
    redistribution_allowed: bool = True,
) -> RightsReview:
    reviewed = status is RightsReviewStatus.REVIEWED
    return RightsReview(
        license_expression="public-domain-US-government",
        review_status=status,
        reviewed_by="patent-legal-governance" if reviewed else "",
        reviewed_at="2026-08-01T00:00:00Z" if reviewed else "",
        redistribution_allowed=redistribution_allowed,
    )


def _candidate(
    *,
    record_id: str = "usc:35:101",
    artifact_kind: str = "usc",
    classification: str = "public_official",
    payload: dict | None = None,
    rights: RightsReview | None = None,
    lineage: SourceLineage | None = None,
) -> ReleaseCandidate:
    return ReleaseCandidate(
        record_id=record_id,
        artifact_kind=artifact_kind,
        classification=classification,
        payload=payload
        or {
            "title": "35 U.S.C. 101",
            "text": "Whoever invents or discovers any new and useful process...",
        },
        source_lineage=lineage or _lineage(),
        rights_review=rights or _rights(),
    )


def test_artifact_kinds_cover_law_and_patent_families() -> None:
    expected = {
        "cfr",
        "usc",
        "public_law",
        "federal_register",
        "projected_rules",
        "applications",
        "claims",
        "events",
        "office_actions",
        "citations",
        "graph",
        "bm25",
        "vector_metadata",
    }
    assert set(ARTIFACT_KINDS) == expected
    assert ArtifactKind.OFFICE_ACTIONS.value == "office_actions"


def test_public_and_private_classification_helpers() -> None:
    assert is_public_classification("public_official")
    assert is_public_classification(ClassificationStatus.PUBLIC_USER)
    assert is_private_classification("confidential_application")
    assert is_private_classification(ClassificationStatus.PRIVILEGED_WORK_PRODUCT)
    assert not is_public_classification("unknown")


def test_public_record_is_admitted_with_lineage_and_rights() -> None:
    decision = evaluate_record_admission(_candidate())

    assert decision.admitted is True
    assert decision.reason_codes == ()
    projected = decision.projected_record
    assert projected["classification"] == "public_official"
    assert projected["source_lineage"]["source_id"] == "govinfo/uscode"
    assert projected["rights_review"]["review_status"] == "reviewed"
    assert projected["policy_version"] == RELEASE_POLICY_VERSION
    assert projected["policy_sha256"] == RELEASE_POLICY_SHA256
    assert projected["record_sha256"]


def test_private_classification_is_rejected() -> None:
    decision = evaluate_record_admission(
        _candidate(
            record_id="app:private:1",
            artifact_kind="applications",
            classification="confidential_application",
            payload={"application_number": "16/000001", "title": "secret draft"},
        )
    )

    assert decision.admitted is False
    assert "classification.private" in decision.reason_codes
    with pytest.raises(PublicationRejectedError):
        decision.require_admitted()


def test_unreviewed_rights_block_release() -> None:
    decision = evaluate_record_admission(
        _candidate(
            rights=_rights(
                status=RightsReviewStatus.UNREVIEWED,
                redistribution_allowed=False,
            )
        )
    )

    assert decision.admitted is False
    assert "rights.unreviewed" in decision.reason_codes
    assert "rights.redistribution_not_allowed" in decision.reason_codes


def test_secret_payload_blocks_release() -> None:
    token = "".join(("hf_", "a" * 24))
    decision = evaluate_record_admission(
        _candidate(
            payload={
                "title": "leaked note",
                "text": f"do not publish token={token}",
            }
        )
    )

    assert decision.admitted is False
    assert "content.secret_detected" in decision.reason_codes
    # Matched secret text must not appear in findings payload.
    for finding in decision.findings:
        assert token not in finding.to_dict().values()


def test_mixed_private_public_batch_fails_before_staging() -> None:
    public = _candidate(record_id="usc:35:102")
    private = _candidate(
        record_id="app:priv:9",
        artifact_kind="applications",
        classification="privileged_work_product",
        payload={"notes": "attorney analysis"},
    )
    batch = evaluate_batch_admission([public, private])

    assert batch.admitted is False
    assert "batch.mixed_private_public" in batch.reason_codes
    assert "batch.private_input" in batch.reason_codes
    assert "privacy.rejected_before_staging" in batch.reason_codes
    assert batch.admitted_records == ()
    assert batch.projected_records == ()
    with pytest.raises(PrivacyRejectedError, match="before staging"):
        assert_public_batch([public, private])


def test_all_private_batch_fails_closed() -> None:
    batch = evaluate_batch_admission(
        [
            _candidate(
                record_id="priv:1",
                classification="confidential_application",
                artifact_kind="applications",
            ),
            _candidate(
                record_id="priv:2",
                classification="credential_or_payment",
                artifact_kind="events",
            ),
        ]
    )
    assert batch.admitted is False
    assert "privacy.rejected_before_staging" in batch.reason_codes


def test_unknown_classification_quarantines_batch() -> None:
    batch = evaluate_batch_admission(
        [
            _candidate(
                record_id="unk:1",
                classification="unknown",
                artifact_kind="claims",
            )
        ]
    )
    assert batch.admitted is False
    assert "batch.unknown_classification" in batch.reason_codes


def test_policy_drift_rejects_batch() -> None:
    batch = PatentReleasePolicy().evaluate_batch(
        [_candidate()],
        expected_policy_sha256="0" * 64,
    )
    assert batch.admitted is False
    assert "policy.drift" in batch.reason_codes


def test_duplicate_record_ids_rejected() -> None:
    batch = evaluate_batch_admission([_candidate(), _candidate()])
    assert batch.admitted is False
    assert "batch.duplicate_record_id" in batch.reason_codes


def test_source_lineage_and_rights_are_immutable() -> None:
    lineage = _lineage()
    rights = _rights()
    with pytest.raises(FrozenInstanceError):
        lineage.source_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        rights.redistribution_allowed = False  # type: ignore[misc]
    with pytest.raises(ReleasePolicyError, match="https://"):
        SourceLineage(
            source_id="x",
            source_revision="y",
            source_uri="http://insecure.example/x",
            source_sha256=_sha("x"),
        )


def test_public_batch_of_multiple_kinds_is_admitted() -> None:
    batch = assert_public_batch(
        [
            _candidate(record_id="usc:35:101", artifact_kind="usc"),
            _candidate(
                record_id="cfr:37:1.56",
                artifact_kind="cfr",
                payload={"title": "37 CFR 1.56", "text": "Duty to disclose..."},
                lineage=_lineage(
                    source_id="govinfo/cfr",
                    source_revision="2024-title-37",
                    source_uri="https://www.govinfo.gov/app/details/CFR-2024-title37-vol1",
                    source_sha256=_sha("cfr-2024-title37"),
                ),
            ),
            _candidate(
                record_id="claim:US1234567B2:1",
                artifact_kind="claims",
                payload={"claim_number": 1, "text": "A method comprising..."},
                lineage=_lineage(
                    source_id="uspto/patentsview",
                    source_revision="2024-01-01",
                    source_uri="https://patentsview.org/download/data-download-tables",
                    source_sha256=_sha("patentsview-2024-01-01"),
                ),
            ),
            _candidate(
                record_id="bm25:shard:0",
                artifact_kind="bm25",
                payload={"term": "novelty", "df": 12},
                lineage=_lineage(
                    source_id="patent-index/bm25",
                    source_revision="v1",
                    source_uri="ipfs://bafybm25index0000000000000000000000000000000000000000000000",
                    source_sha256=_sha("bm25-v1"),
                ),
            ),
        ]
    )
    assert batch.admitted is True
    assert set(batch.classification_summary) == {"public_official"}
    assert len(batch.projected_records) == 4


def test_candidate_round_trip_dict() -> None:
    original = _candidate()
    restored = ReleaseCandidate.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.record_sha256 == original.record_sha256
