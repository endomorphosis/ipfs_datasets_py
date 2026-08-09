"""Unit tests for the all-title official-source authority contract (USCIR-004).

Acceptance:

* Policy distinguishes proposed latest from approved exact release point.
* Records per-title provenance.
* Rejects unapproved mixed vintages.
* Supports deterministic resume receipts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (
    CANONICAL_USCODE_TITLES,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_APPROVED_RELEASE_POINT,
    EXPECTED_TITLE_COUNT,
    FIXTURE_SCHEMA_VERSION,
    AllTitleReleaseManifest,
    ApprovedReleasePoint,
    ExclusionKind,
    FixtureSchemaError,
    HardCodedLatestEditionError,
    MissingApprovedReleaseError,
    ReleasePointRole,
    ResumeReceiptError,
    SourceProvider,
    TitleExclusion,
    TitlePackageProvenance,
    TitlePackageStatus,
    TitleResumeReceipt,
    UnapprovedMixedVintageError,
    UnapprovedProposedReleaseError,
    UscodeSourcePolicy,
    UscodeSourcePolicyError,
    VerificationResult,
    build_default_receipt_fixture_payload,
    default_receipt_fixture_path,
    digest_mapping,
    expand_receipt_fixture,
    expected_title_package_sha256,
    load_receipt_fixture,
    load_receipt_fixture_payload,
    normalize_title,
    parse_release_point_id,
    require_approved_exact,
    require_canonical_title,
    titles_missing_from_manifest,
    ushouse_releasepoint_zip_url,
    validate_no_unapproved_mixed_vintages,
)

# tests/unit/processors/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "legal_ir"
    / "uscode_release_receipts.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_receipt_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_manifest(fixture_payload: dict) -> AllTitleReleaseManifest:
    return expand_receipt_fixture(fixture_payload)


@pytest.fixture
def policy() -> UscodeSourcePolicy:
    return UscodeSourcePolicy()


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_receipt_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_receipt_fixture_path().name == "uscode_release_receipts.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 32_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["expected_title_count"] == EXPECTED_TITLE_COUNT
    assert "generators" in payload
    # Recipe form: not 53 fully expanded inline envelopes.
    assert len(payload.get("titles") or {}) < 5
    assert len(payload.get("resume_receipts") or {}) < 5


def test_default_payload_matches_on_disk_recipe():
    built = build_default_receipt_fixture_payload()
    on_disk = load_receipt_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["expected_title_count"] == on_disk["expected_title_count"]
    assert built["approved_release"]["release_point"] == on_disk["approved_release"]["release_point"]
    assert built["proposed_release"]["role"] == ReleasePointRole.PROPOSED_LATEST.value
    assert on_disk["proposed_release"]["role"] == ReleasePointRole.PROPOSED_LATEST.value
    assert built["approved_release"]["role"] == ReleasePointRole.APPROVED_EXACT.value
    assert on_disk["approved_release"]["role"] == ReleasePointRole.APPROVED_EXACT.value


def test_fixture_expands_to_all_53_titles(fixture_manifest: AllTitleReleaseManifest):
    assert fixture_manifest.title_count == EXPECTED_TITLE_COUNT
    assert set(fixture_manifest.titles) == set(CANONICAL_USCODE_TITLES)
    assert "53" not in fixture_manifest.titles
    assert titles_missing_from_manifest(fixture_manifest) == ()
    assert len(fixture_manifest.resume_receipts) == EXPECTED_TITLE_COUNT


def test_fixture_carries_currentness_disclaimer(fixture_manifest: AllTitleReleaseManifest):
    assert fixture_manifest.currentness_disclaimer == CURRENTNESS_DISCLAIMER
    assert "not a claim" in fixture_manifest.currentness_disclaimer.lower()
    assert "official source" in fixture_manifest.currentness_disclaimer.lower()


def test_load_receipt_fixture_helper():
    manifest = load_receipt_fixture(_FIXTURE_PATH)
    assert manifest.approved_release.release_point == DEFAULT_APPROVED_RELEASE_POINT
    assert manifest.proposed_release is not None
    assert manifest.proposed_release.role is ReleasePointRole.PROPOSED_LATEST


# ---------------------------------------------------------------------------
# Proposed latest vs approved exact
# ---------------------------------------------------------------------------


def test_proposed_latest_is_not_admissible_as_final_provenance(policy: UscodeSourcePolicy):
    proposed = policy.propose_latest_from_discovery(
        release_point="118/45",
        discovery_source="https://uscode.house.gov/download/download.shtml",
    )
    assert proposed.role is ReleasePointRole.PROPOSED_LATEST
    assert proposed.release_point == "us/pl/118/45"

    with pytest.raises(UnapprovedProposedReleaseError):
        require_approved_exact(proposed)

    with pytest.raises(MissingApprovedReleaseError):
        policy.build_title_provenance("35")


def test_approve_exact_promotes_proposed_and_enables_provenance(policy: UscodeSourcePolicy):
    proposed = policy.propose_latest_from_discovery(release_point="us/pl/118/45")
    approved = policy.approve_exact_release(
        proposed,
        approved_by="operator@example.test",
        approved_at="2024-09-20T12:00:00Z",
    )
    assert approved.role is ReleasePointRole.APPROVED_EXACT
    assert approved.release_point == proposed.release_point
    assert approved.approved_by == "operator@example.test"
    assert approved.metadata.get("promoted_from") == "proposed_latest"

    prov = policy.build_title_provenance("35")
    assert prov.release_point == approved.release_point
    assert prov.title == "35"
    assert prov.verification is VerificationResult.VERIFIED


def test_hard_coded_latest_rejected_everywhere(policy: UscodeSourcePolicy):
    with pytest.raises(HardCodedLatestEditionError):
        parse_release_point_id("latest")
    with pytest.raises(HardCodedLatestEditionError):
        policy.propose_latest_from_discovery(release_point="latest")
    with pytest.raises(HardCodedLatestEditionError):
        policy.approve_exact_release(
            "latest",
            approved_by="operator@example.test",
            approved_at="2024-09-20T12:00:00Z",
        )
    with pytest.raises(HardCodedLatestEditionError):
        ApprovedReleasePoint(
            release_point="us/pl/118/latest",
            provider=SourceProvider.OLRC_HOUSE,
            approved_by="x",
            approved_at="2024-09-20T12:00:00Z",
        )


def test_proposed_and_approved_roles_differ_in_fixture(fixture_manifest: AllTitleReleaseManifest):
    assert fixture_manifest.proposed_release is not None
    assert fixture_manifest.proposed_release.role is ReleasePointRole.PROPOSED_LATEST
    assert fixture_manifest.approved_release.role is ReleasePointRole.APPROVED_EXACT
    # Same concrete identity may be proposed then approved, but roles stay distinct.
    assert (
        fixture_manifest.proposed_release.release_point
        == fixture_manifest.approved_release.release_point
    )
    assert fixture_manifest.proposed_release.to_dict()["role"] != (
        fixture_manifest.approved_release.to_dict()["role"]
    )


def test_require_approved_exact_rejects_proposed_mapping():
    with pytest.raises(UnapprovedProposedReleaseError):
        require_approved_exact(
            {
                "role": "proposed_latest",
                "release_point": "us/pl/118/45",
                "provider": "olrc_house",
                "discovered_at": "2024-09-18T09:30:00Z",
                "discovery_source": "catalog",
            }
        )


# ---------------------------------------------------------------------------
# Per-title provenance
# ---------------------------------------------------------------------------


def test_records_per_title_provenance_for_all_titles(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        DEFAULT_APPROVED_RELEASE_POINT,
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    provenances = policy.record_all_canonical_titles()
    assert len(provenances) == EXPECTED_TITLE_COUNT
    for title in CANONICAL_USCODE_TITLES:
        prov = provenances[title]
        assert prov.title == title
        assert prov.release_point == DEFAULT_APPROVED_RELEASE_POINT
        assert prov.content_sha256 == expected_title_package_sha256(
            release_point=DEFAULT_APPROVED_RELEASE_POINT, title=title
        )
        assert prov.source_url.startswith("https://uscode.house.gov/download/releasepoints/")
        assert prov.package_id == DEFAULT_APPROVED_RELEASE_POINT
        assert prov.verification is VerificationResult.VERIFIED
        assert prov.status is TitlePackageStatus.VERIFIED
        assert "acquired_at" in prov.to_dict()


def test_fixture_title_provenance_fields(fixture_manifest: AllTitleReleaseManifest):
    title35 = fixture_manifest.titles["35"]
    assert title35.provider is SourceProvider.OLRC_HOUSE
    assert title35.release_point == "us/pl/118/45"
    assert len(title35.content_sha256) == 64
    assert title35.source_url == ushouse_releasepoint_zip_url(
        congress="118", release="45", title="35", format_kind="xml"
    )
    # Spot-check a few titles span the sealed baseline.
    for title in ("1", "26", "42", "52", "54"):
        assert title in fixture_manifest.titles
        assert fixture_manifest.titles[title].release_point == "us/pl/118/45"


def test_canonical_title_span():
    assert len(CANONICAL_USCODE_TITLES) == 53
    assert CANONICAL_USCODE_TITLES[0] == "1"
    assert CANONICAL_USCODE_TITLES[-1] == "54"
    assert "53" not in CANONICAL_USCODE_TITLES
    assert require_canonical_title("35") == "35"
    assert normalize_title("035") == "35"
    with pytest.raises(UscodeSourcePolicyError):
        require_canonical_title("53")
    with pytest.raises(UscodeSourcePolicyError):
        require_canonical_title("99")


def test_title_exclusion_requires_record_when_excluded(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        DEFAULT_APPROVED_RELEASE_POINT,
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    with pytest.raises(UscodeSourcePolicyError):
        policy.build_title_provenance(
            "35",
            status=TitlePackageStatus.EXCLUDED,
            verification=VerificationResult.MISSING,
            exclusion=None,
        )
    excl = TitleExclusion(
        kind=ExclusionKind.PACKAGE_UNAVAILABLE,
        title="35",
        reason="package temporarily unavailable at this release point",
    )
    prov = policy.build_title_provenance(
        "35",
        status=TitlePackageStatus.EXCLUDED,
        verification=VerificationResult.MISSING,
        exclusion=excl,
    )
    assert prov.exclusion is not None
    assert prov.exclusion.kind is ExclusionKind.PACKAGE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Mixed vintages fail closed
# ---------------------------------------------------------------------------


def test_rejects_unapproved_mixed_vintages(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        "us/pl/118/45",
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    good = policy.build_title_provenance("1")
    policy.record_title_provenance(good)

    mixed = TitlePackageProvenance(
        title="2",
        release_point="us/pl/117/12",
        provider=SourceProvider.OLRC_HOUSE,
        package_id="us/pl/117/12",
        source_url=ushouse_releasepoint_zip_url(
            congress="117", release="12", title="2", format_kind="xml"
        ),
        content_sha256=expected_title_package_sha256(
            release_point="us/pl/117/12", title="2"
        ),
        acquired_at="2024-09-20T12:05:00Z",
        verification=VerificationResult.VERIFIED,
        status=TitlePackageStatus.VERIFIED,
    )
    with pytest.raises(UnapprovedMixedVintageError):
        policy.record_title_provenance(mixed)

    with pytest.raises(UnapprovedMixedVintageError):
        validate_no_unapproved_mixed_vintages(
            [good, mixed],
            approved=policy.require_approved(),
        )


def test_explicit_mixed_override_is_allowed(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        "us/pl/118/45",
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    policy.approve_mixed_override("2", "us/pl/117/12")
    alt = policy.build_title_provenance("2", release_point="us/pl/117/12")
    policy.record_title_provenance(alt)
    assert policy.provenances()["2"].release_point == "us/pl/117/12"

    # Still rejects a third unapproved vintage.
    rogue = TitlePackageProvenance(
        title="3",
        release_point="us/pl/116/1",
        provider=SourceProvider.OLRC_HOUSE,
        package_id="us/pl/116/1",
        source_url=ushouse_releasepoint_zip_url(
            congress="116", release="1", title="3", format_kind="xml"
        ),
        content_sha256=expected_title_package_sha256(
            release_point="us/pl/116/1", title="3"
        ),
        acquired_at="2024-09-20T12:05:00Z",
        verification=VerificationResult.VERIFIED,
        status=TitlePackageStatus.VERIFIED,
    )
    with pytest.raises(UnapprovedMixedVintageError):
        policy.record_title_provenance(rogue)


def test_manifest_rejects_mixed_vintages_at_construction():
    approved = ApprovedReleasePoint(
        release_point="us/pl/118/45",
        provider=SourceProvider.OLRC_HOUSE,
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    t1 = TitlePackageProvenance(
        title="1",
        release_point="us/pl/118/45",
        provider=SourceProvider.OLRC_HOUSE,
        package_id="us/pl/118/45",
        source_url=ushouse_releasepoint_zip_url(
            congress="118", release="45", title="1"
        ),
        content_sha256=expected_title_package_sha256(
            release_point="us/pl/118/45", title="1"
        ),
        acquired_at="2024-09-20T12:05:00Z",
        verification=VerificationResult.VERIFIED,
    )
    t2 = TitlePackageProvenance(
        title="2",
        release_point="us/pl/117/12",
        provider=SourceProvider.OLRC_HOUSE,
        package_id="us/pl/117/12",
        source_url=ushouse_releasepoint_zip_url(
            congress="117", release="12", title="2"
        ),
        content_sha256=expected_title_package_sha256(
            release_point="us/pl/117/12", title="2"
        ),
        acquired_at="2024-09-20T12:05:00Z",
        verification=VerificationResult.VERIFIED,
    )
    with pytest.raises(UnapprovedMixedVintageError):
        AllTitleReleaseManifest(
            approved_release=approved,
            titles={"1": t1, "2": t2},
            resume_receipts={},
        )


# ---------------------------------------------------------------------------
# Deterministic resume receipts
# ---------------------------------------------------------------------------


def test_resume_receipts_are_deterministic(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        DEFAULT_APPROVED_RELEASE_POINT,
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    prov = policy.build_title_provenance("35")
    r1 = policy.build_resume_receipt(prov, checkpoint_seq=1)
    r2 = TitleResumeReceipt.from_dict(r1.to_dict())
    assert r1.receipt_digest == r2.receipt_digest
    assert r1.to_dict() == r2.to_dict()

    # Same body always yields the same digest.
    body = r1._body_dict()
    assert digest_mapping(body) == r1.receipt_digest


def test_resume_skips_verified_redownload(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        DEFAULT_APPROVED_RELEASE_POINT,
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    prov = policy.build_title_provenance("26")
    receipt = policy.build_resume_receipt(prov, checkpoint_seq=7)

    skip = policy.resume_from_receipt(receipt, on_disk_sha256=prov.content_sha256)
    assert skip["action"] == "skip"
    assert skip["should_skip_redownload"] is True
    assert skip["title"] == "26"

    # Missing on-disk file still skips when receipt is verified (trusted checkpoint).
    skip_trusted = policy.resume_from_receipt(receipt)
    assert skip_trusted["action"] == "skip"

    # Checksum mismatch forces verify_failed (caller must redownload/repair).
    bad = policy.resume_from_receipt(
        receipt,
        on_disk_sha256="0" * 64,
    )
    assert bad["action"] == "verify_failed"
    assert bad["should_skip_redownload"] is False


def test_pending_receipt_requires_redownload(policy: UscodeSourcePolicy):
    policy.approve_exact_release(
        DEFAULT_APPROVED_RELEASE_POINT,
        approved_by="uscir-004",
        approved_at="2024-09-20T12:00:00Z",
    )
    pending = policy.build_title_provenance(
        "11",
        status=TitlePackageStatus.PENDING,
        verification=VerificationResult.UNVERIFIED,
    )
    receipt = policy.build_resume_receipt(pending, checkpoint_seq=3)
    disposition = policy.resume_from_receipt(receipt)
    assert disposition["action"] == "redownload"
    assert disposition["should_skip_redownload"] is False


def test_tampered_receipt_digest_is_rejected():
    receipt = TitleResumeReceipt(
        title="35",
        release_point="us/pl/118/45",
        package_id="us/pl/118/45",
        content_sha256=expected_title_package_sha256(
            release_point="us/pl/118/45", title="35"
        ),
        status=TitlePackageStatus.VERIFIED,
        verification=VerificationResult.VERIFIED,
        source_url=ushouse_releasepoint_zip_url(
            congress="118", release="45", title="35"
        ),
        acquired_at="2024-09-20T12:05:00Z",
        checkpoint_seq=1,
    )
    payload = receipt.to_dict()
    payload["receipt_digest"] = "a" * 64
    with pytest.raises(ResumeReceiptError):
        TitleResumeReceipt.from_dict(payload)


def test_fixture_resume_receipts_are_deterministic(fixture_manifest: AllTitleReleaseManifest):
    digests = []
    for title in sorted(fixture_manifest.resume_receipts):
        receipt = fixture_manifest.resume_receipts[title]
        assert receipt.receipt_digest
        # Round-trip preserves digest.
        again = TitleResumeReceipt.from_dict(receipt.to_dict())
        assert again.receipt_digest == receipt.receipt_digest
        digests.append(receipt.receipt_digest)
    # All digests unique across titles (different package content seeds).
    assert len(set(digests)) == EXPECTED_TITLE_COUNT


def test_policy_manifest_matches_fixture_release(policy: UscodeSourcePolicy, fixture_manifest):
    policy.propose_latest_from_discovery(
        release_point=fixture_manifest.proposed_release.release_point,
        discovered_at=fixture_manifest.proposed_release.discovered_at,
        discovery_source=fixture_manifest.proposed_release.discovery_source,
    )
    policy.approve_exact_release(
        fixture_manifest.approved_release.release_point,
        approved_by=fixture_manifest.approved_release.approved_by,
        approved_at=fixture_manifest.approved_release.approved_at,
        edition=fixture_manifest.approved_release.edition,
    )
    policy.record_all_canonical_titles(
        acquired_at=fixture_manifest.titles["1"].acquired_at,
    )
    manifest = policy.build_manifest()
    assert manifest.approved_release.release_point == fixture_manifest.approved_release.release_point
    assert manifest.title_count == EXPECTED_TITLE_COUNT
    assert set(manifest.verified_titles) == set(CANONICAL_USCODE_TITLES)
    # Deterministic package checksums match the fixture expansion.
    for title in CANONICAL_USCODE_TITLES:
        assert (
            manifest.titles[title].content_sha256
            == fixture_manifest.titles[title].content_sha256
        )


# ---------------------------------------------------------------------------
# Parse / URL helpers
# ---------------------------------------------------------------------------


def test_parse_release_point_variants():
    assert parse_release_point_id("us/pl/118/45") == ("us/pl/118/45", "118", "45")
    assert parse_release_point_id("118-45") == ("us/pl/118/45", "118", "45")
    assert parse_release_point_id("118/45") == ("us/pl/118/45", "118", "45")


def test_malformed_fixture_schema_rejected():
    with pytest.raises(FixtureSchemaError):
        expand_receipt_fixture({"schema_version": "not-a-real-schema"})


def test_source_provider_aliases():
    assert SourceProvider.coerce("ushouse").canonical() is SourceProvider.OLRC_HOUSE
    assert SourceProvider.coerce("govinfo") is SourceProvider.GOVINFO
    with pytest.raises(UscodeSourcePolicyError):
        SourceProvider.coerce("random-blog")
