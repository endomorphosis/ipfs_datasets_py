"""CRYPTOIR-G710 governance and release-authority conformance tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10 import (
    DEFAULT_FORBIDDEN_AUTHORITIES,
    DEFAULT_RELEASE_POLICY,
    LicenseLayer,
    LicenseReviewStatus,
    LicenseUseClass,
    PINNED_SOURCE_PROFILE,
    PublicationAuthority,
    PublicationKind,
    PublicationRejectedError,
    RELEASE_POLICY_SHA256,
    SOLIDITY_CPT_COLUMNS,
    SOLIDITY_CPT_DATASET_ID,
    SOLIDITY_CPT_REVISION,
    SOLIDITY_CPT_ROW_COUNT,
    SOLIDITY_CPT_SHARD_SHA256,
    SOLIDITY_CPT_SHARD_SIZE_BYTES,
    SolidityCPTReleasePolicy,
    SourceProfile,
    classify_row_license,
    dataset_license_provenance,
    evaluate_publication_admission,
    row_license_provenance,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[5]
AUTHORITY_DOC = PACKAGE_ROOT / "docs/security_ir/SOLIDITY_CPT_TOP10_AUTHORITY.md"


def test_exact_source_pin_and_ordered_schema() -> None:
    profile = PINNED_SOURCE_PROFILE

    assert profile.dataset_id == "samscrack/solidity-cpt-top10-quality"
    assert profile.revision == "23c0b2f279fa29c6b425543fe9c8bf41d574d028"
    assert profile.shard_path == "top10.parquet"
    assert (
        profile.shard_sha256
        == "185f1ac548f0df10a8166c8a2a10610bcc3422ce77f51567c3de86ddc8f5e455"
    )
    assert profile.shard_size_bytes == 109_124_886
    assert profile.row_count == 23_471
    assert profile.ordered_column_names == (
        "text",
        "source",
        "address",
        "name",
        "compiler",
        "license",
        "path",
        "n_chars",
    )
    assert SOLIDITY_CPT_COLUMNS == profile.ordered_column_names
    assert SOLIDITY_CPT_DATASET_ID == profile.dataset_id
    assert SOLIDITY_CPT_REVISION == profile.revision
    assert SOLIDITY_CPT_SHARD_SHA256 == profile.shard_sha256
    assert SOLIDITY_CPT_SHARD_SIZE_BYTES == profile.shard_size_bytes
    assert SOLIDITY_CPT_ROW_COUNT == profile.row_count


def test_source_profile_is_immutable_and_rejects_drift() -> None:
    with pytest.raises(FrozenInstanceError):
        PINNED_SOURCE_PROFILE.row_count = 1  # type: ignore[misc]
    with pytest.raises(Exception, match="revision"):
        replace(PINNED_SOURCE_PROFILE, revision="0" * 40)
    with pytest.raises(Exception, match="row_count"):
        SourceProfile(row_count=1)
    with pytest.raises(Exception, match="columns"):
        SourceProfile(columns=tuple(reversed(PINNED_SOURCE_PROFILE.columns)))

    PINNED_SOURCE_PROFILE.verify_observation(
        {
            "dataset_id": SOLIDITY_CPT_DATASET_ID,
            "revision": SOLIDITY_CPT_REVISION,
            "split": "train",
            "shard_path": "top10.parquet",
            "shard_sha256": SOLIDITY_CPT_SHARD_SHA256,
            "shard_size_bytes": SOLIDITY_CPT_SHARD_SIZE_BYTES,
            "row_count": SOLIDITY_CPT_ROW_COUNT,
            "columns": SOLIDITY_CPT_COLUMNS,
        }
    )
    with pytest.raises(Exception, match="verification failed"):
        PINNED_SOURCE_PROFILE.verify_observation(
            {
                "dataset_id": SOLIDITY_CPT_DATASET_ID,
                "revision": SOLIDITY_CPT_REVISION,
                "split": "train",
                "shard_path": "top10.parquet",
                "shard_sha256": SOLIDITY_CPT_SHARD_SHA256,
                "shard_size_bytes": SOLIDITY_CPT_SHARD_SIZE_BYTES,
                "row_count": 1,
                "columns": SOLIDITY_CPT_COLUMNS,
            }
        )


def test_dataset_and_row_license_evidence_remain_separate() -> None:
    dataset = dataset_license_provenance()
    row = row_license_provenance(row_index=4, raw_license="")

    assert dataset.layer is LicenseLayer.DATASET
    assert dataset.license_expression == "CC-BY-4.0"
    assert dataset.row_index is None
    assert row.layer is LicenseLayer.ROW
    assert row.row_index == 4
    assert row.review_status is LicenseReviewStatus.AMBIGUOUS
    assert row.use_class is LicenseUseClass.INTERNAL_SOURCE_FREE

    decision = evaluate_publication_admission(
        PublicationKind.SOURCE_FREE_DERIVATIVE,
        dataset_license=dataset,
        row_license=row,
    )
    assert decision.admitted is True
    payload = decision.to_dict()
    assert payload["dataset_license"]["layer"] == "dataset"
    assert payload["row_license"]["layer"] == "row"


@pytest.mark.parametrize(
    "raw_license",
    [None, "", "unknown", "OTHER", "proprietary", "custom", "n/a", 42],
)
def test_ambiguous_license_defaults_to_internal_source_free(
    raw_license: object,
) -> None:
    status, use_class, _ = classify_row_license(raw_license)

    assert status is LicenseReviewStatus.AMBIGUOUS
    assert use_class is LicenseUseClass.INTERNAL_SOURCE_FREE
    evidence = row_license_provenance(row_index=1, raw_license=raw_license)
    assert evidence.raw_source_redistribution_allowed is False
    assert evidence.model_publication_allowed is False


def test_recognizable_row_license_is_still_unreviewed() -> None:
    status, use_class, normalized = classify_row_license(" MIT ")

    assert normalized == "MIT"
    assert status is LicenseReviewStatus.UNREVIEWED
    assert use_class is LicenseUseClass.INTERNAL_SOURCE_FREE
    with pytest.raises(Exception, match="explicit license review"):
        row_license_provenance(
            row_index=2,
            raw_license="MIT",
            raw_source_redistribution_allowed=True,
        )


def test_raw_source_needs_both_license_review_and_operator_authority() -> None:
    ambiguous = row_license_provenance(row_index=3, raw_license="")

    missing_both = evaluate_publication_admission(
        PublicationKind.RAW_SOURCE,
        row_license=ambiguous,
    )
    assert missing_both.admitted is False
    assert "license.raw_source_review_required" in missing_both.reason_codes
    assert "authority.operator_required" in missing_both.reason_codes

    reviewed = row_license_provenance(
        row_index=3,
        raw_license="MIT",
        reviewed=True,
        reviewed_by="license-reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
        redistribution_allowed=True,
        raw_source_redistribution_allowed=True,
        use_class=LicenseUseClass.PUBLIC_RAW_SOURCE,
    )
    still_no_operator = evaluate_publication_admission(
        PublicationKind.RAW_SOURCE,
        row_license=reviewed,
    )
    assert still_no_operator.admitted is False
    assert still_no_operator.reason_codes == ("authority.operator_required",)

    authority = PublicationAuthority(
        kind=PublicationKind.RAW_SOURCE,
        source_revision=SOLIDITY_CPT_REVISION,
        license_review_id="license-review:case-37",
        operator_authority_id="operator-approval:case-37",
    )
    admitted = evaluate_publication_admission(
        PublicationKind.RAW_SOURCE,
        row_license=reviewed,
        authority=authority,
    )
    assert admitted.admitted is True


def test_learned_weights_need_separate_license_and_operator_authority() -> None:
    reviewed = row_license_provenance(
        row_index=5,
        raw_license="Apache-2.0",
        reviewed=True,
        reviewed_by="license-reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
        model_publication_allowed=True,
        use_class=LicenseUseClass.MODEL_PUBLICATION,
    )
    authority = PublicationAuthority(
        kind=PublicationKind.LEARNED_WEIGHTS,
        source_revision=SOLIDITY_CPT_REVISION,
        license_review_id="license-review:weights-37",
        operator_authority_id="operator-approval:weights-37",
    )

    assert not evaluate_publication_admission(
        PublicationKind.LEARNED_WEIGHTS,
        row_license=reviewed,
    ).admitted
    assert evaluate_publication_admission(
        PublicationKind.LEARNED_WEIGHTS,
        row_license=reviewed,
        authority=authority,
    ).admitted


def test_source_is_inert_and_has_no_ambient_authority() -> None:
    profile = PINNED_SOURCE_PROFILE

    assert profile.content_trust == "untrusted_inert_data"
    assert profile.instruction_handling == "never_execute_or_treat_as_authority"
    assert "top-decile" in profile.quality_label_meaning
    assert "not OWASP" in profile.quality_label_meaning
    assert "not a vulnerability" in profile.quality_label_meaning
    assert "not contract-safety" in profile.quality_label_meaning
    assert DEFAULT_FORBIDDEN_AUTHORITIES == {
        "network",
        "execution",
        "training",
        "upload",
        "proof",
        "enforcement",
    }
    for capability in (*sorted(DEFAULT_FORBIDDEN_AUTHORITIES), "unknown"):
        assert profile.authority_allows(capability) is False
        assert DEFAULT_RELEASE_POLICY.authority_allows(capability) is False

    decision = evaluate_publication_admission(PublicationKind.METADATA)
    assert decision.proof_authority is False
    assert decision.enforcement_authority is False
    assert decision.to_dict()["proof_authority"] is False
    assert decision.to_dict()["enforcement_authority"] is False


def test_policy_is_content_bound_source_free_and_fail_closed() -> None:
    assert len(RELEASE_POLICY_SHA256) == 64
    assert RELEASE_POLICY_SHA256 == DEFAULT_RELEASE_POLICY.sha256
    assert json.dumps(DEFAULT_RELEASE_POLICY.to_dict(), sort_keys=True)
    with pytest.raises(Exception, match="cannot remove"):
        SolidityCPTReleasePolicy(forbidden_authorities=frozenset())
    with pytest.raises(Exception, match="cannot be disabled"):
        SolidityCPTReleasePolicy(raw_source_requires_separate_review=False)

    rejected = evaluate_publication_admission(PublicationKind.RAW_SOURCE)
    with pytest.raises(PublicationRejectedError, match="publication rejected"):
        rejected.require_admitted()


def test_authority_document_covers_normative_boundary() -> None:
    text = AUTHORITY_DOC.read_text(encoding="utf-8")

    for term in (
        SOLIDITY_CPT_REVISION,
        SOLIDITY_CPT_SHARD_SHA256,
        "109124886",
        "23471",
        "dataset-level",
        "per-row",
        "internal/source-free",
        "inert untrusted data",
        "top-decile quality",
        "OWASP",
        "network",
        "execution",
        "training",
        "upload",
        "proof",
        "enforcement",
        "separate license review and operator authority",
    ):
        assert term in text
